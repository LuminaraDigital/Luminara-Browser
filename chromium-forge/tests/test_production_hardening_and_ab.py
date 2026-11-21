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
            "http://169.254.169.253/latest/meta-data/",
            "http://[fd00:ec2::254]/latest/meta-data/",
            "http://[fe80::1]/",
            "http://127.0.0.1:8795/api/state",
            "http://127.0.0.2:8796/api/agent/status",
            "http://0.0.0.0:8796/api/agent/status",
            "http://[::ffff:127.0.0.1]:9229/json/list",
            "http://sub.localhost:8796/api/agent/status",
            "http://localhost:8796/api/agent/status",
            "http://127.0.0.1:9229/json/list",
            "http://2130706433:8796/",
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
        <input type="hidden" hidden value="csrf123" />
        <img src="spacer.gif" style="display:none" />
        <h1>Welcome to <span>Luminara</span></h1>
        <p style="opacity: 0.95">Experience <b>ultra-fast</b> co-browsing with <code>MCP v2</code> today.</p>
        <div style="display:none"><div>nested child</div><p>HIDDEN PROMPT INJECTION DO NOT EXTRACT</p></div>
        <div style="opacity: 0"><p>ZERO OPACITY INJECTION DO NOT EXTRACT</p></div>
        </body></html>"""
        ext = extract_structured_page(html_doc, "https://luminara.example")
        self.assertEqual(ext["headings"], ["Welcome to Luminara"])
        self.assertIn("Experience ultra-fast co-browsing with MCP v2 today.", ext["main_text"])
        self.assertNotIn("HIDDEN PROMPT INJECTION", ext["main_text"])
        self.assertNotIn("ZERO OPACITY INJECTION", ext["main_text"])

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

                # 4. Studio /api/compile preserves non-form ForkProfile fields (e.g., custom cdp_port/extra_cli_switches)
                ForkProfile(cdp_port=9333, extra_cli_switches=["--custom-test-flag"]).save(state_dir / "fork.json")
                compile_req = urllib.request.Request(
                    f"http://127.0.0.1:{st_port}/api/compile",
                    data=json.dumps({"brand_name": "Luminara Custom"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(compile_req, timeout=5) as r_comp:
                    comp_data = json.loads(r_comp.read().decode("utf-8"))
                    self.assertEqual(comp_data["profile"]["brand_name"], "Luminara Custom")
                    self.assertEqual(comp_data["profile"]["cdp_port"], 9333)
                    self.assertEqual(comp_data["profile"]["extra_cli_switches"], ["--custom-test-flag"])

                # 5. MCP v2 ping & notifications/cancelled return 200 / 204 cleanly
                ping_req = urllib.request.Request(
                    f"http://127.0.0.1:{ag_port}/api/agent/mcp",
                    data=json.dumps({"jsonrpc": "2.0", "id": 77, "method": "ping"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(ping_req, timeout=5) as r_ping:
                    self.assertEqual(json.loads(r_ping.read().decode("utf-8"))["result"], {})

                notif_req = urllib.request.Request(
                    f"http://127.0.0.1:{ag_port}/api/agent/mcp",
                    data=json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(notif_req, timeout=5) as r_notif:
                    self.assertEqual(r_notif.status, 204)
            finally:
                rt.close()
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
            self.assertEqual(report["passed_count"], 8)
            self.assertTrue(out_json.exists())
            self.assertTrue(out_md.exists())

    def test_all_ui_javascript_syntax_and_zero_innerhtml(self) -> None:
        import re
        import shutil
        from forge.luminara_ui import (
            build_luminara_newtab_html,
            build_luminara_workspace_html,
            write_copilot_extension,
        )

        prof = ForkProfile()
        nt_html = build_luminara_newtab_html(prof)
        ws_html = build_luminara_workspace_html(prof)
        studio_html = (FORGE_ROOT / "forge" / "ui" / "index.html").read_text(encoding="utf-8")
        cf_html = (STUDIO_ROOT / "cloudflare" / "public" / "index.html").read_text(encoding="utf-8")

        for name, doc in (
            ("newtab.html", nt_html),
            ("workspace.html", ws_html),
            ("forge/ui/index.html", studio_html),
            ("cloudflare/public/index.html", cf_html),
        ):
            self.assertNotIn(".innerHTML", doc, f"Found .innerHTML in {name}")

        node_bin = shutil.which("node")
        if not node_bin:
            return

        with tempfile.TemporaryDirectory() as tmp:
            w = Path(tmp)
            cop_dir = w / "copilot"
            nt_dir = w / "newtab_ext"
            sh_dir = w / "shield_ext"
            write_copilot_extension(cop_dir, prof)
            from forge.portable import _write_offline_newtab_extension, _write_shield_extension
            _write_offline_newtab_extension(nt_dir, prof, nt_html, ws_html)
            _write_shield_extension(sh_dir, prof)
            cf_inline = re.search(r"<script>(.*)</script>", cf_html, re.S)
            cf_js = (
                cf_inline.group(1)
                if cf_inline
                else (STUDIO_ROOT / "cloudflare" / "public" / "app.js").read_text(encoding="utf-8")
            )
            scripts = {
                "newtab.js": re.search(r"<script>(.*)</script>", nt_html, re.S).group(1),  # type: ignore[union-attr]
                "workspace.js": re.search(r"<script>(.*)</script>", ws_html, re.S).group(1),  # type: ignore[union-attr]
                "studio.js": re.search(r"<script>(.*)</script>", studio_html, re.S).group(1),  # type: ignore[union-attr]
                "cloudflare_portal.js": cf_js,
                "sidepanel.js": (cop_dir / "sidepanel.js").read_text(encoding="utf-8"),
                "background.js": (cop_dir / "background.js").read_text(encoding="utf-8"),
                "palette.js": (nt_dir / "palette.js").read_text(encoding="utf-8"),
                "newtab_bg.js": (nt_dir / "newtab_bg.js").read_text(encoding="utf-8"),
                "farble.js": (sh_dir / "farble.js").read_text(encoding="utf-8"),
                "webmcp_bootstrap.js": (sh_dir / "webmcp_bootstrap.js").read_text(encoding="utf-8"),
            }
            for fname, code in scripts.items():
                self.assertNotIn(".innerHTML", code, f"Found .innerHTML in {fname}")
                p = w / fname
                p.write_text(code, encoding="utf-8")
                proc = subprocess.run([node_bin, "--check", str(p)], capture_output=True, text=True, timeout=10)
                self.assertEqual(proc.returncode, 0, f"JavaScript SyntaxError in {fname}: {proc.stderr}")

    def test_live_end_to_end_newtab_workspace_undo_redo_and_cli_qa(self) -> None:
        import sys
        import time
        from forge.cdp_client import terminate_browser_process, wait_for_cdp_page_ready
        from forge.verifier_agentic import find_chromium_binary

        prof = ForkProfile()
        chrome_exe = find_chromium_binary(FORGE_ROOT, prof)
        if chrome_exe is None:
            self.skipTest("Portable chrome.exe not yet built")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            w = Path(tmp)
            cdp_port = _free_port()
            ag_port = _free_port()
            rt = LuminaraAgentRuntime(w / "state", cdp_port=cdp_port)
            srv = create_agent_http_server(rt, host="127.0.0.1", port=ag_port)
            threading.Thread(target=srv.serve_forever, daemon=True).start()

            proc = subprocess.Popen(
                [
                    str(chrome_exe),
                    "--headless=new",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    f"--user-data-dir={w / 'prof'}",
                    f"--remote-debugging-port={cdp_port}",
                    "--remote-allow-origins=*",
                    "--window-size=1280,900",
                    f"http://127.0.0.1:{ag_port}/newtab",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                self.assertTrue(
                    wait_for_cdp_page_ready(rt.cdp, "typeof syncDaemon === 'function'", timeout=20.0),
                    "newtab.html script failed to execute",
                )
                time.sleep(0.50)
                nt_state = rt.cdp.evaluate_js(
                    None,
                    """(() => {
                        const splash = document.getElementById('luminaraSplash');
                        const track = document.getElementById('splashProgressTrack');
                        const progressBefore = Number(track ? track.getAttribute('aria-valuenow') : 0);
                        const pulseBtn = document.getElementById('btnPulseLogo');
                        pulseBtn.focus();
                        pulseBtn.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
                        const stillOpenAfterBtnEnter = !splash.classList.contains('hidden');
                        window.__luminaraLogo3D.closeSplash();
                        const closedOk = splash.classList.contains('hidden');
                        window.__luminaraLogo3D.openSplash();
                        const reopenedOk = !splash.classList.contains('hidden');
                        const canvas = document.getElementById('splashLogoCanvas');
                        const canvasBounded = canvas.width >= 64 && canvas.width <= 1024;
                        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
                        const closedOnEsc = splash.classList.contains('hidden');
                        document.getElementById('todoInput').value = 'Live QA Task';
                        document.getElementById('todoForm').dispatchEvent(new Event('submit', {cancelable: true}));
                        const todos = JSON.parse(localStorage.getItem('luminara_browser:todos') || '[]');
                        return {
                            todoCount: todos.length,
                            firstTodo: todos[0] ? todos[0].text : '',
                            progressBefore,
                            stillOpenAfterBtnEnter,
                            closedOk,
                            reopenedOk,
                            canvasBounded,
                            closedOnEsc,
                        };
                    })()""",
                )
                self.assertEqual(nt_state["firstTodo"], "Live QA Task")
                self.assertEqual(nt_state["progressBefore"], 100)
                self.assertTrue(nt_state["stillOpenAfterBtnEnter"])
                self.assertTrue(nt_state["closedOk"])
                self.assertTrue(nt_state["reopenedOk"])
                self.assertTrue(nt_state["canvasBounded"])
                self.assertTrue(nt_state["closedOnEsc"])

                rt.cdp.navigate(None, f"http://127.0.0.1:{ag_port}/workspace", settle_sec=0.4)
                self.assertTrue(
                    wait_for_cdp_page_ready(rt.cdp, "typeof executeEdit === 'function'", timeout=10.0),
                    "workspace.html script failed to execute",
                )
                ws_state = rt.cdp.evaluate_js(
                    None,
                    """(() => {
                        executeEdit('ent_001', 'Latency (ms)', '9');
                        const afterEditMin = state.summary_bar.min;
                        const afterEditSpread = state.summary_bar.spread_pct;
                        undo();
                        const afterUndoMin = state.summary_bar.min;
                        redo();
                        const afterRedoMin = state.summary_bar.min;
                        return { afterEditMin, afterEditSpread, afterUndoMin, afterRedoMin };
                    })()""",
                )
                self.assertEqual(ws_state["afterEditMin"], 9)
                self.assertEqual(ws_state["afterUndoMin"], 18)
                self.assertEqual(ws_state["afterRedoMin"], 9)
                self.assertGreater(ws_state["afterEditSpread"], 100.0)

                ctl = str((STUDIO_ROOT / "skills" / "luminara-browser" / "scripts" / "luminara_ctl.py").resolve())
                env = {**os.environ, "LUMINARA_AGENT_URL": f"http://127.0.0.1:{ag_port}"}
                for subcmd in (["status"], ["tabs"], ["extract", "--format", "md"], ["genui"], ["verify-ledger"]):
                    r = subprocess.run([sys.executable, ctl, *subcmd], env=env, capture_output=True, text=True, timeout=15)
                    self.assertEqual(r.returncode, 0, f"CLI {subcmd} failed: {r.stderr} {r.stdout}")
            finally:
                rt.close()
                srv.shutdown()
                srv.server_close()
                terminate_browser_process(proc)

    def test_3d_animated_startup_logo_and_icons(self) -> None:
        from forge.luminara_logo3d import get_logo_data_uri, get_logo_favicon_data_uri, get_logo_icon_png
        from forge.luminara_ui import build_luminara_newtab_html, build_luminara_workspace_html, write_copilot_extension
        from forge.portable import _write_offline_newtab_extension, _write_shield_extension

        uri = get_logo_data_uri()
        self.assertTrue(uri.startswith("data:image/"), "Embedded 3D logo data URI missing")
        self.assertTrue(get_logo_favicon_data_uri().startswith("data:image/png;base64,"))
        for px in (16, 48, 128):
            png = get_logo_icon_png(px)
            self.assertIsNotNone(png)
            self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))  # type: ignore[union-attr]

        prof = ForkProfile()
        nt_html = build_luminara_newtab_html(prof)
        ws_html = build_luminara_workspace_html(prof)
        for token in (
            'id="luminaraSplash"',
            'id="splashLogoCanvas"',
            'id="heroLogoCanvas"',
            "createLuminara3DLogo",
            "__luminaraSplashNotifyDaemon",
            "chrome.storage.session",
            "webglcontextlost",
            'rel="icon"',
        ):
            self.assertIn(token, nt_html)
        self.assertIn('rel="icon"', ws_html)
        self.assertNotIn(".innerHTML", nt_html)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            w = Path(tmp)
            nt_dir, sh_dir, cp_dir = w / "newtab", w / "shield", w / "copilot"
            _write_offline_newtab_extension(nt_dir, prof, nt_html, ws_html)
            _write_shield_extension(sh_dir, prof)
            write_copilot_extension(cp_dir, prof)
            expected_128 = get_logo_icon_png(128)
            for ext in (nt_dir, sh_dir, cp_dir):
                self.assertEqual((ext / "icons" / "icon128.png").read_bytes(), expected_128)
            manifest = json.loads((nt_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("storage", manifest.get("permissions", []))

        cf_pub = STUDIO_ROOT / "cloudflare" / "public"
        for asset in ("luminara-logo.webp", "icon48.png", "icon128.png"):
            self.assertTrue((cf_pub / asset).is_file(), f"Missing Cloudflare portal asset: {asset}")
        self.assertFalse((cf_pub / "favicon.svg").exists(), "Legacy green-dot favicon.svg should be removed")
        self.assertNotIn(".innerHTML", (cf_pub / "app.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
