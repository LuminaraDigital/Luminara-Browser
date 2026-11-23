"""Core v1/v2 MCP Tool Dispatcher (`forge/agent_tools_core.py`).

Extracted from `agent_server.py` (Thermo-Nuclear Code Judo) so all four MCP tool tiers
(`dispatch_core_tool`, `dispatch_100x_tool`, `dispatch_flow_tool`, `dispatch_v31_tool`)
share one uniform dispatch contract while keeping `agent_server.py` lean (~620 lines).
"""

from __future__ import annotations

from typing import Any

from .agent_tools_100x import _bool_opt, _int_opt, _require_str
from .extractor import (
    build_dialog_control_js,
    build_dom_action_js,
    build_dom_snapshot_js,
    extract_structured_page,
    format_extracted_rows,
    synthesize_generative_ui,
)


def _record_goal_output(runtime: Any, args: dict[str, Any], res: dict[str, Any]) -> dict[str, Any]:
    """Persist synthesized Generative UI and index extracted entities from a goal or handoff resume."""
    runtime.set_latest_genui(res.get("generative_ui"))
    ext_obj = res.get("extracted")
    if isinstance(ext_obj, dict):
        runtime._index_extracted_rows(
            args,
            str(res.get("url") or res.get("final_url") or ""),
            str(ext_obj.get("title") or ""),
            ext_obj.get("rows"),
            str((res.get("receipt") or {}).get("receipt_id") or ""),
        )
    return res


def dispatch_core_tool(runtime: Any, name: str, args: dict[str, Any], agent_id: str) -> dict[str, Any] | None:
    """Dispatch core Luminara Browser MCP v2 tools; returns `None` when `name` belongs to another tier."""
    if name == "browser_list_tabs":
        connected = runtime.cdp.is_alive()
        raw_tabs = runtime.cdp.list_tabs() if connected else []
        tabs = [{**t, "frozen": runtime.lifecycle.is_frozen(str(t.get("target_id") or ""))} for t in raw_tabs]
        return {"cdp_connected": connected, "cdp_port": runtime.cdp.port, "tabs": tabs}

    if name == "browser_open_tab":
        url = _require_str(args, "url")
        bg = _bool_opt(args, "background", True)
        tab = runtime.cdp.open_tab(url, background=bg)
        runtime.lifecycle.touch_tab(tab["target_id"])
        if runtime.current_profile().guard_network_mutations:
            try:
                runtime.mutation_firewall.enable_guard(tab["target_id"])
            except Exception:  # noqa: BLE001
                pass
        rec = runtime.ledger.record(agent_id, "open_tab", tab["target_id"], {"url": url, "background": bg}, summary=f"Opened {url}")
        return {"tab": tab, "receipt": rec}

    if name == "browser_close_tab":
        tid = _require_str(args, "target_id")
        runtime.cdp.leases.check_allowed(tid, agent_id)
        closed = runtime.cdp.close_tab(tid)
        rec = runtime.ledger.record(agent_id, "close_tab", tid, {}, summary=f"Closed tab {tid}")
        return {"closed": closed, "receipt": rec}

    if name == "browser_snapshot":
        tid = args.get("target_id")
        frame_id = args.get("frame_id")
        include_frames = _bool_opt(args, "include_frames", False)
        badges = _bool_opt(args, "show_badges", True)
        resolved_tid = runtime.cdp._pick_target_id(tid)
        runtime.lifecycle.touch_tab(resolved_tid)
        snap = runtime.cdp.evaluate_js(
            resolved_tid,
            build_dom_snapshot_js(show_badges=badges, agent_label=agent_id),
            frame_id=str(frame_id) if frame_id else None,
        )
        if isinstance(snap, dict):
            snap.pop("outer_html", None)
            snap["target_id"] = resolved_tid
            if frame_id:
                snap["frame_id"] = str(frame_id)
            native_dlgs = runtime.cdp.get_native_dialogs(resolved_tid)
            if native_dlgs:
                snap["native_dialogs"] = native_dlgs
            if include_frames:
                snap["frame_tree"] = runtime.cdp.get_frame_tree(resolved_tid)
        rec = runtime.ledger.record(
            agent_id,
            "snapshot",
            resolved_tid,
            {"show_badges": badges, "frame_id": frame_id or ""},
            summary=f"Indexed {len(snap.get('elements', [])) if isinstance(snap, dict) else 0} targets",
        )
        return {"snapshot": snap, "receipt": rec}

    if name == "browser_act":
        act = _require_str(args, "action").lower()
        tid = args.get("target_id")
        frame_id = args.get("frame_id")
        resolved_tid = runtime.cdp._pick_target_id(tid)
        runtime.lifecycle.touch_tab(resolved_tid)
        if act == "human_takeover":
            runtime.cdp.leases.force_human_override(resolved_tid)
            try:
                runtime.cdp.evaluate_js(resolved_tid, build_dom_action_js("clear_hud"))
            except Exception:  # noqa: BLE001
                pass
            try:
                runtime.presence.clear(resolved_tid)
            except Exception:  # noqa: BLE001
                pass
            rec = runtime.ledger.record("human-user", "human_takeover", resolved_tid, {}, summary="Human preempted agent lease")
            return {"ok": True, "target_id": resolved_tid, "receipt": rec}

        if act != "clear_hud":
            runtime.cdp.leases.check_allowed(resolved_tid, agent_id)

        if act == "navigate":
            url = str(args.get("url") or "about:blank")
            nav = runtime.cdp.navigate(resolved_tid, url)
            rec = runtime.ledger.record(agent_id, "navigate", resolved_tid, {"url": url}, summary=f"Navigated to {url}")
            return {"ok": True, "navigation": nav, "receipt": rec}

        res = runtime.cdp.evaluate_js(
            resolved_tid,
            build_dom_action_js(
                act,
                index=_int_opt(args, "index", 0) if args.get("index") is not None else None,
                selector=args.get("selector"),
                text=str(args.get("text") or ""),
            ),
            frame_id=str(frame_id) if frame_id else None,
        )
        rec = runtime.ledger.record(
            agent_id,
            f"dom_{act}",
            resolved_tid,
            {"index": args.get("index"), "selector": args.get("selector"), "frame_id": frame_id or ""},
            status="OK" if isinstance(res, dict) and res.get("ok") else "WARN",
            summary=f"Executed {act} on tab {resolved_tid}",
        )
        return {"result": res, "target_id": resolved_tid, "receipt": rec}

    if name == "browser_dialog":
        act = str(args.get("action") or "status").strip().lower()
        tid = args.get("target_id")
        prompt_text = str(args.get("prompt_text") or "")
        dialog_id = args.get("dialog_id")
        resolved_tid = runtime.cdp._pick_target_id(tid)
        runtime.lifecycle.touch_tab(resolved_tid)
        if act in ("accept", "dismiss"):
            runtime.cdp.leases.check_allowed(resolved_tid, agent_id)
            runtime.cdp.set_native_dialog_policy(resolved_tid, accept=(act == "accept"), prompt_text=prompt_text)
            try:
                runtime.cdp.run_session(
                    resolved_tid,
                    [
                        ("Page.enable", {}),
                        ("Page.handleJavaScriptDialog", {"accept": act == "accept", "promptText": prompt_text}),
                    ],
                    timeout=3.0,
                )
            except Exception:  # noqa: BLE001
                pass
        res = runtime.cdp.evaluate_js(
            resolved_tid,
            build_dialog_control_js(action=act, prompt_text=prompt_text, dialog_id=str(dialog_id) if dialog_id else None),
        )
        native_dlgs = runtime.cdp.get_native_dialogs(resolved_tid)
        rec = runtime.ledger.record(
            agent_id,
            f"dialog_{act}",
            resolved_tid,
            {"action": act, "dialog_id": dialog_id or ""},
            summary=f"Dialog supervisor {act} on tab {resolved_tid}",
        )
        return {"target_id": resolved_tid, "dialog": res, "native_dialogs": native_dlgs, "receipt": rec}

    if name == "browser_vault":
        v_act = str(args.get("action") or "list").strip().lower()
        if v_act == "list":
            entries = runtime.vault.list_entries(origin_filter=args.get("origin"))
            return {"ok": True, "action": "list", "entries": entries}
        if v_act == "register":
            pub = runtime.vault.upsert_entry(
                origin=_require_str(args, "origin"),
                username=str(args.get("username") or ""),
                password=str(args.get("password") or ""),
                totp_secret=str(args.get("totp_secret") or ""),
                vault_id=args.get("vault_id") if isinstance(args.get("vault_id"), str) and args.get("vault_id").strip() else None,
                label=str(args.get("label") or ""),
            )
            rec = runtime.ledger.record(
                agent_id,
                "vault_register",
                "",
                {"vault_id": pub["vault_id"], "origin": pub["origin"], "username": pub["username"]},
                summary=f"Registered origin-bound vault credential {pub['vault_id']} for {pub['origin']}",
            )
            return {"ok": True, "action": "register", "entry": pub, "receipt": rec}
        if v_act == "delete":
            vid = _require_str(args, "vault_id")
            deleted = runtime.vault.delete_entry(vid)
            rec = runtime.ledger.record(agent_id, "vault_delete", "", {"vault_id": vid}, summary=f"Deleted vault entry {vid}")
            return {"ok": True, "action": "delete", "deleted": deleted, "receipt": rec}
        if v_act in ("fill", "enter_totp"):
            vid = _require_str(args, "vault_id")
            tid = args.get("target_id")
            fill_res = (
                runtime.vault.fill_credential(runtime.cdp, tid, vid, agent_id=agent_id)
                if v_act == "fill"
                else runtime.vault.fill_totp(runtime.cdp, tid, vid, agent_id=agent_id)
            )
            rec = runtime.ledger.record(
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
        pipe_res = runtime.pipeline.run_pipeline(
            steps=args.get("steps"),
            script=args.get("script"),
            max_calls=max_calls,
            agent_id=agent_id,
        )
        rec = runtime.ledger.record(
            agent_id,
            "exec_pipeline",
            "",
            {"calls_executed": pipe_res.get("calls_executed", 0), "status": pipe_res.get("status", "COMPLETED")},
            status=str(pipe_res.get("status") or "OK"),
            summary=f"Executed single-turn pipeline ({pipe_res.get('calls_executed', 0)} calls)",
        )
        return {**pipe_res, "receipt": rec}

    if name == "browser_playbooks":
        p_act = str(args.get("action") or "list").strip().lower()
        if p_act == "list":
            return {"ok": True, "playbooks": runtime.playbooks.list_playbooks(domain=args.get("domain"))}
        req_url = str(args.get("url") or "") or runtime._active_tab_url(args.get("target_id"))
        req_goal = str(args.get("goal") or "")
        if p_act == "match":
            matched = runtime.playbooks.match_playbook(req_url, req_goal) or (
                runtime.playbooks.match_playbook("", req_goal) if req_url else None
            )
            return {"ok": True, "matched": matched}
        if p_act == "replay":
            pid = str(args.get("playbook_id") or "")
            pb = (
                runtime.playbooks.get_playbook(pid)
                if pid
                else (
                    runtime.playbooks.match_playbook(req_url, req_goal)
                    or (runtime.playbooks.match_playbook("", req_goal) if req_url else None)
                )
            )
            if pb is None:
                raise ValueError("No verified playbook matched playbook_id or (url, goal)")
            rep = runtime.playbooks.replay_playbook(
                pb,
                cdp=runtime.cdp,
                ledger=runtime.ledger,
                target_id=args.get("target_id"),
                agent_id=agent_id,
            )
            if rep.get("status") == "COMPLETED":
                snap_after = runtime.cdp.evaluate_js(rep["target_id"], build_dom_snapshot_js(show_badges=False, agent_label=""))
                after_url = str(snap_after.get("url") or "") if isinstance(snap_after, dict) else ""
                ext = extract_structured_page(
                    snap_after.get("outer_html", "") if isinstance(snap_after, dict) else "",
                    after_url,
                )
                gen_ui = synthesize_generative_ui(ext["rows"], title=ext["title"] or pb["playbook_id"])
                runtime.set_latest_genui(gen_ui)
                runtime._index_extracted_rows(args, after_url, str(ext.get("title") or ""), ext["rows"])
                rep["extracted"] = ext
                rep["generative_ui"] = gen_ui
            return rep
        if p_act == "delete":
            pid = _require_str(args, "playbook_id")
            deleted = runtime.playbooks.delete_playbook(pid)
            rec = runtime.ledger.record(agent_id, "playbook_delete", "", {"playbook_id": pid, "deleted": deleted}, summary=f"Deleted playbook {pid}")
            return {"ok": True, "deleted": deleted, "playbook_id": pid, "receipt": rec}
        raise ValueError(f"Unsupported browser_playbooks action: {p_act!r}")

    if name in ("browser_extract_structured", "browser_generative_ui"):
        resolved_tid = runtime.cdp._pick_target_id(args.get("target_id"))
        runtime.lifecycle.touch_tab(resolved_tid)
        snap = runtime.cdp.evaluate_js(resolved_tid, build_dom_snapshot_js(show_badges=False, agent_label=""))
        html_src = snap.get("outer_html", "") if isinstance(snap, dict) else ""
        url = snap.get("url", "") if isinstance(snap, dict) else ""
        extracted = extract_structured_page(html_src, url)
        gen_ui = synthesize_generative_ui(extracted["rows"], title=extracted["title"] or "Live Tab Workspace")
        runtime.set_latest_genui(gen_ui)
        fmt = str(args.get("format") or "json")
        rec = runtime.ledger.record(
            agent_id, name, resolved_tid, {"url": url}, summary=f"Synthesized {len(extracted['rows'])} entities from {url[:60]}"
        )
        runtime._index_extracted_rows(args, url, str(extracted.get("title") or ""), extracted["rows"], rec["receipt_id"])
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
        res = runtime.goals.run_goal(
            goal=_require_str(args, "goal"),
            target_id=args.get("target_id"),
            start_url=args.get("start_url"),
            max_steps=max_steps,
            agent_id=agent_id,
            show_badges=_bool_opt(args, "show_badges", True),
        )
        return _record_goal_output(runtime, args, res)

    if name == "browser_bulk_extract":
        raw_urls = args.get("urls")
        if not isinstance(raw_urls, list):
            raise ValueError("'urls' must be a JSON array of URL strings")
        conc = _int_opt(args, "concurrency", 4)
        res = runtime.bulk.run_job(
            urls=[str(u) for u in raw_urls],
            concurrency=conc,
            output_format=str(args.get("format") or "json"),
            agent_id=agent_id,
        )
        runtime.set_latest_genui(res.get("generative_ui"))
        runtime._index_extracted_rows(
            args,
            "luminara://bulk-extract",
            f"Bulk Job {res.get('job_id', '')}",
            res.get("rows"),
            str((res.get("receipt") or {}).get("receipt_id") or ""),
        )
        return res

    if name == "browser_handoff_resume":
        res = runtime.goals.resume_handoff(_require_str(args, "run_id"))
        return _record_goal_output(runtime, args, res)

    return None


__all__ = ["dispatch_core_tool"]
