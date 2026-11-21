"""Pure-stdlib Chrome DevTools Protocol (CDP) WebSocket Bridge & Tab Lease Manager (`forge/cdp_client.py`).

Hardened for concurrent multi-agent & parallel `BulkEngine` workloads:
- Browser-level `Target.createTarget` (`version_info()["webSocketDebuggerUrl"]`) prevents `tabs[0]` WS collisions.
- Per-target `RLock` serializes concurrent sessions on the same tab without throwing exclusive-debugger errors.
- `validate_navigation_url` blocks `javascript:`, `data:`, `chrome:`, trailing-dot DNS (`localhost.`),
  shorthand/octal IPv4 (`127.1`, `0177.0.0.1`), cloud metadata (`169.254.169.254`), and control ports.
- Single-WebSocket `Page.createIsolatedWorld` + `Runtime.evaluate(contextId)` + OOPIF target WS routing.
- Fast `int.from_bytes` XOR WebSocket masking, `32 MiB` frame cap, and configurable native JS dialog policy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
import ipaddress
import json
import os
import re
import subprocess
import threading
import time
from typing import Any
import unicodedata
import urllib.parse
import urllib.request

from .cdp_mux import CDPError, CDPMuxError, MultiplexedCDPPool, _RFC6455Socket, _xor_mask

ENCODING = "utf-8"
_BLOCKED_NAV_SCHEMES = frozenset({"javascript", "vbscript", "data", "chrome", "chrome-extension", "devtools", "view-source", "luminara"})
_INTERNAL_CONTROL_PORTS = frozenset({8795, 8796, 9229})
_CLOUD_METADATA_HOSTS = frozenset({"169.254.169.254", "metadata.google.internal", "100.100.100.200", "fd00:ec2::254"})
_NUMERIC_OR_HEX_LABEL_RE = re.compile(r"^(?:0x[0-9a-f]+|\d+)$", re.IGNORECASE)
_NUMERIC_DOTTED_RE = re.compile(r"^[\d.]+$")
_IDNA_DOTS_MAP = str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": "."})


def is_internal_browser_url(url: str, *, cdp_port: int | None = None) -> bool:
    """Canonical check for internal browser, extension, Studio (:8795), or Agent (:8796) surfaces."""
    u = (url or "").strip()
    if not u or u == "about:blank":
        return True
    low = u.lower()
    if low.startswith(("chrome://", "chrome-extension://", "devtools://", "luminara://", "view-source:")):
        return True
    if "luminara_pages/" in low or "forge_ntp/" in low:
        return True
    parsed = urllib.parse.urlsplit(low)
    host = (parsed.hostname or "").rstrip(".")
    if host in ("127.0.0.1", "localhost", "::1"):
        try:
            port = parsed.port
        except ValueError:
            return True
        blocked = {8795, 8796} | ({cdp_port} if cdp_port else set())
        if port in blocked or parsed.path.startswith(("/newtab", "/ui/newtab", "/workspace", "/ui/workspace")):
            return True
    return False


def _unwrap_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip.sixtofour is not None:
            return ip.sixtofour
        raw_int = int(ip)
        if ip not in (ipaddress.IPv6Address("::1"), ipaddress.IPv6Address("::")) and 0 < raw_int <= 0xFFFFFFFF:
            return ipaddress.IPv4Address(raw_int)
    return ip


def _is_loopback_or_unspecified_host(host: str) -> bool:
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "::") or host.endswith(".localhost"):
        return True
    ip = _unwrap_ip(host)
    return bool(ip and (ip.is_loopback or ip.is_unspecified))


def _is_cloud_metadata_or_link_local(host: str) -> bool:
    if host in _CLOUD_METADATA_HOSTS:
        return True
    ip = _unwrap_ip(host)
    return bool(ip and (ip.is_link_local or str(ip) in _CLOUD_METADATA_HOSTS))


def validate_navigation_url(
    url: str,
    *,
    allow_file: bool = False,
    blocked_ports: frozenset[int] = _INTERNAL_CONTROL_PORTS,
) -> str:
    """Validate target URL before opening or navigating a tab (blocks WHATWG/RFC3986 SSRF differentials)."""
    cleaned = (url or "").strip()
    if not cleaned:
        raise CDPError("Navigation URL must be non-empty")
    if cleaned == "about:blank":
        return cleaned

    pre_query = cleaned.split("?", 1)[0].split("#", 1)[0]
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

    after_scheme = pre_query.split(":", 1)[1] if ":" in pre_query else ""
    if not after_scheme.startswith("//") or "\\" in after_scheme.lstrip("/").split("/", 1)[0]:
        raise CDPError(f"Blocked malformed authority or backslash SSRF differential in URL: {cleaned!r}")
    authority = after_scheme[2:].split("/", 1)[0]
    if "@" in authority or ("[" in authority and "%" in authority):
        raise CDPError(f"Blocked userinfo or IPv6 zone-ID in navigation URL: {cleaned!r}")

    raw_host = (parsed.hostname or "").strip()
    unquoted_host = unicodedata.normalize("NFKC", urllib.parse.unquote(raw_host)).translate(_IDNA_DOTS_MAP).strip().lower()
    host = unquoted_host.rstrip(".")
    if host and ":" not in host and not host.isascii():
        try:
            host = host.encode("idna").decode("ascii").lower().rstrip(".")
        except UnicodeError as exc:
            raise CDPError(f"Invalid IDNA hostname in navigation URL: {raw_host!r}") from exc

    all_numeric_or_hex_labels = (
        bool(host)
        and ":" not in host
        and all(_NUMERIC_OR_HEX_LABEL_RE.match(lbl) is not None for lbl in host.split("."))
    )
    has_ambiguous_ip = all_numeric_or_hex_labels and (
        host.count(".") != 3
        or any(lbl.startswith("0x") or (len(lbl) > 1 and lbl.startswith("0")) for lbl in host.split("."))
    )
    unwrapped_ip = _unwrap_ip(host)
    is_obfuscated_host = (unwrapped_ip is not None or _is_loopback_or_unspecified_host(host)) and (
        raw_host.lower().rstrip(".") != host
        or (":" in host and isinstance(unwrapped_ip, ipaddress.IPv4Address))
    )
    if (
        not host
        or any(ch in host for ch in ("/", "\\", "@", " ", "\t", "\r", "\n"))
        or host.isdigit()
        or has_ambiguous_ip
        or is_obfuscated_host
        or (_NUMERIC_DOTTED_RE.match(host) and host.count(".") != 3)
    ):
        raise CDPError(f"Blocked ambiguous or numeric-encoded host: {raw_host!r}")
    if _is_cloud_metadata_or_link_local(host):
        raise CDPError(f"Blocked cloud metadata / link-local SSRF host: {host}")
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise CDPError(f"Invalid port in navigation URL: {cleaned!r}") from exc
    eff_port = parsed_port or (443 if scheme == "https" else 80)
    if _is_loopback_or_unspecified_host(host) and eff_port in blocked_ports:
        raise CDPError(f"Blocked navigation to internal control plane port: {eff_port}")
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


class CDPBridge:
    """High-level co-browsing controller talking to Chromium's loopback DevTools port.

    Uses `MultiplexedCDPPool` (single persistent browser-level WebSocket + flat `sessionId`
    attachments) by default for `< 1.5 ms` command latency and zero `F12` DevTools collisions,
    with seamless fallback to per-target WebSocket sessions when needed.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9229, *, use_mux: bool = True) -> None:
        self.host = host
        self.port = port
        self.use_mux = use_mux
        self.leases = TabLeaseManager()
        self._browser_lock = threading.RLock()
        self._target_locks_guard = threading.Lock()
        self._target_locks: dict[str, threading.RLock] = {}
        self._dialog_lock = threading.Lock()
        self._dialog_history: dict[str, list[dict[str, Any]]] = {}
        self._dialog_policies: dict[str, dict[str, Any]] = {}
        self._fetch_lock = threading.Lock()
        self._fetch_policies: dict[str, dict[str, str]] = {}
        self._fetch_hooks: list[tuple[int, str, Callable[[dict[str, Any]], str | None]]] = []
        self._mux = MultiplexedCDPPool(
            ws_url_provider=self._resolve_browser_ws_url,
            socket_factory=lambda ws_url, timeout: _RFC6455Socket(ws_url, timeout=timeout),
        )
        self._mux.subscribe("Page.javascriptDialogOpening", self._on_mux_dialog_event)
        self._mux.subscribe("Target.detachedFromTarget", self._on_mux_target_detached)
        self._mux.subscribe("Fetch.requestPaused", self._on_mux_fetch_paused)

    def _on_mux_target_detached(self, event: dict[str, Any]) -> None:
        tid = str(event.get("target_id") or "")
        if not tid:
            return
        self.leases.release(tid)
        with self._target_locks_guard:
            self._target_locks.pop(tid, None)
        with self._dialog_lock:
            self._dialog_history.pop(tid, None)
            self._dialog_policies.pop(tid, None)
        with self._fetch_lock:
            self._fetch_policies.pop(tid, None)

    def register_fetch_hook(
        self,
        priority: int,
        owner: str,
        hook: Callable[[dict[str, Any]], str | None],
    ) -> Callable[[], None]:
        """Register an ordered `Fetch.requestPaused` hook returning `'FAIL'`, `'PAUSE'`, or `None`."""
        entry = (int(priority), str(owner), hook)
        with self._fetch_lock:
            self._fetch_hooks = [h for h in self._fetch_hooks if h[1] != owner]
            self._fetch_hooks.append(entry)
            self._fetch_hooks.sort(key=lambda h: h[0])

        def _unsub() -> None:
            with self._fetch_lock:
                self._fetch_hooks = [h for h in self._fetch_hooks if h[1] != owner]

        return _unsub

    def set_fetch_interception(
        self,
        target_id: str,
        owner: str,
        *,
        enabled: bool,
        url_pattern: str = "*",
    ) -> None:
        """Ref-counted per-tab `Fetch.enable`/`Fetch.disable` preventing guards from disarming each other."""
        with self._fetch_lock:
            owners = self._fetch_policies.setdefault(target_id, {})
            if enabled:
                owners[owner] = url_pattern or "*"
            else:
                owners.pop(owner, None)
            patterns = ["*"] if ("*" in owners.values()) else sorted(set(owners.values()))
            if not owners:
                self._fetch_policies.pop(target_id, None)

        if patterns:
            self.run_session(
                target_id,
                [("Fetch.enable", {"patterns": [{"urlPattern": p, "requestStage": "Request"} for p in patterns]})],
            )
        else:
            try:
                self.run_session(target_id, [("Fetch.disable", {})])
            except Exception:  # noqa: BLE001
                pass

    def _on_mux_fetch_paused(self, event: dict[str, Any]) -> None:
        params = event.get("params") or {}
        session_id = str(event.get("session_id") or "")
        request_id = str(params.get("requestId") or "")
        if not session_id or not request_id:
            return
        if ("responseStatusCode" in params) or ("responseErrorReason" in params):
            try:
                self._mux.send_command_async("Fetch.continueRequest", {"requestId": request_id}, session_id=session_id)
            except Exception:  # noqa: BLE001
                pass
            return

        with self._fetch_lock:
            hooks = list(self._fetch_hooks)

        for _prio, _owner, hook in hooks:
            try:
                verdict = hook(event)
            except Exception:  # noqa: BLE001
                verdict = None
            if verdict == "FAIL":
                try:
                    self._mux.send_command_async(
                        "Fetch.failRequest",
                        {"requestId": request_id, "errorReason": "BlockedByClient"},
                        session_id=session_id,
                    )
                except Exception:  # noqa: BLE001
                    pass
                return
            if verdict == "PAUSE":
                return

        try:
            self._mux.send_command_async("Fetch.continueRequest", {"requestId": request_id}, session_id=session_id)
        except Exception:  # noqa: BLE001
            pass

    def _resolve_browser_ws_url(self) -> str:
        ver = self.version_info()
        return str(ver.get("webSocketDebuggerUrl") or "")

    def _on_mux_dialog_event(self, event: dict[str, Any]) -> None:
        tid = str(event.get("target_id") or "")
        sid = str(event.get("session_id") or "")
        params = event.get("params") or {}
        accept, p_txt = self._get_native_dialog_policy(
            tid,
            default_prompt=str(params.get("defaultPrompt") or ""),
        )
        if tid:
            self.record_native_dialog(tid, params, accepted=accept)
        if sid:
            try:
                self._mux.send_command_async(
                    "Page.handleJavaScriptDialog",
                    {"accept": accept, "promptText": p_txt},
                    session_id=sid,
                )
            except Exception:  # noqa: BLE001
                pass

    @property
    def mux(self) -> MultiplexedCDPPool:
        return self._mux

    def mux_stats(self) -> dict[str, Any]:
        return self._mux.stats()

    def recent_events(self, *, since_seq: int = 0, method: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self._mux.recent_events(since_seq=since_seq, method=method, limit=limit)

    def close(self) -> None:
        self._mux.close()

    def set_native_dialog_policy(self, target_id: str, *, accept: bool = True, prompt_text: str = "") -> None:
        with self._dialog_lock:
            self._dialog_policies[target_id] = {"accept": bool(accept), "prompt_text": str(prompt_text)}

    def _get_native_dialog_policy(self, target_id: str, default_prompt: str = "") -> tuple[bool, str]:
        with self._dialog_lock:
            pol = self._dialog_policies.get(target_id)
            if not pol:
                return True, default_prompt
            p_txt = pol["prompt_text"] if pol["prompt_text"] != "" else default_prompt
            return bool(pol["accept"]), p_txt

    def record_native_dialog(self, target_id: str, dialog_event: dict[str, Any], accepted: bool) -> None:
        with self._dialog_lock:
            bucket = self._dialog_history.setdefault(target_id, [])
            bucket.append(
                {
                    "id": f"cdp_dlg_{len(bucket) + 1}",
                    "type": str(dialog_event.get("type") or "alert"),
                    "message": str(dialog_event.get("message") or "")[:500],
                    "default_prompt": str(dialog_event.get("defaultPrompt") or "")[:200],
                    "resolved_action": "accept" if accepted else "dismiss",
                    "timestamp_ms": int(time.time() * 1000),
                    "source": "cdp_page_event",
                }
            )
            if len(bucket) > 20:
                del bucket[:-20]

    def get_native_dialogs(self, target_id: str) -> list[dict[str, Any]]:
        with self._dialog_lock:
            return list(self._dialog_history.get(target_id, []))

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
        try:
            with urllib.request.urlopen(f"{self.base_http}/json/version", timeout=3.0) as resp:
                return json.loads(resp.read().decode(ENCODING))
        except (OSError, ValueError) as exc:
            raise CDPError(f"CDP endpoint {self.base_http} unreachable: {exc}") from exc

    def _raw_targets(self) -> list[dict[str, Any]]:
        try:
            with urllib.request.urlopen(f"{self.base_http}/json/list", timeout=3.0) as resp:
                return json.loads(resp.read().decode(ENCODING))
        except (OSError, ValueError) as exc:
            raise CDPError(f"CDP target list {self.base_http} unreachable: {exc}") from exc

    def list_tabs(self, include_extensions: bool = False) -> list[dict[str, Any]]:
        tabs: list[dict[str, Any]] = []
        for item in self._raw_targets():
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

    def open_tab(self, url: str = "about:blank", background: bool = True, allow_file: bool = False) -> dict[str, Any]:
        """Open a new tab via browser-level `Target.createTarget` (concurrent-safe) or `/json/new`."""
        checked_url = validate_navigation_url(
            url,
            allow_file=allow_file,
            blocked_ports=_INTERNAL_CONTROL_PORTS | {self.port},
        )
        if background:
            if self.use_mux:
                try:
                    res = self._mux.send_command(
                        "Target.createTarget",
                        {"url": checked_url, "background": True},
                        timeout=10.0,
                    )
                    new_id = res["targetId"]
                    try:
                        for tab in self.list_tabs(include_extensions=True):
                            if tab["target_id"] == new_id:
                                return tab
                    except Exception:  # noqa: BLE001
                        pass
                    return {"target_id": new_id, "url": checked_url, "title": "", "ws_url": ""}
                except CDPMuxError:
                    pass
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
                    try:
                        for tab in self.list_tabs(include_extensions=True):
                            if tab["target_id"] == new_id:
                                return tab
                    except Exception:  # noqa: BLE001
                        pass
                    return {"target_id": new_id, "url": checked_url, "title": "", "ws_url": ""}

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
        with self._target_locks_guard:
            self._target_locks.pop(target_id, None)
        with self._dialog_lock:
            self._dialog_history.pop(target_id, None)
            self._dialog_policies.pop(target_id, None)
        with self._fetch_lock:
            self._fetch_policies.pop(target_id, None)
        safe_tid = urllib.parse.quote(target_id, safe="")
        try:
            with urllib.request.urlopen(f"{self.base_http}/json/close/{safe_tid}", timeout=3.0) as resp:
                return resp.status == 200
        except Exception:  # noqa: BLE001
            return False

    def _pick_target_id(self, target_id: str | None) -> str:
        clean_tid = (target_id or "").strip()
        if clean_tid:
            return clean_tid
        tabs = self.list_tabs(include_extensions=True)
        if not tabs:
            created = self.open_tab("about:blank", background=False)
            return created["target_id"]
        external = [t for t in tabs if not is_internal_browser_url(t["url"], cdp_port=self.port)]
        normal = [
            t
            for t in tabs
            if not t["url"].lower().startswith(("chrome-extension://", "devtools://", "chrome://", "luminara://"))
        ]
        if external:
            return external[0]["target_id"]
        if normal:
            return normal[0]["target_id"]
        created = self.open_tab("about:blank", background=False)
        return created["target_id"]

    def _resolve_ws_url(self, target_id: str | None) -> tuple[str, str]:
        tid = self._pick_target_id(target_id)
        for attempt in range(6):
            raw_items = self._raw_targets()
            for item in raw_items:
                if item.get("id") == tid and item.get("type") in ("page", "iframe"):
                    ws_url = str(item.get("webSocketDebuggerUrl") or "")
                    if ws_url:
                        return tid, ws_url
                    break
            else:
                raise CDPError(f"Tab target_id not found: {tid}")
            if attempt < 5:
                time.sleep(0.05)
        raise CDPError(f"Tab {tid} already has an exclusive debugger attached")

    def _send_and_await(
        self,
        sock: _RFC6455Socket,
        msg_id: int,
        method: str,
        params: dict[str, Any],
        deadline: float,
        target_id: str,
        auto_seq: list[int],
    ) -> dict[str, Any]:
        sock.send_text(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            rem = deadline - time.monotonic()
            if rem <= 0:
                raise CDPError(f"Timeout waiting for CDP {method}" + (f" on tab {target_id}" if target_id else ""))
            sock.set_remaining_timeout(rem)
            frame = json.loads(sock.recv_text())
            if frame.get("method") == "Page.javascriptDialogOpening":
                dlg_params = frame.get("params") or {}
                accept, p_txt = self._get_native_dialog_policy(
                    target_id,
                    default_prompt=str(dlg_params.get("defaultPrompt") or ""),
                )
                if target_id:
                    self.record_native_dialog(target_id, dlg_params, accepted=accept)
                auto_seq[0] += 1
                sock.send_text(
                    json.dumps(
                        {
                            "id": auto_seq[0],
                            "method": "Page.handleJavaScriptDialog",
                            "params": {"accept": accept, "promptText": p_txt},
                        }
                    )
                )
                continue
            if frame.get("id") == msg_id:
                if "error" in frame:
                    raise CDPError(f"CDP {method} error: {frame['error']}")
                return frame.get("result", {})

    def _exec_on_ws(
        self,
        ws_url: str,
        commands: list[tuple[str, dict[str, Any]]],
        timeout: float = 20.0,
        target_id: str = "",
    ) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        sock = _RFC6455Socket(ws_url, timeout=timeout)
        results: list[dict[str, Any]] = []
        auto_seq = [1_000_000]
        try:
            for idx, (method, params) in enumerate(commands, start=1):
                results.append(self._send_and_await(sock, idx, method, params, deadline, target_id, auto_seq))
            return results
        finally:
            sock.close()

    def _call_ws(self, ws_url: str, method: str, params: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
        return self._exec_on_ws(ws_url, [(method, params or {})], timeout=timeout)[0]

    def run_session(
        self,
        target_id: str | None,
        commands: list[tuple[str, dict[str, Any]]],
        timeout: float = 20.0,
    ) -> tuple[str, list[dict[str, Any]]]:
        tid = self._pick_target_id(target_id)
        if self.use_mux:
            try:
                return tid, self._mux.run_target_commands(tid, commands, timeout=timeout)
            except CDPMuxError:
                pass
        with self._lock_for_target(tid):
            resolved_tid, ws_url = self._resolve_ws_url(tid)
            return resolved_tid, self._exec_on_ws(ws_url, commands, timeout=timeout, target_id=resolved_tid)

    def navigate(self, target_id: str | None, url: str, settle_sec: float = 0.6, allow_file: bool = False) -> dict[str, Any]:
        from .extractor import DIALOG_SUPERVISOR_INIT_JS
        from .webmcp import WEBMCP_BOOTSTRAP_JS

        checked_url = validate_navigation_url(
            url,
            allow_file=allow_file,
            blocked_ports=_INTERNAL_CONTROL_PORTS | {self.port},
        )
        tid, res = self.run_session(
            target_id,
            [
                ("Page.enable", {}),
                ("Page.addScriptToEvaluateOnNewDocument", {"source": DIALOG_SUPERVISOR_INIT_JS + "\n" + WEBMCP_BOOTSTRAP_JS}),
                ("Page.navigate", {"url": checked_url}),
            ],
        )
        if settle_sec > 0:
            time.sleep(settle_sec)
        meta = self.evaluate_js(tid, "({title: document.title, url: location.href, readyState: document.readyState})")
        return {"target_id": tid, "nav": res[-1], **(meta if isinstance(meta, dict) else {})}

    def get_frame_tree(self, target_id: str | None = None) -> list[dict[str, Any]]:
        """Retrieve bounded frame hierarchy (`Page.getFrameTree` + OOPIF child target correlation)."""
        _tid, res = self.run_session(
            target_id,
            [
                ("Page.enable", {}),
                ("Page.getFrameTree", {}),
            ],
        )
        root_tree = (res[-1] or {}).get("frameTree") or {}
        oopif_by_id: dict[str, dict[str, Any]] = {}
        try:
            for item in self._raw_targets():
                if item.get("type") == "iframe" and item.get("id"):
                    oopif_by_id[str(item["id"])] = item
        except Exception:  # noqa: BLE001
            pass

        frames: list[dict[str, Any]] = []
        root_origin = str((root_tree.get("frame") or {}).get("securityOrigin") or "")

        def _walk(node: dict[str, Any], depth: int = 0) -> None:
            if len(frames) >= 30 or depth > 4:
                return
            fr = node.get("frame") or {}
            fid = str(fr.get("id") or "")
            if fid:
                origin = str(fr.get("securityOrigin") or "")
                is_cross = bool(depth > 0 and origin and root_origin and origin != root_origin) or (fid in oopif_by_id)
                frames.append(
                    {
                        "frame_id": fid,
                        "parent_frame_id": str(fr.get("parentId") or ""),
                        "name": str(fr.get("name") or ""),
                        "url": str(fr.get("url") or ""),
                        "origin": origin,
                        "depth": depth,
                        "is_cross_origin": is_cross,
                        "oopif_target_id": fid if fid in oopif_by_id else "",
                    }
                )
            for child in node.get("childFrames") or []:
                if isinstance(child, dict):
                    _walk(child, depth + 1)

        if root_tree:
            _walk(root_tree, 0)
        return frames

    def evaluate_js(
        self,
        target_id: str | None,
        expression: str,
        await_promise: bool = True,
        frame_id: str | None = None,
    ) -> Any:
        tid = self._pick_target_id(target_id)
        if frame_id:
            is_oopif = any(
                item.get("type") == "iframe" and str(item.get("id") or "") == frame_id
                for item in self._raw_targets()
            )
            if is_oopif:
                _ftid, res = self.run_session(
                    frame_id,
                    [
                        ("Page.enable", {}),
                        (
                            "Runtime.evaluate",
                            {"expression": expression, "returnByValue": True, "awaitPromise": await_promise},
                        ),
                    ],
                )
                payload = res[-1]
            else:
                world_cmd = (
                    "Page.createIsolatedWorld",
                    {"frameId": frame_id, "worldName": "luminara_frame_bridge", "grantUniveralAccess": True},
                )
                if self.use_mux:
                    try:
                        w_res = self._mux.run_target_commands(tid, [("Page.enable", {}), world_cmd])
                        ctx_id = (w_res[-1] if w_res else {}).get("executionContextId")
                        if ctx_id is None:
                            raise CDPError(f"Frame {frame_id!r} isolated world unavailable")
                        e_res = self._mux.run_target_commands(
                            tid,
                            [("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": await_promise, "contextId": ctx_id})],
                        )
                        payload = e_res[-1]
                    except CDPMuxError:
                        payload = None
                else:
                    payload = None
                if payload is None:
                    with self._lock_for_target(tid):
                        resolved_tid, ws_url = self._resolve_ws_url(tid)
                        deadline = time.monotonic() + 20.0
                        sock = _RFC6455Socket(ws_url, timeout=20.0)
                        auto_seq = [1_000_000]
                        try:
                            self._send_and_await(sock, 1, "Page.enable", {}, deadline, resolved_tid, auto_seq)
                            w_out = self._send_and_await(sock, 2, world_cmd[0], world_cmd[1], deadline, resolved_tid, auto_seq)
                            ctx_id = w_out.get("executionContextId")
                            if ctx_id is None:
                                raise CDPError(f"Frame {frame_id!r} isolated world unavailable")
                            payload = self._send_and_await(
                                sock,
                                3,
                                "Runtime.evaluate",
                                {"expression": expression, "returnByValue": True, "awaitPromise": await_promise, "contextId": ctx_id},
                                deadline,
                                resolved_tid,
                                auto_seq,
                            )
                        finally:
                            sock.close()
        else:
            _tid, res = self.run_session(
                tid,
                [
                    ("Page.enable", {}),
                    (
                        "Runtime.evaluate",
                        {
                            "expression": expression,
                            "returnByValue": True,
                            "awaitPromise": await_promise,
                        },
                    ),
                ],
            )
            payload = res[-1]

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


def wait_for_cdp_page_ready(
    cdp: CDPBridge,
    js_predicate: str = "Boolean(document.documentElement && document.readyState === 'complete')",
    timeout: float = 20.0,
) -> bool:
    """Wait until CDP is listening and a non-blank tab satisfies `js_predicate` (eliminates blind sleep races)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cdp.is_alive():
            try:
                tabs = [
                    t
                    for t in cdp.list_tabs(include_extensions=False)
                    if t.get("url") and t.get("url") != "about:blank" and (cdp.use_mux or t.get("ws_url"))
                ]
                if tabs and cdp.evaluate_js(tabs[0]["target_id"], js_predicate) is True:
                    return True
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.12)
    return False


def terminate_browser_process(proc: subprocess.Popen[Any]) -> None:
    """Terminate a headless Chromium process tree cleanly on Windows & POSIX without orphan locks."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=8,
            )
        except Exception:  # noqa: BLE001
            pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        pass
