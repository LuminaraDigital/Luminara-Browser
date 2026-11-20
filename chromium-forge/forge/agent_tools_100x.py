"""Extended 100x MCP v2 Tool Specifications & Dispatchers (`forge/agent_tools_100x.py`).

Keeps `agent_server.py` lean (< 1,000 lines) while exposing Luminara v3.0 engine primitives:
- `browser_perception_axtree`: Native Blink AXTree + Shadow-DOM + OOPIF semantic perception & hardware input.
- `webmcp_list_tools` / `webmcp_call_tool`: W3C WebMCP (`navigator.modelContext`) & auto-form tool execution.
- `browser_mutation_guard`: Network Mutation Firewall (`Fetch.enable` Savepoint Diff Approval).
- `browser_workspace`: SQLite WAL + FTS5 Cross-Tab Knowledge Graph & Named Workspaces.
- `browser_hibernate_tabs`: Background Tab Lifecycle Freezer (`Page.setWebLifecycleState`).
"""

from __future__ import annotations

from typing import Any

MCP_TOOLS_100X_SPEC: list[dict[str, Any]] = [
    {
        "name": "browser_perception_axtree",
        "description": "Capture Blink Accessibility Tree (AXTree), Shadow-DOM pierced controls, and Site-Isolated OOPIF elements, or dispatch compositor hardware click/type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["snapshot", "hardware_click", "hardware_type"],
                    "default": "snapshot",
                },
                "target_id": {"type": "string"},
                "max_nodes": {"type": "integer", "default": 250},
                "include_shadow_dom": {"type": "boolean", "default": True},
                "backend_node_id": {"type": "integer"},
                "x": {"type": "number"},
                "y": {"type": "number"},
                "text": {"type": "string"},
                "press_enter": {"type": "boolean", "default": False},
                "agent_id": {"type": "string", "default": "mcp-agent"},
            },
        },
    },
    {
        "name": "webmcp_list_tools",
        "description": "Discover W3C WebMCP tools (`navigator.modelContext.registerTool`, declarative `<form toolname>`, and auto-compiled semantic forms) on the live tab.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string"},
                "agent_id": {"type": "string", "default": "mcp-agent"},
            },
        },
    },
    {
        "name": "webmcp_call_tool",
        "description": "Invoke a discovered W3C WebMCP page tool or declarative form in one deterministic schema-validated call with zero vision tokens.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string"},
                "arguments": {"type": "object", "default": {}},
                "target_id": {"type": "string"},
                "auto_submit": {"type": "boolean", "default": True},
                "agent_id": {"type": "string", "default": "mcp-agent"},
            },
            "required": ["tool_name"],
        },
    },
    {
        "name": "browser_mutation_guard",
        "description": "Control the Network Mutation Firewall (enable Fetch.enable interception, inspect PAUSED_MUTATION_APPROVAL savepoints, or human-authorized approve/reject/disable via X-Luminara-UI-Key).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "enable", "disable", "approve", "reject"],
                    "default": "status",
                },
                "target_id": {"type": "string"},
                "url_pattern": {"type": "string", "default": "*"},
                "mutation_id": {"type": "string"},
                "agent_id": {"type": "string", "default": "mcp-agent"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "browser_workspace",
        "description": "Manage named Tab Workspaces and query the SQLite WAL + FTS5 Cross-Tab Knowledge Graph (`list`, `snapshot`, `upsert`, `index`, `search`).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "snapshot", "upsert", "index", "search"],
                    "default": "list",
                },
                "workspace_id": {"type": "string", "default": "default"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "pinned_urls": {"type": "array", "items": {"type": "string"}},
                "url": {"type": "string"},
                "title": {"type": "string"},
                "rows": {"type": "array", "items": {"type": "object"}},
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 25},
                "agent_id": {"type": "string", "default": "mcp-agent"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "browser_hibernate_tabs",
        "description": "Freeze idle background tabs via CDP `Page.setWebLifecycleState('frozen')` (never freezing active, pinned, or agent-leased tabs), or wake/pin a specific tab.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["hibernate", "wake", "pin", "unpin"],
                    "default": "hibernate",
                },
                "target_id": {"type": "string"},
                "min_idle_sec": {"type": "number", "default": 0.0},
                "dry_run": {"type": "boolean", "default": False},
                "agent_id": {"type": "string", "default": "mcp-agent"},
            },
        },
    },
]


def _require_str(args: dict[str, Any], key: str) -> str:
    val = args.get(key)
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"Missing required non-empty string parameter: {key}")
    return val.strip()


def _int_opt(args: dict[str, Any], key: str, default: int) -> int:
    val = args.get(key)
    return default if val is None else int(val)


def _float_opt(args: dict[str, Any], key: str, default: float) -> float:
    val = args.get(key)
    return default if val is None else float(val)


def dispatch_100x_tool(runtime: Any, name: str, args: dict[str, Any], agent_id: str) -> dict[str, Any] | None:
    """Handle Luminara v3.0 100x MCP tools; returns `None` if `name` is not handled here."""
    if name == "browser_perception_axtree":
        act = str(args.get("action") or "snapshot")
        tid = args.get("target_id")
        if act == "snapshot":
            snap = runtime.perception.capture_ax_snapshot(
                tid,
                max_nodes=_int_opt(args, "max_nodes", 250),
                include_shadow_dom=bool(args.get("include_shadow_dom", True)),
            )
            snap_tid = str(snap.get("target_id") or "")
            if snap_tid:
                runtime.lifecycle.touch_tab(snap_tid)
            rec = runtime.ledger.record(
                agent_id,
                "perception_axtree",
                str(snap.get("target_id") or ""),
                {"ax_count": snap.get("ax_interactive_count", 0), "shadow_hosts": snap.get("shadow_hosts_pierced", 0)},
                summary=f"AXTree indexed {snap.get('ax_interactive_count', 0)} nodes + {snap.get('oopif_interactive_count', 0)} OOPIF",
            )
            return {"perception": snap, "receipt": rec}
        resolved_tid = runtime.cdp._pick_target_id(tid)
        runtime.cdp.leases.check_allowed(resolved_tid, agent_id)
        runtime.lifecycle.touch_tab(resolved_tid)
        if act == "hardware_click":
            res = runtime.perception.dispatch_hardware_click(
                resolved_tid,
                backend_node_id=int(args["backend_node_id"]) if args.get("backend_node_id") is not None else None,
                x=float(args["x"]) if args.get("x") is not None else None,
                y=float(args["y"]) if args.get("y") is not None else None,
            )
            rec = runtime.ledger.record(agent_id, "hardware_click", str(res["target_id"]), res, summary="Compositor hardware click")
            return {**res, "receipt": rec}
        if act == "hardware_type":
            res = runtime.perception.dispatch_hardware_type(
                resolved_tid,
                str(args.get("text") or ""),
                backend_node_id=int(args["backend_node_id"]) if args.get("backend_node_id") is not None else None,
                press_enter=bool(args.get("press_enter", False)),
            )
            rec = runtime.ledger.record(
                agent_id,
                "hardware_type",
                str(res["target_id"]),
                {"chars_inserted": res["chars_inserted"], "press_enter": res["press_enter"]},
                summary=f"Compositor hardware type ({res['chars_inserted']} chars)",
            )
            return {**res, "receipt": rec}
        raise ValueError(f"Unsupported browser_perception_axtree action: {act!r}")

    if name == "webmcp_list_tools":
        info = runtime.webmcp.list_page_tools(args.get("target_id"))
        info_tid = str(info.get("target_id") or "")
        if info_tid:
            runtime.lifecycle.touch_tab(info_tid)
        rec = runtime.ledger.record(
            agent_id,
            "webmcp_list",
            info_tid,
            {"tool_count": info.get("tool_count", 0)},
            summary=f"Discovered {info.get('tool_count', 0)} WebMCP tools on {info.get('origin', '')}",
        )
        return {**info, "receipt": rec}

    if name == "webmcp_call_tool":
        tname = _require_str(args, "tool_name")
        targs = args.get("arguments") if isinstance(args.get("arguments"), dict) else {}
        resolved_tid = runtime.cdp._pick_target_id(args.get("target_id"))
        runtime.cdp.leases.check_allowed(resolved_tid, agent_id)
        runtime.lifecycle.touch_tab(resolved_tid)
        res = runtime.webmcp.call_page_tool(
            tname,
            targs,
            target_id=resolved_tid,
            auto_submit=bool(args.get("auto_submit", True)),
        )
        rec = runtime.ledger.record(
            agent_id,
            "webmcp_call",
            str(res.get("target_id") or ""),
            {"tool_name": tname, "ok": res.get("ok", False)},
            status="OK" if res.get("ok") else "WARN",
            summary=f"Invoked WebMCP tool {tname}",
        )
        return {**res, "receipt": rec}

    if name == "browser_mutation_guard":
        act = str(args.get("action") or "status")
        if act == "status":
            return {"ok": True, **runtime.mutation_firewall.status()}
        if act == "enable":
            res = runtime.mutation_firewall.enable_guard(
                args.get("target_id"),
                url_pattern=str(args.get("url_pattern") or "*"),
            )
            rec = runtime.ledger.record(agent_id, "mutation_guard_enable", str(res["target_id"]), res, summary="Enabled Network Mutation Firewall")
            return {**res, "receipt": rec}
        if act == "disable":
            res = runtime.mutation_firewall.disable_guard(args.get("target_id"))
            rec = runtime.ledger.record(agent_id, "mutation_guard_disable", str(res["target_id"]), res, summary="Disabled Network Mutation Firewall")
            return {**res, "receipt": rec}
        if act in ("approve", "reject"):
            mid = _require_str(args, "mutation_id")
            res = runtime.mutation_firewall.resolve_mutation(mid, decision=act)
            rec = runtime.ledger.record(
                agent_id,
                f"mutation_{act}",
                str(res.get("target_id") or ""),
                {"mutation_id": mid, "method": res.get("method"), "url": res.get("url")},
                summary=f"Human {act}d paused {res.get('method')} mutation {mid}",
            )
            return {**res, "receipt": rec}
        raise ValueError(f"Unsupported browser_mutation_guard action: {act!r}")

    if name == "browser_workspace":
        act = str(args.get("action") or "list")
        if act == "list":
            return {"ok": True, "workspaces": runtime.knowledge.list_workspaces()}
        if act == "snapshot":
            wid = str(args.get("workspace_id") or "default")
            ws = runtime.lifecycle.snapshot_workspace(runtime.knowledge, wid, name=args.get("name"))
            rec = runtime.ledger.record(agent_id, "workspace_snapshot", "", {"workspace_id": wid}, summary=f"Snapshotted workspace {wid}")
            return {"ok": True, "workspace": ws, "receipt": rec}
        if act == "upsert":
            wid = str(args.get("workspace_id") or "default")
            ws = runtime.knowledge.upsert_workspace(
                wid,
                name=args.get("name"),
                description=str(args.get("description") or ""),
                pinned_urls=list(args["pinned_urls"]) if isinstance(args.get("pinned_urls"), list) else None,
            )
            rec = runtime.ledger.record(agent_id, "workspace_upsert", "", {"workspace_id": wid}, summary=f"Upserted workspace {wid}")
            return {"ok": True, "workspace": ws, "receipt": rec}
        if act == "index":
            wid = str(args.get("workspace_id") or "default")
            raw_rows = args.get("rows")
            if raw_rows is not None and not isinstance(raw_rows, list):
                raise ValueError("'rows' must be a JSON array of entity objects")
            rec = runtime.ledger.record(
                agent_id,
                "workspace_index",
                "",
                {"workspace_id": wid, "rows": len(raw_rows or [])},
                summary=f"Indexed {len(raw_rows or [])} entities into workspace {wid}",
            )
            count = runtime.knowledge.index_entities(
                workspace_id=wid,
                url=str(args.get("url") or "luminara://manual"),
                title=str(args.get("title") or ""),
                rows=list(raw_rows or []),
                receipt_id=rec["receipt_id"],
            )
            return {"ok": True, "workspace_id": wid, "indexed_count": count, "receipt": rec}
        if act == "search":
            hits = runtime.knowledge.search_knowledge(
                str(args.get("query") or ""),
                workspace_id=args.get("workspace_id") if args.get("workspace_id") else None,
                limit=_int_opt(args, "limit", 25),
            )
            return {"ok": True, "count": len(hits), "hits": hits}
        raise ValueError(f"Unsupported browser_workspace action: {act!r}")

    if name == "browser_hibernate_tabs":
        act = str(args.get("action") or "hibernate")
        if act == "hibernate":
            res = runtime.lifecycle.hibernate_idle_tabs(
                active_target_id=args.get("target_id"),
                min_idle_sec=_float_opt(args, "min_idle_sec", 0.0),
                dry_run=bool(args.get("dry_run", False)),
            )
            rec = runtime.ledger.record(
                agent_id,
                "hibernate_tabs",
                "",
                {"frozen_count": res["frozen_count"], "protected_count": res["protected_count"]},
                summary=f"Hibernated {res['frozen_count']}/{res['total_tabs']} idle tabs",
            )
            return {**res, "receipt": rec}
        tid = _require_str(args, "target_id")
        if act == "wake":
            res = runtime.lifecycle.wake_tab(tid)
            rec = runtime.ledger.record(agent_id, "wake_tab", tid, {}, summary=f"Woke frozen tab {tid}")
            return {**res, "receipt": rec}
        if act in ("pin", "unpin"):
            runtime.lifecycle.pin_tab(tid, pinned=(act == "pin"))
            rec = runtime.ledger.record(agent_id, f"tab_{act}", tid, {"pinned": act == "pin"}, summary=f"Set tab {tid} {act}")
            return {"ok": True, "target_id": tid, "pinned": act == "pin", "receipt": rec}
        raise ValueError(f"Unsupported browser_hibernate_tabs action: {act!r}")

    return None
