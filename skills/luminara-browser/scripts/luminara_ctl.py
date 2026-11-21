#!/usr/bin/env python3
"""Zero-dependency CLI controller for Luminara Browser Agent Daemon v3.1.0 (`127.0.0.1:8796`).

Exposes all 28 MCP v2 co-browsing, perception, outline, wait, screenshot, schedule,
WebMCP, mutation-firewall, sequence-guard, VRT, monitors, search-eval, workspace,
tab-hibernation, vault, dialog, pipeline, playbook, and ledger tools safely.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

ENCODING = "utf-8"


def _daemon_url() -> str:
    return (os.environ.get("LUMINARA_AGENT_URL") or "http://127.0.0.1:8796").rstrip("/")


def _discover_newest_local_ui_key() -> str:
    candidates: list[Path] = []
    env_forge = (os.environ.get("LUMINARA_FORGE_ROOT") or "").strip()
    if env_forge:
        candidates.append(Path(env_forge).expanduser() / "outputs" / "local_ui_key.txt")
    candidates.append(Path.home() / ".luminara-browser" / "local_ui_key.txt")
    cwd = Path.cwd()
    for base in (cwd, cwd / "chromium-forge", cwd / "Agent", Path(__file__).resolve().parents[3] / "chromium-forge"):
        if (base / "fork.json").is_file():
            candidates.append(base / "outputs" / "local_ui_key.txt")
    existing = [p for p in candidates if p.is_file()]
    existing.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for cand in existing:
        try:
            val = cand.read_text(encoding=ENCODING).strip()
            if val:
                return val
        except OSError:
            continue
    return ""


def _headers(is_post: bool, *, include_disk_ui_key: bool = False) -> dict[str, str]:
    hdrs: dict[str, str] = {}
    if is_post:
        hdrs["Content-Type"] = "application/json"
    tok = (os.environ.get("LUMINARA_AGENT_TOKEN") or "").strip()
    if tok:
        hdrs["Authorization"] = f"Bearer {tok}"
    ui_key = (os.environ.get("LUMINARA_UI_KEY") or "").strip()
    if not ui_key and include_disk_ui_key:
        ui_key = _discover_newest_local_ui_key()
    if ui_key:
        hdrs["X-Luminara-UI-Key"] = ui_key
    return hdrs


def _request(path: str, payload: dict[str, object] | None = None, *, human_auth: bool = False) -> dict[str, object]:
    url = f"{_daemon_url()}{path}"
    data = json.dumps(payload).encode(ENCODING) if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers=_headers(payload is not None, include_disk_ui_key=human_auth),
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=45.0) as resp:
        return json.loads(resp.read().decode(ENCODING))


def _resolve_secret_safe_text(inline: str, env_var: str | None, use_stdin: bool) -> str:
    if use_stdin:
        return sys.stdin.read()
    if env_var:
        return os.environ.get(env_var, "")
    return inline


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="luminara_ctl", description="Control Luminara Browser v3.1.0 (28 MCP v2 tools)")
    p.add_argument("--human-auth", action="store_true", help="Authorize human-only security overrides using local_ui_key.txt")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show daemon health, CDP mux state, vault encryption, active handoffs, and recent LUM-* receipts")
    sub.add_parser("tabs", help="List open shared browser tabs and active leases (browser_list_tabs)")
    sub.add_parser("verify-ledger", help="Verify cryptographic SHA-256 & HMAC chain integrity of LUM-* action ledger")

    p_open = sub.add_parser("open", help="Open URL in a shared or background tab (browser_open_tab)")
    p_open.add_argument("--url", required=True)
    p_open.add_argument("--foreground", action="store_true")

    p_close = sub.add_parser("close", help="Close a tab by target_id and release any active lease (browser_close_tab)")
    p_close.add_argument("--target-id", required=True)

    p_snap = sub.add_parser("snapshot", help="Index visible [1..N] Set-of-Marks DOM elements across frames (browser_snapshot)")
    p_snap.add_argument("--target-id", default=None)
    p_snap.add_argument("--frame-id", default=None)
    p_snap.add_argument("--include-frames", action="store_true")
    p_snap.add_argument("--no-badges", action="store_true")

    p_act = sub.add_parser("act", help="Execute click, type, select, scroll, navigate, human_takeover, or clear_hud (browser_act)")
    p_act.add_argument("--action", required=True, choices=["click", "type", "select", "scroll", "navigate", "human_takeover", "clear_hud"])
    p_act.add_argument("--target-id", default=None)
    p_act.add_argument("--frame-id", default=None)
    p_act.add_argument("--index", type=int, default=None)
    p_act.add_argument("--selector", default=None)
    p_act.add_argument("--text", default="")
    p_act.add_argument("--text-env", default=None, help="Read text from environment variable (avoids argv exposure)")
    p_act.add_argument("--text-stdin", action="store_true", help="Read text from stdin")
    p_act.add_argument("--url", default="")

    p_dlg = sub.add_parser("dialog", help="Inspect, accept, or dismiss native JS dialogs (browser_dialog)")
    p_dlg.add_argument("--action", default="status", choices=["status", "accept", "dismiss"])
    p_dlg.add_argument("--target-id", default=None)
    p_dlg.add_argument("--dialog-id", default=None)
    p_dlg.add_argument("--prompt-text", default="")
    p_dlg.add_argument("--text-env", default=None)
    p_dlg.add_argument("--text-stdin", action="store_true")

    p_vlt = sub.add_parser("vault", help="Manage or autofill from the origin-pinned DPAPI/AEAD Model-Blind Vault (browser_vault)")
    p_vlt.add_argument("--action", default="list", choices=["list", "register", "fill", "enter_totp", "delete"])
    p_vlt.add_argument("--vault-id", default=None)
    p_vlt.add_argument("--origin", default=None)
    p_vlt.add_argument("--username", default="")
    p_vlt.add_argument("--label", default="")
    p_vlt.add_argument("--password-env", default="LUMINARA_VAULT_PASSWORD", help="Env var holding password (avoids argv exposure)")
    p_vlt.add_argument("--totp-env", default="LUMINARA_VAULT_TOTP_SECRET", help="Env var holding Base32 TOTP secret")
    p_vlt.add_argument("--stdin", action="store_true", help="Read JSON payload from stdin for secret-safe registration")
    p_vlt.add_argument("--target-id", default=None)

    p_pipe = sub.add_parser("pipeline", help="Execute a single-turn AST-sandboxed Python script or declarative pipeline (browser_exec_pipeline)")
    p_pipe.add_argument("--script", default=None, help="Inline AST-sandboxed Python script")
    p_pipe.add_argument("--script-file", type=Path, default=None)
    p_pipe.add_argument("--steps-file", type=Path, default=None)
    p_pipe.add_argument("--stdin", action="store_true", help="Read Python script from stdin")
    p_pipe.add_argument("--max-calls", type=int, default=25)

    p_pb = sub.add_parser("playbooks", help="List, match, replay (0 LLM calls), or delete learned domain playbooks (browser_playbooks)")
    p_pb.add_argument("--action", default="list", choices=["list", "match", "replay", "delete"])
    p_pb.add_argument("--domain", default=None)
    p_pb.add_argument("--url", default="")
    p_pb.add_argument("--goal", default="")
    p_pb.add_argument("--playbook-id", default=None)
    p_pb.add_argument("--target-id", default=None)
    p_pb.add_argument("--workspace-id", default="default")

    p_ax = sub.add_parser("perception", help="Capture Blink AXTree + Shadow-DOM + OOPIFs or dispatch hardware input (browser_perception_axtree)")
    p_ax.add_argument("--action", default="snapshot", choices=["snapshot", "hardware_click", "hardware_type"])
    p_ax.add_argument("--target-id", default=None)
    p_ax.add_argument("--max-nodes", type=int, default=250)
    p_ax.add_argument("--no-shadow-dom", action="store_true")
    p_ax.add_argument("--backend-node-id", type=int, default=None)
    p_ax.add_argument("--x", type=float, default=None)
    p_ax.add_argument("--y", type=float, default=None)
    p_ax.add_argument("--text", default="")
    p_ax.add_argument("--text-env", default=None)
    p_ax.add_argument("--text-stdin", action="store_true")
    p_ax.add_argument("--press-enter", action="store_true")

    p_wlist = sub.add_parser("webmcp-list", help="Discover W3C WebMCP (`navigator.modelContext`) & declarative form tools (webmcp_list_tools)")
    p_wlist.add_argument("--target-id", default=None)

    p_wcall = sub.add_parser("webmcp-call", help="Invoke a W3C WebMCP page tool or declarative form in 1 call (webmcp_call_tool)")
    p_wcall.add_argument("--tool-name", required=True)
    p_wcall.add_argument("--args-json", default="{}")
    p_wcall.add_argument("--stdin", action="store_true", help="Read JSON arguments object from stdin")
    p_wcall.add_argument("--target-id", default=None)
    p_wcall.add_argument("--no-submit", action="store_true")

    p_mut = sub.add_parser("mutations", help="Control Network Mutation Firewall (`Fetch.enable` savepoints) (browser_mutation_guard)")
    p_mut.add_argument("--action", default="status", choices=["status", "enable", "disable", "approve", "reject"])
    p_mut.add_argument("--target-id", default=None)
    p_mut.add_argument("--url-pattern", default="*")
    p_mut.add_argument("--mutation-id", default=None)

    p_ws = sub.add_parser("workspaces", help="Manage named Tab Workspaces & SQLite FTS5 Knowledge Graph (browser_workspace)")
    p_ws.add_argument("--action", default="list", choices=["list", "snapshot", "upsert", "index", "search"])
    p_ws.add_argument("--workspace-id", default=None, help="Target workspace ID (defaults to 'default' on write; searches all workspaces when omitted)")
    p_ws.add_argument("--name", default=None)
    p_ws.add_argument("--description", default="")
    p_ws.add_argument("--pinned-urls", default="", help="Comma-separated pinned URLs for upsert")
    p_ws.add_argument("--url", default="")
    p_ws.add_argument("--title", default="")
    p_ws.add_argument("--rows-json", default=None, help="JSON array of entity dicts for --action index")
    p_ws.add_argument("--stdin", action="store_true", help="Read JSON rows array from stdin for --action index")
    p_ws.add_argument("--query", default="")
    p_ws.add_argument("--limit", type=int, default=25)

    p_hib = sub.add_parser("hibernate", help="Freeze idle background tabs or wake/pin a tab (browser_hibernate_tabs)")
    p_hib.add_argument("--action", default="hibernate", choices=["hibernate", "wake", "pin", "unpin"])
    p_hib.add_argument("--target-id", default=None)
    p_hib.add_argument("--min-idle-sec", type=float, default=0.0)
    p_hib.add_argument("--dry-run", action="store_true")

    p_ext = sub.add_parser("extract", help="Extract structured tables, rows, headings, and links from a tab (browser_extract_structured)")
    p_ext.add_argument("--target-id", default=None)
    p_ext.add_argument("--format", default="json", choices=["json", "csv", "md", "txt"])
    p_ext.add_argument("--workspace-id", default="default")

    p_gen = sub.add_parser("genui", help="Synthesize Generative UI workspace specification from a live tab (browser_generative_ui)")
    p_gen.add_argument("--target-id", default=None)
    p_gen.add_argument("--workspace-id", default="default")

    p_goal = sub.add_parser("goal", help="Run bounded perceive-decide-act goal on a tab (browser_run_goal)")
    p_goal.add_argument("--goal", required=True)
    p_goal.add_argument("--target-id", default=None)
    p_goal.add_argument("--start-url", default=None)
    p_goal.add_argument("--max-steps", type=int, default=8)
    p_goal.add_argument("--workspace-id", default="default")

    p_bulk = sub.add_parser("bulk", help="Extract structured data across comma-separated URLs in parallel (browser_bulk_extract)")
    p_bulk.add_argument("--urls", required=True, help="Comma-separated URLs")
    p_bulk.add_argument("--concurrency", type=int, default=4)
    p_bulk.add_argument("--format", default="json", choices=["json", "csv", "md", "txt"])
    p_bulk.add_argument("--workspace-id", default="default")

    p_res = sub.add_parser("resume", help="Resume a PAUSED_HUMAN_HANDOFF goal after human completes login/2FA (browser_handoff_resume)")
    p_res.add_argument("--run-id", required=True)
    p_res.add_argument("--workspace-id", default="default")

    p_out = sub.add_parser("outline", help="Accessibility outline with stable [ref=eN] handles, diff, grep, click, and type (browser_outline)")
    p_out.add_argument("--action", default="snapshot", choices=["snapshot", "diff", "grep", "click", "type"])
    p_out.add_argument("--target-id", default=None)
    p_out.add_argument("--ref", default=None)
    p_out.add_argument("--text", default="")
    p_out.add_argument("--press-enter", action="store_true")
    p_out.add_argument("--pattern", default="")
    p_out.add_argument("--interactive-only", action="store_true")

    p_wait = sub.add_parser("wait", help="Wait up to 30s for DOM settle, time, visible text, or CSS selector (browser_wait)")
    p_wait.add_argument("--for", dest="wait_for", default="settle", choices=["settle", "time", "text", "selector"])
    p_wait.add_argument("--value", default="")
    p_wait.add_argument("--timeout-sec", type=float, default=10.0)
    p_wait.add_argument("--target-id", default=None)

    p_shot = sub.add_parser("screenshot", help="Capture visible viewport as base64 JPEG, PNG, or WebP (browser_screenshot)")
    p_shot.add_argument("--target-id", default=None)
    p_shot.add_argument("--format", default="jpeg", choices=["jpeg", "png", "webp"])
    p_shot.add_argument("--quality", type=int, default=75)

    p_sched = sub.add_parser("schedule", help="Manage interval/daily scheduled goals (browser_schedule)")
    p_sched.add_argument("--action", default="list", choices=["list", "add", "remove", "enable", "disable", "run_now"])
    p_sched.add_argument("--task-id", default=None)
    p_sched.add_argument("--goal", default="")
    p_sched.add_argument("--start-url", default="")
    p_sched.add_argument("--kind", default="interval", choices=["interval", "daily"])
    p_sched.add_argument("--every-min", type=int, default=None)
    p_sched.add_argument("--at", default=None)
    p_sched.add_argument("--max-steps", type=int, default=8)

    p_seq = sub.add_parser("sequences", help="Inspect Numbat-derived Sequence Guard, evaluate events, export/verify signed CASE-*.zip bundles, or clear blocks (browser_sequence_guard)")
    p_seq.add_argument("--action", default="status", choices=["status", "evaluate", "export_casebundle", "verify_casebundle", "clear_block"])
    p_seq.add_argument("--tool-name", default="")
    p_seq.add_argument("--event-json", default="{}")
    p_seq.add_argument("--target-url", default="")
    p_seq.add_argument("--case-id", default=None)
    p_seq.add_argument("--bundle-path", default=None)
    p_seq.add_argument("--target-agent-id", default=None)

    p_vrt = sub.add_parser("vrt", help="Lock/unlock declared HTTP(S) origins and capture/compare pure-stdlib PNG VRT baselines (browser_vrt_isolation)")
    p_vrt.add_argument("--action", default="status", choices=["status", "lock_origins", "unlock_origins", "capture_baseline", "compare_vrt"])
    p_vrt.add_argument("--target-id", default=None)
    p_vrt.add_argument("--origins", default="", help="Comma-separated declared http(s) origins")
    p_vrt.add_argument("--baseline-id", default=None)
    p_vrt.add_argument("--max-mismatch-ratio", type=float, default=0.01)

    p_mon = sub.add_parser("monitors", help="Manage fenced SQLite WAL Web Monitors and CAS Playbook Revisions (browser_monitors)")
    p_mon.add_argument("--action", default="list", choices=["list", "create", "run_now", "runs", "delete", "snapshot_revision", "list_revisions", "rollback_playbook"])
    p_mon.add_argument("--monitor-id", default=None)
    p_mon.add_argument("--workspace-id", default="default")
    p_mon.add_argument("--name", default=None)
    p_mon.add_argument("--target-url", default=None)
    p_mon.add_argument("--extract-selector", default="body")
    p_mon.add_argument("--webhook-url", default="")
    p_mon.add_argument("--interval-sec", type=int, default=3600)
    p_mon.add_argument("--limit", type=int, default=25)
    p_mon.add_argument("--playbook-id", default=None)
    p_mon.add_argument("--expected-revision", default=None)
    p_mon.add_argument("--target-revision", default=None)

    p_evl = sub.add_parser("eval", help="Run multi-provider Search/Extraction Eval Suite or validate Perplexity wire contracts (browser_search_eval)")
    p_evl.add_argument("--action", default="scorecard", choices=["scorecard", "run_suite", "validate_wire"])
    p_evl.add_argument("--suite", default="extraction")
    p_evl.add_argument("--providers", default="", help="Comma-separated provider list")
    p_evl.add_argument("--endpoint", default="")
    p_evl.add_argument("--wire-json", default="{}")

    args = p.parse_args(argv)

    req_fn = lambda path, payload=None: _request(path, payload, human_auth=bool(args.human_auth))

    try:
        if args.cmd == "status":
            out = req_fn("/api/agent/status")
        elif args.cmd == "tabs":
            out = req_fn("/api/agent/tabs")
        elif args.cmd == "verify-ledger":
            out = req_fn("/api/agent/ledger/verify")
        elif args.cmd == "open":
            out = req_fn("/api/agent/open", {"url": args.url, "background": not args.foreground})
        elif args.cmd == "close":
            out = req_fn("/api/agent/close", {"target_id": args.target_id})
        elif args.cmd == "snapshot":
            out = req_fn(
                "/api/agent/snapshot",
                {
                    "target_id": args.target_id,
                    "frame_id": args.frame_id,
                    "include_frames": args.include_frames,
                    "show_badges": not args.no_badges,
                },
            )
        elif args.cmd == "act":
            txt = _resolve_secret_safe_text(args.text, args.text_env, args.text_stdin)
            out = req_fn(
                "/api/agent/act",
                {
                    "action": args.action,
                    "target_id": args.target_id,
                    "frame_id": args.frame_id,
                    "index": args.index,
                    "selector": args.selector,
                    "text": txt,
                    "url": args.url,
                },
            )
        elif args.cmd == "dialog":
            ptxt = _resolve_secret_safe_text(args.prompt_text, args.text_env, args.text_stdin)
            out = req_fn(
                "/api/agent/dialog",
                {
                    "action": args.action,
                    "target_id": args.target_id,
                    "dialog_id": args.dialog_id,
                    "prompt_text": ptxt,
                },
            )
        elif args.cmd == "vault":
            if args.action == "register":
                if args.stdin:
                    stdin_obj = json.loads(sys.stdin.read())
                    if not isinstance(stdin_obj, dict):
                        raise ValueError("vault --action register --stdin requires a JSON object")
                    v_payload: dict[str, object] = {"action": "register", **stdin_obj}
                else:
                    if not args.origin:
                        raise ValueError("vault --action register requires --origin (or --stdin JSON)")
                    pw = os.environ.get(args.password_env, "")
                    totp = os.environ.get(args.totp_env, "")
                    if not pw and not totp and sys.stdin.isatty():
                        pw = getpass.getpass("Vault password (input hidden): ")
                    v_payload = {
                        "action": "register",
                        "vault_id": args.vault_id,
                        "origin": args.origin,
                        "username": args.username,
                        "password": pw,
                        "totp_secret": totp,
                        "label": args.label,
                    }
                out = req_fn("/api/agent/vault", v_payload)
            else:
                if args.action in ("fill", "enter_totp", "delete") and not args.vault_id:
                    raise ValueError(f"vault --action {args.action} requires --vault-id")
                out = req_fn(
                    "/api/agent/vault",
                    {"action": args.action, "vault_id": args.vault_id, "origin": args.origin, "target_id": args.target_id},
                )
        elif args.cmd == "pipeline":
            pipe_body: dict[str, object] = {"max_calls": args.max_calls}
            if args.script is not None:
                pipe_body["script"] = args.script
            elif args.script_file is not None:
                pipe_body["script"] = args.script_file.read_text(encoding=ENCODING)
            elif args.steps_file is not None:
                pipe_body["steps"] = json.loads(args.steps_file.read_text(encoding=ENCODING))
            elif args.stdin:
                pipe_body["script"] = sys.stdin.read()
            else:
                raise ValueError("pipeline requires --script, --script-file, --steps-file, or --stdin")
            out = req_fn("/api/agent/pipeline", pipe_body)
        elif args.cmd == "playbooks":
            if args.action == "delete" and not args.playbook_id:
                raise ValueError("playbooks --action delete requires --playbook-id")
            out = req_fn(
                "/api/agent/playbooks",
                {
                    "action": args.action,
                    "domain": args.domain,
                    "url": args.url,
                    "goal": args.goal,
                    "playbook_id": args.playbook_id,
                    "target_id": args.target_id,
                    "workspace_id": args.workspace_id,
                },
            )
        elif args.cmd == "perception":
            txt = _resolve_secret_safe_text(args.text, args.text_env, args.text_stdin)
            out = req_fn(
                "/api/agent/perception",
                {
                    "action": args.action,
                    "target_id": args.target_id,
                    "max_nodes": args.max_nodes,
                    "include_shadow_dom": not args.no_shadow_dom,
                    "backend_node_id": args.backend_node_id,
                    "x": args.x,
                    "y": args.y,
                    "text": txt,
                    "press_enter": args.press_enter,
                },
            )
        elif args.cmd == "webmcp-list":
            out = req_fn("/api/agent/webmcp/list", {"target_id": args.target_id})
        elif args.cmd == "webmcp-call":
            parsed_args = json.loads(sys.stdin.read() if args.stdin else args.args_json)
            if not isinstance(parsed_args, dict):
                raise ValueError("webmcp-call arguments must be a JSON object")
            out = req_fn(
                "/api/agent/webmcp/call",
                {
                    "tool_name": args.tool_name,
                    "arguments": parsed_args,
                    "target_id": args.target_id,
                    "auto_submit": not args.no_submit,
                },
            )
        elif args.cmd == "mutations":
            if args.action in ("approve", "reject") and not args.mutation_id:
                raise ValueError(f"mutations --action {args.action} requires --mutation-id")
            out = req_fn(
                "/api/agent/mutations",
                {
                    "action": args.action,
                    "target_id": args.target_id,
                    "url_pattern": args.url_pattern,
                    "mutation_id": args.mutation_id,
                },
            )
        elif args.cmd == "workspaces":
            pinned = [u.strip() for u in args.pinned_urls.split(",") if u.strip()] if args.pinned_urls else None
            rows_payload = None
            if args.stdin:
                rows_payload = json.loads(sys.stdin.read())
            elif args.rows_json is not None:
                rows_payload = json.loads(args.rows_json)
            if rows_payload is not None and not isinstance(rows_payload, list):
                raise ValueError("workspaces --action index requires a JSON array of row objects")
            eff_ws_id = args.workspace_id if args.action == "search" else (args.workspace_id or "default")
            out = req_fn(
                "/api/agent/workspaces",
                {
                    "action": args.action,
                    "workspace_id": eff_ws_id,
                    "name": args.name,
                    "description": args.description,
                    "pinned_urls": pinned,
                    "url": args.url,
                    "title": args.title,
                    "rows": rows_payload,
                    "query": args.query,
                    "limit": args.limit,
                },
            )
        elif args.cmd == "hibernate":
            if args.action in ("wake", "pin", "unpin") and not args.target_id:
                raise ValueError(f"hibernate --action {args.action} requires --target-id")
            out = req_fn(
                "/api/agent/hibernate",
                {
                    "action": args.action,
                    "target_id": args.target_id,
                    "min_idle_sec": args.min_idle_sec,
                    "dry_run": args.dry_run,
                },
            )
        elif args.cmd == "extract":
            out = req_fn("/api/agent/extract", {"target_id": args.target_id, "format": args.format, "workspace_id": args.workspace_id})
        elif args.cmd == "genui":
            out = req_fn("/api/agent/genui", {"target_id": args.target_id, "workspace_id": args.workspace_id})
        elif args.cmd == "goal":
            out = req_fn(
                "/api/agent/goal",
                {
                    "goal": args.goal,
                    "target_id": args.target_id,
                    "start_url": args.start_url,
                    "max_steps": args.max_steps,
                    "workspace_id": args.workspace_id,
                },
            )
        elif args.cmd == "bulk":
            urls = [u.strip() for u in args.urls.split(",") if u.strip()]
            out = req_fn(
                "/api/agent/bulk",
                {"urls": urls, "concurrency": args.concurrency, "format": args.format, "workspace_id": args.workspace_id},
            )
        elif args.cmd == "resume":
            out = req_fn("/api/agent/handoff/resume", {"run_id": args.run_id, "workspace_id": args.workspace_id})
        elif args.cmd == "outline":
            out = req_fn(
                "/api/agent/outline",
                {
                    "action": args.action,
                    "target_id": args.target_id,
                    "ref": args.ref,
                    "text": args.text,
                    "press_enter": args.press_enter,
                    "pattern": args.pattern,
                    "interactive_only": args.interactive_only,
                },
            )
        elif args.cmd == "wait":
            out = req_fn(
                "/api/agent/wait",
                {
                    "for": args.wait_for,
                    "value": args.value,
                    "timeout_sec": args.timeout_sec,
                    "target_id": args.target_id,
                },
            )
        elif args.cmd == "screenshot":
            out = req_fn(
                "/api/agent/screenshot",
                {"target_id": args.target_id, "format": args.format, "quality": args.quality},
            )
        elif args.cmd == "schedule":
            out = req_fn(
                "/api/agent/schedule",
                {
                    "action": args.action,
                    "task_id": args.task_id,
                    "goal": args.goal,
                    "start_url": args.start_url,
                    "kind": args.kind,
                    "every_min": args.every_min,
                    "at": args.at,
                    "max_steps": args.max_steps,
                },
            )
        elif args.cmd == "sequences":
            ev_params = json.loads(args.event_json) if args.action == "evaluate" else {}
            out = req_fn(
                "/api/agent/sequences",
                {
                    "action": args.action,
                    "tool_name": args.tool_name,
                    "event_params": ev_params,
                    "target_url": args.target_url,
                    "case_id": args.case_id,
                    "bundle_path": args.bundle_path,
                    "target_agent_id": args.target_agent_id,
                },
            )
        elif args.cmd == "vrt":
            origs = [o.strip() for o in args.origins.split(",") if o.strip()] if args.origins else None
            out = req_fn(
                "/api/agent/vrt",
                {
                    "action": args.action,
                    "target_id": args.target_id,
                    "declared_origins": origs,
                    "baseline_id": args.baseline_id,
                    "max_mismatch_ratio": args.max_mismatch_ratio,
                },
            )
        elif args.cmd == "monitors":
            out = req_fn(
                "/api/agent/monitors",
                {
                    "action": args.action,
                    "monitor_id": args.monitor_id,
                    "workspace_id": args.workspace_id,
                    "name": args.name,
                    "target_url": args.target_url,
                    "extract_selector": args.extract_selector,
                    "webhook_url": args.webhook_url,
                    "interval_sec": args.interval_sec,
                    "limit": args.limit,
                    "playbook_id": args.playbook_id,
                    "expected_revision": args.expected_revision,
                    "target_revision": args.target_revision,
                },
            )
        elif args.cmd == "eval":
            provs = [x.strip() for x in args.providers.split(",") if x.strip()] if args.providers else None
            wire_obj = json.loads(args.wire_json) if args.action == "validate_wire" else None
            out = req_fn(
                "/api/agent/eval",
                {
                    "action": args.action,
                    "suite": args.suite,
                    "providers": provs,
                    "endpoint": args.endpoint,
                    "wire_payload": wire_obj,
                },
            )
        else:
            return 1
    except urllib.error.HTTPError as herr:
        body = herr.read().decode(ENCODING, errors="replace")
        herr.close()
        print(json.dumps({"ok": False, "http_status": herr.code, "error": body or str(herr)}, indent=2))
        return 1
    except urllib.error.URLError as uerr:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"Luminara Agent Daemon unreachable at {_daemon_url()}: {uerr.reason}",
                    "fix": "Run Launch-Luminara-Browser.cmd to start the browser and local Agent Daemon.",
                },
                indent=2,
            )
        )
        return 1
    except (ValueError, OSError) as verr:
        print(json.dumps({"ok": False, "error": str(verr)}, indent=2))
        return 1

    print(json.dumps(out, indent=2, ensure_ascii=False))
    if isinstance(out, dict) and (out.get("ok") is False or out.get("valid") is False):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
