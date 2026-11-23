"""Comprehensive Luminara Browser v3.0 — 100x Engine Verification & Security Test Suite."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request

from forge.agent_engine import ActionLedger
from forge.agent_server import LuminaraAgentRuntime, MCP_TOOLS_SPEC, create_agent_http_server
from forge.benchmark_100x import _LocalRFC6455EchoServer, run_100x_benchmark_suite
from forge.cdp_client import CDPBridge, _RFC6455Socket
from forge.cdp_mux import MultiplexedCDPPool
from forge.chromium_src import audit_version_provenance, verify_patches_against_upstream
from forge.customizer import generate_github_actions_cloud_workflow
from forge.knowledge_graph import KnowledgeWorkspaceStore, TabLifecycleManager
from forge.luminara_crypto import (
    CryptoError,
    EphemeralSessionSigner,
    LuminaraEnvelopeCipher,
    aead_open,
    aead_seal,
)
from forge.luminara_security import LuminaraRedactor, LuminaraVault
from forge.models import ForkProfile
from forge.mutation_firewall import NetworkMutationFirewall, classify_mutation_risk
from forge.perception import build_shadow_piercing_snapshot_js, parse_ax_tree_nodes
from forge.portable import _extract_inline_script_for_mv3
from forge.shield_compiler import (
    build_deterministic_farbling_js,
    compile_dnr_shield_rules,
    derive_farbling_seed,
    parse_adblock_domains,
    strip_tracking_params_url,
)
from forge.updater import sign_release_manifest, verify_release_manifest
from forge.webmcp import WEBMCP_BOOTSTRAP_JS, build_invoke_webmcp_tool_js

FORGE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = FORGE_ROOT.parent


class TestLuminara100xEngine(unittest.TestCase):
    def test_01_dpapi_aead_vault_zero_plaintext_and_legacy_migration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lum_t100_vault_") as td:
            vpath = Path(td) / "vault.json"
            # Seed a legacy v1 plaintext vault file to verify automatic migration
            legacy = {
                "legacy_gh": {
                    "vault_id": "legacy_gh",
                    "origin": "https://github.com",
                    "username": "dev",
                    "password": "LegacyPlainPassword#99",
                    "totp_secret": "JBSWY3DPEHPK3PXP",
                }
            }
            vpath.write_text(json.dumps(legacy), encoding="utf-8")

            vault = LuminaraVault(vpath, redactor=LuminaraRedactor())
            # Disk file must immediately be encrypted with ZERO plaintext secrets!
            raw_disk = vpath.read_text(encoding="utf-8")
            self.assertIn("luminara-vault-v2-encrypted", raw_disk)
            self.assertNotIn("LegacyPlainPassword#99", raw_disk)
            self.assertNotIn("JBSWY3DPEHPK3PXP", raw_disk)

            # Re-open vault from disk -> decrypted cleanly in memory
            vault2 = LuminaraVault(vpath, redactor=LuminaraRedactor())
            entries = vault2.list_entries()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["vault_id"], "legacy_gh")
            self.assertTrue(entries[0]["has_password"])
            self.assertNotIn("password", entries[0])

            # Origin-AAD cross-origin ciphertext transplant must fail cryptographically!
            parsed = json.loads(raw_disk)
            sealed = parsed["entries"]["legacy_gh"]["sealed_secrets"]
            with self.assertRaises(CryptoError):
                vault2._cipher.open_json(sealed, aad_context=vault2._aad_for("legacy_gh", "https://evil.example.com"))

    def test_02_passphrase_roaming_cipher_and_aead_tamper_detection(self) -> None:
        key = b"K" * 32
        blob = aead_seal(key, b"top-secret-payload", aad=b"origin:a")
        self.assertEqual(aead_open(key, blob, aad=b"origin:a"), b"top-secret-payload")
        with self.assertRaises(CryptoError):
            aead_open(key, blob, aad=b"origin:b")

        with tempfile.TemporaryDirectory(prefix="lum_t100_pass_") as td:
            kpath = Path(td) / "usb.key.json"
            c1 = LuminaraEnvelopeCipher(kpath, passphrase="correct horse battery staple")
            self.assertEqual(c1.protection_mode, "passphrase")
            sealed = c1.seal_json({"pw": "SecretUSB123!"}, aad_context="test:aad")
            c2 = LuminaraEnvelopeCipher(kpath, passphrase="correct horse battery staple")
            self.assertEqual(c2.open_json(sealed, aad_context="test:aad")["pw"], "SecretUSB123!")
            with self.assertRaises(CryptoError):
                LuminaraEnvelopeCipher(kpath, passphrase="wrong passphrase")

    def test_03_ephemeral_session_tokens_and_signed_action_ledger(self) -> None:
        signer = EphemeralSessionSigner(b"S" * 32, default_ttl_sec=120)
        tok = signer.issue_token("ui", ttl_sec=60)
        self.assertTrue(signer.verify_token(tok, required_scope="ui"))
        self.assertFalse(signer.verify_token(tok, required_scope="admin"))
        self.assertFalse(signer.verify_token(tok + "x", required_scope="ui"))

        with tempfile.TemporaryDirectory(prefix="lum_t100_ledger_") as td:
            lpath = Path(td) / "ledger.jsonl"
            ledger = ActionLedger(lpath, signer=signer)
            rec = ledger.record("agent-1", "click", "tab_1", {"index": 3}, summary="Clicked submit")
            self.assertIn("signature", rec)
            self.assertTrue(ledger.verify_ledger()["valid"])

            # Tamper signature on disk -> must fail cryptographic verification
            tampered = dict(rec)
            tampered["signature"] = "lum-hmac256:bad:0000"
            lpath.write_text(json.dumps(tampered) + "\n", encoding="utf-8")
            self.assertFalse(ledger.verify_ledger()["valid"])

    def test_04_os_crypt_enabled_by_default_in_fork_profile(self) -> None:
        prof = ForkProfile()
        switches = prof.runtime_switches()
        self.assertNotIn("--disable-encryption", switches)
        self.assertNotIn("--disable-machine-id", switches)

        usb_prof = ForkProfile(portable_mode=True, roaming_unencrypted_cookies=True)
        usb_switches = usb_prof.runtime_switches()
        self.assertIn("--disable-encryption", usb_switches)
        self.assertIn("--disable-machine-id", usb_switches)

    def test_05_multiplexed_cdp_pool_concurrent_commands(self) -> None:
        srv = _LocalRFC6455EchoServer()
        try:
            mux = MultiplexedCDPPool(
                ws_url_provider=lambda: srv.ws_url,
                socket_factory=lambda u, t: _RFC6455Socket(u, timeout=t),
            )
            sid = mux.attach_target("tab_a", enable_oopif=False)
            self.assertEqual(sid, "sid_bench_1")

            results: list[dict[str, object]] = []
            errors: list[Exception] = []

            def _worker(n: int) -> None:
                try:
                    out = mux.run_target_commands("tab_a", [("Runtime.evaluate", {"expression": f"{n}+{n}"})])
                    results.append(out[0])
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=_worker, args=(i,)) for i in range(12)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)

            self.assertEqual(errors, [])
            self.assertEqual(len(results), 12)
            self.assertEqual(mux.stats()["reconnects"], 1)  # Single persistent socket!
            mux.close()
        finally:
            srv.close()

    def test_06_axtree_parser_and_shadow_dom_walker(self) -> None:
        sample_ax = [
            {"nodeId": "1", "ignored": True, "role": {"value": "button"}, "name": {"value": "Hidden"}},
            {
                "nodeId": "2",
                "ignored": False,
                "backendDOMNodeId": 42,
                "role": {"value": "button"},
                "name": {"value": "Deploy to Production"},
                "properties": [{"name": "focused", "value": {"value": True}}],
            },
            {
                "nodeId": "3",
                "ignored": False,
                "backendDOMNodeId": 43,
                "role": {"value": "textbox"},
                "name": {"value": "Search repository"},
                "value": {"value": "chromium"},
                "properties": [{"name": "disabled", "value": {"value": False}}],
            },
            {
                "nodeId": "4",
                "ignored": False,
                "backendDOMNodeId": 44,
                "role": {"value": "button"},
                "name": {"value": "Disabled Action"},
                "properties": [{"name": "disabled", "value": {"value": True}}],
            },
        ]
        parsed = parse_ax_tree_nodes(sample_ax)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["backend_node_id"], 42)
        self.assertEqual(parsed[1]["is_input"], True)

        js = build_shadow_piercing_snapshot_js(max_elements=250)
        self.assertIn("host.shadowRoot", js)
        self.assertIn("250", js)

    def test_07_webmcp_runtime_and_mutation_firewall(self) -> None:
        self.assertIn("navigator", WEBMCP_BOOTSTRAP_JS)
        self.assertIn("modelContext", WEBMCP_BOOTSTRAP_JS)
        invoke_js = build_invoke_webmcp_tool_js("search_flights", {"origin": "SYD", "dest": "SFO"})
        self.assertIn("search_flights", invoke_js)
        self.assertIn("'password'", invoke_js)  # Model-blind password + hidden CSRF guard!
        self.assertIn(".includes(ftype)", invoke_js)

        self.assertEqual(classify_mutation_risk("DELETE", "https://api.example.com/users/1"), "HIGH")
        self.assertEqual(classify_mutation_risk("POST", "https://shop.example.com/checkout"), "HIGH")
        self.assertEqual(classify_mutation_risk("POST", "https://api.example.com/comments"), "MEDIUM")
        self.assertEqual(classify_mutation_risk("GET", "https://api.example.com/comments"), "LOW")

        cdp = CDPBridge(port=65529, use_mux=False)
        fw = NetworkMutationFirewall(cdp, redactor=LuminaraRedactor())
        try:
            mut = fw.record_intercepted_mutation(
                request_id="r1",
                session_id="",
                target_id="t1",
                method="POST",
                url="https://api.example.com/billing/charge",
                headers={"Authorization": "Bearer sk-proj-secret1234567890abcdef"},
                post_data='{"amount":500}',
            )
            self.assertEqual(mut["status"], "PAUSED_MUTATION_APPROVAL")
            self.assertEqual(mut["risk_level"], "HIGH")
            self.assertNotIn("sk-proj-secret", json.dumps(mut))
            approved = fw.resolve_mutation(mut["mutation_id"], decision="approve")
            self.assertEqual(approved["status"], "APPROVED")
        finally:
            fw.close()
            cdp.close()

    def test_08_knowledge_graph_fts5_and_tab_hibernation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lum_t100_kg_") as td:
            store = KnowledgeWorkspaceStore(Path(td) / "kg.sqlite3")
            ws = store.upsert_workspace("trading", name="Trading Desk", pinned_urls=["https://example.com"])
            self.assertEqual(ws["workspace_id"], "trading")
            count = store.index_entities(
                workspace_id="trading",
                url="https://quotes.example.com",
                title="NVDA Quote",
                rows=[{"name": "NVDA", "rsi": "64.2", "note": "AI Datacenter Leader"}],
                receipt_id="LUM-1",
            )
            self.assertEqual(count, 1)
            hits = store.search_knowledge("NVDA Datacenter", workspace_id="trading")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["receipt_id"], "LUM-1")

            cdp = CDPBridge(port=65528, use_mux=False)
            mgr = TabLifecycleManager(cdp)
            tabs = [
                {"target_id": "t0", "url": "https://active.example.com"},
                {"target_id": "t1", "url": "https://leased.example.com"},
                {"target_id": "t2", "url": "https://pinned.example.com"},
                {"target_id": "t3", "url": "http://127.0.0.1:8796/workspace"},
                {"target_id": "t4", "url": "https://idle1.example.com"},
                {"target_id": "t5", "url": "https://idle2.example.com"},
            ]
            cdp.leases.acquire("t1", "agent-a")
            mgr.pin_tab("t2", True)
            eligible, protected = mgr.evaluate_candidates(tabs, active_target_id="t0")
            self.assertEqual({e["target_id"] for e in eligible}, {"t4", "t5"})
            self.assertEqual(len(protected), 4)
            cdp.close()

    def test_09_privacy_shield_v3_and_mv3_script_extraction(self) -> None:
        parsed_domains = parse_adblock_domains(["! Comment", "@@||allow.example.com^", "||ads.tracker.io^$third-party", "||beacon.foo.net^"])
        self.assertEqual(parsed_domains, ["ads.tracker.io", "beacon.foo.net"])

        prof = ForkProfile(extra_blocked_domains=["custom-spy.io"])
        rules = compile_dnr_shield_rules(prof, extra_filter_lines=["||extra-ad.net^"])
        self.assertGreaterEqual(len(rules), 65)
        self.assertEqual(rules[1]["action"]["type"], "redirect")

        cleaned = strip_tracking_params_url("https://news.example.com/a?keep=1&utm_source=x&fbclid=y&gclid=z")
        self.assertEqual(cleaned, "https://news.example.com/a?keep=1")

        s1 = derive_farbling_seed(b"k", "https://a.site.com/p1")
        s2 = derive_farbling_seed(b"k", "https://b.site.com/p2")
        s3 = derive_farbling_seed(b"k", "https://other.org/p1")
        self.assertEqual(s1, s2)
        self.assertNotEqual(s1, s3)
        self.assertIn("__luminaraFarbleV3", build_deterministic_farbling_js("tok"))

        html_out, js_out = _extract_inline_script_for_mv3("<html><body><h1>Hi</h1><script>console.log(1);</script></body></html>", "app.js")
        self.assertIn('<script src="app.js" defer></script>', html_out)
        self.assertIn("console.log(1);", js_out)

    def test_10_16_stage_cloud_compiler_upstream_patches_and_updater(self) -> None:
        wf = generate_github_actions_cloud_workflow(ForkProfile())
        self.assertIn("compile-stage-1:", wf)
        self.assertIn("compile-stage-16:", wf)
        self.assertIn("package-signed-release:", wf)

        patch_rep = verify_patches_against_upstream(FORGE_ROOT / "patches" / "luminara", REPO_ROOT / "vendor" / "chromium-src")
        self.assertTrue(patch_rep["ok"])
        self.assertEqual(patch_rep["patch_count"], 4)

        prov = audit_version_provenance(ForkProfile(), REPO_ROOT / "ungoogled-chromium", FORGE_ROOT / "cache")
        self.assertTrue(prov["major_aligned"])

        with tempfile.TemporaryDirectory(prefix="lum_t100_upd_") as td:
            art = Path(td) / "luminara-win64.zip"
            art.write_bytes(b"deterministic-release-artifact")
            art_sha = hashlib.sha256(b"deterministic-release-artifact").hexdigest()
            key = b"release-signing-key-32-bytes-ok!"
            manifest = sign_release_manifest(
                {
                    "version": "3.0.0",
                    "chromium_version": "157.0.8103.78",
                    "artifact_name": art.name,
                    "artifact_sha256": art_sha,
                },
                key,
            )
            res = verify_release_manifest(manifest, signing_key=key, artifact_path=art)
            self.assertTrue(res["valid"])
            self.assertTrue(res["signature_verified"])
            self.assertTrue(res["artifact_verified"])

            bad = verify_release_manifest({**manifest, "version": "9.9.9"}, signing_key=key, artifact_path=art)
            self.assertFalse(bad["valid"])

    def test_11_mcp_v2_server_exposes_all_20_tools_and_100x_benchmarks_pass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lum_t100_srv_") as td:
            runtime = LuminaraAgentRuntime(Path(td), cdp_port=65527)
            runtime.passport_token = ""
            runtime.goals.router.use_env_providers = False
            srv = create_agent_http_server(runtime, host="127.0.0.1", port=0)
            port = srv.server_port
            th = threading.Thread(target=srv.serve_forever, daemon=True)
            th.start()
            try:
                # 1. Verify MCP v2 tools/list exposes all 20 tools including v3.0 100x tools
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/agent/mcp",
                    data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                tool_names = {t["name"] for t in payload["result"]["tools"]}
                self.assertEqual(len(tool_names), len(MCP_TOOLS_SPEC))
                for expected in (
                    "browser_perception_axtree",
                    "webmcp_list_tools",
                    "webmcp_call_tool",
                    "browser_mutation_guard",
                    "browser_workspace",
                    "browser_hibernate_tabs",
                ):
                    self.assertIn(expected, tool_names)

                # 2. Verify status + session-token + workspaces REST routes
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/agent/status", timeout=5.0) as resp:
                    st = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(st["version"], "4.0.0")
                self.assertIn("cdp_mux", st)
                self.assertIn("vault_encryption", st)

                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/agent/workspaces", timeout=5.0) as resp:
                    ws = json.loads(resp.read().decode("utf-8"))
                self.assertGreaterEqual(len(ws["workspaces"]), 3)
            finally:
                srv.shutdown()
                srv.server_close()
                runtime.mutation_firewall.close()
                runtime.cdp.close()

        bench = run_100x_benchmark_suite()
        self.assertTrue(bench["all_passed"], f"100x benchmark failed: {bench}")

    def test_12_security_regressions_passport_token_ast_augassign_and_file_ssrf(self) -> None:
        from forge.cdp_client import CDPError, validate_navigation_url
        from forge.luminara_automation import validate_pipeline_ast

        # 1. Default validate_navigation_url & open_tab block file:// exfiltration unless allow_file=True
        with self.assertRaises(CDPError):
            validate_navigation_url("file:///C:/Windows/win.ini")
        self.assertTrue(validate_navigation_url("file:///C:/Windows/win.ini", allow_file=True).startswith("file:"))

        # 2. AST sandbox blocks AugAssign (**=, <<=, *=) and chained variable multiplication bombs
        for bad_script in (
            "x = 10\nx **= 99999999",
            "x = 1\nx <<= 500",
            "x = 'a'\nx *= 100000000",
            "s = 'a' * 5000 * 5000",
            "a = 'x'\nb = 99999\nc = a * b",
        ):
            with self.assertRaises(ValueError, msg=f"Failed to reject {bad_script!r}"):
                validate_pipeline_ast(bad_script)

        # 3. Updater rejects unsigned manifests by default and supports idempotent re-signing
        unsigned = {
            "version": "3.0.0",
            "chromium_version": "157.0.8103.78",
            "artifact_name": "app.zip",
            "artifact_sha256": "a" * 64,
        }
        self.assertFalse(verify_release_manifest(unsigned)["valid"])
        self.assertTrue(verify_release_manifest(unsigned, allow_unsigned=True)["valid"])
        key = b"K" * 32
        s1 = sign_release_manifest(unsigned, key)
        s2 = sign_release_manifest(s1, key)  # Re-sign existing signed manifest
        self.assertTrue(verify_release_manifest(s2, signing_key=key)["valid"])

        # 4. Passport token (LUMINARA_AGENT_TOKEN) never leaks UI_KEY on public /newtab & accepts lum2.* session tokens
        import os as _os

        with tempfile.TemporaryDirectory(prefix="lum_t100_auth_") as td:
            old_env = _os.environ.get("LUMINARA_AGENT_TOKEN")
            _os.environ["LUMINARA_AGENT_TOKEN"] = "passport-secret-token-999"
            try:
                rt = LuminaraAgentRuntime(Path(td), cdp_port=65526)
                srv = create_agent_http_server(rt, host="127.0.0.1", port=0)
                port = srv.server_port
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/newtab", timeout=5.0) as r_pub:
                        ntp_html = r_pub.read().decode("utf-8")
                    self.assertNotIn(rt.local_ui_key, ntp_html)

                    with self.assertRaises(urllib.error.HTTPError) as unauth_ctx:
                        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/agent/status", timeout=5.0)
                    self.assertEqual(unauth_ctx.exception.code, 401)
                    unauth_ctx.exception.close()

                    eph_tok = rt.signer.issue_token("ui", ttl_sec=60)
                    req_eph = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/agent/status",
                        headers={"X-Luminara-UI-Key": eph_tok},
                    )
                    with urllib.request.urlopen(req_eph, timeout=5.0) as r_ok:
                        self.assertEqual(r_ok.status, 200)
                finally:
                    srv.shutdown()
                    srv.server_close()
                    rt.close()
            finally:
                if old_env is None:
                    _os.environ.pop("LUMINARA_AGENT_TOKEN", None)
                else:
                    _os.environ["LUMINARA_AGENT_TOKEN"] = old_env

    def test_13_live_chromium_e2e_mux_axtree_webmcp_mutation_kg_and_hibernation(self) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import socket
        import subprocess
        import time

        from forge.cdp_client import terminate_browser_process, wait_for_cdp_page_ready
        from forge.verifier_agentic import find_chromium_binary

        chrome_exe = find_chromium_binary(FORGE_ROOT, ForkProfile())
        if chrome_exe is None:
            self.skipTest("Portable chrome.exe not unpacked; skipping live Chromium 100x E2E")

        transfers_received: list[str] = []

        class FixtureHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                html_doc = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Luminara 100x Live E2E</title></head>
<body>
  <h1>Hardware Matrix</h1>
  <table>
    <thead><tr><th>Name</th><th>VRAM</th><th>Price</th></tr></thead>
    <tbody><tr><td>Quantum Blade X1</td><td>24GB</td><td>$1499</td></tr></tbody>
  </table>
  <button id="hwBtn" onclick="window.__hwClicked = (window.__hwClicked || 0) + 1">Click Hardware</button>
  <input id="hwInput" aria-label="Command Input" type="text" />
  <div id="shadowHost"></div>
  <form id="ticketForm" toolname="submit_ticket" tooldescription="Create support ticket" onsubmit="event.preventDefault(); window.__ticketData = this.elements.subject.value;">
    <input name="subject" placeholder="Ticket subject" required />
    <input type="hidden" name="csrf_tok" value="keep_csrf_intact" />
    <button type="submit">Send</button>
  </form>
  <script>
    const host = document.getElementById('shadowHost');
    const sr = host.attachShadow({ mode: 'open' });
    const sb = document.createElement('button');
    sb.id = 'innerShadowBtn';
    sb.textContent = 'Shadow Action';
    sr.appendChild(sb);

    function registerImperative() {
      if (navigator.modelContext && typeof navigator.modelContext.registerTool === 'function') {
        navigator.modelContext.registerTool({
          name: 'calc_total',
          description: 'Sum two numbers',
          inputSchema: { type: 'object', properties: { a: { type: 'number' }, b: { type: 'number' } } },
          execute: async ({ a, b }) => ({ sum: Number(a) + Number(b) })
        });
      }
    }
    registerImperative();
    window.__registerImperative = registerImperative;

    window.__fireTransfer = async () => {
      try {
        const r = await fetch('/api/transfer', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer sk-proj-supersecretkey1234567890abcdef' },
          body: JSON.stringify({ amount: 250 })
        });
        return r.status;
      } catch (_e) {
        return -1;
      }
    };
  </script>
</body></html>"""
                raw = html_doc.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:  # noqa: N802
                ln = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(ln).decode("utf-8", errors="replace")
                transfers_received.append(body)
                out = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        fixture_srv = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        fx_port = fixture_srv.server_port
        threading.Thread(target=fixture_srv.serve_forever, daemon=True).start()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s_cdp:
            s_cdp.bind(("127.0.0.1", 0))
            cdp_port = int(s_cdp.getsockname()[1])

        with tempfile.TemporaryDirectory(prefix="lum_live100x_", ignore_cleanup_errors=True) as td:
            work = Path(td)
            prof_dir = work / "profile"
            prof_dir.mkdir(parents=True, exist_ok=True)
            fx_url = f"http://127.0.0.1:{fx_port}/"

            proc = subprocess.Popen(
                [
                    str(chrome_exe),
                    "--headless=new",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    f"--user-data-dir={prof_dir}",
                    f"--remote-debugging-port={cdp_port}",
                    "--remote-allow-origins=*",
                    "--window-size=1280,900",
                    fx_url,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            rt = LuminaraAgentRuntime(work / "state", cdp_port=cdp_port)
            rt.passport_token = ""
            rt.goals.router.use_env_providers = False
            ag_srv = create_agent_http_server(rt, host="127.0.0.1", port=0)
            ag_port = ag_srv.server_port
            threading.Thread(target=ag_srv.serve_forever, daemon=True).start()

            try:
                self.assertTrue(wait_for_cdp_page_ready(rt.cdp, "Boolean(document.getElementById('hwBtn'))", timeout=20.0))

                # 1. Verify MultiplexedCDPPool is active on real Chromium 157!
                self.assertTrue(rt.cdp.mux_stats()["connected"])
                tabs = rt.cdp.list_tabs()
                main_tid = tabs[0]["target_id"]

                # 2. Verify Blink AXTree + Shadow-DOM piercing + Hardware compositor click & type!
                ax_res = rt.dispatch_tool("browser_perception_axtree", {"action": "snapshot", "target_id": main_tid})
                perc = ax_res["perception"]
                self.assertGreaterEqual(perc["ax_interactive_count"], 3)
                self.assertGreaterEqual(perc["shadow_hosts_pierced"], 1)
                btn_node = next(e for e in perc["elements"] if "Click Hardware" in e.get("name", ""))
                rt.dispatch_tool(
                    "browser_perception_axtree",
                    {"action": "hardware_click", "target_id": main_tid, "backend_node_id": btn_node["backend_node_id"]},
                )
                self.assertEqual(rt.cdp.evaluate_js(main_tid, "window.__hwClicked"), 1)

                inp_node = next(e for e in perc["elements"] if e.get("is_input"))
                rt.dispatch_tool(
                    "browser_perception_axtree",
                    {"action": "hardware_type", "target_id": main_tid, "backend_node_id": inp_node["backend_node_id"], "text": "Apex100x"},
                )
                self.assertEqual(rt.cdp.evaluate_js(main_tid, "document.getElementById('hwInput').value"), "Apex100x")

                # 3. Verify W3C WebMCP discovery & execution (imperative + declarative form + hidden CSRF protection!)
                rt.webmcp.list_page_tools(main_tid)
                rt.cdp.evaluate_js(main_tid, "window.__registerImperative()")
                wm_list = rt.dispatch_tool("webmcp_list_tools", {"target_id": main_tid})
                wm_names = {t["name"] for t in wm_list["tools"]}
                self.assertIn("calc_total", wm_names)
                self.assertIn("submit_ticket", wm_names)

                imp_call = rt.dispatch_tool(
                    "webmcp_call_tool",
                    {"target_id": main_tid, "tool_name": "calc_total", "arguments": {"a": 40, "b": 2}},
                )
                self.assertEqual(imp_call["result"]["sum"], 42)

                decl_call = rt.dispatch_tool(
                    "webmcp_call_tool",
                    {
                        "target_id": main_tid,
                        "tool_name": "submit_ticket",
                        "arguments": {"subject": "WebMCP Works", "csrf_tok": "hacked"},
                    },
                )
                self.assertTrue(decl_call["ok"])
                self.assertEqual(rt.cdp.evaluate_js(main_tid, "window.__ticketData"), "WebMCP Works")
                self.assertEqual(
                    rt.cdp.evaluate_js(main_tid, "document.querySelector('[name=csrf_tok]').value"),
                    "keep_csrf_intact",
                )

                # 4. Verify live Fetch.enable Network Mutation Firewall (intercept POST -> scrub secret -> reject -> approve!)
                rt.dispatch_tool("browser_mutation_guard", {"action": "enable", "target_id": main_tid})
                rt.cdp.evaluate_js(main_tid, "window.__txPromise = window.__fireTransfer(); true;", await_promise=False)
                pending = []
                for _ in range(30):
                    pending = rt.mutation_firewall.list_pending(main_tid)
                    if pending:
                        break
                    time.sleep(0.05)
                self.assertEqual(len(pending), 1)
                self.assertNotIn("sk-proj-supersecretkey", json.dumps(pending[0]))
                rt.dispatch_tool("browser_mutation_guard", {"action": "reject", "mutation_id": pending[0]["mutation_id"]})
                self.assertEqual(rt.cdp.evaluate_js(main_tid, "window.__txPromise", await_promise=True), -1)
                self.assertEqual(len(transfers_received), 0)

                rt.cdp.evaluate_js(main_tid, "window.__txPromise2 = window.__fireTransfer(); true;", await_promise=False)
                for _ in range(30):
                    pending = rt.mutation_firewall.list_pending(main_tid)
                    if pending:
                        break
                    time.sleep(0.05)
                self.assertEqual(len(pending), 1)
                rt.dispatch_tool("browser_mutation_guard", {"action": "approve", "mutation_id": pending[0]["mutation_id"]})
                self.assertEqual(rt.cdp.evaluate_js(main_tid, "window.__txPromise2", await_promise=True), 200)
                self.assertEqual(len(transfers_received), 1)
                rt.dispatch_tool("browser_mutation_guard", {"action": "disable", "target_id": main_tid})

                # 5. Verify Structured Extraction auto-indexes into SQLite FTS5 Knowledge Graph!
                ext_out = rt.dispatch_tool("browser_extract_structured", {"target_id": main_tid, "workspace_id": "research"})
                self.assertGreaterEqual(len(ext_out["extracted"]["rows"]), 1)
                kg_hits = rt.dispatch_tool("browser_workspace", {"action": "search", "workspace_id": "research", "query": "Quantum 24GB"})
                self.assertGreaterEqual(kg_hits["count"], 1)

                # 6. Verify Background Tab Hibernation on live Chromium 157 + luminara_ctl CLI!
                bg_tab = rt.dispatch_tool("browser_open_tab", {"url": fx_url, "background": True})["tab"]
                hib = rt.dispatch_tool("browser_hibernate_tabs", {"action": "hibernate", "target_id": main_tid})
                self.assertIn(bg_tab["target_id"], hib["frozen_target_ids"])
                woken = rt.dispatch_tool("browser_hibernate_tabs", {"action": "wake", "target_id": bg_tab["target_id"]})
                self.assertEqual(woken["state"], "active")

                # 7. Verify luminara_ctl CLI subcommands against live daemon!
                ctl_script = REPO_ROOT / "skills" / "luminara-browser" / "scripts" / "luminara_ctl.py"
                import os as _os
                ctl_env = {**_os.environ, "LUMINARA_AGENT_URL": f"http://127.0.0.1:{ag_port}", "LUMINARA_AGENT_TOKEN": ""}
                for ctl_args in (
                    ["status"],
                    ["webmcp-list", "--target-id", main_tid],
                    ["mutations", "--action", "status"],
                    ["workspaces", "--action", "search", "--workspace-id", "research", "--query", "Quantum"],
                    ["verify-ledger"],
                ):
                    cp = subprocess.run(
                        [sys.executable, str(ctl_script), *ctl_args],
                        env=ctl_env,
                        capture_output=True,
                        text=True,
                        timeout=15,
                        check=False,
                    )
                    self.assertEqual(cp.returncode, 0, f"luminara_ctl {ctl_args} failed: {cp.stdout} {cp.stderr}")
            finally:
                ag_srv.shutdown()
                ag_srv.server_close()
                rt.close()
                terminate_browser_process(proc)
                fixture_srv.shutdown()
                fixture_srv.server_close()

    def test_14_adversarial_loop_regressions_studio_sig_strip_leases_and_cli(self) -> None:
        import inspect
        import subprocess
        from forge import studio
        from forge.luminara_automation import PlaybookMemory
        from forge.webmcp import build_invoke_webmcp_tool_js

        # 1. Studio _port_is_listening contract & time import check
        self.assertTrue(hasattr(studio, "time"))
        sig_params = list(inspect.signature(studio._port_is_listening).parameters)
        self.assertEqual(sig_params, ["port"])
        self.assertFalse(studio._port_is_listening(65531))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 2. ActionLedger rejects HMAC signature-stripping downgrade
            signer = EphemeralSessionSigner(b"k" * 32)
            with self.assertRaises(ValueError):
                signer.issue_token(scope="bad.scope")
            ledger_file = root / "ledger.jsonl"
            ledger = ActionLedger(ledger_file, signer=signer)
            rec = ledger.record("agent-1", "click", "tab-1", {"index": 1}, summary="Signed step")
            self.assertIn("signature", rec)
            self.assertTrue(ledger.verify_ledger()["valid"])
            # Strip signature while keeping sha256 valid -> must FAIL verification!
            stripped = dict(rec)
            stripped.pop("signature", None)
            ledger_file.write_text(json.dumps(stripped) + "\n", encoding="utf-8")
            ver = ledger.verify_ledger()
            self.assertFalse(ver["valid"])
            self.assertTrue(any("signature" in e for e in ver["errors"]))

            # 3. Domainless PlaybookMemory.match_playbook("", goal) matches HTTPS origin playbook
            pbm = PlaybookMemory(root / "playbooks")
            pbm.record_successful_run(
                url="https://portal.example.com/billing",
                goal="Export monthly billing CSV",
                steps=[{"action": "click", "selector": "#export", "tag": "button", "target_text": "Export"}],
            )
            matched = pbm.match_playbook("", "Export monthly billing CSV")
            self.assertIsNotNone(matched)
            self.assertEqual(matched["domain"], "portal.example.com")  # type: ignore[index]

            # 4. Malformed bulk urls string rejection, null integer handling, & TabLease on 100x tools
            rt = LuminaraAgentRuntime(root, cdp_port=65532)
            rt.passport_token = ""
            rt.goals.router.use_env_providers = False
            try:
                with self.assertRaises(ValueError):
                    rt.dispatch_tool("browser_bulk_extract", {"urls": "https://example.com"})
                with self.assertRaises(ValueError):
                    rt.dispatch_tool("browser_workspace", {"action": "index", "rows": "not-a-list"})
                ws_null_lim = rt.dispatch_tool("browser_workspace", {"action": "search", "query": "none", "limit": None})
                self.assertEqual(ws_null_lim["count"], 0)

                # Lease collision check on hardware_click / webmcp_call_tool
                rt.cdp._pick_target_id = lambda tid=None: "tab-leased"  # type: ignore[method-assign]
                rt.cdp.leases.acquire("tab-leased", "agent-owner", ttl_sec=60.0)
                from forge.cdp_client import CDPError
                with self.assertRaises(CDPError) as ctx_hw:
                    rt.dispatch_tool(
                        "browser_perception_axtree",
                        {"action": "hardware_click", "target_id": "tab-leased", "x": 10, "y": 10, "agent_id": "intruder"},
                    )
                self.assertIn("leased by", str(ctx_hw.exception))
                with self.assertRaises(CDPError) as ctx_wm:
                    rt.dispatch_tool(
                        "webmcp_call_tool",
                        {"tool_name": "t", "target_id": "tab-leased", "agent_id": "intruder"},
                    )
                self.assertIn("leased by", str(ctx_wm.exception))

                # 5. luminara_ctl workspaces --action index --stdin end-to-end
                ag_srv = create_agent_http_server(rt, host="127.0.0.1", port=0)
                ag_port = ag_srv.server_address[1]
                th = threading.Thread(target=ag_srv.serve_forever, daemon=True)
                th.start()
                try:
                    ctl_script = Path(__file__).resolve().parents[2] / "skills" / "luminara-browser" / "scripts" / "luminara_ctl.py"
                    import os as _os
                    cp = subprocess.run(
                        [sys.executable, str(ctl_script), "workspaces", "--action", "index", "--workspace-id", "audit", "--url", "https://example.com", "--title", "Audit", "--stdin"],
                        input='[{"vendor":"Luminara","tier":"Enterprise"}]',
                        env={**_os.environ, "LUMINARA_AGENT_URL": f"http://127.0.0.1:{ag_port}", "LUMINARA_AGENT_TOKEN": ""},
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
                    self.assertEqual(json.loads(cp.stdout)["indexed_count"], 1)
                finally:
                    ag_srv.shutdown()
                    ag_srv.server_close()
            finally:
                rt.close()

        # 6. WebMCP unsafe javascript: form action guard & radio support present
        js_code = build_invoke_webmcp_tool_js("form_tool", {"plan": "pro"})
        self.assertIn("blocked_unsafe_form_action_scheme", js_code)
        self.assertIn('input[type="radio"]', js_code)


if __name__ == "__main__":
    unittest.main()
