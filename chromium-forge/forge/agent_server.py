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
from typing import Any
import urllib.parse

from .agent_engine import ActionLedger, AgentGoalRunner, BulkEngine
from .agent_tools_100x import MCP_TOOLS_100X_SPEC, _bool_opt, _int_opt, _require_str, dispatch_100x_tool
from .agent_tools_flow import HUMAN_ONLY_ACTIONS, dispatch_flow_tool, run_scheduled_task
from .agent_tools_v31 import dispatch_v31_tool, requires_human_ui_key_v31
from .cdp_client import CDPBridge, CDPError
from .extractor import (
    build_dialog_control_js,
    build_dom_action_js,
    build_dom_snapshot_js,
    extract_structured_page,
    format_extracted_rows,
    synthesize_generative_ui,
)
from .http_base import LoopbackHTTPServer, LoopbackJSONHandler, atomic_write_private, ensure_local_ui_key
from .knowledge_graph import KnowledgeWorkspaceStore, TabLifecycleManager
from .luminara_automation import PipelineSandboxRunner, PlaybookMemory
from .luminara_crypto import EphemeralSessionSigner
from .luminara_security import DEFAULT_REDACTOR, LuminaraVault
from .luminara_ui import build_luminara_newtab_html, build_luminara_workspace_html
from .mcp_specs import (
    APP_VERSION,
    MCP_PROTOCOL_VERSION,
    MCP_RESOURCES_SPEC,
    MCP_TOOLS_SPEC,
    build_agent_manifest,
    build_llms_txt,
)
from .models import ForkProfile
from .monitors_eval import MonitorEvalEngine
from .mutation_firewall import NetworkMutationFirewall
from .perception import HybridPerceptionEngine
from .perception_refs import OutlinePerception
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
        self.goals = AgentGoalRunner(
            self.cdp,
            self.ledger,
            self.outputs_dir / "active_handoffs.json",
            playbooks=self.playbooks,
        )
        self.pipeline = PipelineSandboxRunner(self.dispatch_tool)
        self.outline = OutlinePerception(self.cdp)
        self.schedules = ScheduledTaskStore(self.outputs_dir / "scheduled_tasks.json")
        self.sequence_guard = SequenceGuard(self.outputs_dir, redactor=self.redactor, signer=self.signer)
        self.vrt_isolation = VRTIsolationManager(self.cdp, self.outputs_dir / "vrt_baselines", redactor=self.redactor)
        self.monitors_eval = MonitorEvalEngine(
            self.outputs_dir / "monitors_eval.sqlite3",
            cdp=self.cdp,
            ledger=self.ledger,
            playbooks=self.playbooks,
            redactor=self.redactor,
        )
        self.scheduler = ScheduleRunner(
            self.schedules,
            lambda task: run_scheduled_task(self, task),
            on_tick=lambda: self.monitors_eval.run_due_monitors(),
        )
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
        if name in (
            "browser_snapshot",
            "browser_perception_axtree",
            "browser_extract_structured",
            "browser_generative_ui",
            "webmcp_list_tools",
            "webmcp_call_tool",
            "browser_act",
            "browser_outline",
            "browser_dialog",
            "browser_vault",
        ):
            return self._active_tab_url(args.get("target_id"))
        return ""

    def dispatch_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        out = self._dispatch_tool_raw(name, args)
        return self.redactor.redact_payload(out)

    def _dispatch_tool_raw(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(args.get("agent_id") or "luminara-agent")
        if not self._is_readonly_or_recovery_tool(name, args):
            latched = self.sequence_guard.active_daemon_block()
            if latched is not None:
                rec = self.ledger.record(
                    agent_id,
                    "sequence_block",
                    str(args.get("target_id") or ""),
                    {"blocked_tool": name, "status": "PAUSED_SEQUENCE_BLOCK"},
                    status="BLOCKED",
                    summary=f"SequenceGuard latched block rejected {name} (PAUSED_SEQUENCE_BLOCK)",
                )
                return {
                    "ok": False,
                    "blocked": True,
                    "status": "PAUSED_SEQUENCE_BLOCK",
                    "findings": [latched],
                    "receipt": rec,
                }
            seq_chk = self.sequence_guard.evaluate_step(
                agent_id=agent_id,
                tool_name=name,
                params=args,
                target_url=self._resolve_sequence_url(name, args),
                workspace_id=str(args.get("workspace_id") or "default"),
            )
            if seq_chk.get("blocked"):
                rec = self.ledger.record(
                    agent_id,
                    "sequence_block",
                    str(args.get("target_id") or ""),
                    {"blocked_tool": name, "status": "PAUSED_SEQUENCE_BLOCK"},
                    status="BLOCKED",
                    summary=f"SequenceGuard blocked {name} (PAUSED_SEQUENCE_BLOCK)",
                )
                return {**seq_chk, "receipt": rec}
        if name == "browser_list_tabs":
            connected = self.cdp.is_alive()
            tabs = self.cdp.list_tabs() if connected else []
            return {"cdp_connected": connected, "cdp_port": self.cdp.port, "tabs": tabs}

        if name == "browser_open_tab":
            url = _require_str(args, "url")
            bg = _bool_opt(args, "background", True)
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
            include_frames = _bool_opt(args, "include_frames", False)
            badges = _bool_opt(args, "show_badges", True)
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
                    index=_int_opt(args, "index", 0) if args.get("index") is not None else None,
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
            max_calls = _int_opt(args, "max_calls", 25)
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
            max_steps = _int_opt(args, "max_steps", 8)
            res = self.goals.run_goal(
                goal=_require_str(args, "goal"),
                target_id=args.get("target_id"),
                start_url=args.get("start_url"),
                max_steps=max_steps,
                agent_id=agent_id,
                show_badges=_bool_opt(args, "show_badges", True),
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
            conc = _int_opt(args, "concurrency", 4)
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

        handled = (
            dispatch_100x_tool(self, name, args, agent_id)
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
                    "/api/agent/monitors": ("browser_monitors", {"action": "list"}),
                    "/api/agent/eval": ("browser_search_eval", {"action": "scorecard"}),
                }
                if path in simple_get_tools:
                    t_name, t_args = simple_get_tools[path]
                    self.send_json(runtime.dispatch_tool(t_name, t_args))
                    return

                if path == "/api/agent/casebundles":
                    case_id = (qs.get("case_id") or [None])[0]
                    exp = runtime.sequence_guard.export_casebundle(case_id=case_id)
                    zpath = Path(str(exp["bundle_path"])).resolve()
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
                if (
                    str(body.get("action") or "") in HUMAN_ONLY_ACTIONS.get(tool_name, ())
                    or requires_human_ui_key_v31(tool_name, body)
                ) and not self._has_valid_ui_key((self.headers.get("X-Luminara-UI-Key") or "").strip()):
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
                    if str(t_args.get("action") or "") in HUMAN_ONLY_ACTIONS.get(t_name, ()) or requires_human_ui_key_v31(t_name, t_args):
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


def run_agent_daemon(
    forge_root: Path,
    host: str = "127.0.0.1",
    port: int = 8796,
    cdp_port: int = 9229,
) -> None:
    runtime = LuminaraAgentRuntime(forge_root=forge_root, cdp_host="127.0.0.1", cdp_port=cdp_port)
    try:
        atomic_write_private(Path.home() / ".luminara-browser" / "local_ui_key.txt", runtime.local_ui_key + "\n")
    except OSError:
        pass
    srv = create_agent_http_server(runtime, host=host, port=port)
    runtime.scheduler.start()
    print(
        f"Luminara Browser Agent Daemon v{APP_VERSION} (REST + MCP v2) listening on http://{host}:{port} -> CDP 127.0.0.1:{cdp_port}",
        flush=True,
    )
    srv.serve_forever()
