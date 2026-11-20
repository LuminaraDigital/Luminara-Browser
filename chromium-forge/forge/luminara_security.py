"""Luminara Browser Security Primitives (`forge/luminara_security.py`).

Clean-room, zero-dependency implementation of:
1. `LuminaraRedactor`: Binary-safe egress scrubber that redacts API keys, bearer tokens,
   Basic-Auth URLs, OAuth `#access_token` fragments, AWS/Stripe tokens, JWTs, PEM keys,
   and registered vault secrets (raw + URL-encoded) while keeping binary base64 blobs
   (`data_base64`, `captureScreenshot`, `printToPDF`) byte-identical.
2. `LuminaraVault`: Origin-pinned, model-blind credential & RFC 6238 TOTP vault (`outputs/vault.json`)
   with Windows Current-User DPAPI encryption at rest, `0o600` atomic writes, immutable origin
   binding per `vault_id`, form-scoped username resolution, same-origin iframe traversal, and
   1-box / 6-box TOTP injection.

License: MIT — Luminara Engineering.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import shutil
import struct
import threading
import time
from typing import Any
import urllib.parse

from .cdp_client import CDPBridge, CDPError
from .http_base import atomic_write_private
from .luminara_crypto import LuminaraEnvelopeCipher, dpapi_unprotect

ENCODING = "utf-8"
MAX_REDACT_DEPTH = 32
REDACT_DEPTH_SENTINEL = "[LUMINARA_MAX_DEPTH_REDACTED]"

_SENSITIVE_HEADER_KEYS = frozenset(
    {"authorization", "proxy-authorization", "x-api-key", "api-key", "cookie", "set-cookie", "x-luminara-ui-key"}
)

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]{1,16384}?-----END [A-Z0-9 ]*PRIVATE KEY-----"),
        "[REDACTED:PRIVATE_KEY]",
    ),
    (
        re.compile(r'(?i)(["\']?authorization["\']?\s*[:=]\s*["\']?bearer\s+)([A-Za-z0-9._\-~+/]+=*)'),
        r"\1[REDACTED:BEARER_TOKEN]",
    ),
    (
        re.compile(r"\b(sk-(?:proj-|ant-|live-|test-)?[A-Za-z0-9_\-]{16,})\b"),
        "[REDACTED:API_KEY]",
    ),
    (
        re.compile(r"\b((?:rk_live_|rk_test_|whsec_)[A-Za-z0-9_\-]{16,})\b"),
        "[REDACTED:API_KEY]",
    ),
    (
        re.compile(r"\b((?:AKIA|ASIA)[0-9A-Z]{16})\b"),
        "[REDACTED:AWS_KEY]",
    ),
    (
        re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{24,})\b"),
        "[REDACTED:GITHUB_TOKEN]",
    ),
    (
        re.compile(r"\b(AIza[0-9A-Za-z\-_]{31,39})\b"),
        "[REDACTED:GOOGLE_API_KEY]",
    ),
    (
        re.compile(r"\b(xox[baprs]-[0-9A-Za-z\-]{16,})\b"),
        "[REDACTED:SLACK_TOKEN]",
    ),
    (
        re.compile(r"\b(eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})\b"),
        "[REDACTED:JWT]",
    ),
    (
        re.compile(r"(?i)(\bhttps?://)([^/\s:@\"'<>]+:[^/\s@\"'<>]+)(@)"),
        r"\1[REDACTED:URL_AUTH]\3",
    ),
    (
        re.compile(
            r"(?i)([?&#](?:api_key|apikey|access_token|id_token|refresh_token|auth_token|client_secret|password|secret)=)([^&#\s\"'<>]+)"
        ),
        r"\1[REDACTED:URL_SECRET]",
    ),
)

_BINARY_EXEMPT_KEYS = frozenset({"data_base64", "screenshotData", "bufferedData"})


def _unprotect_secret_at_rest(stored: str) -> str:
    """Decrypt legacy `dpapi:` secret blobs via canonical `dpapi_unprotect`; pass plaintext through."""
    if not stored or not stored.startswith("dpapi:"):
        return stored
    enc = base64.b64decode(stored[6:])
    return dpapi_unprotect(enc, entropy=None).decode(ENCODING)


class LuminaraRedactor:
    """Thread-safe secret scrubber with dynamic registration for model-blind vault secrets."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._literal_secrets: set[str] = set()

    def register_secret(self, secret_value: str) -> None:
        """Register exact and URL-encoded forms of a secret so neither can be echoed back."""
        cleaned = (secret_value or "").strip()
        if len(cleaned) >= 4:
            url_enc = urllib.parse.quote(cleaned, safe="")
            with self._lock:
                self._literal_secrets.add(cleaned)
                if len(url_enc) >= 4:
                    self._literal_secrets.add(url_enc)

    def redact_text(self, text: str) -> str:
        if not text or not isinstance(text, str):
            return text
        out = text
        with self._lock:
            literals = sorted(self._literal_secrets, key=len, reverse=True)
        for lit in literals:
            if lit in out:
                out = out.replace(lit, "[REDACTED:VAULT_SECRET]")
        for pattern, replacement in _SECRET_PATTERNS:
            out = pattern.sub(replacement, out)
        return out

    def redact_payload(
        self,
        value: Any,
        *,
        exempt_keys: frozenset[str] = _BINARY_EXEMPT_KEYS,
        _depth: int = 0,
    ) -> Any:
        """Recursively scrub strings in dicts/lists while preserving declared binary base64 leaves."""
        if _depth >= MAX_REDACT_DEPTH:
            return REDACT_DEPTH_SENTINEL
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, list):
            return [self.redact_payload(item, exempt_keys=exempt_keys, _depth=_depth + 1) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact_payload(item, exempt_keys=exempt_keys, _depth=_depth + 1) for item in value)
        if not isinstance(value, dict):
            return value

        base64_flagged = value.get("base64Encoded") is True
        scrubbed: dict[str, Any] = {}
        for k, v in value.items():
            safe_key = self.redact_text(k) if isinstance(k, str) else k
            is_binary_leaf = isinstance(v, str) and (
                k in exempt_keys or (k in ("data", "body") and base64_flagged)
            )
            if is_binary_leaf:
                scrubbed[safe_key] = v
            elif isinstance(k, str) and k.strip().lower() in _SENSITIVE_HEADER_KEYS and isinstance(v, str) and v.strip():
                scrubbed[safe_key] = "[REDACTED:HEADER_SECRET]"
            else:
                scrubbed[safe_key] = self.redact_payload(v, exempt_keys=exempt_keys, _depth=_depth + 1)
        return scrubbed


DEFAULT_REDACTOR = LuminaraRedactor()


def normalize_origin(url_or_origin: str) -> str:
    """Extract canonical `scheme://host[:port]` origin (preserving IPv6 brackets) for vault binding."""
    raw = (url_or_origin or "").strip()
    if not raw:
        raise ValueError("Origin URL must be non-empty")
    parsed = urllib.parse.urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Vault origin must use http or https (got {scheme!r})")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError(f"Vault origin is missing hostname: {raw!r}")
    fmt_host = f"[{host}]" if ":" in host else host
    port = parsed.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        return f"{scheme}://{fmt_host}:{port}"
    return f"{scheme}://{fmt_host}"


def generate_totp_code(base32_secret: str, timestamp: float | None = None, period: int = 30, digits: int = 6) -> str:
    """Compute an RFC 6238 HMAC-SHA1 TOTP code using pure Python stdlib."""
    cleaned = re.sub(r"[\s\-]+", "", (base32_secret or "")).upper()
    if not cleaned:
        raise ValueError("TOTP secret must be non-empty Base32")
    pad_len = (8 - (len(cleaned) % 8)) % 8
    key_bytes = base64.b32decode(cleaned + ("=" * pad_len), casefold=True)
    ts = int(time.time() if timestamp is None else timestamp)
    counter = ts // max(1, period)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key_bytes, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10**digits)).zfill(digits)


_VAULT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\-]{0,63}$")

_VAULT_DOM_HELPERS_JS = r"""
    const setVal = (win, el, val) => {
      el.focus();
      const proto = el.tagName === 'TEXTAREA' ? win.HTMLTextAreaElement.prototype : win.HTMLInputElement.prototype;
      const desc = Object.getOwnPropertyDescriptor(proto, 'value');
      if (desc && desc.set) desc.set.call(el, val);
      else el.value = val;
      el.dispatchEvent(new win.Event('input', { bubbles: true }));
      el.dispatchEvent(new win.Event('change', { bubbles: true }));
    };
    const collectSameOriginDocs = (expectedOrigin) => {
      const list = [{ doc: document, win: window }];
      for (const fr of Array.from(document.querySelectorAll('iframe')).slice(0, 10)) {
        try {
          if (fr.contentDocument && fr.contentWindow && fr.contentWindow.location.origin.toLowerCase() === expectedOrigin.toLowerCase()) {
            list.push({ doc: fr.contentDocument, win: fr.contentWindow });
          }
        } catch (_e) {}
      }
      return list;
    };
"""


class LuminaraVault:
    """Origin-bound, model-blind, AEAD-encrypted credential and TOTP autofill manager."""

    SCHEMA_VERSION = "luminara-vault-v2-encrypted"

    def __init__(
        self,
        vault_path: Path,
        redactor: LuminaraRedactor | None = None,
        *,
        passphrase: str | None = None,
        prefer_dpapi: bool = True,
    ) -> None:
        self.vault_path = vault_path.resolve()
        self.redactor = redactor or DEFAULT_REDACTOR
        self._lock = threading.Lock()
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        self._cipher = LuminaraEnvelopeCipher(
            self.vault_path.with_suffix(".key.json"),
            passphrase=passphrase,
            prefer_dpapi=prefer_dpapi,
        )
        self._entries: dict[str, dict[str, Any]] = self._load()

    @staticmethod
    def _aad_for(vault_id: str, origin: str) -> str:
        return f"luminara:vault:v2:{origin}:{vault_id}"

    @property
    def encryption_mode(self) -> str:
        return self._cipher.protection_mode

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.vault_path.exists():
            return {}
        try:
            raw = json.loads(self.vault_path.read_text(encoding=ENCODING))
            if not isinstance(raw, dict):
                return {}
            # Encrypted v2 schema (AEAD + origin-bound AAD)
            if raw.get("schema") == self.SCHEMA_VERSION and isinstance(raw.get("entries"), dict):
                loaded: dict[str, dict[str, Any]] = {}
                for vid, meta in raw["entries"].items():
                    if not isinstance(meta, dict):
                        continue
                    origin = str(meta.get("origin") or "")
                    sealed = meta.get("sealed_secrets")
                    secrets_obj: dict[str, Any] = {}
                    if isinstance(sealed, dict) and origin:
                        secrets_obj = self._cipher.open_json(sealed, aad_context=self._aad_for(vid, origin))
                    pw = str(secrets_obj.get("password") or "")
                    totp = str(secrets_obj.get("totp_secret") or "")
                    if pw:
                        self.redactor.register_secret(pw)
                    if totp:
                        self.redactor.register_secret(totp)
                    loaded[vid] = {
                        "vault_id": vid,
                        "origin": origin,
                        "username": str(meta.get("username") or ""),
                        "label": str(meta.get("label") or origin),
                        "updated_at_ms": int(meta.get("updated_at_ms") or 0),
                        "password": pw,
                        "totp_secret": totp,
                    }
                return loaded

            # Legacy v1/plaintext migration -> immediately re-seal atomically on disk!
            hydrated: dict[str, dict[str, Any]] = {}
            for vid, item in raw.items():
                if not isinstance(item, dict) or not item.get("origin"):
                    continue
                pw = _unprotect_secret_at_rest(str(item.get("password") or ""))
                totp = _unprotect_secret_at_rest(str(item.get("totp_secret") or ""))
                if pw:
                    self.redactor.register_secret(pw)
                if totp:
                    self.redactor.register_secret(totp)
                hydrated[str(vid)] = {**item, "vault_id": str(vid), "password": pw, "totp_secret": totp}
            if hydrated:
                self._entries = hydrated
                self._save()
            return hydrated
        except Exception:  # noqa: BLE001
            backup = self.vault_path.with_suffix(".json.corrupt")
            try:
                shutil.copy2(self.vault_path, backup)
            except OSError:
                pass
            return {}

    def _save(self) -> None:
        sealed_entries: dict[str, Any] = {}
        for vid, entry in self._entries.items():
            origin = str(entry["origin"])
            sealed_blob = self._cipher.seal_json(
                {
                    "password": str(entry.get("password") or ""),
                    "totp_secret": str(entry.get("totp_secret") or ""),
                },
                aad_context=self._aad_for(vid, origin),
            )
            sealed_entries[vid] = {
                "vault_id": vid,
                "origin": origin,
                "username": str(entry.get("username") or ""),
                "label": str(entry.get("label") or origin),
                "has_password": bool(entry.get("password")),
                "has_totp": bool(entry.get("totp_secret")),
                "updated_at_ms": int(entry.get("updated_at_ms") or 0),
                "sealed_secrets": sealed_blob,
            }
        envelope = {
            "schema": self.SCHEMA_VERSION,
            "protection_mode": self._cipher.protection_mode,
            "entries": sealed_entries,
        }
        atomic_write_private(self.vault_path, json.dumps(envelope, indent=2, ensure_ascii=False) + "\n")

    @staticmethod
    def _public_view(entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "vault_id": entry["vault_id"],
            "origin": entry["origin"],
            "username": entry.get("username", ""),
            "label": entry.get("label", ""),
            "has_password": bool(entry.get("password")),
            "has_totp": bool(entry.get("totp_secret")),
            "updated_at_ms": entry.get("updated_at_ms", 0),
        }

    def list_entries(self, origin_filter: str | None = None) -> list[dict[str, Any]]:
        norm_filter = normalize_origin(origin_filter) if origin_filter else None
        with self._lock:
            items = [
                self._public_view(e)
                for e in self._entries.values()
                if norm_filter is None or e.get("origin") == norm_filter
            ]
        items.sort(key=lambda x: (x["origin"], x["vault_id"]))
        return items

    def upsert_entry(
        self,
        *,
        origin: str,
        username: str,
        password: str = "",
        totp_secret: str = "",
        vault_id: str | None = None,
        label: str = "",
    ) -> dict[str, Any]:
        bound_origin = normalize_origin(origin)
        vid = (vault_id or f"vault_{secrets.token_hex(4)}").strip()
        if not _VAULT_ID_RE.match(vid):
            raise ValueError(f"Invalid vault_id {vid!r}")
        if not password and not totp_secret:
            raise ValueError("Vault entry requires at least a password or totp_secret")
        if totp_secret:
            generate_totp_code(totp_secret)

        if password:
            self.redactor.register_secret(password)
        if totp_secret:
            self.redactor.register_secret(totp_secret)

        with self._lock:
            existing = self._entries.get(vid)
            if existing and existing.get("origin") != bound_origin:
                raise ValueError(
                    f"Vault entry {vid!r} is immutably pinned to {existing.get('origin')}; "
                    f"delete it first or choose a new vault_id for {bound_origin}"
                )
            prev = existing or {}
            record = {
                "vault_id": vid,
                "origin": bound_origin,
                "username": str(username or prev.get("username") or "").strip(),
                "password": password if password else str(prev.get("password") or ""),
                "totp_secret": totp_secret if totp_secret else str(prev.get("totp_secret") or ""),
                "label": str(label or prev.get("label") or bound_origin).strip()[:120],
                "updated_at_ms": int(time.time() * 1000),
            }
            self._entries[vid] = record
            self._save()
            return self._public_view(record)

    def delete_entry(self, vault_id: str) -> bool:
        with self._lock:
            if self._entries.pop(vault_id, None) is not None:
                self._save()
                return True
            return False

    def _execute_origin_pinned_dom(
        self,
        cdp: CDPBridge,
        target_id: str | None,
        vault_id: str,
        *,
        agent_id: str = "luminara-agent",
        script_builder: Callable[[dict[str, Any]], str],
        default_err: str,
    ) -> dict[str, Any]:
        with self._lock:
            entry = self._entries.get(vault_id)
            if not entry:
                raise ValueError(f"Unknown vault_id: {vault_id!r}")
            snapshot_entry = dict(entry)

        bound_origin = snapshot_entry["origin"]
        resolved_tid = cdp._pick_target_id(target_id)
        leases = getattr(cdp, "leases", None)
        if leases is not None:
            leases.check_allowed(resolved_tid, agent_id)

        page_meta = cdp.evaluate_js(resolved_tid, "({origin: window.location.origin, href: window.location.href})")
        if not isinstance(page_meta, dict):
            raise CDPError("Could not inspect live tab origin before vault injection")
        live_origin_raw = str(page_meta.get("origin") or "")
        try:
            live_origin = normalize_origin(live_origin_raw)
        except ValueError as exc:
            raise CDPError(f"Refusing vault autofill on non-HTTP(S) origin {live_origin_raw!r}") from exc

        if live_origin != bound_origin:
            raise CDPError(
                f"Vault origin mismatch: entry {vault_id!r} is bound to {bound_origin}, "
                f"but active tab is at {live_origin}"
            )

        res = cdp.evaluate_js(resolved_tid, script_builder(snapshot_entry))
        if not isinstance(res, dict) or not res.get("ok"):
            err_code = res.get("error", default_err) if isinstance(res, dict) else default_err
            return {
                "ok": False,
                "vault_id": vault_id,
                "target_id": resolved_tid,
                "origin": bound_origin,
                "error": str(err_code),
            }
        return {
            "ok": True,
            "vault_id": vault_id,
            "target_id": resolved_tid,
            "origin": bound_origin,
            "filled_fields": res.get("filled_fields", []),
        }

    def fill_credential(
        self,
        cdp: CDPBridge,
        target_id: str | None,
        vault_id: str,
        *,
        agent_id: str = "luminara-agent",
    ) -> dict[str, Any]:
        """Perform origin-verified, model-blind credential autofill across main doc & same-origin iframes."""
        def _build_script(entry: dict[str, Any]) -> str:
            password = entry.get("password", "")
            if not password:
                raise ValueError(f"Vault entry {vault_id!r} does not contain a password")
            bound_origin = entry["origin"]
            username = entry.get("username", "")
            return f"""
(() => {{
  try {{
    const expectedOrigin = {json.dumps(bound_origin)};
    if (window.location.origin.toLowerCase() !== expectedOrigin.toLowerCase()) {{
      return {{ ok: false, error: 'origin_mismatch_in_page' }};
    }}
    {_VAULT_DOM_HELPERS_JS}
    const docs = collectSameOriginDocs(expectedOrigin);
    for (const ctx of docs) {{
      const passInputs = Array.from(ctx.doc.querySelectorAll('input[type="password"]')).filter(
        el => !el.disabled && !el.readOnly && el.getBoundingClientRect().width > 0
      );
      if (passInputs.length === 0) continue;
      const passEl = passInputs[0];
      const filled = [];
      const userVal = {json.dumps(username)};
      if (userVal) {{
        const scope = passEl.form || passEl.closest('form, [role="dialog"], main, section') || ctx.doc;
        const userSel = 'input[autocomplete*="username" i], input[type="email"], input[name*="user" i], input[name*="email" i], input[name*="login" i], input[id*="user" i], input[id*="email" i], input[type="text"]';
        const userInputs = Array.from(scope.querySelectorAll(userSel)).filter(
          el => el !== passEl && el.type !== 'password' && !el.disabled && !el.readOnly && el.getBoundingClientRect().width > 0
        );
        if (userInputs.length > 0) {{
          setVal(ctx.win, userInputs[0], userVal);
          filled.push('username');
        }}
      }}
      setVal(ctx.win, passEl, {json.dumps(password)});
      filled.push('password');
      return {{ ok: true, filled_fields: filled, origin: window.location.origin }};
    }}
    return {{ ok: false, error: 'no_visible_password_field' }};
  }} catch (_err) {{
    return {{ ok: false, error: 'vault_dom_injection_failed' }};
  }}
}})()
"""

        return self._execute_origin_pinned_dom(
            cdp,
            target_id,
            vault_id,
            agent_id=agent_id,
            script_builder=_build_script,
            default_err="vault_fill_failed",
        )

    def fill_totp(
        self,
        cdp: CDPBridge,
        target_id: str | None,
        vault_id: str,
        *,
        agent_id: str = "luminara-agent",
    ) -> dict[str, Any]:
        """Generate an origin-verified RFC 6238 TOTP code in-memory and inject into 1-box or 6-box OTP fields."""
        def _build_script(entry: dict[str, Any]) -> str:
            totp_secret = entry.get("totp_secret", "")
            if not totp_secret:
                raise ValueError(f"Vault entry {vault_id!r} does not have a TOTP secret configured")
            otp_code = generate_totp_code(totp_secret)
            self.redactor.register_secret(otp_code)
            bound_origin = entry["origin"]
            return f"""
(() => {{
  try {{
    const expectedOrigin = {json.dumps(bound_origin)};
    const code = {json.dumps(otp_code)};
    if (window.location.origin.toLowerCase() !== expectedOrigin.toLowerCase()) {{
      return {{ ok: false, error: 'origin_mismatch_in_page' }};
    }}
    {_VAULT_DOM_HELPERS_JS}
    const docs = collectSameOriginDocs(expectedOrigin);
    const otpSel = 'input[autocomplete="one-time-code"], input[name*="otp" i], input[name*="totp" i], input[name*="code" i], input[name*="2fa" i], input[name*="mfa" i], input[id*="otp" i], input[id*="code" i], input[inputmode="numeric"]';
    for (const ctx of docs) {{
      const candidates = Array.from(ctx.doc.querySelectorAll(otpSel)).filter(
        el => el.type !== 'password' && !el.disabled && !el.readOnly && el.getBoundingClientRect().width > 0
      );
      if (candidates.length >= code.length && candidates.slice(0, code.length).every(el => el.maxLength === 1)) {{
        for (let i = 0; i < code.length; i++) setVal(ctx.win, candidates[i], code[i]);
        return {{ ok: true, filled_fields: ['one_time_code_split'], origin: window.location.origin }};
      }}
      if (candidates.length > 0) {{
        setVal(ctx.win, candidates[0], code);
        return {{ ok: true, filled_fields: ['one_time_code'], origin: window.location.origin }};
      }}
    }}
    return {{ ok: false, error: 'no_visible_totp_field' }};
  }} catch (_err) {{
    return {{ ok: false, error: 'totp_dom_injection_failed' }};
  }}
}})()
"""

        return self._execute_origin_pinned_dom(
            cdp,
            target_id,
            vault_id,
            agent_id=agent_id,
            script_builder=_build_script,
            default_err="totp_fill_failed",
        )
