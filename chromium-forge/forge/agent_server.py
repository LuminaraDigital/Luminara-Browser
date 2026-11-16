"""Clean-room OBL-14: Luminara Agent Daemon (`127.0.0.1:8796`) — Hardened REST + MCP v2 + Same-Origin UI.

Upgrades over initial prototype:
- Inherits `LoopbackJSONHandler` (blocks DNS rebinding, `<iframe sandbox>` `Origin: null` bypass, `<form>` CSRF, and body OOM).
- Serves `/newtab` and `/workspace` directly on `http://127.0.0.1:8796` + caches `GET /api/agent/genui/latest`
  so the MV3 `luminara-copilot` Side Panel opens Workspace hydrated with zero cross-origin `localStorage` loss!
- Exposes `GET /api/agent/ledger/verify` and `luminara://ledger/verify` MCP resource for SHA-256 chain audits.
- Enforces `TabLeaseManager.check_allowed()` on mutating `browser_act` calls.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from typing import Any
import urllib.parse

from .agent_engine import ActionLedger, AgentGoalRunner, BulkEngine
from .cdp_client import CDPBridge, CDPError
from .extractor import (
    build_dom_action_js,
    build_dom_snapshot_js,
    extract_structured_page,
    format_extracted_rows,
    synthesize_generative_ui,
)
from .http_base import LoopbackHTTPServer, LoopbackJSONHandler, ensure_local_ui_key
from .luminara_ui import build_luminara_newtab_html, build_luminara_workspace_html
from .models import ForkProfile

ENCODING = "utf-8"
MCP_PROTOCOL_VERSION = "2025-06-18"

MCP_TOOLS_SPEC: list[dict[str, Any]] = [
    {
        "name": "browser_list_tabs",
        "description": "List all open co-browsing tabs in the live Luminara Browser window and their active lease status.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "browser_open_tab",
        "description": "Open a URL in a new shared or background tab without interrupting the human user's active tab.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "background": {"type": "boolean", "default": True},
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_close_tab",
        "description": "Close a tab by target_id and release any active lease.",
        "inputSchema": {
            "type": "object",
            "properties": {"target_id": {"type": "string"}},
            "required": ["target_id"],
        },
    },
    {
        "name": "browser_snapshot",
        "description": "Index visible interactive DOM elements [1..N] with real CSS selectors, ARIA roles, coordinates, and HITL gate detection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string"},
                "show_badges": {"type": "boolean", "default": True},
                "agent_id": {"type": "string", "default": "mcp-agent"},
            },
        },
    },
    {
        "name": "browser_act",
        "description": "Execute a co-browsing action (click, type, select, scroll, navigate, human_takeover, clear_hud) with a verifiable LUM-* receipt.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["click", "type", "select", "scroll", "navigate", "human_takeover", "clear_hud"],
                },
                "target_id": {"type": "string"},
                "index": {"type": "integer"},
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "url": {"type": "string"},
                "agent_id": {"type": "string", "default": "mcp-agent"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "browser_extract_structured",
        "description": "Extract clean tables, entities, headings, links, and formatted CSV/Markdown/JSON from a live tab.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string"},
                "format": {"type": "string", "enum": ["json", "csv", "md", "txt"], "default": "json"},
            },
        },
    },
    {
        "name": "browser_generative_ui",
        "description": "Transform the live tab into a Generative UI workspace specification (SummaryBar KPIs, Comparison/Table/Stack entities).",
        "inputSchema": {
            "type": "object",
            "properties": {"target_id": {"type": "string"}},
        },
    },
    {
        "name": "browser_run_goal",
        "description": "Run an autonomous perceive-decide-act goal on a tab; pauses cleanly with PAUSED_HUMAN_HANDOFF on login/MFA/verification gates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "target_id": {"type": "string"},
                "start_url": {"type": "string"},
                "max_steps": {"type": "integer", "default": 8},
                "agent_id": {"type": "string", "default": "mcp-autopilot"},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "browser_bulk_extract",
        "description": "Extract structured data and Generative UI across multiple URLs in parallel background tabs with per-domain adaptive throttling.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}},
                "concurrency": {"type": "integer", "default": 4},
                "format": {"type": "string", "default": "json"},
            },
            "required": ["urls"],
        },
    },
    {
        "name": "browser_handoff_resume",
        "description": "Resume a PAUSED_HUMAN_HANDOFF goal after the human completes login, MFA, or verification in the shared browser tab.",
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    },
]


class LuminaraAgentRuntime:
    """Stateful coordinator shared by REST & MCP v2 handlers."""

    def __init__(self, forge_root: Path, cdp_host: str = "127.0.0.1", cdp_port: int = 9229) -> None:
        self.forge_root = forge_root.resolve()
        self.outputs_dir = self.forge_root / "outputs"
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.local_ui_key = ensure_local_ui_key(self.forge_root)
        self.cdp = CDPBridge(host=cdp_host, port=cdp_port)
        self.ledger = ActionLedger(self.outputs_dir / "action_ledger.jsonl")
        self.bulk = BulkEngine(self.cdp, self.ledger, self.outputs_dir / "checkpoints")
        self.goals = AgentGoalRunner(self.cdp, self.ledger, self.outputs_dir / "active_handoffs.json")
        self.passport_token = os.environ.get("LUMINARA_AGENT_TOKEN", "").strip()
        self._genui_lock = threading.Lock()
        self.latest_genui: dict[str, Any] | None = None

    def current_profile(self) -> ForkProfile:
        prof_path = self.forge_root / "fork.json"
        if prof_path.exists():
            try:
                return ForkProfile.load(prof_path)
            except Exception:  # noqa: BLE001
                pass
        return ForkProfile()

    def set_latest_genui(self, payload: dict[str, Any] | None) -> None:
        if isinstance(payload, dict):
            with self._genui_lock:
                self.latest_genui = payload

    def get_latest_genui(self) -> dict[str, Any] | None:
        with self._genui_lock:
            return self.latest_genui

    def dispatch_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(args.get("agent_id") or "luminara-agent")
        if name == "browser_list_tabs":
            connected = self.cdp.is_alive()
            tabs = self.cdp.list_tabs() if connected else []
            return {"cdp_connected": connected, "cdp_port": self.cdp.port, "tabs": tabs}

        if name == "browser_open_tab":
            url = str(args["url"])
            bg = bool(args.get("background", True))
            tab = self.cdp.open_tab(url, background=bg)
            rec = self.ledger.record(agent_id, "open_tab", tab["target_id"], {"url": url, "background": bg}, summary=f"Opened {url}")
            return {"tab": tab, "receipt": rec}

        if name == "browser_close_tab":
            tid = str(args["target_id"])
            self.cdp.leases.check_allowed(tid, agent_id)
            closed = self.cdp.close_tab(tid)
            rec = self.ledger.record(agent_id, "close_tab", tid, {}, summary=f"Closed tab {tid}")
            return {"closed": closed, "receipt": rec}

        if name == "browser_snapshot":
            tid = args.get("target_id")
            badges = bool(args.get("show_badges", True))
            resolved_tid = self.cdp._pick_target_id(tid)
            snap = self.cdp.evaluate_js(resolved_tid, build_dom_snapshot_js(show_badges=badges, agent_label=agent_id))
            if isinstance(snap, dict):
                snap.pop("outer_html", None)
                snap["target_id"] = resolved_tid
            rec = self.ledger.record(
                agent_id,
                "snapshot",
                resolved_tid,
                {"show_badges": badges},
                summary=f"Indexed {len(snap.get('elements', [])) if isinstance(snap, dict) else 0} targets",
            )
            return {"snapshot": snap, "receipt": rec}

        if name == "browser_act":
            act = str(args["action"])
            tid = args.get("target_id")
            resolved_tid = self.cdp._pick_target_id(tid)
            if act == "human_takeover":
                self.cdp.leases.force_human_override(resolved_tid)
                self.cdp.evaluate_js(resolved_tid, build_dom_action_js("clear_hud"))
                rec = self.ledger.record("human-user", "human_takeover", resolved_tid, {}, summary="Human preempted agent lease")
                return {"ok": True, "target_id": resolved_tid, "receipt": rec}

            if act != "clear_hud":
                self.cdp.leases.check_allowed(resolved_tid, agent_id)

            if act == "navigate":
                url = str(args.get("url") or "about:blank")
                nav = self.cdp.navigate(resolved_tid, url)
                rec = self.ledger.record(agent_id, "navigate", resolved_tid, {"url": url}, summary=f"Navigated to {url}")
                return {"ok": True, "navigation": nav, "receipt": rec}

            res = self.cdp.evaluate_js(
                resolved_tid,
                build_dom_action_js(
                    act,
                    index=int(args["index"]) if args.get("index") is not None else None,
                    selector=args.get("selector"),
                    text=str(args.get("text") or ""),
                ),
            )
            rec = self.ledger.record(
                agent_id,
                f"dom_{act}",
                resolved_tid,
                {"index": args.get("index"), "selector": args.get("selector")},
                status="OK" if isinstance(res, dict) and res.get("ok") else "WARN",
                summary=f"Executed {act} on tab {resolved_tid}",
            )
            return {"result": res, "target_id": resolved_tid, "receipt": rec}

        if name in ("browser_extract_structured", "browser_generative_ui"):
            tid = args.get("target_id")
            resolved_tid = self.cdp._pick_target_id(tid)
            snap = self.cdp.evaluate_js(resolved_tid, build_dom_snapshot_js(show_badges=False, agent_label=""))
            html_src = snap.get("outer_html", "") if isinstance(snap, dict) else ""
            url = snap.get("url", "") if isinstance(snap, dict) else ""
            extracted = extract_structured_page(html_src, url)
            gen_ui = synthesize_generative_ui(extracted["rows"], title=extracted["title"] or "Live Tab Workspace")
            self.set_latest_genui(gen_ui)
            fmt = str(args.get("format") or "json")
            rec = self.ledger.record(
                agent_id,
                name,
                resolved_tid,
                {"url": url},
                summary=f"Synthesized {len(extracted['rows'])} entities from {url[:60]}",
            )
            if name == "browser_generative_ui":
                return {"target_id": resolved_tid, "url": url, "generative_ui": gen_ui, "rows": extracted["rows"], "receipt": rec}
            return {
                "target_id": resolved_tid,
                "extracted": extracted,
                "formatted": format_extracted_rows(extracted["rows"], fmt),
                "generative_ui": gen_ui,
                "receipt": rec,
            }

        if name == "browser_run_goal":
            res = self.goals.run_goal(
                goal=str(args["goal"]),
                target_id=args.get("target_id"),
                start_url=args.get("start_url"),
                max_steps=int(args.get("max_steps", 8)),
                agent_id=agent_id,
            )
            self.set_latest_genui(res.get("generative_ui"))
            return res

        if name == "browser_bulk_extract":
            res = self.bulk.run_job(
                urls=list(args.get("urls") or []),
                concurrency=int(args.get("concurrency", 4)),
                output_format=str(args.get("format") or "json"),
                agent_id=agent_id,
            )
            self.set_latest_genui(res.get("generative_ui"))
            return res

        if name == "browser_handoff_resume":
            res = self.goals.resume_handoff(str(args["run_id"]))
            self.set_latest_genui(res.get("generative_ui"))
            return res

        raise ValueError(f"Unknown MCP tool: {name!r}")


def create_agent_http_server(
    runtime: LuminaraAgentRuntime,
    host: str = "127.0.0.1",
    port: int = 8796,
) -> LoopbackHTTPServer:
    """Create a thread-pooled HTTP + MCP v2 server bound strictly to loopback."""

    class Handler(LoopbackJSONHandler):
        local_ui_key = runtime.local_ui_key
        bearer_token = runtime.passport_token
        allow_extension_origins = True

        def do_GET(self) -> None:  # noqa: N802
            if not self.check_loopback_security(is_post=False):
                return
            try:
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path
                qs = urllib.parse.parse_qs(parsed.query)
                srv_port = self.server.server_port

                if path in ("/newtab", "/ui/newtab"):
                    prof = runtime.current_profile()
                    html_doc = build_luminara_newtab_html(
                        prof,
                        workspace_uri="/workspace",
                        agent_port=srv_port,
                        cdp_port=runtime.cdp.port,
                        ui_key=runtime.local_ui_key,
                    )
                    self.send_text(html_doc, content_type="text/html; charset=utf-8")
                    return

                if path in ("/workspace", "/ui/workspace"):
                    prof = runtime.current_profile()
                    html_doc = build_luminara_workspace_html(
                        prof,
                        newtab_uri="/newtab",
                        agent_port=srv_port,
                        ui_key=runtime.local_ui_key,
                    )
                    self.send_text(html_doc, content_type="text/html; charset=utf-8")
                    return

                if path == "/llms.txt":
                    llms_doc = "\n".join(
                        [
                            "# Luminara Browser — Dual Human + AI Agent Co-Browsing Engine",
                            "> Ungoogled-Chromium 157 hardened desktop browser with loopback CDP co-presence, Set-of-Marks DOM indexing, parallel Bulk Extraction, Generative UI Workspace, and MCP v2.",
                            "",
                            "## Agent Control Endpoints",
                            f"- MCP v2 JSON-RPC (`{MCP_PROTOCOL_VERSION}`): `POST http://{host}:{srv_port}/api/agent/mcp`",
                            f"- Agent Manifest: `GET http://{host}:{srv_port}/.well-known/agent.json`",
                            f"- Live Tabs & Leases: `GET http://{host}:{srv_port}/api/agent/tabs`",
                            f"- Hash-Chained LUM-* Receipts: `GET http://{host}:{srv_port}/api/agent/receipts`",
                            f"- Verify Receipt Chain: `GET http://{host}:{srv_port}/api/agent/ledger/verify`",
                            "",
                            "## Co-Browsing & Safety Contract",
                            "- Humans and AI agents share the exact same live browser window without exclusive locks.",
                            "- Human takeover (`human_takeover`) immediately preempts any active agent tab lease.",
                            "- Login, MFA, payment, and verification gates return `PAUSED_HUMAN_HANDOFF` so the human completes them directly.",
                            "",
                        ]
                    )
                    self.send_text(llms_doc)
                    return

                if path == "/.well-known/agent.json":
                    self.send_json(
                        {
                            "name": "Luminara Browser Agent Daemon",
                            "slug": "luminara-browser",
                            "version": "2.1.0",
                            "protocol": "mcp-v2",
                            "mcp_protocol_version": MCP_PROTOCOL_VERSION,
                            "mcp_endpoint": f"http://{host}:{srv_port}/api/agent/mcp",
                            "rest_base": f"http://{host}:{srv_port}/api/agent",
                            "ui_newtab": f"http://{host}:{srv_port}/newtab",
                            "ui_workspace": f"http://{host}:{srv_port}/workspace",
                            "cdp_target": runtime.cdp.base_http,
                            "hitl_handoff_state": "PAUSED_HUMAN_HANDOFF",
                            "receipt_prefix": "LUM-",
                            "tools": [t["name"] for t in MCP_TOOLS_SPEC],
                        }
                    )
                    return

                if path == "/api/agent/status":
                    connected = runtime.cdp.is_alive()
                    tabs = runtime.cdp.list_tabs() if connected else []
                    self.send_json(
                        {
                            "ok": True,
                            "browser": "Luminara Browser",
                            "cdp_connected": connected,
                            "cdp_port": runtime.cdp.port,
                            "open_tabs": len(tabs),
                            "active_handoffs": list(runtime.goals.active_handoffs.values()),
                            "recent_receipts": runtime.ledger.recent(10),
                        }
                    )
                    return

                if path == "/api/agent/tabs":
                    self.send_json(runtime.dispatch_tool("browser_list_tabs", {}))
                    return

                if path == "/api/agent/genui/latest":
                    self.send_json({"generative_ui": runtime.get_latest_genui()})
                    return

                if path == "/api/agent/receipts":
                    raw_lim = (qs.get("limit") or ["40"])[0]
                    limit = max(1, min(200, int(raw_lim)))
                    self.send_json({"receipts": runtime.ledger.recent(limit)})
                    return

                if path == "/api/agent/ledger/verify":
                    self.send_json(runtime.ledger.verify_ledger())
                    return

                if path == "/api/agent/screenshot":
                    tid = (qs.get("target_id") or [None])[0]
                    fmt = (qs.get("format") or ["jpeg"])[0]
                    qual = int((qs.get("quality") or ["75"])[0])
                    resolved_tid, b64 = runtime.cdp.capture_screenshot(tid, fmt=fmt, quality=qual)
                    norm_fmt = "jpeg" if fmt.lower() == "jpg" else fmt.lower()
                    self.send_json({"target_id": resolved_tid, "mime": f"image/{norm_fmt}", "data_base64": b64})
                    return

                self.send_json({"error": "Not found"}, status=404)
            except Exception as exc:  # noqa: BLE001
                self.send_json({"error": str(exc)}, status=400)

        def do_POST(self) -> None:  # noqa: N802
            if not self.check_loopback_security(is_post=True):
                return
            try:
                body = self.read_json_dict()
            except json.JSONDecodeError as exc:
                if self.path == "/api/agent/mcp":
                    self.send_json({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}})
                else:
                    self.send_json({"error": f"Invalid JSON: {exc}"}, status=400)
                return
            except ValueError as exc:
                if self.path == "/api/agent/mcp":
                    self.send_json({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": str(exc)}})
                else:
                    self.send_json({"error": str(exc)}, status=400)
                return

            try:
                if self.path == "/api/agent/mcp":
                    self._handle_mcp(body)
                    return

                if self.path == "/api/agent/bulk/cancel":
                    jid = str(body.get("job_id") or "")
                    runtime.bulk.cancel(jid)
                    self.send_json({"ok": True, "cancelled": jid})
                    return

                route_map = {
                    "/api/agent/open": "browser_open_tab",
                    "/api/agent/close": "browser_close_tab",
                    "/api/agent/snapshot": "browser_snapshot",
                    "/api/agent/act": "browser_act",
                    "/api/agent/extract": "browser_extract_structured",
                    "/api/agent/genui": "browser_generative_ui",
                    "/api/agent/goal": "browser_run_goal",
                    "/api/agent/bulk": "browser_bulk_extract",
                    "/api/agent/handoff/resume": "browser_handoff_resume",
                }
                tool_name = route_map.get(self.path)
                if not tool_name:
                    self.send_json({"error": f"Unknown endpoint {self.path}"}, status=404)
                    return
                self.send_json(runtime.dispatch_tool(tool_name, body))
            except CDPError as exc:
                self.send_json({"error": str(exc), "cdp_connected": runtime.cdp.is_alive()}, status=502)
            except Exception as exc:  # noqa: BLE001
                self.send_json({"error": str(exc)}, status=400)

        def _handle_mcp(self, rpc: dict[str, Any]) -> None:
            req_id = rpc.get("id")
            method = rpc.get("method", "")
            params = rpc.get("params") or {}
            if not isinstance(params, dict):
                self.send_json({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "params must be an object"}})
                return

            if method == "notifications/initialized":
                self.send_response(204)
                self.write_cors_headers()
                self.end_headers()
                return

            try:
                if method == "initialize":
                    result: dict[str, Any] = {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {"tools": {}, "resources": {}},
                        "serverInfo": {"name": "luminara-browser-mcp", "version": "2.1.0"},
                    }
                elif method == "tools/list":
                    result = {"tools": MCP_TOOLS_SPEC}
                elif method == "tools/call":
                    t_name = str(params.get("name") or "")
                    t_args = params.get("arguments") or {}
                    if not isinstance(t_args, dict):
                        raise ValueError("tool arguments must be an object")
                    payload = runtime.dispatch_tool(t_name, t_args)
                    result = {
                        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                        "structuredContent": payload,
                        "isError": False,
                    }
                elif method == "resources/list":
                    result = {
                        "resources": [
                            {"uri": "luminara://tabs/live", "name": "Live Co-Browsing Tabs", "mimeType": "application/json"},
                            {"uri": "luminara://ledger/recent", "name": "Recent Verifiable LUM-* Action Receipts", "mimeType": "application/json"},
                            {"uri": "luminara://ledger/verify", "name": "SHA-256 Chain Verification Status", "mimeType": "application/json"},
                        ]
                    }
                elif method == "resources/read":
                    uri = str(params.get("uri") or "")
                    if uri == "luminara://tabs/live":
                        data = runtime.dispatch_tool("browser_list_tabs", {})
                    elif uri == "luminara://ledger/recent":
                        data = {"receipts": runtime.ledger.recent(25)}
                    elif uri == "luminara://ledger/verify":
                        data = runtime.ledger.verify_ledger()
                    else:
                        raise ValueError(f"Unknown MCP resource URI: {uri}")
                    result = {
                        "contents": [
                            {"uri": uri, "mimeType": "application/json", "text": json.dumps(data, ensure_ascii=False)}
                        ]
                    }
                else:
                    self.send_json({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}})
                    return

                self.send_json({"jsonrpc": "2.0", "id": req_id, "result": result})
            except Exception as exc:  # noqa: BLE001
                self.send_json({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(exc)}})

    return LoopbackHTTPServer((host, port), Handler)


def run_agent_daemon(
    forge_root: Path,
    host: str = "127.0.0.1",
    port: int = 8796,
    cdp_port: int = 9229,
) -> None:
    runtime = LuminaraAgentRuntime(forge_root=forge_root, cdp_host="127.0.0.1", cdp_port=cdp_port)
    srv = create_agent_http_server(runtime, host=host, port=port)
    print(
        f"Luminara Browser Agent Daemon (REST + MCP v2) listening on http://{host}:{port} -> CDP 127.0.0.1:{cdp_port}",
        flush=True,
    )
    srv.serve_forever()
