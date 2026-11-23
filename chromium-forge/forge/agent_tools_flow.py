"""Flow MCP tools: stable-ref outline, waits, screenshots and scheduled goals (`forge/agent_tools_flow.py`).

Same contract as `agent_tools_100x`: specs are appended to `MCP_TOOLS_SPEC`, and
`dispatch_flow_tool` returns `None` for names it does not own.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .agent_tools_100x import _bool_opt, _float_opt, _int_opt, _require_str
from .scheduler import parse_schedule

MAX_WAIT_SEC = 30.0

_AGENT = {"type": "string", "default": "mcp-agent"}

MCP_TOOLS_FLOW_SPEC: list[dict[str, Any]] = [
    {
        "name": "browser_outline",
        "description": "Accessibility outline of a tab with stable refs (`[ref=e12]` stays valid across snapshots of the same document). `snapshot` reads it, `diff` returns only what changed since the last read, `grep` filters lines by regex, `click`/`type` act on a ref with real input events, wait for the page to settle, and return the resulting diff. Page text is fenced as untrusted data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["snapshot", "diff", "grep", "click", "type"], "default": "snapshot"},
                "target_id": {"type": "string"},
                "ref": {"type": "string", "description": "Ref from a previous outline, e.g. e12 (click/type)."},
                "text": {"type": "string", "description": "Text to insert (type)."},
                "press_enter": {"type": "boolean", "default": False},
                "pattern": {"type": "string", "description": "Case-insensitive regex (grep)."},
                "interactive_only": {"type": "boolean", "default": False},
                "agent_id": _AGENT,
            },
        },
    },
    {
        "name": "browser_wait",
        "description": "Wait until the tab settles (loaded and DOM quiet), a fixed time passes, visible text appears, or a CSS selector matches. Capped at 30 seconds; returns whether the condition was met.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "for": {"type": "string", "enum": ["settle", "time", "text", "selector"], "default": "settle"},
                "value": {"type": "string", "description": "Text or CSS selector to wait for."},
                "timeout_sec": {"type": "number", "default": 10.0},
                "target_id": {"type": "string"},
            },
        },
    },
    {
        "name": "browser_screenshot",
        "description": "Capture the visible viewport of a tab as base64 JPEG, PNG or WebP.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string"},
                "format": {"type": "string", "enum": ["jpeg", "png", "webp"], "default": "jpeg"},
                "quality": {"type": "integer", "default": 75},
                "agent_id": _AGENT,
            },
        },
    },
    {
        "name": "browser_schedule",
        "description": "Scheduled goals that run on an interval (minutes) or daily at a local HH:MM. `list`, `remove` and `disable` are open to agents; `add`, `enable` and `run_now` require human UI authorization.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "add", "remove", "enable", "disable", "run_now"], "default": "list"},
                "task_id": {"type": "string"},
                "goal": {"type": "string"},
                "start_url": {"type": "string"},
                "kind": {"type": "string", "enum": ["interval", "daily"]},
                "every_min": {"type": "integer"},
                "at": {"type": "string", "description": "HH:MM, 24-hour local time (daily)."},
                "max_steps": {"type": "integer", "default": 8},
                "agent_id": _AGENT,
            },
        },
    },
]


def _wait_for(runtime: Any, tid: str, kind: str, value: str, timeout_sec: float) -> dict[str, Any]:
    if kind == "settle":
        return runtime.outline.settle(tid, timeout_sec=timeout_sec)
    start = time.monotonic()
    if kind == "time":
        time.sleep(timeout_sec)
        return {"settled": True, "waited_ms": round(timeout_sec * 1000)}
    if not value:
        raise ValueError(f"browser_wait for={kind!r} needs a non-empty 'value'")
    needle = json.dumps(value)
    expr = (
        f"!!(document.body && document.body.innerText.includes({needle}))"
        if kind == "text"
        else f"(() => {{ try {{ return !!document.querySelector({needle}); }} catch (_e) {{ return null; }} }})()"
    )
    while True:
        try:
            found = runtime.cdp.evaluate_js(tid, expr)
        except Exception:  # noqa: BLE001 - mid-navigation: keep polling
            found = False
        if found is None:
            raise ValueError(f"Invalid CSS selector: {value!r}")
        waited = time.monotonic() - start
        if found or waited >= timeout_sec:
            return {"settled": bool(found), "waited_ms": round(waited * 1000)}
        time.sleep(0.15)


def run_scheduled_task(runtime: Any, task: dict[str, Any]) -> str:
    """Run one scheduled goal through the normal goal runner and return its final status."""
    res = runtime.goals.run_goal(
        task["goal"],
        start_url=task.get("start_url") or None,
        max_steps=int(task.get("max_steps") or 8),
        agent_id="luminara-scheduler",
        show_badges=False,
    )
    status = str(res.get("status") or "UNKNOWN")
    runtime.ledger.record(
        "luminara-scheduler",
        "scheduled_goal",
        str(res.get("target_id") or ""),
        {"task_id": task["id"], "status": status},
        status="OK" if status == "COMPLETED" else "WARN",
        summary=f"Scheduled goal {task['id']} finished: {status}",
    )
    return status


def dispatch_flow_tool(runtime: Any, name: str, args: dict[str, Any], agent_id: str) -> dict[str, Any] | None:
    if name == "browser_outline":
        act = str(args.get("action") or "snapshot")
        interactive_only = _bool_opt(args, "interactive_only", False)
        if act == "snapshot":
            res = runtime.outline.snapshot(args.get("target_id"), interactive_only=interactive_only)
        elif act == "diff":
            res = runtime.outline.diff(args.get("target_id"), interactive_only=interactive_only)
        elif act == "grep":
            res = runtime.outline.grep(args.get("target_id"), _require_str(args, "pattern"))
        elif act in ("click", "type"):
            tid = runtime.cdp._pick_target_id(args.get("target_id"))
            runtime.cdp.leases.check_allowed(tid, agent_id)
            ref = _require_str(args, "ref")
            backend_id = runtime.outline.backend_node_for(tid, ref)
            if act == "click":
                runtime.perception.dispatch_hardware_click(tid, backend_node_id=backend_id)
                params: dict[str, Any] = {"ref": ref}
            else:
                text = str(args.get("text") or "")
                press_enter = _bool_opt(args, "press_enter", False)
                runtime.perception.dispatch_hardware_type(tid, text, backend_node_id=backend_id, press_enter=press_enter)
                params = {"ref": ref, "chars_inserted": len(text), "press_enter": press_enter}
            settle = runtime.outline.settle(tid, timeout_sec=5.0)
            res = {**runtime.outline.diff(tid, interactive_only=interactive_only), "settle": settle}
            res["receipt"] = runtime.ledger.record(agent_id, f"outline_{act}", tid, params, summary=f"Outline {act} on {ref}")
        else:
            raise ValueError(f"Unsupported browser_outline action: {act!r}")
        runtime.lifecycle.touch_tab(res["target_id"])
        return {"ok": True, **res}

    if name == "browser_wait":
        kind = str(args.get("for") or "settle")
        if kind not in ("settle", "time", "text", "selector"):
            raise ValueError(f"Unsupported browser_wait condition: {kind!r}")
        timeout_sec = max(0.0, min(MAX_WAIT_SEC, _float_opt(args, "timeout_sec", 10.0)))
        tid = runtime.cdp._pick_target_id(args.get("target_id"))
        return {"ok": True, "target_id": tid, "for": kind, **_wait_for(runtime, tid, kind, str(args.get("value") or ""), timeout_sec)}

    if name == "browser_screenshot":
        fmt = str(args.get("format") or "jpeg")
        tid, data = runtime.cdp.capture_screenshot(args.get("target_id"), fmt=fmt, quality=_int_opt(args, "quality", 75))
        rec = runtime.ledger.record(agent_id, "screenshot", tid, {"format": fmt, "base64_chars": len(data)}, summary="Captured viewport screenshot")
        return {"ok": True, "target_id": tid, "format": fmt, "data_base64": data, "receipt": rec}

    if name == "browser_schedule":
        act = str(args.get("action") or "list")
        store = runtime.schedules
        if act == "list":
            return {"ok": True, "tasks": store.list()}
        if act == "add":
            schedule = parse_schedule(
                str(args.get("kind") or ""),
                every_min=args.get("every_min"),
                at=args.get("at"),
            )
            task = store.add(
                _require_str(args, "goal"),
                schedule,
                start_url=str(args.get("start_url") or ""),
                max_steps=_int_opt(args, "max_steps", 8),
            )
            rec = runtime.ledger.record(agent_id, "schedule_add", "", {"task_id": task["id"], "schedule": schedule}, summary=f"Scheduled goal {task['id']}")
            return {"ok": True, "task": task, "receipt": rec}
        task_id = _require_str(args, "task_id")
        if act == "remove":
            store.remove(task_id)
            rec = runtime.ledger.record(agent_id, "schedule_remove", "", {"task_id": task_id}, summary=f"Removed scheduled goal {task_id}")
            return {"ok": True, "task_id": task_id, "receipt": rec}
        if act in ("enable", "disable"):
            task = store.set_enabled(task_id, act == "enable")
            rec = runtime.ledger.record(agent_id, f"schedule_{act}", "", {"task_id": task_id}, summary=f"Scheduled goal {task_id} {act}d")
            return {"ok": True, "task": task, "receipt": rec}
        if act == "run_now":
            return {"ok": True, "task_id": task_id, "status": runtime.scheduler.run_one(store.get(task_id))}
        raise ValueError(f"Unsupported browser_schedule action: {act!r}")

    return None
