"""Clean-room OBL-14: Luminara Agent Daemon (`127.0.0.1:8796`) — Hardened REST + MCP v2 + Same-Origin UI.

Production `v3.1.0` architecture:
- Inherits `LoopbackJSONHandler` (blocks DNS rebinding, cross-port loopback Origin scraping, `<iframe sandbox>`
  `Origin: null` bypass, `<form>` CSRF, and body OOM).
- Serves `/newtab` and `/workspace` directly on `http://127.0.0.1:8796` + caches redacted `GET /api/agent/genui/latest`
  so the MV3 `luminara-copilot` Side Panel opens Workspace hydrated with zero cross-origin `localStorage` loss.
- Exposes 28 MCP v2 tools and 9 MCP resources, enforcing `LuminaraRedactor` across all REST, MCP, and error egress.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any
import urllib.parse

from .agent_desktop import build_desktop_heartbeat, initiate_graceful_shutdown, trigger_desktop_takeover
from .agent_engine import ActionLedger, AgentGoalRunner, BulkEngine
from .agent_team_hub import TeamHub, handle_team_get, handle_team_post
from .agent_tools_100x import _int_opt, dispatch_100x_tool
from .agent_tools_core import dispatch_core_tool
from .agent_tools_flow import dispatch_flow_tool, run_scheduled_task
from .agent_tools_v31 import dispatch_v31_tool, requires_human_ui_key_v31
from .cdp_client import CDPBridge, CDPError
from .http_base import LoopbackHTTPServer, LoopbackJSONHandler, atomic_write_private, ensure_local_ui_key, safe_join
from .knowledge_graph import KnowledgeWorkspaceStore, TabLifecycleManager
from .luminara_automation import PipelineSandboxRunner, PlaybookMemory
from .luminara_crypto import EphemeralSessionSigner
from .luminara_security import DEFAULT_REDACTOR, LuminaraVault
from .luminara_ui import build_luminara_newtab_html, build_luminara_workspace_html
from .mcp_specs import (
    APP_VERSION, MCP_PROTOCOL_VERSION, MCP_RESOURCES_SPEC, MCP_TOOLS_SPEC,
    build_agent_manifest, build_llms_txt,
)
from .models import ForkProfile
from .monitors_eval import MonitorEvalEngine
from .mutation_firewall import NetworkMutationFirewall
from .perception import HybridPerceptionEngine
from .perception_refs import OutlinePerception
from .presence import PresenceShield
from .scheduler import ScheduledTaskStore, ScheduleRunner
from .sequence_guard import SequenceGuard
from .vrt_isolation import VRTIsolationManager
from .webmcp import WebMCPBridge

ENCODING = "utf-8"


class LuminaraAgentRuntime:
    """Stateful coordinator shared by REST & MCP v2 handlers."""

    def __init__(self, forge_root: Path, cdp_host: str = "127.0.0.1", cdp_port: int = 9229) -> None:
        self.forge_root = forge_root.resolve()
        self.outputs_dir = self.forge_root / "outputs"
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.local_ui_key = ensure_local_ui_key(self.forge_root)
        try:
            key_bytes = bytes.fromhex(self.local_ui_key[:64]) if len(self.local_ui_key) >= 64 else b""
        except ValueError:
            key_bytes = b""
        if len(key_bytes) < 32:
            import hashlib

            key_bytes = hashlib.sha256(self.local_ui_key.encode(ENCODING)).digest()
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
        self.goals = AgentGoalRunner(self.cdp, self.ledger, self.outputs_dir / "active_handoffs.json", playbooks=self.playbooks)
        self.pipeline = PipelineSandboxRunner(self.dispatch_tool)
        self.outline = OutlinePerception(self.cdp)
        self.presence = PresenceShield(self.cdp, self.cdp.leases)
        self.cdp.leases.on_action = self.presence.hold
        self.schedules = ScheduledTaskStore(self.outputs_dir / "scheduled_tasks.json")
        self.sequence_guard = SequenceGuard(self.outputs_dir, redactor=self.redactor, signer=self.signer)
        self.vrt_isolation = VRTIsolationManager(self.cdp, self.outputs_dir / "vrt_baselines", redactor=self.redactor)
        self.monitors_eval = MonitorEvalEngine(
            self.outputs_dir / "monitors_eval.sqlite3", cdp=self.cdp, ledger=self.ledger, playbooks=self.playbooks, redactor=self.redactor
        )
        self.scheduler = ScheduleRunner(self.schedules, lambda task: run_scheduled_task(self, task), on_tick=lambda: self.monitors_eval.run_due_monitors())
        self.team_hub = TeamHub(self)
        self.goals.router.llm_config_getter = self.team_hub.llm_config.get_runtime_config
        self.passport_token = os.environ.get("LUMINARA_AGENT_TOKEN", "").strip()
        if self.passport_token:
            self.redactor.register_secret(self.passport_token)
        self._genui_lock = threading.Lock()
        self._genui_path = self.outputs_dir / "latest_genui.json"
        self.latest_genui: dict[str, Any] | None = None
        if self._genui_path.exists():
            try:
                loaded_genui = json.loads(self._genui_path.read_text(encoding=ENCODING))
                if isinstance(loaded_genui, dict):
                    self.latest_genui = self.redactor.redact_payload(loaded_genui)
            except Exception:  # noqa: BLE001
                self.latest_genui = None

    def close(self) -> None:
        self.scheduler.stop()
        self.vrt_isolation.close()
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
                try:
                    atomic_write_private(self._genui_path, json.dumps(scrubbed, ensure_ascii=False, allow_nan=False) + "\n")
                except OSError:
                    pass

    def get_latest_genui(self) -> dict[str, Any] | None:
        with self._genui_lock:
            return self.redactor.redact_payload(self.latest_genui) if self.latest_genui is not None else None

    def _index_extracted_rows(self, args: dict[str, Any], url: str, title: str, rows: list[dict[str, Any]] | None, receipt_id: str = "") -> None:
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

    @staticmethod
    def _is_readonly_or_recovery_tool(name: str, args: dict[str, Any]) -> bool:
        act = str(args.get("action") or "").strip().lower()
        if name in ("browser_list_tabs", "browser_sequence_guard"):
            return True
        if name == "browser_act" and act == "human_takeover":
            return True
        if name == "browser_vrt_isolation" and act in ("", "status", "unlock_origins"):
            return True
        if name == "browser_monitors" and act in ("", "list", "runs", "list_revisions", "delete"):
            return True
        if name == "browser_search_eval" and act in ("", "scorecard"):
            return True
        if name == "browser_mutation_guard" and act in ("", "status", "approve", "reject", "disable"):
            return True
        if name in ("browser_workspace", "browser_vault", "browser_playbooks", "browser_schedule") and act in ("", "list"):
            return True
        return False

    def _resolve_sequence_url(self, name: str, args: dict[str, Any]) -> str:
        for key in ("url", "origin", "start_url", "webhook_url", "target_url"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        urls = args.get("urls")
        if isinstance(urls, list) and urls and isinstance(urls[0], str) and urls[0].strip():
            return urls[0].strip()
        if name == "browser_vault":
            vid = str(args.get("vault_id") or "").strip()
            if vid:
                for entry in self.vault.list_entries():
                    if entry.get("vault_id") == vid and entry.get("origin"):
                        return str(entry["origin"])
        if name == "browser_monitors" and str(args.get("action") or "").strip().lower() == "run_now":
            mid = str(args.get("monitor_id") or "").strip()
            if mid:
                for m in self.monitors_eval.list_monitors():
                    if m.get("monitor_id") == mid and m.get("target_url"):
                        return str(m["target_url"])
        if name in (
            "browser_snapshot", "browser_perception_axtree", "browser_extract_structured", "browser_generative_ui",
            "webmcp_list_tools", "webmcp_call_tool", "browser_act", "browser_outline",
            "browser_dialog", "browser_vault", "browser_run_goal", "browser_playbooks", "browser_exec_pipeline",
        ):
            return self._active_tab_url(args.get("target_id"))
        return ""

    def dispatch_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        return self.redactor.redact_payload(self._dispatch_tool_raw(name, args))

    def _dispatch_tool_raw(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(args.get("agent_id") or "luminara-agent")
        if not self._is_readonly_or_recovery_tool(name, args):
            latched = self.sequence_guard.active_daemon_block()
            if latched is not None:
                rec = self.ledger.record(
                    agent_id, "sequence_block", str(args.get("target_id") or ""),
                    {"blocked_tool": name, "status": "PAUSED_SEQUENCE_BLOCK"},
                    status="BLOCKED", summary=f"SequenceGuard latched block rejected {name} (PAUSED_SEQUENCE_BLOCK)",
                )
                return {"ok": False, "blocked": True, "status": "PAUSED_SEQUENCE_BLOCK", "findings": [latched], "receipt": rec}
            seq_urls = (
                [str(u).strip() for u in args["urls"] if isinstance(u, str) and u.strip()]
                if (name == "browser_bulk_extract" and isinstance(args.get("urls"), list))
                else []
            )
            if not seq_urls:
                seq_urls = [self._resolve_sequence_url(name, args)]
            for eval_u in seq_urls:
                step_params = {**args, "url": eval_u} if (len(seq_urls) > 1 and eval_u) else args
                seq_chk = self.sequence_guard.evaluate_step(
                    agent_id=agent_id, tool_name=name, params=step_params,
                    target_url=eval_u, workspace_id=str(args.get("workspace_id") or "default"),
                )
                if seq_chk.get("blocked"):
                    rec = self.ledger.record(
                        agent_id, "sequence_block", str(args.get("target_id") or ""),
                        {"blocked_tool": name, "status": "PAUSED_SEQUENCE_BLOCK"},
                        status="BLOCKED", summary=f"SequenceGuard blocked {name} (PAUSED_SEQUENCE_BLOCK)",
                    )
                    return {**seq_chk, "receipt": rec}
        handled = (
            dispatch_core_tool(self, name, args, agent_id)
            or dispatch_100x_tool(self, name, args, agent_id)
            or dispatch_flow_tool(self, name, args, agent_id)
            or dispatch_v31_tool(self, name, args, agent_id)
        )
        if handled is not None:
            return handled

        raise ValueError(f"Unknown MCP tool: {name!r}")


def create_agent_http_server(
    runtime: LuminaraAgentRuntime,
    host: str = "127.0.0.1",
    port: int = 8796,
) -> LoopbackHTTPServer:
    """Create a thread-pooled HTTP + MCP v2 server bound strictly to loopback."""
    started_at = time.time()

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
                    self.send_text(build_llms_txt(runtime.current_profile(), host, srv_port))
                    return

                if path == "/.well-known/agent.json":
                    self.send_json(build_agent_manifest(runtime.current_profile(), host, srv_port, runtime.cdp.base_http))
                    return

                if path == "/api/agent/desktop/status":
                    self.send_json(build_desktop_heartbeat(runtime, started_at))
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
                                "pending_mutations": runtime.mutation_firewall.list_pending(),
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
                    "/api/agent/schedules": ("browser_schedule", {"action": "list"}),
                    "/api/agent/sequences": ("browser_sequence_guard", {"action": "status"}),
                    "/api/agent/vrt": ("browser_vrt_isolation", {"action": "status"}),
                    "/api/agent/monitors": ("browser_monitors", {"action": "list", "workspace_id": (qs.get("workspace_id") or [None])[0]}),
                    "/api/agent/eval": ("browser_search_eval", {"action": "scorecard"}),
                }
                if path in simple_get_tools:
                    t_name, t_args = simple_get_tools[path]
                    self.send_json(runtime.dispatch_tool(t_name, t_args))
                    return

                if path == "/api/agent/casebundles":
                    raw_name = (qs.get("name") or qs.get("bundle_file") or [None])[0]
                    case_id = (qs.get("case_id") or [None])[0]
                    zpath: Path | None = None
                    if raw_name:
                        cand = safe_join(runtime.sequence_guard.casebundles_dir, Path(str(raw_name)).name)
                        if cand.is_file():
                            zpath = cand
                    elif case_id:
                        slug = "".join(ch for ch in str(case_id) if ch.isalnum() or ch in ("-", "_", "."))
                        cand_name = slug if slug.endswith(".zip") else f"{slug}.zip"
                        cand = safe_join(runtime.sequence_guard.casebundles_dir, cand_name)
                        if cand.is_file():
                            zpath = cand
                    else:
                        existing = sorted(
                            runtime.sequence_guard.casebundles_dir.glob("*.zip"),
                            key=lambda p: p.stat().st_mtime,
                            reverse=True,
                        )
                        if existing:
                            zpath = existing[0]
                    if zpath is None or not zpath.is_file():
                        self.send_json({"error": f"Casebundle not found: {raw_name or case_id or 'latest'}"}, status=404)
                        return
                    self.send_bytes(zpath.read_bytes(), content_type="application/zip", filename=zpath.name)
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
                    self.send_json(runtime.redactor.redact_payload({"target_id": resolved_tid, "mime": f"image/{norm_fmt}", "data_base64": b64}))
                    return

                runtime.server_port = srv_port
                team_get = handle_team_get(runtime, path.rstrip("/") or "/", qs)
                if team_get is not None:
                    self.send_json(team_get[0], status=team_get[1])
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

                if req_path in ("/api/agent/desktop/takeover", "/api/agent/shutdown"):
                    if not self._has_valid_ui_key((self.headers.get("X-Luminara-UI-Key") or "").strip()):
                        self.send_json({"error": f"{req_path} requires human UI authorization (X-Luminara-UI-Key)"}, status=403)
                        return
                    cb = bool(body.get("close_browser", False))
                    out = trigger_desktop_takeover(runtime) if req_path.endswith("/takeover") else initiate_graceful_shutdown(runtime, self.server, close_browser=cb)
                    self.send_json(out)
                    return

                if req_path == "/api/agent/bulk/cancel":
                    jid = str(body.get("job_id") or "")
                    runtime.bulk.cancel(jid)
                    self.send_json({"ok": True, "cancelled": jid})
                    return

                if req_path == "/api/agent/genui/sync":
                    payload = body.get("generative_ui") if isinstance(body.get("generative_ui"), dict) else body
                    runtime.set_latest_genui(payload)
                    self.send_json({"ok": True})
                    return

                if req_path == "/api/agent/session-token":
                    ui_hdr = (self.headers.get("X-Luminara-UI-Key") or "").strip()
                    auth_hdr = (self.headers.get("Authorization") or "").strip()
                    raw_bearer = auth_hdr[7:].strip() if auth_hdr.startswith("Bearer ") else ""
                    sec_site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
                    same_origin_passport = bool(
                        runtime.passport_token
                        and raw_bearer
                        and secrets.compare_digest(raw_bearer, runtime.passport_token)
                        and sec_site == "same-origin"
                        and self._matched_cors_origin() is not None
                    )
                    scope = str(body.get("scope") or "ui")
                    if scope not in ("ui", "agent"):
                        raise ValueError("scope must be 'ui' or 'agent'")
                    has_static_ui = self._has_static_ui_key(ui_hdr)
                    if scope == "ui" and not has_static_ui:
                        self.send_json({"error": "Session token scope 'ui' requires static human UI authorization"}, status=403)
                        return
                    if scope == "agent" and not (has_static_ui or same_origin_passport):
                        self.send_json({"error": "Session token issuance requires static UI key or same-origin passport"}, status=403)
                        return
                    eff_ttl = max(10, min(3600, _int_opt(body, "ttl_sec", 300)))
                    tok = runtime.signer.issue_token(scope=scope, ttl_sec=eff_ttl)
                    self.send_json({"ok": True, "scope": scope, "ttl_sec": eff_ttl, "token": tok})
                    return

                runtime.server_port = self.server.server_port
                ui_ok = self._has_valid_ui_key((self.headers.get("X-Luminara-UI-Key") or "").strip())
                team_post = handle_team_post(runtime, req_path, body, has_ui_key=ui_ok)
                if team_post is not None:
                    self.send_json(team_post[0], status=team_post[1])
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
                    "/api/agent/hibernate": "browser_hibernate_tabs", "/api/agent/outline": "browser_outline",
                    "/api/agent/wait": "browser_wait", "/api/agent/screenshot": "browser_screenshot",
                    "/api/agent/schedule": "browser_schedule", "/api/agent/sequences": "browser_sequence_guard",
                    "/api/agent/vrt": "browser_vrt_isolation", "/api/agent/monitors": "browser_monitors",
                    "/api/agent/eval": "browser_search_eval",
                }
                tool_name = route_map.get(req_path)
                if not tool_name:
                    self.send_json({"error": f"Unknown endpoint {req_path}"}, status=404)
                    return
                if requires_human_ui_key_v31(tool_name, body) and not self._has_valid_ui_key(
                    (self.headers.get("X-Luminara-UI-Key") or "").strip()
                ):
                    self.send_json(
                        {"error": f"{tool_name} {body.get('action')} requires human UI authorization (X-Luminara-UI-Key)"},
                        status=403,
                    )
                    return
                self.send_json(runtime.dispatch_tool(tool_name, body))
            except CDPError as exc:
                self.send_json({"error": runtime.redactor.redact_text(str(exc)), "cdp_connected": runtime.cdp.is_alive()}, status=502)
            except Exception as exc:  # noqa: BLE001
                self.send_json({"error": runtime.redactor.redact_text(str(exc))}, status=400)

        def _handle_mcp(self, rpc: dict[str, Any]) -> None:
            req_id = rpc.get("id")
            method = rpc.get("method")
            if rpc.get("jsonrpc") not in (None, "2.0") or not isinstance(method, str) or not method.strip():
                self.send_json({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32600, "message": "Invalid JSON-RPC 2.0 Request"}})
                return

            if method.startswith("notifications/") or "id" not in rpc:
                self.send_response(204)
                self.write_cors_headers()
                self.end_headers()
                return

            params = rpc.get("params") if rpc.get("params") is not None else {}
            if not isinstance(params, dict):
                self.send_json({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "params must be an object"}})
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
                    if requires_human_ui_key_v31(t_name, t_args):
                        if not self._has_valid_ui_key((self.headers.get("X-Luminara-UI-Key") or "").strip()):
                            raise PermissionError(f"{t_name} {t_args.get('action')} requires human UI authorization (X-Luminara-UI-Key)")
                    payload = runtime.dispatch_tool(t_name, t_args)
                    result = {
                        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, allow_nan=False)}],
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
                        "luminara://ledger/verify": lambda: runtime.redactor.redact_payload(runtime.ledger.verify_ledger()),
                        "luminara://vault/entries": lambda: runtime.dispatch_tool("browser_vault", {"action": "list"}),
                        "luminara://playbooks/list": lambda: runtime.dispatch_tool("browser_playbooks", {"action": "list"}),
                        "luminara://workspaces/list": lambda: runtime.dispatch_tool("browser_workspace", {"action": "list"}),
                        "luminara://mutations/status": lambda: runtime.dispatch_tool("browser_mutation_guard", {"action": "status"}),
                        "luminara://security/sequences": lambda: runtime.dispatch_tool("browser_sequence_guard", {"action": "status"}),
                        "luminara://monitors/runs": lambda: runtime.dispatch_tool("browser_monitors", {"action": "runs"}),
                    }
                    if uri not in res_handlers:
                        raise ValueError(f"Unknown MCP resource URI: {uri}")
                    data = res_handlers[uri]()
                    result = {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(data, ensure_ascii=False, allow_nan=False)}]}
                else:
                    self.send_json({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}})
                    return

                self.send_json({"jsonrpc": "2.0", "id": req_id, "result": result})
            except (ValueError, TypeError) as exc:
                self.send_json(
                    {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": runtime.redactor.redact_text(str(exc))}}
                )
            except Exception as exc:  # noqa: BLE001
                self.send_json(
                    {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": runtime.redactor.redact_text(str(exc))}}
                )

    return LoopbackHTTPServer((host, port), Handler)


def run_agent_daemon(forge_root: Path, host: str = "127.0.0.1", port: int = 8796, cdp_port: int = 9229) -> None:
    runtime = LuminaraAgentRuntime(forge_root=forge_root, cdp_host="127.0.0.1", cdp_port=cdp_port)
    try:
        atomic_write_private(Path.home() / ".luminara-browser" / "local_ui_key.txt", runtime.local_ui_key + "\n")
    except OSError:
        pass
    srv = create_agent_http_server(runtime, host=host, port=port)
    runtime.scheduler.start()
    print(f"Luminara Browser Agent Daemon v{APP_VERSION} (REST + MCP v2) listening on http://{host}:{port} -> CDP 127.0.0.1:{cdp_port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()
        srv.server_close()
