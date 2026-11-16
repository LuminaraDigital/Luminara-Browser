"""Canonical Security Primitives: Path Containment (`safe_join`) & Loopback HTTP Guard (`forge/http_base.py`).

Eliminates duplicated HTTP scaffolding across `studio.py` and `agent_server.py` while enforcing:
1. `safe_join`: Blocks `..` traversal, Windows drive resets (`C:/...`), and POSIX root anchors (`/...`).
2. `LoopbackHTTPServer` + `LoopbackJSONHandler`:
   - Strict `Host` validation (`127.0.0.1`, `localhost`, `[::1]`) blocking DNS rebinding.
   - Cross-site & `<iframe sandbox="allow-scripts">` (`Origin: null`) rejection unless authenticated with
     `X-Luminara-UI-Key` or `Authorization: Bearer ...`.
   - Mandatory `Content-Type: application/json` on `POST` (blocks `<form>` / `no-cors` CSRF).
   - Bounded `MAX_BODY_BYTES = 2 MiB` and `timeout = 30.0s` (blocks OOM & slowloris thread leaks).
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
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


def ensure_local_ui_key(forge_root: Path) -> str:
    """Load or generate a persistent 256-bit local UI key authenticating local `file://` pages."""
    out_dir = forge_root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    key_file = out_dir / "local_ui_key.txt"
    if key_file.exists():
        existing = key_file.read_text(encoding=ENCODING).strip()
        if len(existing) >= 32:
            return existing
    token = secrets.token_hex(32)
    key_file.write_text(token + "\n", encoding=ENCODING, newline="\n")
    return token


def _extract_host_only(host_header: str) -> str:
    h = (host_header or "").strip().lower()
    if not h:
        return ""
    if h.startswith("["):
        end = h.find("]")
        return h[: end + 1] if end != -1 else h
    return h.split(":", 1)[0]


def is_valid_loopback_host(host_header: str) -> bool:
    return _extract_host_only(host_header) in ALLOWED_LOOPBACK_HOSTS


class LoopbackHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True


class LoopbackJSONHandler(BaseHTTPRequestHandler):
    """Hardened loopback HTTP handler shared by Studio (`:8795`) and Agent Daemon (`:8796`)."""

    timeout = 30.0
    local_ui_key: str = ""
    bearer_token: str = ""
    allow_extension_origins: bool = True

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _matched_cors_origin(self) -> str | None:
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            return None
        ui_hdr = (self.headers.get("X-Luminara-UI-Key") or "").strip()
        has_valid_ui_key = bool(self.local_ui_key) and secrets.compare_digest(ui_hdr, self.local_ui_key)
        if self.allow_extension_origins and origin.startswith("chrome-extension://"):
            return origin if has_valid_ui_key else None
        if origin in ("null", "file://"):
            return "null" if has_valid_ui_key else None
        parsed = urllib.parse.urlparse(origin)
        if (parsed.hostname or "").lower() in ("127.0.0.1", "localhost", "::1"):
            return origin
        return None

    def check_loopback_security(self, *, is_post: bool = False) -> bool:
        # 1. Always enforce Host header against DNS rebinding
        if not is_valid_loopback_host(self.headers.get("Host", "")):
            self.send_json({"error": "Forbidden Host header (DNS rebinding guard)"}, status=403)
            return False

        # 2. Enforce Origin / Sec-Fetch-Site against cross-site & sandboxed-iframe attacks
        origin = (self.headers.get("Origin") or "").strip()
        sec_site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()

        if origin:
            if self._matched_cors_origin() is None:
                self.send_json({"error": f"Forbidden Origin: {origin}"}, status=403)
                return False
        elif sec_site not in ("", "same-origin", "same-site", "none"):
            self.send_json({"error": f"Forbidden Sec-Fetch-Site: {sec_site}"}, status=403)
            return False

        # 3. Require Content-Type: application/json on POST to defeat <form> / no-cors CSRF
        if is_post:
            ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if ctype != "application/json":
                self.send_json({"error": "POST requires Content-Type: application/json"}, status=415)
                return False

        # 4. Enforce optional Bearer Passport token (local built-in UI key also satisfies local UI calls)
        if self.bearer_token:
            auth = (self.headers.get("Authorization") or "").strip()
            ui_hdr = (self.headers.get("X-Luminara-UI-Key") or "").strip()
            valid_bearer = auth.startswith("Bearer ") and secrets.compare_digest(auth[7:].strip(), self.bearer_token)
            valid_ui = bool(self.local_ui_key) and secrets.compare_digest(ui_hdr, self.local_ui_key)
            if not (valid_bearer or valid_ui):
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
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")

    def send_json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode(ENCODING)
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
        parsed = json.loads(self.rfile.read(length).decode(ENCODING))
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
