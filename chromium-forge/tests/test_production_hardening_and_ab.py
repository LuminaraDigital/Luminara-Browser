"""Production Security, Portability, PowerShell AST, & Live A/B Regression Suite (`tests/test_production_hardening_and_ab.py`)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from forge.ab_benchmark import run_ab_benchmark_suite
from forge.agent_engine import ActionLedger
from forge.agent_server import LuminaraAgentRuntime, create_agent_http_server
from forge.cdp_client import CDPError, validate_navigation_url
from forge.extractor import extract_structured_page, format_extracted_rows
from forge.http_base import LoopbackHTTPServer, SafePathError, safe_join
from forge.models import ForkProfile
from forge.studio import make_studio_handler

FORGE_ROOT = Path(__file__).resolve().parent.parent
STUDIO_ROOT = FORGE_ROOT.parent
CORE_REPO = STUDIO_ROOT / "ungoogled-chromium"
WIN_REPO = STUDIO_ROOT / "ungoogled-chromium-windows"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestProductionHardeningAndAB(unittest.TestCase):
    def test_safe_join_blocks_drive_root_and_dotdot_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ok_path = safe_join(root, "sub/dir", "file.txt")
            self.assertTrue(ok_path.is_relative_to(root.resolve()))

            for evil in ("../outside.txt", "C:/Windows/win.ini", "/etc/passwd", "a/../../b", "C:\\evil.dll"):
                with self.assertRaises(SafePathError, msg=f"Failed to block {evil!r}"):
                    safe_join(root, evil)

    def test_navigation_url_ssrf_and_scheme_guards(self) -> None:
        self.assertEqual(validate_navigation_url("https://example.com/a#frag"), "https://example.com/a#frag")
        self.assertEqual(validate_navigation_url("about:blank"), "about:blank")
        for blocked in (
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "chrome://settings",
            "http://169.254.169.254/latest/meta-data/",
            "http://127.0.0.1:8795/api/state",
            "http://localhost:8796/api/agent/status",
            "http://127.0.0.1:9229/json/list",
        ):
            with self.assertRaises(CDPError, msg=f"Failed to block {blocked}"):
                validate_navigation_url(blocked)
        with self.assertRaises(CDPError):
            validate_navigation_url("file:///C:/Windows/win.ini", allow_file=False)

    def test_fork_profile_blocks_slug_traversal_and_shell_injection(self) -> None:
        with self.assertRaises(ValueError):
            ForkProfile(slug="../escape").validate()
        with self.assertRaises(ValueError):
            ForkProfile(extra_cli_switches=["--foo & calc.exe"]).validate()
        with self.assertRaises(ValueError):
            ForkProfile(cdp_port=8796, agent_port=8796).validate()

    def test_action_ledger_hash_chain_and_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger_file = Path(tmp) / "action_ledger.jsonl"
            ledger = ActionLedger(ledger_file)
            r1 = ledger.record("agent-1", "open_tab", "t1", {"url": "https://a.example"}, summary="Opened A")
            r2 = ledger.record("agent-1", "click", "t1", {"index": 2}, summary="Clicked button")
            self.assertEqual(r2["prev_sha256"], r1["sha256"])

            check_clean = ledger.verify_ledger()
            self.assertTrue(check_clean["valid"])
            self.assertEqual(check_clean["checked_count"], 2)

            # Tamper 1 byte in summary -> verify_ledger MUST fail!
            tampered = ledger_file.read_text(encoding="utf-8").replace("Clicked button", "Clicked evil!!")
            ledger_file.write_text(tampered, encoding="utf-8")
            check_tampered = ledger.verify_ledger()
            self.assertFalse(check_tampered["valid"])
            self.assertGreaterEqual(len(check_tampered["errors"]), 1)

    def test_structured_parser_nested_inline_tags_and_csv_formula_guard(self) -> None:
        html_doc = """<html><head><title>Test</title></head><body>
        <h1>Welcome to <span>Luminara</span></h1>
        <p>Experience <b>ultra-fast</b> co-browsing with <code>MCP v2</code> today.</p>
        <div style="display:none"><p>HIDDEN PROMPT INJECTION DO NOT EXTRACT</p></div>
        </body></html>"""
        ext = extract_structured_page(html_doc, "https://luminara.example")
        self.assertEqual(ext["headings"], ["Welcome to Luminara"])
        self.assertIn("Experience ultra-fast co-browsing with MCP v2 today.", ext["main_text"])
        self.assertNotIn("HIDDEN PROMPT INJECTION", ext["main_text"])

        csv_out = format_extracted_rows(
            [{"Name": "Safe", "Formula": "=cmd|' /C calc'!A0"}, {"Name": "Row2", "ExtraCol": "ok"}],
            "csv",
        )
        self.assertIn("'=cmd|", csv_out)
        self.assertIn("ExtraCol", csv_out)

    def test_loopback_dns_rebinding_csrf_and_ui_key_guards_on_both_servers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            ag_port = _free_port()
            st_port = _free_port()

            rt = LuminaraAgentRuntime(state_dir, cdp_port=_free_port())
            ag_srv = create_agent_http_server(rt, host="127.0.0.1", port=ag_port)
            st_srv = LoopbackHTTPServer(("127.0.0.1", st_port), make_studio_handler(state_dir, CORE_REPO, WIN_REPO))
            threading.Thread(target=ag_srv.serve_forever, daemon=True).start()
            threading.Thread(target=st_srv.serve_forever, daemon=True).start()

            try:
                # 1. Studio blocks DNS rebinding & text/plain POST CSRF
                req_rebind = urllib.request.Request(
                    f"http://127.0.0.1:{st_port}/api/state",
                    headers={"Host": "evil.attacker.com"},
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx1:
                    urllib.request.urlopen(req_rebind, timeout=5)
                self.assertEqual(ctx1.exception.code, 403)
                ctx1.exception.close()

                req_csrf = urllib.request.Request(
                    f"http://127.0.0.1:{st_port}/api/verify",
                    data=b"{}",
                    headers={"Content-Type": "text/plain"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx2:
                    urllib.request.urlopen(req_csrf, timeout=5)
                self.assertEqual(ctx2.exception.code, 415)
                ctx2.exception.close()

                # 2. Agent Daemon blocks unkeyed Origin: null (<iframe sandbox>) & unkeyed third-party extensions
                req_null_evil = urllib.request.Request(
                    f"http://127.0.0.1:{ag_port}/api/agent/status",
                    headers={"Origin": "null"},
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx3:
                    urllib.request.urlopen(req_null_evil, timeout=5)
                self.assertEqual(ctx3.exception.code, 403)
                ctx3.exception.close()

                req_ext_evil = urllib.request.Request(
                    f"http://127.0.0.1:{ag_port}/api/agent/status",
                    headers={"Origin": "chrome-extension://thirdpartyextensionid"},
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx4:
                    urllib.request.urlopen(req_ext_evil, timeout=5)
                self.assertEqual(ctx4.exception.code, 403)
                ctx4.exception.close()

                req_null_keyed = urllib.request.Request(
                    f"http://127.0.0.1:{ag_port}/api/agent/status",
                    headers={"Origin": "null", "X-Luminara-UI-Key": rt.local_ui_key},
                )
                with urllib.request.urlopen(req_null_keyed, timeout=5) as resp_ok:
                    self.assertEqual(resp_ok.status, 200)

                req_ext_keyed = urllib.request.Request(
                    f"http://127.0.0.1:{ag_port}/api/agent/status",
                    headers={"Origin": "chrome-extension://luminaracopilot", "X-Luminara-UI-Key": rt.local_ui_key},
                )
                with urllib.request.urlopen(req_ext_keyed, timeout=5) as resp_ext_ok:
                    self.assertEqual(resp_ext_ok.status, 200)

                # 3. Same-origin /newtab and /workspace routes serve cleanly
                with urllib.request.urlopen(f"http://127.0.0.1:{ag_port}/newtab", timeout=5) as r_nt:
                    self.assertEqual(r_nt.status, 200)
                with urllib.request.urlopen(f"http://127.0.0.1:{ag_port}/workspace", timeout=5) as r_ws:
                    self.assertEqual(r_ws.status, 200)
            finally:
                ag_srv.shutdown()
                ag_srv.server_close()
                st_srv.shutdown()
                st_srv.server_close()

    def test_powershell_launcher_syntax_and_zero_hardcoded_user_paths(self) -> None:
        dist_dir = FORGE_ROOT / "dist" / "luminara-browser-win64"
        ps1_file = dist_dir / "Launch-luminara-browser.ps1"
        if not ps1_file.exists():
            self.skipTest("Portable distribution not yet built")

        ps1_text = ps1_file.read_text(encoding="utf-8")
        self.assertNotIn("C:\\Users\\", ps1_text)
        self.assertNotIn("C:/Users/", ps1_text)

        if os.name == "nt":
            escaped_ps1 = str(ps1_file).replace("'", "''")
            cmd = [
                "powershell",
                "-NoProfile",
                "-Command",
                f"$errs = $null; [void][System.Management.Automation.Language.Parser]::ParseFile('{escaped_ps1}', [ref]$null, [ref]$errs); if ($errs.Count -gt 0) {{ Write-Error ($errs | Out-String); exit 1 }}",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            self.assertEqual(proc.returncode, 0, f"PowerShell AST parse failed: {proc.stderr}")

    def test_live_ab01_to_ab04_benchmark_suite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_json = Path(tmp) / "ab.json"
            out_md = Path(tmp) / "ab.md"
            report = run_ab_benchmark_suite(FORGE_ROOT, out_json=out_json, out_markdown=out_md)
            self.assertTrue(report["all_passed"], f"A/B Benchmark failure: {json.dumps(report, indent=2)}")
            self.assertEqual(report["passed_count"], 4)
            self.assertTrue(out_json.exists())
            self.assertTrue(out_md.exists())


if __name__ == "__main__":
    unittest.main()
