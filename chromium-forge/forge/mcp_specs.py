"""Canonical MCP v2 Tool/Resource Schemas & Discovery Manifest Builders (`forge/mcp_specs.py`)."""

from __future__ import annotations

from typing import Any

from .agent_tools_100x import MCP_TOOLS_100X_SPEC
from .agent_tools_flow import MCP_TOOLS_FLOW_SPEC
from .agent_tools_v31 import MCP_RESOURCES_V31_SPEC, MCP_TOOLS_V31_SPEC
from .models import ForkProfile

APP_VERSION = "3.1.0"
MCP_PROTOCOL_VERSION = "2025-06-18"

MCP_RESOURCES_SPEC: list[dict[str, str]] = [
    {"uri": "luminara://tabs/live", "name": "Live Co-Browsing Tabs", "mimeType": "application/json"},
    {"uri": "luminara://ledger/recent", "name": "Recent Verifiable LUM-* Action Receipts", "mimeType": "application/json"},
    {"uri": "luminara://ledger/verify", "name": "SHA-256 & HMAC Chain Verification Status", "mimeType": "application/json"},
    {"uri": "luminara://vault/entries", "name": "Origin-Pinned DPAPI/AEAD Model-Blind Vault Handles", "mimeType": "application/json"},
    {"uri": "luminara://playbooks/list", "name": "Learned Domain Co-Browsing Playbooks", "mimeType": "application/json"},
    {"uri": "luminara://workspaces/list", "name": "SQLite WAL + FTS5 Knowledge Workspaces", "mimeType": "application/json"},
    {"uri": "luminara://mutations/status", "name": "Network Mutation Firewall Savepoints", "mimeType": "application/json"},
    *MCP_RESOURCES_V31_SPEC,
]


def _tool_spec(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = list(required)
    return {"name": name, "description": description, "inputSchema": schema}


MCP_TOOLS_SPEC: list[dict[str, Any]] = [
    _tool_spec("browser_list_tabs", "List all open co-browsing tabs in the live Luminara Browser window and their active lease status."),
    _tool_spec(
        "browser_open_tab",
        "Open a URL in a new shared or background tab without interrupting the human user's active tab.",
        {"url": {"type": "string"}, "background": {"type": "boolean", "default": True}},
        required=("url",),
    ),
    _tool_spec("browser_close_tab", "Close a tab by target_id and release any active lease.", {"target_id": {"type": "string"}}, required=("target_id",)),
    _tool_spec(
        "browser_snapshot",
        "Index visible interactive DOM elements [1..N] across main document and frames with CSS selectors, ARIA roles, dialog state, and HITL gate detection.",
        {
            "target_id": {"type": "string"}, "frame_id": {"type": "string"},
            "include_frames": {"type": "boolean", "default": False}, "show_badges": {"type": "boolean", "default": True},
            "agent_id": {"type": "string", "default": "mcp-agent"},
        },
    ),
    _tool_spec(
        "browser_act",
        "Execute a co-browsing action (click, type, select, scroll, navigate, human_takeover, clear_hud) with a verifiable LUM-* receipt.",
        {
            "action": {"type": "string", "enum": ["click", "type", "select", "scroll", "navigate", "human_takeover", "clear_hud"]},
            "target_id": {"type": "string"}, "frame_id": {"type": "string"}, "index": {"type": "integer"},
            "selector": {"type": "string"}, "text": {"type": "string"}, "url": {"type": "string"},
            "agent_id": {"type": "string", "default": "mcp-agent"},
        },
        required=("action",),
    ),
    _tool_spec(
        "browser_extract_structured",
        "Extract clean tables, entities, headings, links, and formatted CSV/Markdown/JSON from a live tab.",
        {"target_id": {"type": "string"}, "format": {"type": "string", "enum": ["json", "csv", "md", "txt"], "default": "json"}, "workspace_id": {"type": "string", "default": "default"}},
    ),
    _tool_spec(
        "browser_generative_ui",
        "Transform the live tab into a Generative UI workspace specification (SummaryBar KPIs, Comparison/Table/Stack entities).",
        {"target_id": {"type": "string"}, "workspace_id": {"type": "string", "default": "default"}},
    ),
    _tool_spec(
        "browser_run_goal",
        "Run an autonomous perceive-decide-act goal on a tab (replaying verified domain playbooks in 0 LLM calls when matched); pauses cleanly with PAUSED_HUMAN_HANDOFF on login/MFA/verification gates.",
        {"goal": {"type": "string"}, "target_id": {"type": "string"}, "start_url": {"type": "string"}, "max_steps": {"type": "integer", "default": 8}, "show_badges": {"type": "boolean", "default": True}, "workspace_id": {"type": "string", "default": "default"}, "agent_id": {"type": "string", "default": "mcp-autopilot"}},
        required=("goal",),
    ),
    _tool_spec(
        "browser_bulk_extract",
        "Extract structured data and Generative UI across multiple URLs in parallel background tabs with per-domain adaptive throttling.",
        {"urls": {"type": "array", "items": {"type": "string"}}, "concurrency": {"type": "integer", "default": 4}, "format": {"type": "string", "default": "json"}, "workspace_id": {"type": "string", "default": "default"}},
        required=("urls",),
    ),
    _tool_spec(
        "browser_handoff_resume",
        "Resume a PAUSED_HUMAN_HANDOFF goal after the human completes login, MFA, or verification in the shared browser tab.",
        {"run_id": {"type": "string"}, "workspace_id": {"type": "string", "default": "default"}},
        required=("run_id",),
    ),
    _tool_spec(
        "browser_dialog",
        "Inspect, accept, or dismiss native JS dialogs (alert, confirm, prompt) captured by Luminara Dialog Supervisor.",
        {"action": {"type": "string", "enum": ["status", "accept", "dismiss"], "default": "status"}, "target_id": {"type": "string"}, "prompt_text": {"type": "string", "default": ""}, "dialog_id": {"type": "string"}, "agent_id": {"type": "string", "default": "mcp-agent"}},
        required=("action",),
    ),
    _tool_spec(
        "browser_vault",
        "Origin-pinned, model-blind credential and RFC 6238 TOTP vault. Fills passwords/TOTP over loopback CDP after synchronous origin verification without exposing secrets to the model or ledger.",
        {"action": {"type": "string", "enum": ["list", "register", "fill", "enter_totp", "delete"], "default": "list"}, "vault_id": {"type": "string"}, "origin": {"type": "string"}, "username": {"type": "string"}, "password": {"type": "string"}, "totp_secret": {"type": "string"}, "label": {"type": "string"}, "target_id": {"type": "string"}, "agent_id": {"type": "string", "default": "mcp-agent"}},
        required=("action",),
    ),
    _tool_spec(
        "browser_exec_pipeline",
        "Execute a multi-step co-browsing workflow (declarative steps or AST-verified Python script) in a single turn with zero LLM round-trip overhead and full LUM-* receipts.",
        {"steps": {"type": "array", "items": {"type": "object"}}, "script": {"type": "string"}, "max_calls": {"type": "integer", "default": 25}, "agent_id": {"type": "string", "default": "mcp-pipeline"}},
    ),
    _tool_spec(
        "browser_playbooks",
        "List, match, replay (0 LLM calls), or delete domain-keyed procedural playbooks learned from past co-browsing goals.",
        {"action": {"type": "string", "enum": ["list", "match", "replay", "delete"], "default": "list"}, "domain": {"type": "string"}, "url": {"type": "string"}, "goal": {"type": "string"}, "playbook_id": {"type": "string"}, "target_id": {"type": "string"}, "workspace_id": {"type": "string", "default": "default"}, "agent_id": {"type": "string", "default": "mcp-playbook"}},
    ),
    *MCP_TOOLS_100X_SPEC,
    *MCP_TOOLS_FLOW_SPEC,
    *MCP_TOOLS_V31_SPEC,
]


def build_llms_txt(prof: ForkProfile, host: str, srv_port: int) -> str:
    tool_lines = [f"- `{t['name']}`: {t['description']}" for t in MCP_TOOLS_SPEC]
    res_lines = [f"- `{r['uri']}`: {r['name']}" for r in MCP_RESOURCES_SPEC]
    return "\n".join(
        [
            f"# Luminara Browser v{APP_VERSION} — Dual Human + AI Agent Co-Browsing Engine",
            f"> Ungoogled-Chromium {prof.chromium_version}-1.1 hardened desktop browser with Multiplexed Loopback CDP (<1.5ms RTT), Blink AXTree + Shadow-DOM + OOPIF perception, W3C WebMCP (`navigator.modelContext`), Network Mutation Firewall (`Fetch.enable`), DPAPI/AEAD Vault, SQLite FTS5 Workspaces, Tab Hibernation, and {len(MCP_TOOLS_SPEC)}-Tool MCP v2.",
            "",
            "## Agent Control Endpoints",
            f"- MCP v2 JSON-RPC (`{MCP_PROTOCOL_VERSION}`): `POST http://{host}:{srv_port}/api/agent/mcp`",
            f"- Agent Manifest: `GET http://{host}:{srv_port}/.well-known/agent.json`",
            f"- REST Base: `http://{host}:{srv_port}/api/agent/{{status,tabs,open,close,snapshot,act,frames,extract,genui,goal,bulk,handoff/resume,dialog,vault,pipeline,playbooks,perception,webmcp/list,webmcp/call,mutations,workspaces,hibernate,outline,wait,screenshot,schedule,sequences,vrt,monitors,eval,casebundles,receipts,ledger/verify}}`",
            "",
            f"## MCP v2 Tools ({len(MCP_TOOLS_SPEC)})",
            *tool_lines,
            "",
            f"## MCP v2 Resources ({len(MCP_RESOURCES_SPEC)})",
            *res_lines,
            "",
            "## Co-Browsing & Safety Contract",
            "- Humans and AI agents share the exact same live browser window without exclusive F12 locks.",
            "- Human takeover (`human_takeover`) immediately preempts any active agent tab lease.",
            "- Login, MFA, payment, and verification gates return `PAUSED_HUMAN_HANDOFF` so the human completes them directly.",
            "- All CDP/MCP outputs and `LUM-*` receipts scrub secrets via `LuminaraRedactor` and carry `LUM-SIG-V2` (`lum-hmac256:...`) signatures.",
            "",
        ]
    )


def build_agent_manifest(prof: ForkProfile, host: str, srv_port: int, cdp_base_http: str) -> dict[str, Any]:
    return {
        "name": "Luminara Browser Agent Daemon",
        "slug": "luminara-browser",
        "version": APP_VERSION,
        "chromium_base": f"{prof.chromium_version}-1.1",
        "protocol": "mcp-v2",
        "mcp_protocol_version": MCP_PROTOCOL_VERSION,
        "mcp_endpoint": f"http://{host}:{srv_port}/api/agent/mcp",
        "rest_base": f"http://{host}:{srv_port}/api/agent",
        "ui_newtab": f"http://{host}:{srv_port}/newtab",
        "ui_workspace": f"http://{host}:{srv_port}/workspace",
        "cdp_target": cdp_base_http,
        "hitl_handoff_state": "PAUSED_HUMAN_HANDOFF",
        "receipt_prefix": "LUM-",
        "receipt_signature_scheme": "LUM-SIG-V2 (lum-hmac256)",
        "tools": [t["name"] for t in MCP_TOOLS_SPEC],
        "resources": [r["uri"] for r in MCP_RESOURCES_SPEC],
    }
