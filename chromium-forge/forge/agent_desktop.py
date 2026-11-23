"""Desktop Host Heartbeat, Human Takeover-All & Graceful Daemon Shutdown (`forge/agent_desktop.py`).

Bridges the native Win32 `LuminaraBrowser.exe` System Tray supervisor to the loopback Agent Daemon:
- `build_desktop_heartbeat`: Fast status & highest-priority alert payload for tray tooltip + notifications.
- `trigger_desktop_takeover`: Immediately preempts every active/recent agent tab and clears Presence + HUD overlays.
- `initiate_graceful_shutdown`: Closes runtime subsystems, checkpoints SQLite WAL stores, and stops HTTP cleanly.
"""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

from .extractor import build_dom_action_js
from .mcp_specs import APP_VERSION


def _checkpoint_sqlite(db_path: Path) -> None:
    if not db_path.is_file():
        return
    try:
        conn = sqlite3.connect(str(db_path), timeout=2.0)
        try:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        finally:
            conn.close()
    except sqlite3.Error:
        pass


def build_desktop_heartbeat(runtime: Any, started_at: float) -> dict[str, Any]:
    """Build compact desktop-host heartbeat and deduplicated tray notification metadata."""
    cdp_connected = False
    open_tabs = 0
    try:
        cdp_connected = bool(runtime.cdp.is_alive())
        if cdp_connected:
            open_tabs = len(runtime.cdp.list_tabs())
    except Exception:  # noqa: BLE001
        cdp_connected = False

    active_leases = runtime.cdp.leases.list_active() if hasattr(runtime.cdp.leases, "list_active") else []
    handoffs = runtime.goals.list_handoffs() if hasattr(runtime.goals, "list_handoffs") else []
    mutations = runtime.mutation_firewall.list_pending() if hasattr(runtime.mutation_firewall, "list_pending") else []
    seq_status = runtime.sequence_guard.status() if hasattr(runtime.sequence_guard, "status") else {}
    seq_blocks = list(seq_status.get("active_blocks") or [])

    alert_id = ""
    alert_title = ""
    alert_body = ""
    if handoffs:
        first = handoffs[0]
        run_id = str(first.get("run_id") or first.get("id") or "handoff")
        reason = str(first.get("reason") or "Verification or sign-in required in browser")
        alert_id = f"handoff:{run_id}"
        alert_title = "Luminara Browser — Human Handoff Required"
        alert_body = f"Agent paused ({reason[:140]}). Complete in tab and resume."
    elif seq_blocks:
        first_blk = seq_blocks[0]
        bid = str(first_blk.get("rule_id") or first_blk.get("partition_key") or "block")
        alert_id = f"seq:{bid}:{len(seq_blocks)}"
        alert_title = "Luminara Security — Sequence Guard Blocked"
        alert_body = f"Behavioral sequence blocked ({bid[:80]}). Open Telemetry Cockpit to review."
    elif mutations:
        first_mut = mutations[0]
        rid = str(first_mut.get("request_id") or "mutation")
        method = str(first_mut.get("method") or "POST")
        url = str(first_mut.get("url") or "")[:100]
        alert_id = f"mutation:{rid}"
        alert_title = "Luminara Firewall — Approval Required"
        alert_body = f"Paused {method} request to {url}. Approve or reject in Command Deck."

    payload = {
        "ok": True,
        "app_version": APP_VERSION,
        "daemon_pid": os.getpid(),
        "uptime_sec": round(max(0.0, time.time() - started_at), 1),
        "cdp_connected": cdp_connected,
        "cdp_port": runtime.cdp.port,
        "open_tabs": open_tabs,
        "active_leases": active_leases,
        "active_leases_count": len(active_leases),
        "pending_handoffs_count": len(handoffs),
        "pending_mutations_count": len(mutations),
        "sequence_blocks_count": len(seq_blocks),
        "alert_id": alert_id,
        "alert_title": alert_title,
        "alert_body": alert_body,
    }
    return runtime.redactor.redact_payload(payload)


def trigger_desktop_takeover(runtime: Any) -> dict[str, Any]:
    """Preempt every active/recent agent tab immediately and clear Presence + Set-of-Marks HUD."""
    preempted = (
        runtime.cdp.leases.force_human_override_all()
        if hasattr(runtime.cdp.leases, "force_human_override_all")
        else []
    )
    clear_hud_js = build_dom_action_js("clear_hud")
    if preempted and runtime.cdp.is_alive():
        for tid in preempted:
            try:
                runtime.presence.clear(tid)
            except Exception:  # noqa: BLE001
                pass
            try:
                runtime.cdp.evaluate_js(tid, clear_hud_js)
            except Exception:  # noqa: BLE001
                pass
    receipt = runtime.ledger.record(
        agent_id="human-desktop-tray",
        action="desktop_human_takeover_all",
        target_id=",".join(preempted) if preempted else "all",
        params={"preempted_tabs": preempted},
        status="OK",
        summary=f"Human takeover preempted {len(preempted)} active agent tab(s)",
    )
    return {
        "ok": True,
        "preempted_tabs": preempted,
        "preempted_count": len(preempted),
        "receipt": receipt,
    }


def initiate_graceful_shutdown(runtime: Any, server: Any, *, close_browser: bool = False) -> dict[str, Any]:
    """Close runtime subsystems, checkpoint SQLite WAL stores, and trigger HTTP server shutdown."""
    browser_closed = False
    if close_browser:
        try:
            if runtime.cdp.is_alive():
                runtime.cdp.mux.send_command("Browser.close", {}, timeout=2.0)
                browser_closed = True
        except Exception:  # noqa: BLE001
            pass
    if hasattr(runtime, "close"):
        try:
            runtime.close()
        except Exception:  # noqa: BLE001
            pass
    else:
        for fn in (
            lambda: runtime.scheduler.stop(),
            lambda: runtime.vrt_isolation.close(),
            lambda: runtime.mutation_firewall.close(),
            lambda: runtime.cdp.close(),
        ):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
    _checkpoint_sqlite(runtime.outputs_dir / "knowledge_graph.sqlite3")
    _checkpoint_sqlite(runtime.outputs_dir / "monitors_eval.sqlite3")

    if server is not None and hasattr(server, "shutdown"):
        def _stop_server() -> None:
            time.sleep(0.05)
            try:
                server.shutdown()
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_stop_server, name="luminara-graceful-shutdown", daemon=True).start()

    return {"ok": True, "shutting_down": True, "browser_closed": browser_closed, "daemon_pid": os.getpid()}


__all__ = [
    "build_desktop_heartbeat",
    "initiate_graceful_shutdown",
    "trigger_desktop_takeover",
]
