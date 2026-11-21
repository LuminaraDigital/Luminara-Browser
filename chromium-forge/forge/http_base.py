"""Canonical Security Primitives: Path Containment (`safe_join`) & Loopback HTTP Guard (`forge/http_base.py`).

Eliminates duplicated HTTP scaffolding across `studio.py` and `agent_server.py` while enforcing:
1. `safe_join`: Blocks `..` traversal, Windows drive resets (`C:/...`), and POSIX root anchors (`/...`).
2. `LoopbackHTTPServer` + `LoopbackJSONHandler`:
   - Strict `Host` validation (`127.0.0.1`, `localhost`, `[::1]`) blocking DNS rebinding.
   - Exact port-matching on unkeyed loopback `Origin` headers (blocks cross-port local dev server CSRF/scraping)
     and rejects `Sec-Fetch-Site: same-site` / `cross-site` and `Origin: null` unless authenticated.
   - Mandatory `Content-Type: application/json` on `POST` (blocks `<form>` / `no-cors` CSRF).
   - Bounded `MAX_BODY_BYTES = 2 MiB`, `0o600` atomic `local_ui_key.txt`, and `timeout = 30.0s`.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import secrets
from typing import Any
import urllib.parse

ENCODING = "utf-8"
MAX_BODY_BYTES = 2 * 1024 * 1024
ALLOWED_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})


class SafePathError(ValueError):
    """Raised when an archive, patch, list, or checkpoint path escapes its sandbox root."""


def safe_join(root: Path, *rel_parts: str) -> Path:
    """Resolve `rel_parts` strictly inside `root`, rejecting drive letters, root anchors, and `..`."""
    root_resolved = root.resolve()
    cleaned_segments: list[str] = []
    for raw in rel_parts:
        norm = raw.replace("\\", "/")
        win_probe = PureWindowsPath(raw)
        posix_probe = PurePosixPath(norm)
        if win_probe.drive or win_probe.root or posix_probe.is_absolute():
            raise SafePathError(f"Absolute or drive-anchored path rejected: {raw!r}")
        for seg in posix_probe.parts:
            if seg in ("", "."):
                continue
            if seg == ".." or ":" in seg:
                raise SafePathError(f"Path traversal segment rejected in {raw!r}")
            cleaned_segments.append(seg)

    candidate = root_resolved.joinpath(*cleaned_segments).resolve()
    if candidate != root_resolved and not candidate.is_relative_to(root_resolved):
        raise SafePathError(f"Resolved path {candidate} escapes root {root_resolved}")
    return candidate


def atomic_write_private(path: Path, content: str) -> None:
    """Atomically write UTF-8 text with owner-only (`0o600`) file permissions (zero TOCTOU)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding=ENCODING, newline="\n") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp_path), str(path))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def ensure_local_ui_key(forge_root: Path) -> str:
    """Load or atomically generate an owner-only (`0o600`) 256-bit local UI key."""
    out_dir = forge_root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    key_file = out_dir / "local_ui_key.txt"
    if key_file.exists():
        existing = key_file.read_text(encoding=ENCODING).strip()
        if len(existing) >= 32:
            return existing
    token = secrets.token_hex(32)
    atomic_write_private(key_file, token + "\n")
    return token


def _extract_host_only(host_header: str) -> str:
    h = (host_header or "").strip().lower().rstrip(".")
    if not h:
        return ""
    if h.startswith("["):
        end = h.find("]")
        return h[: end + 1] if end != -1 else h
    return h.split(":", 1)[0].rstrip(".")


def is_valid_loopback_host(host_header: str) -> bool:
    return _extract_host_only(host_header) in ALLOWED_LOOPBACK_HOSTS


class LoopbackHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        import sys

        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class LoopbackJSONHandler(BaseHTTPRequestHandler):
    """Hardened loopback HTTP handler shared by Studio (`:8795`) and Agent Daemon (`:8796`)."""

    timeout = 30.0
    local_ui_key: str = ""
    bearer_token: str = ""
    session_verifier: Any = None
    allow_extension_origins: bool = True
    forge_root_dir: Path | None = None
    public_get_paths: frozenset[str] = frozenset()

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _has_static_ui_key(self, ui_hdr: str) -> bool:
        if not ui_hdr:
            return False
        if self.local_ui_key and secrets.compare_digest(ui_hdr, self.local_ui_key):
            return True
        if self.forge_root_dir is not None:
            fresh_key = ensure_local_ui_key(self.forge_root_dir)
            if fresh_key and secrets.compare_digest(ui_hdr, fresh_key):
                self.__class__.local_ui_key = fresh_key
                return True
        return False

    def _has_valid_ui_key(self, ui_hdr: str) -> bool:
        if not ui_hdr:
            return False
        if callable(self.session_verifier) and self.session_verifier(ui_hdr, required_scope="ui"):
            return True
        return self._has_static_ui_key(ui_hdr)

    def _has_valid_bearer(self) -> bool:
        auth = (self.headers.get("Authorization") or "").strip()
        if not auth.startswith("Bearer "):
            return False
        tok = auth[7:].strip()
        if not tok:
            return False
        if callable(self.session_verifier) and self.session_verifier(tok):
            return True
        return bool(self.bearer_token and secrets.compare_digest(tok, self.bearer_token))

    def _is_authenticated_caller(self) -> bool:
        ui_hdr = (self.headers.get("X-Luminara-UI-Key") or "").strip()
        return self._has_valid_ui_key(ui_hdr) or self._has_valid_bearer()

    def _matched_cors_origin(self) -> str | None:
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            return None
        authed = self._is_authenticated_caller()
        if self.allow_extension_origins and origin.startswith("chrome-extension://"):
            return origin if authed else None
        if origin in ("null", "file://"):
            return "null" if authed else None
        parsed = urllib.parse.urlparse(origin)
        host = (parsed.hostname or "").lower().rstrip(".")
        if host in ("127.0.0.1", "localhost", "::1"):
            srv_port = getattr(self.server, "server_port", None)
            eff_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if authed or (srv_port is not None and eff_port == srv_port):
                return origin
        return None

    def _drain_small_body(self) -> None:
        """Drain small unread POST bodies before returning early 4xx responses (prevents Windows TCP RST / WinError 10054)."""
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if 0 < length <= 65536:
                self.rfile.read(length)
        except Exception:  # noqa: BLE001
            pass

    def check_loopback_security(self, *, is_post: bool = False) -> bool:
        # 1. Always enforce Host header against DNS rebinding
        if not is_valid_loopback_host(self.headers.get("Host", "")):
            if is_post:
                self._drain_small_body()
            self.send_json({"error": "Forbidden Host header (DNS rebinding guard)"}, status=403)
            return False

        # 2. Enforce Origin / Sec-Fetch-Site against cross-site, cross-port, & sandboxed-iframe attacks
        origin = (self.headers.get("Origin") or "").strip()
        sec_site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        authed = self._is_authenticated_caller()

        if origin:
            if self._matched_cors_origin() is None:
                if is_post:
                    self._drain_small_body()
                self.send_json({"error": f"Forbidden Origin: {origin}"}, status=403)
                return False
        elif not authed and sec_site not in ("", "same-origin", "none"):
            if is_post:
                self._drain_small_body()
            self.send_json({"error": f"Forbidden Sec-Fetch-Site: {sec_site}"}, status=403)
            return False

        # 3. Require Content-Type: application/json on POST to defeat <form> / no-cors CSRF
        if is_post:
            ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if ctype != "application/json":
                self._drain_small_body()
                self.send_json({"error": "POST requires Content-Type: application/json"}, status=415)
                return False

        # 4. Enforce optional Bearer Passport token (top-level GET to UI pages / manifest remains navigable)
        if self.bearer_token and not authed:
            req_path = urllib.parse.urlparse(self.path).path
            is_top_level_ui_get = (
                not is_post
                and not origin
                and sec_site in ("", "same-origin", "none")
                and req_path in self.public_get_paths
            )
            if not is_top_level_ui_get:
                if is_post:
                    self._drain_small_body()
                self.send_json({"error": "Missing or invalid Luminara Agent Passport token"}, status=401)
                return False

        return True

    def write_cors_headers(self, *, is_preflight: bool = False) -> None:
        origin = (self.headers.get("Origin") or "").strip()
        if is_preflight and origin in ("null", "file://"):
            self.send_header("Access-Control-Allow-Origin", "null")
        elif is_preflight and self.allow_extension_origins and origin.startswith("chrome-extension://"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        else:
            matched = self._matched_cors_origin()
            if matched:
                self.send_header("Access-Control-Allow-Origin", matched)
                self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Luminara-UI-Key")
        if is_preflight and (self.headers.get("Access-Control-Request-Private-Network") or "").strip().lower() == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")

    def send_json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(ENCODING)
        self.send_response(status)
        self.write_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_text(self, text: str, content_type: str = "text/plain; charset=utf-8", status: int = 200) -> None:
        raw = text.encode(ENCODING)
        self.send_response(status)
        self.write_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_bytes(self, raw: bytes, content_type: str = "application/octet-stream", *, filename: str = "", status: int = 200) -> None:
        self.send_response(status)
        self.write_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        if filename:
            safe_fn = "".join(ch for ch in filename if ch.isalnum() or ch in "._-")[:96] or "download.bin"
            self.send_header("Content-Disposition", f'attachment; filename="{safe_fn}"')
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json_dict(self) -> dict[str, Any]:
        raw_len = self.headers.get("Content-Length", "0") or "0"
        try:
            length = int(raw_len)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length header") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError(f"Request body exceeds {MAX_BODY_BYTES} byte limit")
        if length == 0:
            return {}

        def _reject_nonfinite(constant: str) -> None:
            raise ValueError(f"Non-standard JSON number rejected: {constant}")

        parsed = json.loads(self.rfile.read(length).decode(ENCODING), parse_constant=_reject_nonfinite)
        if not isinstance(parsed, dict):
            raise ValueError("JSON request body must be a JSON object")
        return parsed

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not is_valid_loopback_host(self.headers.get("Host", "")):
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self.write_cors_headers(is_preflight=True)
        self.end_headers()
