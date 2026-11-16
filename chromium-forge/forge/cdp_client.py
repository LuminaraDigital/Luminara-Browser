"""Pure-stdlib Chrome DevTools Protocol (CDP) WebSocket Bridge & Tab Lease Manager (`forge/cdp_client.py`).

Hardened for concurrent multi-agent & parallel `BulkEngine` workloads:
- Browser-level `Target.createTarget` (`version_info()["webSocketDebuggerUrl"]`) prevents `tabs[0]` WS collisions.
- Per-target `RLock` serializes concurrent sessions on the same tab without throwing exclusive-debugger errors.
- `validate_navigation_url` blocks `javascript:`, `data:`, `chrome:`, cloud metadata (`169.254.169.254`), and control ports.
- RFC 6455 control-frame clamping (`<= 125` bytes), bounded handshake buffer, and monotonic session deadlines.
"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import hashlib
import json
import os
import socket
import struct
import threading
import time
from typing import Any
import urllib.parse
import urllib.request

ENCODING = "utf-8"
_BLOCKED_NAV_SCHEMES = frozenset({"javascript", "vbscript", "data", "chrome", "chrome-extension", "devtools", "view-source"})
_INTERNAL_CONTROL_PORTS = frozenset({8795, 8796, 9229})


class CDPError(RuntimeError):
    """Raised when a CDP target, URL guard, or WebSocket command returns an error."""


def validate_navigation_url(
    url: str,
    *,
    allow_file: bool = True,
    blocked_ports: frozenset[int] = _INTERNAL_CONTROL_PORTS,
) -> str:
    """Validate target URL before opening or navigating a tab (blocks SSRF & dangerous schemes)."""
    cleaned = (url or "").strip()
    if not cleaned:
        raise CDPError("Navigation URL must be non-empty")
    if cleaned == "about:blank":
        return cleaned

    parsed = urllib.parse.urlparse(cleaned)
    scheme = (parsed.scheme or "").lower()
    if scheme in _BLOCKED_NAV_SCHEMES:
        raise CDPError(f"Blocked unsafe navigation scheme: {scheme}:")
    if scheme == "file":
        if not allow_file:
            raise CDPError("file:// navigation is not permitted for untrusted planner decisions")
        return cleaned
    if scheme not in ("http", "https"):
        raise CDPError(f"Unsupported navigation URL scheme: {scheme!r}")

    host = (parsed.hostname or "").lower()
    if host in ("169.254.169.254", "metadata.google.internal", "100.100.100.200"):
        raise CDPError(f"Blocked cloud metadata SSRF host: {host}")
    if host in ("127.0.0.1", "localhost", "::1") and parsed.port in blocked_ports:
        raise CDPError(f"Blocked navigation to internal control plane port: {parsed.port}")
    return cleaned


@dataclass
class TabLease:
    target_id: str
    agent_id: str
    acquired_at: float
    expires_at: float
    purpose: str = ""


class TabLeaseManager:
    """Advisory per-tab co-presence lease manager preventing agent-vs-agent collisions while allowing human override."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._leases: dict[str, TabLease] = {}

    def acquire(self, target_id: str, agent_id: str, ttl_sec: float = 60.0, purpose: str = "") -> TabLease:
        now = time.time()
        with self._lock:
            existing = self._leases.get(target_id)
            if existing and existing.expires_at > now and existing.agent_id != agent_id:
                raise CDPError(
                    f"Tab {target_id} is currently leased by agent {existing.agent_id!r} "
                    f"until {existing.expires_at:.0f}"
                )
            lease = TabLease(
                target_id=target_id,
                agent_id=agent_id,
                acquired_at=now,
                expires_at=now + ttl_sec,
                purpose=purpose,
            )
            self._leases[target_id] = lease
            return lease

    def check_allowed(self, target_id: str, agent_id: str) -> None:
        now = time.time()
        with self._lock:
            existing = self._leases.get(target_id)
            if existing and existing.expires_at > now and existing.agent_id != agent_id:
                raise CDPError(f"Tab {target_id} is leased by {existing.agent_id!r}; use human_takeover to preempt")

    def release(self, target_id: str, agent_id: str | None = None) -> bool:
        with self._lock:
            existing = self._leases.get(target_id)
            if not existing:
                return False
            if agent_id is not None and existing.agent_id != agent_id:
                return False
            del self._leases[target_id]
            return True

    def force_human_override(self, target_id: str) -> None:
        """Human interaction always preempts any active agent lease immediately."""
        with self._lock:
            self._leases.pop(target_id, None)

    def get_active(self, target_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            lease = self._leases.get(target_id)
            if not lease:
                return None
            if lease.expires_at <= now:
                del self._leases[target_id]
                return None
            return asdict(lease)


class _RFC6455Socket:
    """Minimal RFC 6455 client WebSocket over loopback TCP (zero external dependencies)."""

    MAX_HANDSHAKE_BYTES = 65536

    def __init__(self, ws_url: str, timeout: float = 15.0) -> None:
        parsed = urllib.parse.urlparse(ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        try:
            self._sock = socket.create_connection((host, port), timeout=timeout)
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            handshake = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                f"Origin: http://{host}:{port}\r\n\r\n"
            )
            self._sock.sendall(handshake.encode("ascii"))

            header_buf = bytearray()
            while b"\r\n\r\n" not in header_buf:
                if len(header_buf) > self.MAX_HANDSHAKE_BYTES:
                    self._sock.close()
                    raise CDPError("CDP WebSocket handshake headers exceeded 64 KiB")
                chunk = self._sock.recv(4096)
                if not chunk:
                    self._sock.close()
                    raise CDPError("EOF during CDP WebSocket handshake")
                header_buf.extend(chunk)
        except (TimeoutError, OSError) as exc:
            sock = getattr(self, "_sock", None)
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            raise CDPError(f"CDP WebSocket connect error: {exc}") from exc

        sep = header_buf.index(b"\r\n\r\n")
        status_line = header_buf[:sep].splitlines()[0].decode("ascii", errors="replace")
        if "101" not in status_line:
            self._sock.close()
            raise CDPError(f"CDP WebSocket upgrade rejected: {status_line}")

        expected_accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if expected_accept.encode("ascii") not in header_buf[:sep]:
            self._sock.close()
            raise CDPError("Invalid Sec-WebSocket-Accept in CDP handshake")

        self._rx_buf = bytearray(header_buf[sep + 4 :])

    def set_remaining_timeout(self, remaining: float) -> None:
        self._sock.settimeout(max(0.05, remaining))

    def _read_exact(self, count: int) -> bytes:
        try:
            while len(self._rx_buf) < count:
                chunk = self._sock.recv(65536)
                if not chunk:
                    raise CDPError("CDP WebSocket closed unexpectedly")
                self._rx_buf.extend(chunk)
        except (TimeoutError, OSError) as exc:
            raise CDPError(f"CDP WebSocket read timeout/error: {exc}") from exc
        out = bytes(self._rx_buf[:count])
        del self._rx_buf[:count]
        return out

    def send_text(self, text: str) -> None:
        payload = text.encode(ENCODING)
        mask_key = os.urandom(4)
        length = len(payload)
        header = bytearray([0x81])  # FIN=1, opcode=1 (text)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask_key)
        masked = bytes(b ^ mask_key[i & 3] for i, b in enumerate(payload))
        try:
            self._sock.sendall(bytes(header) + masked)
        except (TimeoutError, OSError) as exc:
            raise CDPError(f"CDP WebSocket write error: {exc}") from exc

    def recv_text(self) -> str:
        fragments: list[bytes] = []
        while True:
            b0, b1 = self._read_exact(2)
            fin = bool(b0 & 0x80)
            opcode = b0 & 0x0F
            masked = bool(b1 & 0x80)
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            mask_key = self._read_exact(4) if masked else b""
            data = self._read_exact(length)
            if masked:
                data = bytes(b ^ mask_key[i & 3] for i, b in enumerate(data))

            if opcode == 0x8:  # Close
                raise CDPError("CDP WebSocket closed by browser")
            if opcode == 0x9:  # Ping -> Pong (RFC 6455 §5.5: max 125 bytes on control frames)
                pong_body = data[:125]
                pong = bytearray([0x8A, 0x80 | len(pong_body)])
                m = os.urandom(4)
                pong.extend(m)
                pong.extend(bytes(b ^ m[i & 3] for i, b in enumerate(pong_body)))
                try:
                    self._sock.sendall(bytes(pong))
                except (TimeoutError, OSError) as exc:
                    raise CDPError(f"CDP Pong write error: {exc}") from exc
                continue
            if opcode in (0x0, 0x1, 0x2):
                fragments.append(data)
                if fin:
                    return b"".join(fragments).decode(ENCODING, errors="replace")

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class CDPBridge:
    """High-level co-browsing controller talking to Chromium's loopback DevTools port."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9229) -> None:
        self.host = host
        self.port = port
        self.leases = TabLeaseManager()
        self._browser_lock = threading.RLock()
        self._target_locks_guard = threading.Lock()
        self._target_locks: dict[str, threading.RLock] = {}

    def _lock_for_target(self, target_id: str) -> threading.RLock:
        with self._target_locks_guard:
            lk = self._target_locks.get(target_id)
            if lk is None:
                lk = threading.RLock()
                self._target_locks[target_id] = lk
            return lk

    @property
    def base_http(self) -> str:
        return f"http://{self.host}:{self.port}"

    def is_alive(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_http}/json/version", timeout=1.5) as resp:
                return resp.status == 200
        except Exception:  # noqa: BLE001
            return False

    def version_info(self) -> dict[str, Any]:
        with urllib.request.urlopen(f"{self.base_http}/json/version", timeout=3.0) as resp:
            return json.loads(resp.read().decode(ENCODING))

    def list_tabs(self, include_extensions: bool = False) -> list[dict[str, Any]]:
        with urllib.request.urlopen(f"{self.base_http}/json/list", timeout=3.0) as resp:
            items = json.loads(resp.read().decode(ENCODING))
        tabs: list[dict[str, Any]] = []
        for item in items:
            t_type = item.get("type")
            url = item.get("url", "")
            if t_type != "page":
                continue
            if not include_extensions and url.startswith(("devtools://", "chrome-extension://")):
                continue
            tid = item["id"]
            tabs.append(
                {
                    "target_id": tid,
                    "title": item.get("title", ""),
                    "url": url,
                    "ws_url": item.get("webSocketDebuggerUrl", ""),
                    "lease": self.leases.get_active(tid),
                }
            )
        return tabs

    def open_tab(self, url: str = "about:blank", background: bool = True, allow_file: bool = True) -> dict[str, Any]:
        """Open a new tab via browser-level `Target.createTarget` (concurrent-safe) or `/json/new`."""
        checked_url = validate_navigation_url(url, allow_file=allow_file)
        if background:
            with self._browser_lock:
                ver = self.version_info()
                browser_ws = ver.get("webSocketDebuggerUrl", "")
                if browser_ws:
                    res = self._call_ws(
                        browser_ws,
                        "Target.createTarget",
                        {"url": checked_url, "background": True},
                    )
                    new_id = res["targetId"]
                    for tab in self.list_tabs(include_extensions=True):
                        if tab["target_id"] == new_id:
                            return tab
                    return {"target_id": new_id, "url": checked_url, "title": "", "ws_url": ""}

        # Encode '#' so urllib does not strip URL fragments on PUT /json/new?...
        encoded = urllib.parse.quote(checked_url, safe=":/?&=%+~.-_")
        req = urllib.request.Request(f"{self.base_http}/json/new?{encoded}", method="PUT")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            info = json.loads(resp.read().decode(ENCODING))
        return {
            "target_id": info["id"],
            "title": info.get("title", ""),
            "url": info.get("url", checked_url),
            "ws_url": info.get("webSocketDebuggerUrl", ""),
        }

    def close_tab(self, target_id: str) -> bool:
        self.leases.release(target_id)
        safe_tid = urllib.parse.quote(target_id, safe="")
        try:
            with urllib.request.urlopen(f"{self.base_http}/json/close/{safe_tid}", timeout=3.0) as resp:
                return resp.status == 200
        except Exception:  # noqa: BLE001
            return False

    def _pick_target_id(self, target_id: str | None) -> str:
        if target_id:
            return target_id
        tabs = self.list_tabs(include_extensions=True)
        if not tabs:
            created = self.open_tab("about:blank", background=False)
            return created["target_id"]
        normal = [t for t in tabs if not t["url"].startswith("chrome-extension://")]
        chosen = normal[0] if normal else tabs[0]
        return chosen["target_id"]

    def _resolve_ws_url(self, target_id: str | None) -> tuple[str, str]:
        tid = self._pick_target_id(target_id)
        for attempt in range(6):
            tabs = self.list_tabs(include_extensions=True)
            for t in tabs:
                if t["target_id"] == tid:
                    if t["ws_url"]:
                        return tid, t["ws_url"]
                    break
            else:
                raise CDPError(f"Tab target_id not found: {tid}")
            if attempt < 5:
                time.sleep(0.05)
        raise CDPError(f"Tab {tid} already has an exclusive debugger attached")

    def _call_ws(self, ws_url: str, method: str, params: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        sock = _RFC6455Socket(ws_url, timeout=timeout)
        try:
            msg_id = 1
            sock.send_text(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
            while True:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    raise CDPError(f"Timeout waiting for CDP {method}")
                sock.set_remaining_timeout(rem)
                frame = json.loads(sock.recv_text())
                if frame.get("id") == msg_id:
                    if "error" in frame:
                        raise CDPError(f"CDP {method} failed: {frame['error']}")
                    return frame.get("result", {})
        finally:
            sock.close()

    def run_session(
        self,
        target_id: str | None,
        commands: list[tuple[str, dict[str, Any]]],
        timeout: float = 20.0,
    ) -> tuple[str, list[dict[str, Any]]]:
        tid = self._pick_target_id(target_id)
        with self._lock_for_target(tid):
            resolved_tid, ws_url = self._resolve_ws_url(tid)
            deadline = time.monotonic() + timeout
            sock = _RFC6455Socket(ws_url, timeout=timeout)
            results: list[dict[str, Any]] = []
            try:
                for idx, (method, params) in enumerate(commands, start=1):
                    sock.send_text(json.dumps({"id": idx, "method": method, "params": params}))
                    while True:
                        rem = deadline - time.monotonic()
                        if rem <= 0:
                            raise CDPError(f"Timeout waiting for CDP {method} on tab {resolved_tid}")
                        sock.set_remaining_timeout(rem)
                        frame = json.loads(sock.recv_text())
                        if frame.get("id") == idx:
                            if "error" in frame:
                                raise CDPError(f"CDP {method} error: {frame['error']}")
                            results.append(frame.get("result", {}))
                            break
                return resolved_tid, results
            finally:
                sock.close()

    def navigate(self, target_id: str | None, url: str, settle_sec: float = 0.6, allow_file: bool = True) -> dict[str, Any]:
        checked_url = validate_navigation_url(url, allow_file=allow_file)
        tid, res = self.run_session(
            target_id,
            [
                ("Page.enable", {}),
                ("Page.navigate", {"url": checked_url}),
            ],
        )
        if settle_sec > 0:
            time.sleep(settle_sec)
        meta = self.evaluate_js(tid, "({title: document.title, url: location.href, readyState: document.readyState})")
        return {"target_id": tid, "nav": res[-1], **(meta if isinstance(meta, dict) else {})}

    def evaluate_js(self, target_id: str | None, expression: str, await_promise: bool = True) -> Any:
        _tid, res = self.run_session(
            target_id,
            [
                (
                    "Runtime.evaluate",
                    {
                        "expression": expression,
                        "returnByValue": True,
                        "awaitPromise": await_promise,
                    },
                )
            ],
        )
        payload = res[0]
        if "exceptionDetails" in payload:
            exc_info = payload["exceptionDetails"]
            desc = exc_info.get("exception", {}).get("description") or exc_info.get("text") or "Uncaught JS error"
            raise CDPError(f"JS evaluation error: {desc}")
        res_obj = payload.get("result", {})
        if "value" in res_obj:
            return res_obj["value"]
        if "unserializableValue" in res_obj:
            return res_obj["unserializableValue"]
        return None

    def capture_screenshot(self, target_id: str | None, fmt: str = "jpeg", quality: int = 75) -> tuple[str, str]:
        norm_fmt = "jpeg" if fmt.lower() == "jpg" else fmt.lower()
        if norm_fmt not in ("jpeg", "png", "webp"):
            raise CDPError(f"Unsupported screenshot format {fmt!r}: must be jpeg, png, or webp")
        params: dict[str, Any] = {"format": norm_fmt}
        if norm_fmt in ("jpeg", "webp"):
            params["quality"] = max(0, min(100, int(quality)))
        tid, res = self.run_session(target_id, [("Page.captureScreenshot", params)])
        return tid, res[0].get("data", "")

    def dispatch_mouse_click(self, target_id: str | None, x: float, y: float) -> str:
        tid, _ = self.run_session(
            target_id,
            [
                ("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}),
                ("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}),
                ("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1}),
            ],
        )
        return tid
