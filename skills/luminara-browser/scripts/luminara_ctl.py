#!/usr/bin/env python3
"""Zero-dependency CLI controller for Luminara Browser Agent Daemon (`127.0.0.1:8796`)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ENCODING = "utf-8"


def _daemon_url() -> str:
    return (os.environ.get("LUMINARA_AGENT_URL") or "http://127.0.0.1:8796").rstrip("/")


def _headers(is_post: bool) -> dict[str, str]:
    hdrs: dict[str, str] = {}
    if is_post:
        hdrs["Content-Type"] = "application/json"
    tok = (os.environ.get("LUMINARA_AGENT_TOKEN") or "").strip()
    if tok:
        hdrs["Authorization"] = f"Bearer {tok}"
    return hdrs


def _request(path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    url = f"{_daemon_url()}{path}"
    data = json.dumps(payload).encode(ENCODING) if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers=_headers(payload is not None),
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=30.0) as resp:
        return json.loads(resp.read().decode(ENCODING))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="luminara_ctl", description="Control Luminara Browser via local Agent Daemon")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show daemon health, CDP state, active handoffs, and recent LUM-* receipts")
    sub.add_parser("tabs", help="List open shared browser tabs and active leases")
    sub.add_parser("verify-ledger", help="Verify cryptographic SHA-256 chain integrity of LUM-* action ledger")

    p_open = sub.add_parser("open", help="Open URL in a shared or background tab")
    p_open.add_argument("--url", required=True)
    p_open.add_argument("--foreground", action="store_true")

    p_snap = sub.add_parser("snapshot", help="Index visible [1..N] Set-of-Marks DOM elements")
    p_snap.add_argument("--target-id", default=None)
    p_snap.add_argument("--no-badges", action="store_true")

    p_act = sub.add_parser("act", help="Execute click, type, scroll, navigate, human_takeover, or clear_hud")
    p_act.add_argument("--action", required=True, choices=["click", "type", "select", "scroll", "navigate", "human_takeover", "clear_hud"])
    p_act.add_argument("--target-id", default=None)
    p_act.add_argument("--index", type=int, default=None)
    p_act.add_argument("--selector", default=None)
    p_act.add_argument("--text", default="")
    p_act.add_argument("--url", default="")

    p_goal = sub.add_parser("goal", help="Run bounded perceive-decide-act goal on a tab")
    p_goal.add_argument("--goal", required=True)
    p_goal.add_argument("--target-id", default=None)
    p_goal.add_argument("--max-steps", type=int, default=8)

    p_bulk = sub.add_parser("bulk", help="Extract structured data across comma-separated URLs in parallel")
    p_bulk.add_argument("--urls", required=True, help="Comma-separated URLs")
    p_bulk.add_argument("--concurrency", type=int, default=4)
    p_bulk.add_argument("--format", default="json", choices=["json", "csv", "md", "txt"])

    args = p.parse_args(argv)

    try:
        if args.cmd == "status":
            out = _request("/api/agent/status")
        elif args.cmd == "tabs":
            out = _request("/api/agent/tabs")
        elif args.cmd == "verify-ledger":
            out = _request("/api/agent/ledger/verify")
        elif args.cmd == "open":
            out = _request("/api/agent/open", {"url": args.url, "background": not args.foreground})
        elif args.cmd == "snapshot":
            out = _request("/api/agent/snapshot", {"target_id": args.target_id, "show_badges": not args.no_badges})
        elif args.cmd == "act":
            out = _request(
                "/api/agent/act",
                {
                    "action": args.action,
                    "target_id": args.target_id,
                    "index": args.index,
                    "selector": args.selector,
                    "text": args.text,
                    "url": args.url,
                },
            )
        elif args.cmd == "goal":
            out = _request("/api/agent/goal", {"goal": args.goal, "target_id": args.target_id, "max_steps": args.max_steps})
        elif args.cmd == "bulk":
            urls = [u.strip() for u in args.urls.split(",") if u.strip()]
            out = _request("/api/agent/bulk", {"urls": urls, "concurrency": args.concurrency, "format": args.format})
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

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
