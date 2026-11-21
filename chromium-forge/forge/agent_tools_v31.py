"""Luminara v3.1.0 Perplexity REA Suite MCP v2 Tool Schemas & Dispatchers (`forge/agent_tools_v31.py`).

Isolated from `agent_tools_100x.py` and `agent_server.py` so every file stays well below
the 1,000-line ceiling while expanding MCP v2 from 20 -> 24 tools and 7 -> 9 resources:
- `browser_sequence_guard`: Numbat-derived multi-step chain detector & signed `CASE-*.zip` casebundles.
- `browser_vrt_isolation`: `rules_web_e2e`-derived declared-origin network lock & pure-stdlib PNG VRT.
- `browser_monitors`: `perplexity-py` + `SPACE` fenced Web Monitors & CAS Playbook Revisions.
- `browser_search_eval`: `search_evals` `Decimal` CostLedger & multi-provider extraction/citation grader.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent_tools_100x import _float_opt, _int_opt, _require_str
from .monitors_eval import validate_perplexity_wire_payload
from .sequence_guard import verify_casebundle

MCP_RESOURCES_V31_SPEC: list[dict[str, str]] = [
    {"uri": "luminara://security/sequences", "name": "Behavioral Sequence Guard & Active Chain Blocks", "mimeType": "application/json"},
    {"uri": "luminara://monitors/runs", "name": "Fenced Web Monitor Runs & Diff Receipts", "mimeType": "application/json"},
]

MCP_TOOLS_V31_SPEC: list[dict[str, Any]] = [
    {
        "name": "browser_sequence_guard",
        "description": "Inspect multi-step behavioral sequence chains, evaluate an event, export/verify signed forensic CASE-*.zip bundles, or clear an active PAUSED_SEQUENCE_BLOCK (requires X-Luminara-UI-Key).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "evaluate", "export_casebundle", "verify_casebundle", "clear_block"],
                    "default": "status",
                },
                "tool_name": {"type": "string"},
                "event_params": {"type": "object"},
                "target_url": {"type": "string"},
                "workspace_id": {"type": "string", "default": "default"},
                "session_id": {"type": "string", "default": "live"},
                "case_id": {"type": "string"},
                "bundle_path": {"type": "string"},
                "target_agent_id": {"type": "string"},
                "agent_id": {"type": "string", "default": "mcp-agent"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "browser_vrt_isolation",
        "description": "Enforce hermetic declared-origin network allowlists via CDP Fetch.enable (`lock_origins`/`unlock_origins`) and run pure-stdlib PNG pixel-diff visual regression (`capture_baseline`/`compare_vrt`).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "lock_origins", "unlock_origins", "capture_baseline", "compare_vrt"],
                    "default": "status",
                },
                "target_id": {"type": "string"},
                "declared_origins": {"type": "array", "items": {"type": "string"}},
                "baseline_id": {"type": "string"},
                "max_mismatch_ratio": {"type": "number", "default": 0.01},
                "agent_id": {"type": "string", "default": "mcp-agent"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "browser_monitors",
        "description": "Manage fenced SQLite WAL Web Monitors (`create`, `list`, `run_now`, `runs`, `delete`) and CAS-protected Playbook Revisions (`snapshot_revision`, `list_revisions`, `rollback_playbook`).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "create",
                        "run_now",
                        "runs",
                        "delete",
                        "snapshot_revision",
                        "list_revisions",
                        "rollback_playbook",
                    ],
                    "default": "list",
                },
                "monitor_id": {"type": "string"},
                "workspace_id": {"type": "string", "default": "default"},
                "name": {"type": "string"},
                "target_url": {"type": "string"},
                "extract_selector": {"type": "string", "default": "body"},
                "interval_sec": {"type": "integer", "default": 3600},
                "webhook_url": {"type": "string", "default": ""},
                "playbook_id": {"type": "string"},
                "expected_revision": {"type": "string"},
                "target_revision": {"type": "string"},
                "limit": {"type": "integer", "default": 25},
                "agent_id": {"type": "string", "default": "mcp-agent"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "browser_search_eval",
        "description": "Run multi-provider search/extraction evaluation suites with exact Decimal USD CostLedger accounting (`run_suite`, `scorecard`) or validate Perplexity SDK wire contracts (`validate_wire`).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["scorecard", "run_suite", "validate_wire"],
                    "default": "scorecard",
                },
                "suite": {"type": "string", "default": "extraction"},
                "providers": {"type": "array", "items": {"type": "string"}},
                "endpoint": {"type": "string"},
                "wire_payload": {"type": "object"},
                "agent_id": {"type": "string", "default": "mcp-agent"},
            },
            "required": ["action"],
        },
    },
]


def requires_human_ui_key_v31(tool_name: str, args: dict[str, Any]) -> bool:
    """Canonical predicate for security-sensitive/human-only actions requiring `X-Luminara-UI-Key`."""
    act = str(args.get("action") or "")
    if tool_name == "browser_act" and act == "human_takeover":
        return True
    if tool_name == "browser_mutation_guard" and act in ("approve", "reject", "disable"):
        return True
    if tool_name == "browser_schedule" and act in ("add", "enable", "run_now"):
        return True
    if tool_name == "browser_sequence_guard" and act == "clear_block":
        return True
    if tool_name == "browser_vrt_isolation" and act == "unlock_origins":
        return True
    if tool_name == "browser_monitors":
        if act in ("delete", "rollback_playbook"):
            return True
        if act == "create" and bool(str(args.get("webhook_url") or "").strip()):
            return True
    return False


def dispatch_v31_tool(runtime: Any, name: str, args: dict[str, Any], agent_id: str) -> dict[str, Any] | None:
    """Dispatch Luminara v3.1.0 Perplexity REA Suite MCP tools; returns `None` if unhandled."""
    if name == "browser_sequence_guard":
        act = str(args.get("action") or "status")
        if act == "status":
            return {"ok": True, **runtime.sequence_guard.status()}
        if act == "evaluate":
            ev_res = runtime.sequence_guard.evaluate_step(
                agent_id=agent_id,
                tool_name=_require_str(args, "tool_name"),
                params=args.get("event_params") if isinstance(args.get("event_params"), dict) else {},
                target_url=str(args.get("target_url") or ""),
                workspace_id=str(args.get("workspace_id") or "default"),
                session_id=str(args.get("session_id") or "live"),
            )
            return ev_res
        if act == "export_casebundle":
            exp = runtime.sequence_guard.export_casebundle(case_id=args.get("case_id"))
            rec = runtime.ledger.record(
                agent_id,
                "export_casebundle",
                "",
                {"case_id": exp["case_id"], "manifest_sha256": exp["manifest_sha256"]},
                summary=f"Exported signed casebundle {exp['case_id']}",
            )
            return {**exp, "receipt": rec}
        if act == "verify_casebundle":
            raw_arg = _require_str(args, "bundle_path")
            cb_root = runtime.sequence_guard.casebundles_dir.resolve()
            if "/" not in raw_arg and "\\" not in raw_arg and ":" not in raw_arg:
                fname = raw_arg if raw_arg.lower().endswith(".zip") else f"{raw_arg}.zip"
                raw_p = (cb_root / fname).resolve()
            else:
                raw_p = Path(raw_arg).resolve()
            if not raw_p.is_relative_to(cb_root):
                raise ValueError("bundle_path must reside inside outputs/casebundles/")
            return verify_casebundle(raw_p, signer=runtime.signer)
        if act == "clear_block":
            res = runtime.sequence_guard.clear_block(agent_id=args.get("target_agent_id"))
            rec = runtime.ledger.record(
                "human-user",
                "sequence_clear_block",
                "",
                {"cleared_blocks": res["cleared_blocks"]},
                summary=f"Human cleared {res['cleared_blocks']} sequence block(s)",
            )
            return {**res, "receipt": rec}
        raise ValueError(f"Unsupported browser_sequence_guard action: {act!r}")

    if name == "browser_vrt_isolation":
        act = str(args.get("action") or "status")
        if act == "status":
            return {"ok": True, **runtime.vrt_isolation.status()}
        if act == "lock_origins":
            raw_origins = args.get("declared_origins")
            if not isinstance(raw_origins, list) or not raw_origins:
                raise ValueError("'declared_origins' must be a non-empty array of http(s) origins")
            res = runtime.vrt_isolation.lock_origins(args.get("target_id"), [str(o) for o in raw_origins])
            rec = runtime.ledger.record(
                agent_id,
                "vrt_lock_origins",
                str(res["target_id"]),
                {"declared_origins": res["declared_origins"]},
                summary=f"Locked tab {res['target_id']} to {len(res['declared_origins'])} origin(s)",
            )
            return {**res, "receipt": rec}
        if act == "unlock_origins":
            res = runtime.vrt_isolation.unlock_origins(args.get("target_id"))
            rec = runtime.ledger.record("human-user", "vrt_unlock_origins", str(res["target_id"]), {}, summary="Unlocked declared-origin filter")
            return {**res, "receipt": rec}
        if act == "capture_baseline":
            res = runtime.vrt_isolation.capture_baseline(_require_str(args, "baseline_id"), target_id=args.get("target_id"))
            rec = runtime.ledger.record(
                agent_id,
                "vrt_capture_baseline",
                str(res.get("target_id") or ""),
                {"baseline_id": res["baseline_id"], "width": res["width"], "height": res["height"]},
                summary=f"Captured VRT baseline {res['baseline_id']} ({res['width']}x{res['height']})",
            )
            return {**res, "receipt": rec}
        if act == "compare_vrt":
            res = runtime.vrt_isolation.compare_vrt(
                _require_str(args, "baseline_id"),
                target_id=args.get("target_id"),
                max_mismatch_ratio=_float_opt(args, "max_mismatch_ratio", 0.01),
            )
            rec = runtime.ledger.record(
                agent_id,
                "vrt_compare",
                str(res.get("target_id") or ""),
                {"baseline_id": res["baseline_id"], "passed": res["passed"], "mismatch_ratio": res["mismatch_ratio"]},
                status="OK" if res["passed"] else "WARN",
                summary=f"VRT {res['baseline_id']}: mismatch={res['mismatch_ratio']:.4%}",
            )
            return {**res, "receipt": rec}
        raise ValueError(f"Unsupported browser_vrt_isolation action: {act!r}")

    if name == "browser_monitors":
        act = str(args.get("action") or "list")
        if act == "list":
            return {"ok": True, "monitors": runtime.monitors_eval.list_monitors(args.get("workspace_id"))}
        if act == "create":
            t_url = _require_str(args, "target_url")
            res = runtime.monitors_eval.create_monitor(
                name=str(args.get("name") or t_url),
                target_url=t_url,
                workspace_id=str(args.get("workspace_id") or "default"),
                extract_selector=str(args.get("extract_selector") or "body"),
                interval_sec=_int_opt(args, "interval_sec", 3600),
                webhook_url=str(args.get("webhook_url") or ""),
            )
            rec = runtime.ledger.record(agent_id, "monitor_create", "", {"monitor_id": res["monitor_id"], "url": t_url}, summary=f"Created monitor {res['monitor_id']}")
            return {**res, "receipt": rec}
        if act == "run_now":
            return runtime.monitors_eval.run_monitor(_require_str(args, "monitor_id"), worker_id=agent_id)
        if act == "runs":
            return {
                "ok": True,
                "runs": runtime.monitors_eval.list_monitor_runs(
                    monitor_id=args.get("monitor_id"),
                    limit=_int_opt(args, "limit", 25),
                ),
            }
        if act == "delete":
            mid = _require_str(args, "monitor_id")
            deleted = runtime.monitors_eval.delete_monitor(mid)
            rec = runtime.ledger.record("human-user", "monitor_delete", "", {"monitor_id": mid, "deleted": deleted}, summary=f"Deleted monitor {mid}")
            return {"ok": True, "monitor_id": mid, "deleted": deleted, "receipt": rec}
        if act == "snapshot_revision":
            snap = runtime.monitors_eval.snapshot_playbook_revision(
                _require_str(args, "playbook_id"),
                expected_revision=args.get("expected_revision"),
            )
            return {"ok": True, **snap}
        if act == "list_revisions":
            return {"ok": True, "revisions": runtime.monitors_eval.list_playbook_revisions(_require_str(args, "playbook_id"))}
        if act == "rollback_playbook":
            return runtime.monitors_eval.rollback_playbook(
                _require_str(args, "playbook_id"),
                _require_str(args, "target_revision"),
                expected_revision=_require_str(args, "expected_revision"),
            )
        raise ValueError(f"Unsupported browser_monitors action: {act!r}")

    if name == "browser_search_eval":
        act = str(args.get("action") or "scorecard")
        if act == "scorecard":
            return runtime.monitors_eval.latest_scorecard()
        if act == "run_suite":
            raw_p = args.get("providers")
            provs = [str(x) for x in raw_p] if isinstance(raw_p, list) and raw_p else None
            rep = runtime.monitors_eval.run_search_eval_suite(suite=str(args.get("suite") or "extraction"), providers=provs)
            rec = runtime.ledger.record(agent_id, "search_eval_run", "", {"suite": rep["suite"], "providers": len(rep["scorecards"])}, summary=f"Executed {rep['suite']} eval suite")
            return {**rep, "receipt": rec}
        if act == "validate_wire":
            wp = args.get("wire_payload")
            if not isinstance(wp, dict):
                raise ValueError("wire_payload must be an object")
            return validate_perplexity_wire_payload(_require_str(args, "endpoint"), wp)
        raise ValueError(f"Unsupported browser_search_eval action: {act!r}")

    return None
