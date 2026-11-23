"""Network Mutation Firewall & Savepoint Dry-Run Diff Preview (`forge/mutation_firewall.py`).

Uses Chromium's `Fetch.enable` interception via `MultiplexedCDPPool` (`Fetch.requestPaused`)
to intercept irreversible HTTP state mutations (`POST`, `PUT`, `PATCH`, `DELETE`) initiated
by autonomous agents before bytes leave Chromium's NetworkService:
- Classifies mutation risk (`HIGH` for `DELETE`, billing/checkout/payment/auth/admin paths;
  `MEDIUM` for standard `POST`/`PUT`/`PATCH`).
- Redacts all secrets/tokens/passwords via `LuminaraRedactor` before emitting the diff preview.
- Pauses with `PAUSED_MUTATION_APPROVAL` until the human explicitly approves (`Fetch.continueRequest`)
  or rejects (`Fetch.failRequest(BlockedByClient)`).
"""

from __future__ import annotations

import fnmatch
import re
import secrets
import threading
import time
from typing import Any
import urllib.parse

from .cdp_client import CDPBridge
from .luminara_security import DEFAULT_REDACTOR, LuminaraRedactor

MUTATING_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_HIGH_RISK_PATH_RE = re.compile(
    r"(?i)/(?:delete|remove|destroy|drop|checkout|pay|payment|billing|charge|transfer|wire|order|confirm|reset|admin|settings/security|oauth|token)(?=$|[^a-z0-9])"
)


MAX_PENDING_MUTATIONS = 100
PENDING_TTL_MS = 300_000


def classify_mutation_risk(method: str, url: str) -> str:
    m = (method or "GET").upper()
    if m == "DELETE":
        return "HIGH"
    parsed = urllib.parse.urlparse(url or "")
    decoded_path = urllib.parse.unquote(parsed.path or "")
    if _HIGH_RISK_PATH_RE.search(decoded_path):
        return "HIGH"
    if m in ("POST", "PUT", "PATCH"):
        return "MEDIUM"
    return "LOW"


class NetworkMutationFirewall:
    """Savepoint firewall guarding mutating HTTP requests on agent-controlled browser tabs."""

    def __init__(self, cdp: CDPBridge, redactor: LuminaraRedactor | None = None) -> None:
        self.cdp = cdp
        self.redactor = redactor or DEFAULT_REDACTOR
        self._lock = threading.Lock()
        self._guarded_targets: dict[str, str] = {}
        self._allowed_domains: set[str] = set()
        self._pending: dict[str, dict[str, Any]] = {}
        self._history: list[dict[str, Any]] = []
        if hasattr(self.cdp, "register_fetch_hook"):
            self._unsub = self.cdp.register_fetch_hook(20, "mutation_firewall", self._evaluate_fetch_hook)
        else:
            self._unsub = self.cdp.mux.subscribe("Fetch.requestPaused", self._on_request_paused)
        self._unsub_detach = self.cdp.mux.subscribe("Target.detachedFromTarget", self._on_target_detached)

    def close(self) -> None:
        for fn in (self._unsub, self._unsub_detach):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    def _evict_target_pending(self, target_id: str) -> None:
        if not target_id:
            return
        with self._lock:
            stale = [mid for mid, item in self._pending.items() if item.get("target_id") == target_id]
            for mid in stale:
                self._pending.pop(mid, None)

    def _on_target_detached(self, event: dict[str, Any]) -> None:
        t_id = str(event.get("target_id") or "")
        if t_id:
            with self._lock:
                self._guarded_targets.pop(t_id, None)
            self._evict_target_pending(t_id)

    def enable_guard(self, target_id: str | None = None, *, url_pattern: str = "*") -> dict[str, Any]:
        """Enable CDP `Fetch` request interception on `target_id`."""
        tid = self.cdp._pick_target_id(target_id)
        pat = (url_pattern or "*").strip() or "*"
        with self._lock:
            self._guarded_targets[tid] = pat
        if hasattr(self.cdp, "set_fetch_interception"):
            self.cdp.set_fetch_interception(tid, "mutation_firewall", enabled=True, url_pattern=pat)
        else:
            self.cdp.run_session(
                tid,
                [("Fetch.enable", {"patterns": [{"urlPattern": pat, "requestStage": "Request"}]})],
            )
        return {"ok": True, "target_id": tid, "guard_enabled": True, "url_pattern": pat}

    def disable_guard(self, target_id: str | None = None) -> dict[str, Any]:
        tid = self.cdp._pick_target_id(target_id)
        with self._lock:
            self._guarded_targets.pop(tid, None)
        self._evict_target_pending(tid)
        if hasattr(self.cdp, "set_fetch_interception"):
            self.cdp.set_fetch_interception(tid, "mutation_firewall", enabled=False)
        else:
            try:
                self.cdp.run_session(tid, [("Fetch.disable", {})])
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, "target_id": tid, "guard_enabled": False}

    @staticmethod
    def _normalize_host(url_or_host: str) -> str:
        raw = (url_or_host or "").strip()
        if not raw:
            return ""
        host = (urllib.parse.urlparse(raw).hostname or "") if "://" in raw else raw
        clean = host.strip().lower().rstrip(".")
        if not clean or any(ch in clean for ch in ("/", "\\", "*", " ", "\t", "\r", "\n", "@")):
            return ""
        return clean

    def allow_domain(self, host: str) -> str:
        """Allow non-HIGH-risk mutating requests for an explicitly human-approved domain."""
        norm = self._normalize_host(host)
        if not norm:
            raise ValueError(f"Invalid domain for allow_site: {host!r}")
        with self._lock:
            self._allowed_domains.add(norm)
        return norm

    def is_domain_allowed(self, url_or_host: str) -> bool:
        norm = self._normalize_host(url_or_host)
        if not norm:
            return False
        with self._lock:
            return norm in self._allowed_domains

    def _evaluate_fetch_hook(self, event: dict[str, Any]) -> str | None:
        """Priority-20 hook on `CDPBridge`: pauses mutating HTTP requests on guarded tabs."""
        params = event.get("params") or {}
        session_id = str(event.get("session_id") or "")
        target_id = str(event.get("target_id") or "")
        request_id = str(params.get("requestId") or "")
        req = params.get("request") or {}
        method = str(req.get("method") or "GET").upper()
        url = str(req.get("url") or "")

        is_response_stage = ("responseStatusCode" in params) or ("responseErrorReason" in params)
        with self._lock:
            pattern = self._guarded_targets.get(target_id) if target_id else None

        if is_response_stage or (pattern is None) or (method not in MUTATING_HTTP_METHODS):
            return None
        if pattern != "*" and not fnmatch.fnmatchcase(url, pattern):
            return None

        risk = classify_mutation_risk(method, url)
        if self.is_domain_allowed(url) and risk != "HIGH":
            audit = {
                "mutation_id": f"allow_{secrets.token_hex(4)}",
                "status": "AUTO_ALLOWED_SITE",
                "risk_level": risk,
                "method": method,
                "url": self.redactor.redact_text(url),
                "target_id": target_id,
                "request_id": request_id,
                "resolved_at_ms": int(time.time() * 1000),
            }
            with self._lock:
                self._history.append(audit)
                if len(self._history) > 100:
                    del self._history[:-100]
            return None

        raw_post = str(req.get("postData") or "")
        if not raw_post and isinstance(req.get("postDataEntries"), list):
            import base64

            parts_b: list[str] = []
            for entry_p in req["postDataEntries"][:8]:
                if isinstance(entry_p, dict) and isinstance(entry_p.get("bytes"), str):
                    try:
                        parts_b.append(base64.b64decode(entry_p["bytes"]).decode("utf-8", errors="replace"))
                    except Exception:  # noqa: BLE001
                        pass
            raw_post = "".join(parts_b)

        self.record_intercepted_mutation(
            request_id=request_id,
            session_id=session_id,
            target_id=target_id,
            method=method,
            url=url,
            headers=req.get("headers") if isinstance(req.get("headers"), dict) else {},
            post_data=raw_post,
        )
        return "PAUSE"

    def _on_request_paused(self, event: dict[str, Any]) -> None:
        params = event.get("params") or {}
        session_id = str(event.get("session_id") or "")
        request_id = str(params.get("requestId") or "")
        verdict = self._evaluate_fetch_hook(event)
        if verdict != "PAUSE" and session_id and request_id:
            try:
                self.cdp.mux.send_command_async("Fetch.continueRequest", {"requestId": request_id}, session_id=session_id)
            except Exception:  # noqa: BLE001
                pass

    def _sweep_expired(self) -> None:
        cutoff_ms = int(time.time() * 1000) - PENDING_TTL_MS
        to_fail: list[dict[str, Any]] = []
        with self._lock:
            expired_ids = [mid for mid, e in self._pending.items() if int(e.get("created_at_ms") or 0) < cutoff_ms]
            for mid in expired_ids:
                item = self._pending.pop(mid, None)
                if item:
                    to_fail.append(item)
            while len(self._pending) >= MAX_PENDING_MUTATIONS:
                oldest_id = next(iter(self._pending))
                item = self._pending.pop(oldest_id, None)
                if item:
                    to_fail.append(item)
        for item in to_fail:
            sid = str(item.get("session_id") or "")
            rid = str(item.get("request_id") or "")
            if sid and rid:
                try:
                    self.cdp.mux.send_command_async(
                        "Fetch.failRequest",
                        {"requestId": rid, "errorReason": "BlockedByClient"},
                        session_id=sid,
                    )
                except Exception:  # noqa: BLE001
                    pass

    def record_intercepted_mutation(
        self,
        *,
        request_id: str,
        session_id: str,
        target_id: str,
        method: str,
        url: str,
        headers: dict[str, Any] | None = None,
        post_data: str = "",
    ) -> dict[str, Any]:
        """Store a redacted Savepoint Diff Preview for a paused mutating HTTP request."""
        self._sweep_expired()
        mutation_id = f"mut_{secrets.token_hex(5)}"
        clean_headers = self.redactor.redact_payload(
            {str(k): str(v)[:180] for k, v in (headers or {}).items()}
        )
        clean_body = self.redactor.redact_text(post_data)[:1200]
        clean_url = self.redactor.redact_text(url)
        entry = {
            "mutation_id": mutation_id,
            "status": "PAUSED_MUTATION_APPROVAL",
            "risk_level": classify_mutation_risk(method, url),
            "method": method.upper(),
            "url": clean_url,
            "target_id": target_id,
            "request_id": request_id,
            "session_id": session_id,
            "headers_redacted": clean_headers,
            "body_preview": clean_body,
            "created_at_ms": int(time.time() * 1000),
        }
        with self._lock:
            self._pending[mutation_id] = entry
        return self._public_view(entry)

    @staticmethod
    def _public_view(entry: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in entry.items() if k != "session_id"}

    def list_pending(self, target_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = [
                self._public_view(e)
                for e in self._pending.values()
                if target_id is None or e.get("target_id") == target_id
            ]
        items.sort(key=lambda x: x["created_at_ms"])
        return items

    def recent_decisions(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history[-max(1, limit) :])

    def resolve_mutation(self, mutation_id: str, *, decision: str) -> dict[str, Any]:
        """Approve (`Fetch.continueRequest`) or reject (`Fetch.failRequest`) a paused mutation."""
        norm = (decision or "").strip().lower()
        if norm not in ("approve", "reject"):
            raise ValueError(f"Decision must be 'approve' or 'reject' (got {decision!r})")
        with self._lock:
            entry = self._pending.pop(mutation_id, None)
        if not entry:
            raise ValueError(f"Unknown or already resolved mutation_id: {mutation_id!r}")

        cdp_dispatched = False
        cdp_error = ""
        session_id = str(entry.get("session_id") or "")
        request_id = str(entry.get("request_id") or "")
        if session_id and request_id:
            try:
                if norm == "approve":
                    self.cdp.mux.send_command("Fetch.continueRequest", {"requestId": request_id}, session_id=session_id, timeout=5.0)
                else:
                    self.cdp.mux.send_command(
                        "Fetch.failRequest",
                        {"requestId": request_id, "errorReason": "BlockedByClient"},
                        session_id=session_id,
                        timeout=5.0,
                    )
                cdp_dispatched = True
            except Exception as exc:  # noqa: BLE001
                cdp_error = str(exc)

        resolved_status = (
            ("APPROVED" if norm == "approve" else "REJECTED")
            if (not session_id or not request_id or cdp_dispatched)
            else "TARGET_CLOSED"
        )
        resolved = {
            **self._public_view(entry),
            "status": resolved_status,
            "resolved_at_ms": int(time.time() * 1000),
            "cdp_dispatched": cdp_dispatched,
            **({"cdp_error": cdp_error} if cdp_error else {}),
        }
        with self._lock:
            self._history.append(resolved)
            if len(self._history) > 100:
                del self._history[:-100]
        return resolved

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "guarded_targets": sorted(self._guarded_targets),
                "allowed_domains": sorted(self._allowed_domains),
                "pending_count": len(self._pending),
                "pending": [self._public_view(e) for e in self._pending.values()],
                "recent_decisions": list(self._history[-10:]),
            }
