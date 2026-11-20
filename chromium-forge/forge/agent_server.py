"""Clean-room OBL-14: Luminara Agent Daemon (`127.0.0.1:8796`) — Hardened REST + MCP v2 + Same-Origin UI.

Production `v3.0.0` architecture:
- Inherits `LoopbackJSONHandler` (blocks DNS rebinding, cross-port loopback Origin scraping, `<iframe sandbox>`
  `Origin: null` bypass, `<form>` CSRF, and body OOM).
- Serves `/newtab` and `/workspace` directly on `http://127.0.0.1:8796` + caches redacted `GET /api/agent/genui/latest`
  so the MV3 `luminara-copilot` Side Panel opens Workspace hydrated with zero cross-origin `localStorage` loss.
- Exposes 20 MCP v2 tools and 7 MCP resources, enforcing `LuminaraRedactor` across all REST, MCP, and error egress.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from typing import Any
import urllib.parse

from .agent_engine import ActionLedger, AgentGoalRunner, BulkEngine
from .agent_tools_100x import MCP_TOOLS_100X_SPEC, _require_str, dispatch_100x_tool
from .cdp_client import CDPBridge, CDPError
from .extractor import (
    build_dialog_control_js,
    build_dom_action_js,
    build_dom_snapshot_js,
    extract_structured_page,
    format_extracted_rows,
    synthesize_generative_ui,
)
from .http_base import LoopbackHTTPServer, LoopbackJSONHandler, ensure_local_ui_key
from .knowledge_graph import KnowledgeWorkspaceStore, TabLifecycleManager
from .luminara_automation import PipelineSandboxRunner, PlaybookMemory
from .luminara_crypto import EphemeralSessionSigner
from .luminara_security import DEFAULT_REDACTOR, LuminaraVault
from .luminara_ui import build_luminara_newtab_html, build_luminara_workspace_html
from .models import ForkProfile
from .mutation_firewall import NetworkMutationFirewall
from .perception import HybridPerceptionEngine
from .webmcp import WebMCPBridge

ENCODING = "utf-8"
APP_VERSION = "3.0.0"
MCP_PROTOCOL_VERSION = "2025-06-18"

MCP_RESOURCES_SPEC: list[dict[str, str]] = [
    {"uri": "luminara://tabs/live", "name": "Live Co-Browsing Tabs", "mimeType": "application/json"},
    {"uri": "luminara://ledger/recent", "name": "Recent Verifiable LUM-* Action Receipts", "mimeType": "application/json"},
    {"uri": "luminara://ledger/verify", "name": "SHA-256 & HMAC Chain Verification Status", "mimeType": "application/json"},
    {"uri": "luminara://vault/entries", "name": "Origin-Pinned DPAPI/AEAD Model-Blind Vault Handles", "mimeType": "application/json"},
    {"uri": "luminara://playbooks/list", "name": "Learned Domain Co-Browsing Playbooks", "mimeType": "application/json"},
    {"uri": "luminara://workspaces/list", "name": "SQLite WAL + FTS5 Knowledge Workspaces", "mimeType": "application/json"},
    {"uri": "luminara://mutations/status", "name": "Network Mutation Firewall Savepoints", "mimeType": "application/json"},
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
        {"goal": {"type": "string"}, "target_id": {"type": "string"}, "start_url": {"type": "string"}, "max_steps": {"type": "integer", "default": 8}, "workspace_id": {"type": "string", "default": "default"}, "agent_id": {"type": "string", "default": "mcp-autopilot"}},
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
]


class LuminaraAgentRuntime:
    """Stateful coordinator shared by REST & MCP v2 handlers."""

    def __init__(self, forge_root: Path, cdp_host: str = "127.0.0.1", cdp_port: int = 9229) -> None:
        self.forge_root = forge_root.resolve()
        self.outputs_dir = self.forge_root / "outputs"
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.local_ui_key = ensure_local_ui_key(self.forge_root)
        key_bytes = bytes.fromhex(self.local_ui_key[:64]) if len(self.local_ui_key) >= 64 else self.local_ui_key.encode(ENCODING).ljust(32, b"0")
        self.signer = EphemeralSessionSigner(key_bytes)
        self.redactor = DEFAULT_REDACTOR
        self.cdp = CDPBridge(host=cdp_host, port=cdp_port)
        self.ledger = ActionLedger(self.outputs_dir / "action_ledger.jsonl", redactor=self.redactor, signer=self.signer)
        self.vault = LuminaraVault(self.outputs_dir / "vault.json", redactor=self.redactor)
        self.playbooks = PlaybookMemory(self.outputs_dir / "playbooks")
        self.perception = HybridPerceptionEngine(self.cdp)
        self.webmcp = WebMCPBridge(self.cdp)
        self.mutation_firewall = NetworkMutationFirewall(self.cdp, redactor=self.redactor)
        self.knowledge = KnowledgeWorkspaceStore(self.outputs_dir / "knowledge_graph.sqlite3", redactor=self.redactor)
        self.lifecycle = TabLifecycleManager(self.cdp)
        self.bulk = BulkEngine(self.cdp, self.ledger, self.outputs_dir / "checkpoints")
        self.goals = AgentGoalRunner(
            self.cdp,
            self.ledger,
            self.outputs_dir / "active_handoffs.json",
            playbooks=self.playbooks,
        )
        self.pipeline = PipelineSandboxRunner(self.dispatch_tool)
        self.passport_token = os.environ.get("LUMINARA_AGENT_TOKEN", "").strip()
        if self.passport_token:
            self.redactor.register_secret(self.passport_token)
        self._genui_lock = threading.Lock()
        self.latest_genui: dict[str, Any] | None = None

    def close(self) -> None:
        self.mutation_firewall.close()
        self.cdp.close()

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
            scrubbed = self.redactor.redact_payload(payload)
            with self._genui_lock:
                self.latest_genui = scrubbed

    def get_latest_genui(self) -> dict[str, Any] | None:
        with self._genui_lock:
            return self.redactor.redact_payload(self.latest_genui) if self.latest_genui is not None else None

    def _index_extracted_rows(
        self,
        args: dict[str, Any],
        url: str,
        title: str,
        rows: list[dict[str, Any]] | None,
        receipt_id: str = "",
    ) -> None:
        if rows:
            self.knowledge.index_entities(
                workspace_id=str(args.get("workspace_id") or "default"),
                url=self.redactor.redact_text(str(url or "")),
                title=self.redactor.redact_text(str(title or "")),
                rows=self.redactor.redact_payload(rows),
                receipt_id=str(receipt_id or ""),
            )

    def _active_tab_url(self, target_id: str | None = None) -> str:
        if not self.cdp.is_alive():
            return ""
        try:
            tabs = self.cdp.list_tabs()
            if not tabs:
                return ""
            picked = target_id or self.cdp._pick_target_id(None)
            for t in tabs:
                if t.get("target_id") == picked:
                    return str(t.get("url") or "")
            return str(tabs[0].get("url") or "")
        except Exception:  # noqa: BLE001
            return ""

    def dispatch_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        out = self._dispatch_tool_raw(name, args)
        return self.redactor.redact_payload(out)

    def _dispatch_tool_raw(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(args.get("agent_id") or "luminara-agent")
        if name == "browser_list_tabs":
            connected = self.cdp.is_alive()
            tabs = self.cdp.list_tabs() if connected else []
            return {"cdp_connected": connected, "cdp_port": self.cdp.port, "tabs": tabs}

        if name == "browser_open_tab":
            url = _require_str(args, "url")
            bg = bool(args.get("background", True))
            tab = self.cdp.open_tab(url, background=bg)
            self.lifecycle.touch_tab(tab["target_id"])
            if self.current_profile().guard_network_mutations:
                try:
                    self.mutation_firewall.enable_guard(tab["target_id"])
                except Exception:  # noqa: BLE001
                    pass
            rec = self.ledger.record(agent_id, "open_tab", tab["target_id"], {"url": url, "background": bg}, summary=f"Opened {url}")
            return {"tab": tab, "receipt": rec}

        if name == "browser_close_tab":
            tid = _require_str(args, "target_id")
            self.cdp.leases.check_allowed(tid, agent_id)
            closed = self.cdp.close_tab(tid)
            rec = self.ledger.record(agent_id, "close_tab", tid, {}, summary=f"Closed tab {tid}")
            return {"closed": closed, "receipt": rec}

        if name == "browser_snapshot":
            tid = args.get("target_id")
            frame_id = args.get("frame_id")
            include_frames = bool(args.get("include_frames", False))
            badges = bool(args.get("show_badges", True))
            resolved_tid = self.cdp._pick_target_id(tid)
            self.lifecycle.touch_tab(resolved_tid)
            snap = self.cdp.evaluate_js(
                resolved_tid,
                build_dom_snapshot_js(show_badges=badges, agent_label=agent_id),
                frame_id=str(frame_id) if frame_id else None,
            )
            if isinstance(snap, dict):
                snap.pop("outer_html", None)
                snap["target_id"] = resolved_tid
                if frame_id:
                    snap["frame_id"] = str(frame_id)
                native_dlgs = self.cdp.get_native_dialogs(resolved_tid)
                if native_dlgs:
                    snap["native_dialogs"] = native_dlgs
                if include_frames:
                    snap["frame_tree"] = self.cdp.get_frame_tree(resolved_tid)
            rec = self.ledger.record(
                agent_id,
                "snapshot",
                resolved_tid,
                {"show_badges": badges, "frame_id": frame_id or ""},
                summary=f"Indexed {len(snap.get('elements', [])) if isinstance(snap, dict) else 0} targets",
            )
            return {"snapshot": snap, "receipt": rec}

        if name == "browser_act":
            act = _require_str(args, "action")
            tid = args.get("target_id")
            frame_id = args.get("frame_id")
            resolved_tid = self.cdp._pick_target_id(tid)
            self.lifecycle.touch_tab(resolved_tid)
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
                frame_id=str(frame_id) if frame_id else None,
            )
            rec = self.ledger.record(
                agent_id,
                f"dom_{act}",
                resolved_tid,
                {"index": args.get("index"), "selector": args.get("selector"), "frame_id": frame_id or ""},
                status="OK" if isinstance(res, dict) and res.get("ok") else "WARN",
                summary=f"Executed {act} on tab {resolved_tid}",
            )
            return {"result": res, "target_id": resolved_tid, "receipt": rec}

        if name == "browser_dialog":
            act = str(args.get("action") or "status")
            tid = args.get("target_id")
            prompt_text = str(args.get("prompt_text") or "")
            dialog_id = args.get("dialog_id")
            resolved_tid = self.cdp._pick_target_id(tid)
            self.lifecycle.touch_tab(resolved_tid)
            if act in ("accept", "dismiss"):
                self.cdp.leases.check_allowed(resolved_tid, agent_id)
                self.cdp.set_native_dialog_policy(resolved_tid, accept=(act == "accept"), prompt_text=prompt_text)
                try:
                    self.cdp.run_session(
                        resolved_tid,
                        [
                            ("Page.enable", {}),
                            ("Page.handleJavaScriptDialog", {"accept": act == "accept", "promptText": prompt_text}),
                        ],
                        timeout=3.0,
                    )
                except Exception:  # noqa: BLE001
                    pass
            res = self.cdp.evaluate_js(
                resolved_tid,
                build_dialog_control_js(action=act, prompt_text=prompt_text, dialog_id=str(dialog_id) if dialog_id else None),
            )
            native_dlgs = self.cdp.get_native_dialogs(resolved_tid)
            rec = self.ledger.record(
                agent_id,
                f"dialog_{act}",
                resolved_tid,
                {"action": act, "dialog_id": dialog_id or ""},
                summary=f"Dialog supervisor {act} on tab {resolved_tid}",
            )
            return {"target_id": resolved_tid, "dialog": res, "native_dialogs": native_dlgs, "receipt": rec}

        if name == "browser_vault":
            v_act = str(args.get("action") or "list")
            if v_act == "list":
                entries = self.vault.list_entries(origin_filter=args.get("origin"))
                return {"ok": True, "action": "list", "entries": entries}
            if v_act == "register":
                pub = self.vault.upsert_entry(
                    origin=_require_str(args, "origin"),
                    username=str(args.get("username") or ""),
                    password=str(args.get("password") or ""),
                    totp_secret=str(args.get("totp_secret") or ""),
                    vault_id=args.get("vault_id") if isinstance(args.get("vault_id"), str) and args.get("vault_id").strip() else None,
                    label=str(args.get("label") or ""),
                )
                rec = self.ledger.record(
                    agent_id,
                    "vault_register",
                    "",
                    {"vault_id": pub["vault_id"], "origin": pub["origin"], "username": pub["username"]},
                    summary=f"Registered origin-bound vault credential {pub['vault_id']} for {pub['origin']}",
                )
                return {"ok": True, "action": "register", "entry": pub, "receipt": rec}
            if v_act == "delete":
                vid = _require_str(args, "vault_id")
                deleted = self.vault.delete_entry(vid)
                rec = self.ledger.record(agent_id, "vault_delete", "", {"vault_id": vid}, summary=f"Deleted vault entry {vid}")
                return {"ok": True, "action": "delete", "deleted": deleted, "receipt": rec}
            if v_act in ("fill", "enter_totp"):
                vid = _require_str(args, "vault_id")
                tid = args.get("target_id")
                fill_res = (
                    self.vault.fill_credential(self.cdp, tid, vid, agent_id=agent_id)
                    if v_act == "fill"
                    else self.vault.fill_totp(self.cdp, tid, vid, agent_id=agent_id)
                )
                rec = self.ledger.record(
                    agent_id,
                    f"vault_{v_act}",
                    str(fill_res.get("target_id") or ""),
                    {
                        "vault_id": vid,
                        "origin": fill_res.get("origin", ""),
                        "filled_fields": fill_res.get("filled_fields", []),
                    },
                    status="OK" if fill_res.get("ok") else "WARN",
                    summary=f"Executed model-blind {v_act} ({vid}) on {fill_res.get('origin', '')}",
                )
                return {**fill_res, "receipt": rec}
            raise ValueError(f"Unsupported browser_vault action: {v_act!r}")

        if name == "browser_exec_pipeline":
            max_calls = int(args["max_calls"]) if args.get("max_calls") is not None else 25
            pipe_res = self.pipeline.run_pipeline(
                steps=args.get("steps"),
                script=args.get("script"),
                max_calls=max_calls,
                agent_id=agent_id,
            )
            rec = self.ledger.record(
                agent_id,
                "exec_pipeline",
                "",
                {"calls_executed": pipe_res.get("calls_executed", 0), "status": pipe_res.get("status", "COMPLETED")},
                status=str(pipe_res.get("status") or "OK"),
                summary=f"Executed single-turn pipeline ({pipe_res.get('calls_executed', 0)} calls)",
            )
            return {**pipe_res, "receipt": rec}

        if name == "browser_playbooks":
            p_act = str(args.get("action") or "list")
            if p_act == "list":
                return {"ok": True, "playbooks": self.playbooks.list_playbooks(domain=args.get("domain"))}
            req_url = str(args.get("url") or "") or self._active_tab_url(args.get("target_id"))
            req_goal = str(args.get("goal") or "")
            if p_act == "match":
                matched = self.playbooks.match_playbook(req_url, req_goal) or (
                    self.playbooks.match_playbook("", req_goal) if req_url else None
                )
                return {"ok": True, "matched": matched}
            if p_act == "replay":
                pid = str(args.get("playbook_id") or "")
                pb = (
                    self.playbooks.get_playbook(pid)
                    if pid
                    else (
                        self.playbooks.match_playbook(req_url, req_goal)
                        or (self.playbooks.match_playbook("", req_goal) if req_url else None)
                    )
                )
                if pb is None:
                    raise ValueError("No verified playbook matched playbook_id or (url, goal)")
                rep = self.playbooks.replay_playbook(
                    pb,
                    cdp=self.cdp,
                    ledger=self.ledger,
                    target_id=args.get("target_id"),
                    agent_id=agent_id,
                )
                if rep.get("status") == "COMPLETED":
                    snap_after = self.cdp.evaluate_js(rep["target_id"], build_dom_snapshot_js(show_badges=False, agent_label=""))
                    after_url = str(snap_after.get("url") or "") if isinstance(snap_after, dict) else ""
                    ext = extract_structured_page(
                        snap_after.get("outer_html", "") if isinstance(snap_after, dict) else "",
                        after_url,
                    )
                    gen_ui = synthesize_generative_ui(ext["rows"], title=ext["title"] or pb["playbook_id"])
                    self.set_latest_genui(gen_ui)
                    self._index_extracted_rows(args, after_url, str(ext.get("title") or ""), ext["rows"])
                    rep["extracted"] = ext
                    rep["generative_ui"] = gen_ui
                return rep
            if p_act == "delete":
                pid = _require_str(args, "playbook_id")
                deleted = self.playbooks.delete_playbook(pid)
                rec = self.ledger.record(agent_id, "playbook_delete", "", {"playbook_id": pid, "deleted": deleted}, summary=f"Deleted playbook {pid}")
                return {"ok": True, "deleted": deleted, "playbook_id": pid, "receipt": rec}
            raise ValueError(f"Unsupported browser_playbooks action: {p_act!r}")

        if name in ("browser_extract_structured", "browser_generative_ui"):
            resolved_tid = self.cdp._pick_target_id(args.get("target_id"))
            self.lifecycle.touch_tab(resolved_tid)
            snap = self.cdp.evaluate_js(resolved_tid, build_dom_snapshot_js(show_badges=False, agent_label=""))
            html_src = snap.get("outer_html", "") if isinstance(snap, dict) else ""
            url = snap.get("url", "") if isinstance(snap, dict) else ""
            extracted = extract_structured_page(html_src, url)
            gen_ui = synthesize_generative_ui(extracted["rows"], title=extracted["title"] or "Live Tab Workspace")
            self.set_latest_genui(gen_ui)
            fmt = str(args.get("format") or "json")
            rec = self.ledger.record(
                agent_id, name, resolved_tid, {"url": url}, summary=f"Synthesized {len(extracted['rows'])} entities from {url[:60]}"
            )
            self._index_extracted_rows(args, url, str(extracted.get("title") or ""), extracted["rows"], rec["receipt_id"])
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
            max_steps = int(args["max_steps"]) if args.get("max_steps") is not None else 8
            res = self.goals.run_goal(
                goal=_require_str(args, "goal"),
                target_id=args.get("target_id"),
                start_url=args.get("start_url"),
                max_steps=max_steps,
                agent_id=agent_id,
            )
            self.set_latest_genui(res.get("generative_ui"))
            ext_obj = res.get("extracted")
            if isinstance(ext_obj, dict):
                self._index_extracted_rows(
                    args,
                    str(res.get("url") or res.get("final_url") or ""),
                    str(ext_obj.get("title") or ""),
                    ext_obj.get("rows"),
                    str((res.get("receipt") or {}).get("receipt_id") or ""),
                )
            return res

        if name == "browser_bulk_extract":
            raw_urls = args.get("urls")
            if not isinstance(raw_urls, list):
                raise ValueError("'urls' must be a JSON array of URL strings")
            conc = int(args["concurrency"]) if args.get("concurrency") is not None else 4
            res = self.bulk.run_job(
                urls=[str(u) for u in raw_urls],
                concurrency=conc,
                output_format=str(args.get("format") or "json"),
                agent_id=agent_id,
            )
            self.set_latest_genui(res.get("generative_ui"))
            self._index_extracted_rows(
                args,
                "luminara://bulk-extract",
                f"Bulk Job {res.get('job_id', '')}",
                res.get("rows"),
                str((res.get("receipt") or {}).get("receipt_id") or ""),
            )
            return res

        if name == "browser_handoff_resume":
            res = self.goals.resume_handoff(_require_str(args, "run_id"))
            self.set_latest_genui(res.get("generative_ui"))
            ext_obj = res.get("extracted")
            if isinstance(ext_obj, dict):
                self._index_extracted_rows(
                    args,
                    str(res.get("url") or ""),
                    str(ext_obj.get("title") or ""),
                    ext_obj.get("rows"),
                    str((res.get("receipt") or {}).get("receipt_id") or ""),
                )
            return res

        handled_100x = dispatch_100x_tool(self, name, args, agent_id)
        if handled_100x is not None:
            return handled_100x

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
        session_verifier = staticmethod(runtime.signer.verify_token)
        allow_extension_origins = True
        forge_root_dir = runtime.forge_root
        public_get_paths = frozenset({"/newtab", "/ui/newtab", "/workspace", "/ui/workspace", "/llms.txt", "/.well-known/agent.json"})

        def do_GET(self) -> None:  # noqa: N802
            if not self.check_loopback_security(is_post=False):
                return
            try:
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path
                qs = urllib.parse.parse_qs(parsed.query)
                srv_port = self.server.server_port
                # Never expose static UI_KEY on unauthenticated public GET when LUMINARA_AGENT_TOKEN is active
                fresh_ui_key = ensure_local_ui_key(runtime.forge_root)
                runtime.local_ui_key = fresh_ui_key
                embedded_ui_key = "" if (runtime.passport_token and not self._is_authenticated_caller()) else fresh_ui_key

                if path in ("/newtab", "/ui/newtab"):
                    html_doc = build_luminara_newtab_html(
                        runtime.current_profile(), workspace_uri="/workspace", agent_port=srv_port, cdp_port=runtime.cdp.port, ui_key=embedded_ui_key
                    )
                    self.send_text(html_doc, content_type="text/html; charset=utf-8")
                    return

                if path in ("/workspace", "/ui/workspace"):
                    html_doc = build_luminara_workspace_html(
                        runtime.current_profile(), newtab_uri="/newtab", agent_port=srv_port, ui_key=embedded_ui_key
                    )
                    self.send_text(html_doc, content_type="text/html; charset=utf-8")
                    return

                if path == "/llms.txt":
                    prof = runtime.current_profile()
                    tool_lines = [f"- `{t['name']}`: {t['description']}" for t in MCP_TOOLS_SPEC]
                    res_lines = [f"- `{r['uri']}`: {r['name']}" for r in MCP_RESOURCES_SPEC]
                    llms_doc = "\n".join(
                        [
                            f"# Luminara Browser v{APP_VERSION} — Dual Human + AI Agent Co-Browsing Engine",
                            f"> Ungoogled-Chromium {prof.chromium_version}-1.1 hardened desktop browser with Multiplexed Loopback CDP (<1.5ms RTT), Blink AXTree + Shadow-DOM + OOPIF perception, W3C WebMCP (`navigator.modelContext`), Network Mutation Firewall (`Fetch.enable`), DPAPI/AEAD Vault, SQLite FTS5 Workspaces, Tab Hibernation, and 20-Tool MCP v2.",
                            "",
                            "## Agent Control Endpoints",
                            f"- MCP v2 JSON-RPC (`{MCP_PROTOCOL_VERSION}`): `POST http://{host}:{srv_port}/api/agent/mcp`",
                            f"- Agent Manifest: `GET http://{host}:{srv_port}/.well-known/agent.json`",
                            f"- REST Base: `http://{host}:{srv_port}/api/agent/{{status,tabs,open,close,snapshot,act,frames,extract,genui,goal,bulk,handoff/resume,dialog,vault,pipeline,playbooks,perception,webmcp/list,webmcp/call,mutations,workspaces,hibernate,receipts,ledger/verify}}`",
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
                    self.send_text(llms_doc)
                    return

                if path == "/.well-known/agent.json":
                    prof = runtime.current_profile()
                    self.send_json(
                        {
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
                            "cdp_target": runtime.cdp.base_http,
                            "hitl_handoff_state": "PAUSED_HUMAN_HANDOFF",
                            "receipt_prefix": "LUM-",
                            "receipt_signature_scheme": "LUM-SIG-V2 (lum-hmac256)",
                            "tools": [t["name"] for t in MCP_TOOLS_SPEC],
                            "resources": [r["uri"] for r in MCP_RESOURCES_SPEC],
                        }
                    )
                    return

                if path == "/api/agent/status":
                    connected = runtime.cdp.is_alive()
                    tabs = runtime.cdp.list_tabs() if connected else []
                    self.send_json(
                        runtime.redactor.redact_payload(
                            {
                                "ok": True,
                                "browser": "Luminara Browser",
                                "version": APP_VERSION,
                                "cdp_connected": connected,
                                "cdp_port": runtime.cdp.port,
                                "cdp_mux": runtime.cdp.mux.stats(),
                                "vault_encryption": runtime.vault.encryption_mode,
                                "open_tabs": len(tabs),
                                "vault_handles": len(runtime.vault.list_entries()),
                                "learned_playbooks": len(runtime.playbooks.list_playbooks()),
                                "active_handoffs": runtime.goals.list_handoffs(),
                                "recent_receipts": runtime.ledger.recent(10),
                            }
                        )
                    )
                    return

                simple_get_tools = {
                    "/api/agent/workspaces": ("browser_workspace", {"action": "list"}),
                    "/api/agent/mutations": ("browser_mutation_guard", {"action": "status"}),
                    "/api/agent/tabs": ("browser_list_tabs", {}),
                    "/api/agent/vault": ("browser_vault", {"action": "list", "origin": (qs.get("origin") or [None])[0]}),
                    "/api/agent/playbooks": ("browser_playbooks", {"action": "list", "domain": (qs.get("domain") or [None])[0]}),
                }
                if path in simple_get_tools:
                    t_name, t_args = simple_get_tools[path]
                    self.send_json(runtime.dispatch_tool(t_name, t_args))
                    return

                if path == "/api/agent/genui/latest":
                    self.send_json({"generative_ui": runtime.get_latest_genui()})
                    return

                if path == "/api/agent/receipts":
                    limit = max(1, min(200, int((qs.get("limit") or ["40"])[0])))
                    self.send_json(runtime.redactor.redact_payload({"receipts": runtime.ledger.recent(limit)}))
                    return

                if path == "/api/agent/ledger/verify":
                    self.send_json(runtime.ledger.verify_ledger())
                    return

                if path == "/api/agent/frames":
                    tid = (qs.get("target_id") or [None])[0]
                    self.send_json(runtime.redactor.redact_payload({"frames": runtime.cdp.get_frame_tree(tid)}))
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
            except CDPError as exc:
                self.send_json({"error": runtime.redactor.redact_text(str(exc)), "cdp_connected": runtime.cdp.is_alive()}, status=502)
            except Exception as exc:  # noqa: BLE001
                self.send_json({"error": runtime.redactor.redact_text(str(exc))}, status=400)

        def do_POST(self) -> None:  # noqa: N802
            if not self.check_loopback_security(is_post=True):
                return
            req_path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
            try:
                body = self.read_json_dict()
            except json.JSONDecodeError as exc:
                msg = runtime.redactor.redact_text(str(exc))
                if req_path == "/api/agent/mcp":
                    self.send_json({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {msg}"}})
                else:
                    self.send_json({"error": f"Invalid JSON: {msg}"}, status=400)
                return
            except ValueError as exc:
                msg = runtime.redactor.redact_text(str(exc))
                if req_path == "/api/agent/mcp":
                    self.send_json({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": msg}})
                else:
                    self.send_json({"error": msg}, status=400)
                return

            try:
                if req_path == "/api/agent/mcp":
                    self._handle_mcp(body)
                    return

                if req_path == "/api/agent/bulk/cancel":
                    jid = str(body.get("job_id") or "")
                    runtime.bulk.cancel(jid)
                    self.send_json({"ok": True, "cancelled": jid})
                    return

                if req_path == "/api/agent/session-token":
                    ui_hdr = (self.headers.get("X-Luminara-UI-Key") or "").strip()
                    if not self._has_valid_ui_key(ui_hdr):
                        self.send_json({"error": "Session token issuance requires human UI authorization (X-Luminara-UI-Key)"}, status=403)
                        return
                    scope = str(body.get("scope") or "ui")
                    raw_ttl = body.get("ttl_sec")
                    eff_ttl = max(10, min(3600, 300 if raw_ttl is None else int(raw_ttl)))
                    tok = runtime.signer.issue_token(scope=scope, ttl_sec=eff_ttl)
                    self.send_json({"ok": True, "scope": scope, "ttl_sec": eff_ttl, "token": tok})
                    return

                if (
                    req_path == "/api/agent/mutations"
                    and str(body.get("action") or "status") in ("approve", "reject", "disable")
                    and (runtime.passport_token or (self.headers.get("Authorization") or "").strip())
                    and not self._has_valid_ui_key((self.headers.get("X-Luminara-UI-Key") or "").strip())
                ):
                    self.send_json(
                        {"error": "browser_mutation_guard approve/reject/disable requires human UI authorization (X-Luminara-UI-Key)"},
                        status=403,
                    )
                    return

                route_map = {
                    "/api/agent/open": "browser_open_tab", "/api/agent/close": "browser_close_tab",
                    "/api/agent/snapshot": "browser_snapshot", "/api/agent/act": "browser_act",
                    "/api/agent/extract": "browser_extract_structured", "/api/agent/genui": "browser_generative_ui",
                    "/api/agent/goal": "browser_run_goal", "/api/agent/bulk": "browser_bulk_extract",
                    "/api/agent/handoff/resume": "browser_handoff_resume", "/api/agent/dialog": "browser_dialog",
                    "/api/agent/vault": "browser_vault", "/api/agent/pipeline": "browser_exec_pipeline",
                    "/api/agent/playbooks": "browser_playbooks", "/api/agent/perception": "browser_perception_axtree",
                    "/api/agent/webmcp/list": "webmcp_list_tools", "/api/agent/webmcp/call": "webmcp_call_tool",
                    "/api/agent/mutations": "browser_mutation_guard", "/api/agent/workspaces": "browser_workspace",
                    "/api/agent/hibernate": "browser_hibernate_tabs",
                }
                tool_name = route_map.get(req_path)
                if not tool_name:
                    self.send_json({"error": f"Unknown endpoint {req_path}"}, status=404)
                    return
                self.send_json(runtime.dispatch_tool(tool_name, body))
            except CDPError as exc:
                self.send_json({"error": runtime.redactor.redact_text(str(exc)), "cdp_connected": runtime.cdp.is_alive()}, status=502)
            except Exception as exc:  # noqa: BLE001
                self.send_json({"error": runtime.redactor.redact_text(str(exc))}, status=400)

        def _handle_mcp(self, rpc: dict[str, Any]) -> None:
            req_id = rpc.get("id")
            method = rpc.get("method", "")
            params = rpc.get("params") or {}
            if not isinstance(params, dict):
                self.send_json({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "params must be an object"}})
                return

            if method.startswith("notifications/") or "id" not in rpc:
                self.send_response(204)
                self.write_cors_headers()
                self.end_headers()
                return

            try:
                if method == "initialize":
                    result: dict[str, Any] = {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {"tools": {}, "resources": {}},
                        "serverInfo": {"name": "luminara-browser-mcp", "version": APP_VERSION},
                    }
                elif method == "ping":
                    result = {}
                elif method == "tools/list":
                    result = {"tools": MCP_TOOLS_SPEC}
                elif method == "tools/call":
                    t_name = str(params.get("name") or "")
                    t_args = params.get("arguments") or {}
                    if not isinstance(t_args, dict):
                        raise ValueError("tool arguments must be an object")
                    if t_name == "browser_mutation_guard" and str(t_args.get("action") or "status") in ("approve", "reject", "disable"):
                        ui_hdr = (self.headers.get("X-Luminara-UI-Key") or "").strip()
                        if not self._has_valid_ui_key(ui_hdr):
                            raise PermissionError(
                                "browser_mutation_guard approve/reject/disable over MCP requires human UI authorization (X-Luminara-UI-Key)"
                            )
                    payload = runtime.dispatch_tool(t_name, t_args)
                    result = {
                        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                        "structuredContent": payload,
                        "isError": False,
                    }
                elif method == "resources/list":
                    result = {"resources": MCP_RESOURCES_SPEC}
                elif method == "resources/read":
                    uri = str(params.get("uri") or "")
                    res_handlers = {
                        "luminara://tabs/live": lambda: runtime.dispatch_tool("browser_list_tabs", {}),
                        "luminara://ledger/recent": lambda: runtime.redactor.redact_payload({"receipts": runtime.ledger.recent(25)}),
                        "luminara://ledger/verify": runtime.ledger.verify_ledger,
                        "luminara://vault/entries": lambda: runtime.dispatch_tool("browser_vault", {"action": "list"}),
                        "luminara://playbooks/list": lambda: runtime.dispatch_tool("browser_playbooks", {"action": "list"}),
                        "luminara://workspaces/list": lambda: runtime.dispatch_tool("browser_workspace", {"action": "list"}),
                        "luminara://mutations/status": lambda: runtime.dispatch_tool("browser_mutation_guard", {"action": "status"}),
                    }
                    if uri not in res_handlers:
                        raise ValueError(f"Unknown MCP resource URI: {uri}")
                    data = res_handlers[uri]()
                    result = {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(data, ensure_ascii=False)}]}
                else:
                    self.send_json({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}})
                    return

                self.send_json({"jsonrpc": "2.0", "id": req_id, "result": result})
            except Exception as exc:  # noqa: BLE001
                self.send_json(
                    {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": runtime.redactor.redact_text(str(exc))}}
                )

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
        f"Luminara Browser Agent Daemon v{APP_VERSION} (REST + MCP v2) listening on http://{host}:{port} -> CDP 127.0.0.1:{cdp_port}",
        flush=True,
    )
    srv.serve_forever()
