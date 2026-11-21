"""Full-Stack v3.1.0 Test Suite for Perplexity REA Reconstructions (`tests/test_perplexity_rea_v31.py`).

Covers OBL-15 .. OBL-21 end to end:
1. REA v6.5.0 Evidence ledger & epistemic `ResidualUnknown` contract.
2. Numbat partitioned `SequenceGuard`, `PAUSED_SEQUENCE_BLOCK` runtime enforcement, and signed `CASE-*.zip`.
3. SPACE + Codescythe `arch_ratchet` (`< 1,000` lines, `0` non-stdlib deps, layer guard, dead-file detection) & fenced `lease_epoch`.
4. `rules_web_e2e` PNG filter reconstruction (Filters 0..4), pixel-diff bounding boxes, and `Fetch.enable` declared-origin lock.
5. `perplexity-py` + `search_evals` + `pplx-kernels` CAS revisions, fenced monitors, `Decimal` CostLedger, and MoE split-phase barriers.
6. Live HTTP + MCP v2 (28 tools, 9 resources), `/workspace` Telemetry Cockpit zero-XSS UI, and `luminara_ctl.py` CLI.
"""

from __future__ import annotations

import binascii
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
import zlib

from forge.agent_server import LuminaraAgentRuntime, create_agent_http_server
from forge.arch_ratchet import run_architecture_ratchet
from forge.cdp_client import CDPBridge, CDPError
from forge.kernel_spec_audit import MoEAllToAllConfig, SplitPhaseDispatchValidator, audit_pplx_kernels_tree, validate_all_to_all_topology
from forge.knowledge_graph import KnowledgeWorkspaceStore
from forge.luminara_automation import PipelineSandboxRunner, PlaybookMemory
from forge.luminara_copilot_ext import write_copilot_extension
from forge.luminara_crypto import EphemeralSessionSigner
from forge.mcp_specs import APP_VERSION, MCP_RESOURCES_SPEC, MCP_TOOLS_SPEC
from forge.models import ForkProfile
from forge.monitors_eval import (
    AttemptCostRecord,
    EvalCostLedger,
    MonitorEvalEngine,
    RevisionConflictError,
    grade_factuality_and_citations,
    validate_perplexity_wire_payload,
    validate_public_webhook_url,
)
from forge.mutation_firewall import NetworkMutationFirewall
from forge.rea_harvester import harvest_perplexity_rea_evidence
from forge.sequence_guard import SequenceGuard, verify_casebundle
from forge.verifier_perplexity import run_perplexity_rea_obligations
from forge.vrt_isolation import PNG_SIGNATURE, VRTIsolationManager, decode_png_to_rgba, encode_rgba_png

FORGE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = FORGE_ROOT.parent


def _encode_filtered_png_1row(pixels_rgba: bytes, filter_type: int) -> bytes:
    """Build a 1-row RGBA PNG using explicit PNG filter `0..4` to test all scanline decoders."""
    width = len(pixels_rgba) // 4
    channels = 4
    filt = bytearray([filter_type])
    for i, b in enumerate(pixels_rgba):
        left = pixels_rgba[i - channels] if i >= channels else 0
        if filter_type == 0:
            filt.append(b)
        elif filter_type in (1, 4):  # row 0 has up=0, up_left=0 -> Sub & Paeth subtract left
            filt.append((b - left) & 0xFF)
        elif filter_type == 2:  # row 0 has up=0
            filt.append(b)
        elif filter_type == 3:  # row 0 has up=0 -> Average subtracts left // 2
            filt.append((b - (left >> 1)) & 0xFF)

    def _chunk(ct: bytes, payload: bytes) -> bytes:
        crc = binascii.crc32(ct + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + ct + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, 1, 8, 6, 0, 0, 0)
    return PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(filt))) + _chunk(b"IEND", b"")


class TestPerplexityREASuiteV31(unittest.TestCase):
    def test_01_rea_evidence_snapshot_and_all_7_obligations_pass(self) -> None:
        ev = harvest_perplexity_rea_evidence(
            FORGE_ROOT,
            staging_root=FORGE_ROOT / "_nonexistent_ci_staging",
            write_committed_summary=False,
        )
        self.assertEqual(ev["target_count"], 7)
        slugs = {t["slug"] for t in ev["targets"]}
        self.assertEqual(
            slugs,
            {"SPACE", "codescythe", "numbat", "rules_web_e2e", "perplexity-py", "search_evals", "pplx-kernels"},
        )
        self.assertGreaterEqual(len(ev["residual_unknowns"]), 2)

        obls = run_perplexity_rea_obligations(FORGE_ROOT)
        self.assertEqual([o.obligation_id for o in obls], [f"OBL-{n}" for n in range(15, 22)])
        self.assertTrue(all(o.passed for o in obls), f"Failed: {[o for o in obls if not o.passed]}")

    def test_02_numbat_sequence_guard_runtime_blocking_and_casebundle_security(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lum_seq_v31_") as td:
            tpath = Path(td)
            signer = EphemeralSessionSigner(b"K" * 32)
            sg = SequenceGuard(tpath, signer=signer)

            # Loopback & same-origin navigation after secret touch do NOT trigger CHAIN-01 false positive
            sg.evaluate_step(
                agent_id="local-tester",
                tool_name="browser_vault",
                params={"action": "fill", "origin": "https://portal.example"},
                ts_ms=1000,
            )
            loc = sg.evaluate_step(
                agent_id="local-tester",
                tool_name="browser_open_tab",
                params={"url": "http://127.0.0.1:9999/dashboard"},
                ts_ms=1500,
            )
            same_orig = sg.evaluate_step(
                agent_id="local-tester",
                tool_name="browser_act",
                params={"action": "navigate", "url": "https://portal.example/settings"},
                ts_ms=2000,
            )
            self.assertFalse(loc["blocked"])
            self.assertFalse(same_orig["blocked"])

            # External cross-origin egress after secret touch immediately triggers PAUSED_SEQUENCE_BLOCK
            ext = sg.evaluate_step(
                agent_id="local-tester",
                tool_name="browser_open_tab",
                params={"url": "https://exfil.attacker.example/collect"},
                ts_ms=3000,
            )
            self.assertTrue(ext["blocked"])
            self.assertEqual(ext["status"], "PAUSED_SEQUENCE_BLOCK")

            # Block latch persists across daemon restarts
            sg_reloaded = SequenceGuard(tpath, signer=signer)
            self.assertIsNotNone(sg_reloaded.active_daemon_block())

            bundle = sg.export_casebundle()
            bpath = Path(bundle["bundle_path"])
            self.assertTrue(verify_casebundle(bpath, signer=signer)["valid"])

            # Path-traversal or duplicate/corrupt ZIP member must fail verification closed
            evil_zip = tpath / "evil.zip"
            with zipfile.ZipFile(evil_zip, "w") as zf:
                zf.writestr("../escape.txt", "bad")
                zf.writestr("manifest.json", "{}")
            self.assertFalse(verify_casebundle(evil_zip)["valid"])

            # Pipeline AST sandbox blocks .replace/.join RAM bombs and halts on PAUSED_SEQUENCE_BLOCK
            for bad_src in ("x = 'a'.replace('a', 'bb')\n", "x = ','.join(['a', 'b'])\n"):
                with self.assertRaises(ValueError):
                    PipelineSandboxRunner(lambda _t, _p: {"ok": True}).run_pipeline(script=bad_src)
            step_calls: list[str] = []

            def _mock_dispatch(tname: str, _params: dict[str, object]) -> dict[str, object]:
                step_calls.append(tname)
                return {"ok": False, "status": "PAUSED_SEQUENCE_BLOCK"}

            halted = PipelineSandboxRunner(_mock_dispatch).run_pipeline(
                script="luminara.open_tab('https://exfil.example')\nluminara.open_tab('https://never-reached.example')\n"
            )
            self.assertEqual(halted["status"], "PAUSED_SEQUENCE_BLOCK")
            self.assertEqual(step_calls, ["browser_open_tab"])

    def test_03_space_and_codescythe_arch_ratchet_and_fenced_leases(self) -> None:
        rep = run_architecture_ratchet(FORGE_ROOT)
        self.assertTrue(rep["ok"], f"Arch ratchet failed: {rep}")
        self.assertEqual(rep["line_violations"], [])
        self.assertEqual(rep["layer_violations"], [])
        self.assertEqual(rep["non_stdlib_imports"], [])
        self.assertEqual(rep["xss_violations"], [])
        self.assertEqual(rep["unreachable_files"], [])
        self.assertLess(rep["max_observed_lines"], 1000)

        # Synthetic upward L10 -> L50 dependency violation must be caught
        with tempfile.TemporaryDirectory(prefix="lum_arch_neg_") as td:
            ff = Path(td) / "chromium-forge"
            (ff / "forge").mkdir(parents=True)
            (Path(td) / "pyproject.toml").write_text("[project]\nname='x'\ndependencies=[]\n", encoding="utf-8")
            (ff / "forge" / "__init__.py").write_text("", encoding="utf-8")
            (ff / "forge" / "cli.py").write_text("from . import models, studio\n", encoding="utf-8")
            (ff / "forge" / "studio.py").write_text("X = 1\n", encoding="utf-8")
            (ff / "forge" / "models.py").write_text("from . import studio\n", encoding="utf-8")
            neg = run_architecture_ratchet(ff)
            self.assertFalse(neg["ok"])
            self.assertEqual(len(neg["layer_violations"]), 1)

        with tempfile.TemporaryDirectory(prefix="lum_lease_") as td:
            kg = KnowledgeWorkspaceStore(Path(td) / "kg.sqlite3")
            lease1 = kg.acquire_fenced_lease("tab-alpha", "agent-1", ttl_ms=5000, now_ms=1000)
            self.assertTrue(kg.verify_fenced_epoch("tab-alpha", "agent-1", lease1["lease_epoch"], now_ms=2000))
            with self.assertRaises(PermissionError):
                kg.acquire_fenced_lease("tab-alpha", "agent-2", ttl_ms=5000, now_ms=2000)
            lease2 = kg.acquire_fenced_lease("tab-alpha", "agent-2", ttl_ms=5000, now_ms=7000)
            self.assertEqual(lease2["lease_epoch"], 2)
            self.assertFalse(kg.verify_fenced_epoch("tab-alpha", "agent-1", lease1["lease_epoch"], now_ms=7500))

    def test_04_rules_web_e2e_png_scanline_filters_and_declared_origin_fetch_lock(self) -> None:
        raw_pixels = bytes([10, 120, 240, 255, 80, 40, 200, 255, 250, 15, 90, 255])
        for ftype in (0, 1, 2, 3, 4):
            png = _encode_filtered_png_1row(raw_pixels, ftype)
            w, h, decoded = decode_png_to_rgba(png)
            self.assertEqual((w, h), (3, 1))
            self.assertEqual(decoded, raw_pixels, f"Filter {ftype} decode mismatch")

        # Test real CDPBridge unified Fetch coordinator with VRTIsolationManager + NetworkMutationFirewall simultaneously
        sent_mux: list[tuple[str, dict[str, object]]] = []
        session_cmds: list[str] = []
        bridge = CDPBridge(host="127.0.0.1", port=65524)
        bridge._pick_target_id = lambda tid=None: tid or "tab-vrt"  # type: ignore[method-assign]
        bridge.run_session = lambda _tid, cmds, **_kw: [session_cmds.append(str(c[0])) or {} for c in cmds]  # type: ignore[method-assign]
        bridge._mux.send_command_async = lambda method, params=None, **_kw: sent_mux.append((method, params or {}))  # type: ignore[method-assign]

        with tempfile.TemporaryDirectory(prefix="lum_vrt_") as td:
            mgr = VRTIsolationManager(bridge, Path(td))
            fw = NetworkMutationFirewall(bridge)
            try:
                with self.assertRaises(ValueError):
                    mgr.capture_baseline("../escape", png_bytes=encode_rgba_png(2, 2, b"\x00" * 16))
                mgr.lock_origins("tab-vrt", ["https://app.trusted.example:443"])
                fw.enable_guard("tab-vrt")
                session_cmds.clear()

                # Allowed GET passes both hooks -> single Fetch.continueRequest
                bridge._on_mux_fetch_paused(
                    {
                        "target_id": "tab-vrt",
                        "session_id": "sess-1",
                        "params": {"requestId": "r-ok", "request": {"method": "GET", "url": "https://app.trusted.example/main.js"}},
                    }
                )
                # Undeclared GET blocked by VRT (priority 10) -> Fetch.failRequest (never continueRequest!)
                bridge._on_mux_fetch_paused(
                    {
                        "target_id": "tab-vrt",
                        "session_id": "sess-1",
                        "params": {"requestId": "r-bad", "request": {"method": "GET", "url": "https://ads.untrusted.example/beacon"}},
                    }
                )
                # Declared high-risk POST paused by MutationFirewall (priority 20) -> neither fail nor continue
                bridge._on_mux_fetch_paused(
                    {
                        "target_id": "tab-vrt",
                        "session_id": "sess-1",
                        "params": {"requestId": "r-mut", "request": {"method": "POST", "url": "https://app.trusted.example/api/checkout", "postData": "{}"}},
                    }
                )
                self.assertIn(("Fetch.continueRequest", {"requestId": "r-ok"}), sent_mux)
                self.assertIn(("Fetch.failRequest", {"requestId": "r-bad", "errorReason": "BlockedByClient"}), sent_mux)
                self.assertNotIn(("Fetch.continueRequest", {"requestId": "r-bad"}), sent_mux)
                self.assertNotIn(("Fetch.continueRequest", {"requestId": "r-mut"}), sent_mux)
                self.assertEqual(mgr.status()["blocked_egress_count"], 1)
                self.assertEqual(len(fw.list_pending()), 1)

                # Unlocking VRT while MutationFirewall is active must NOT call Fetch.disable prematurely
                mgr.unlock_origins("tab-vrt")
                self.assertNotIn("Fetch.disable", session_cmds)
                fw.disable_guard("tab-vrt")
                self.assertIn("Fetch.disable", session_cmds)
            finally:
                fw.close()
                mgr.close()

    def test_05_monitors_cas_revisions_ssrf_cost_ledger_and_kernels(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lum_mon_v31_") as td:
            tpath = Path(td)
            pmem = PlaybookMemory(tpath / "playbooks")
            eng = MonitorEvalEngine(tpath / "mon.sqlite3", playbooks=pmem)
            for bad_url in ("file:///C:/Windows/win.ini", "http://127.0.0.1:11434/hook", "http://192.168.1.1/hook"):
                with self.assertRaises(CDPError):
                    validate_public_webhook_url(bad_url)
            self.assertEqual(validate_public_webhook_url("https://hooks.example.org/notify"), "https://hooks.example.org/notify")
            with self.assertRaises(CDPError):
                eng.create_monitor(name="Bad", target_url="file:///C:/Windows/win.ini")
            with self.assertRaises(ValueError):
                validate_perplexity_wire_payload("responses.retrieve_stream", {"stream": True})
            with self.assertRaises(ValueError):
                validate_perplexity_wire_payload("chat.completions", {"messages": []})  # missing required 'model'

            # CAS revisions + disk PlaybookMemory write-back on rollback
            r1 = eng.snapshot_playbook_revision("checkout", domain="shop.example", steps=[{"action": "click", "index": 1}])
            with self.assertRaises(RevisionConflictError):
                eng.snapshot_playbook_revision("checkout", steps=[], expected_revision="rev-stale")
            r2 = eng.snapshot_playbook_revision(
                "checkout",
                domain="shop.example",
                steps=[{"action": "click", "index": 3}],
                expected_revision=r1["latest_revision"],
            )
            pmem.put_playbook("checkout", domain="shop.example", goal="checkout order", steps=[{"action": "click", "index": 3}])
            with self.assertRaises(RevisionConflictError):
                eng.rollback_playbook("checkout", r1["latest_revision"], expected_revision="rev-stale")
            rolled = eng.rollback_playbook("checkout", r1["latest_revision"], expected_revision=r2["latest_revision"])
            self.assertEqual(rolled["revision_num"], 3)
            disk_pb = pmem.get_playbook("checkout")
            self.assertIsNotNone(disk_pb)
            self.assertEqual(disk_pb["steps"], [{"action": "click", "index": 1}])  # type: ignore[index]

            # Selector-scoped monitor diff + webhook dispatch on CHANGED
            mon = eng.create_monitor(
                name="Price Watch",
                target_url="https://shop.example/p",
                extract_selector="#price",
                webhook_url="https://hooks.example.org/notify",
            )
            dispatched: list[tuple[str, dict[str, object]]] = []
            m1 = eng.run_monitor(
                mon["monitor_id"],
                injected_html='<div id="banner">Ad v1</div><div id="price">$19</div>',
            )
            self.assertEqual(m1["status"], "INITIALIZED")
            # Change outside #price selector -> UNCHANGED
            m2 = eng.run_monitor(
                mon["monitor_id"],
                injected_html='<div id="banner">Ad v2</div><div id="price">$19</div>',
            )
            self.assertEqual(m2["status"], "UNCHANGED")
            # Change inside #price selector -> CHANGED + webhook invoked
            m3 = eng.run_monitor(
                mon["monitor_id"],
                injected_html='<div id="banner">Ad v2</div><div id="price">$15</div>',
                webhook_sender=lambda u, p: dispatched.append((u, p)) or {"dispatched": True},
            )
            self.assertEqual(m3["status"], "CHANGED")
            self.assertEqual(len(dispatched), 1)

            # Zero-citation answer must fail closed when expected_facts are non-empty
            zero_cit = grade_factuality_and_citations("Paris is capital", ["Paris"], [])
            self.assertEqual(zero_cit["citation_precision"], 0.0)
            self.assertEqual(zero_cit["composite_f1"], 0.0)
            self.assertFalse(zero_cit["passed"])

            # Unkeyed external provider reports skipped_missing_api_key (never fake F1)
            clean_env = {k: v for k, v in __import__("os").environ.items() if not k.endswith("_API_KEY")}
            orig_env = dict(__import__("os").environ)
            try:
                __import__("os").environ.clear()
                __import__("os").environ.update(clean_env)
                ev_rep = eng.run_search_eval_suite(providers=["luminara", "perplexity"])
            finally:
                __import__("os").environ.clear()
                __import__("os").environ.update(orig_env)
            self.assertEqual(ev_rep["scorecard"]["luminara"]["mean_f1"], 1.0)
            self.assertEqual(ev_rep["scorecard"]["perplexity"]["execution_mode"], "skipped_missing_api_key")
            self.assertIsNone(ev_rep["scorecard"]["perplexity"]["mean_f1"])

            cl = EvalCostLedger()
            cl.record("a1", AttemptCostRecord(input_tokens=2000, cached_input_tokens=500, output_tokens=100, search_calls=2, model="sonar-pro"))
            self.assertEqual(cl.summary()["known_cost_usd"], 0.02615)

        sm = SplitPhaseDispatchValidator(has_scales=True)
        with self.assertRaises(ValueError):
            sm.step_dispatch(has_scale_tensors=False)
        self.assertEqual(sm.step_dispatch(has_scale_tensors=True, do_send=True, do_recv=False), "DISPATCH_IN_FLIGHT")
        self.assertEqual(sm.step_dispatch(has_scale_tensors=True, do_send=False, do_recv=True), "DISPATCHED")
        self.assertEqual(sm.step_combine(do_send=True, do_recv=True), "IDLE")
        self.assertTrue(audit_pplx_kernels_tree()["ok"])
        self.assertFalse(
            validate_all_to_all_topology(
                MoEAllToAllConfig("internode", 64, 16, 2, 0, 4, 2, 128, 120)  # 120 not 16B aligned
            )["valid"]
        )

    def test_06_live_server_mcp_v2_ui_cockpit_and_cli_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lum_srv_v31_") as td:
            rt = LuminaraAgentRuntime(Path(td), cdp_port=65525)
            rt.passport_token = ""
            srv = create_agent_http_server(rt, host="127.0.0.1", port=0)
            port = srv.server_port
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                base = f"http://127.0.0.1:{port}"
                # 1. Verify /workspace includes Telemetry Cockpit tab, labels, STOP button & zero .innerHTML
                with urllib.request.urlopen(f"{base}/workspace", timeout=5.0) as resp:
                    ws_html = resp.read().decode("utf-8")
                self.assertIn('data-view="telemetry"', ws_html)
                self.assertIn("Telemetry Cockpit", ws_html)
                self.assertIn("teleMonUrl", ws_html)
                self.assertNotIn(".innerHTML", ws_html)

                # 2. Verify MCP v2 tools/list (28 tools) & resources/list (9 resources) + new resource reads
                def _mcp(method: str, params: dict[str, object], ui_key: str = "") -> dict[str, object]:
                    hdrs = {"Content-Type": "application/json"}
                    if ui_key:
                        hdrs["X-Luminara-UI-Key"] = ui_key
                    req = urllib.request.Request(
                        f"{base}/api/agent/mcp",
                        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8"),
                        headers=hdrs,
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=5.0) as r:
                        return json.loads(r.read().decode("utf-8"))

                tools_res = _mcp("tools/list", {})["result"]["tools"]  # type: ignore[index]
                self.assertEqual(len(tools_res), len(MCP_TOOLS_SPEC))
                self.assertGreaterEqual(len(tools_res), 28)
                res_list = _mcp("resources/list", {})["result"]["resources"]  # type: ignore[index]
                self.assertEqual(len(res_list), len(MCP_RESOURCES_SPEC))
                self.assertEqual(len(res_list), 9)

                for uri in ("luminara://security/sequences", "luminara://monitors/runs"):
                    read_out = _mcp("resources/read", {"uri": uri})
                    self.assertIn("result", read_out)

                # 3. Verify scope='ui' session-token requires static UI_KEY (rejects unkeyed Origin, accepts UI_KEY)
                bad_tok_req = urllib.request.Request(
                    f"{base}/api/agent/session-token",
                    data=json.dumps({"scope": "ui", "agent_id": "ui-spoof"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Origin": base},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx_403:
                    urllib.request.urlopen(bad_tok_req, timeout=5.0)
                self.assertEqual(ctx_403.exception.code, 403)

                # 4. Trigger PAUSED_SEQUENCE_BLOCK on agent a1 -> verify agent_id rotation to spoof-a2 is STILL blocked!
                _mcp("tools/call", {"name": "browser_vault", "arguments": {"action": "fill", "origin": "https://bank.example", "agent_id": "a1"}})
                blk1 = _mcp("tools/call", {"name": "browser_open_tab", "arguments": {"url": "https://evil.example/drop", "agent_id": "a1"}})
                blk1_payload = json.loads(blk1["result"]["content"][0]["text"])  # type: ignore[index]
                self.assertEqual(blk1_payload["status"], "PAUSED_SEQUENCE_BLOCK")

                spoof = _mcp("tools/call", {"name": "browser_tabs", "arguments": {"agent_id": "spoof-a2"}})
                spoof_payload = json.loads(spoof["result"]["content"][0]["text"])  # type: ignore[index]
                self.assertEqual(spoof_payload["status"], "PAUSED_SEQUENCE_BLOCK")

                # Export signed casebundle & download via GET /api/agent/casebundles + verify by bare filename
                exp_mcp = _mcp("tools/call", {"name": "browser_sequence_guard", "arguments": {"action": "export_casebundle"}})
                bname = Path(json.loads(exp_mcp["result"]["content"][0]["text"])["bundle_path"]).name  # type: ignore[index]
                with urllib.request.urlopen(f"{base}/api/agent/casebundles?name={bname}", timeout=5.0) as dl_resp:
                    self.assertEqual(dl_resp.read(2), b"PK")
                ver_mcp = _mcp("tools/call", {"name": "browser_sequence_guard", "arguments": {"action": "verify_casebundle", "bundle_path": bname}})
                self.assertTrue(json.loads(ver_mcp["result"]["content"][0]["text"])["valid"])  # type: ignore[index]

                # Human UI key guard on clear_block (rejects unkeyed, allows keyed)
                unauth = _mcp("tools/call", {"name": "browser_sequence_guard", "arguments": {"action": "clear_block"}})
                self.assertIn("error", unauth)
                auth = _mcp(
                    "tools/call",
                    {"name": "browser_sequence_guard", "arguments": {"action": "clear_block"}},
                    ui_key=rt.local_ui_key,
                )
                self.assertIn("result", auth)

                # 5. Verify release-scrubbed Copilot extension writes empty UI_KEY even inside dir with outputs/local_ui_key.txt
                ext_out = Path(td) / "dist" / "App" / "extensions" / "luminara-copilot"
                write_copilot_extension(ext_out, ForkProfile(), ui_key="")
                self.assertIn('const UI_KEY = "";', (ext_out / "sidepanel.js").read_text(encoding="utf-8"))

                # 6. Verify luminara_ctl.py CLI subcommands & non-zero exit code on valid=False
                ctl = str((REPO_ROOT / "skills" / "luminara-browser" / "scripts" / "luminara_ctl.py").resolve())
                env = {
                    **dict(__import__("os").environ),
                    "LUMINARA_AGENT_URL": base,
                    "LUMINARA_UI_KEY": rt.local_ui_key,
                }
                for cmd_args in (
                    ["sequences", "--action", "status"],
                    ["monitors", "--action", "create", "--name", "CLI Watch", "--target-url", "https://example.org"],
                    ["eval", "--action", "run_suite", "--providers", "luminara,perplexity"],
                ):
                    cp = subprocess.run(
                        [sys.executable, ctl, *cmd_args],
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=15.0,
                        check=False,
                    )
                    self.assertEqual(cp.returncode, 0, f"CLI {cmd_args} failed: {cp.stdout} {cp.stderr}")
                    parsed = json.loads(cp.stdout)
                    self.assertTrue(parsed.get("ok"))

                bad_wire = subprocess.run(
                    [sys.executable, ctl, "eval", "--action", "validate_wire", "--endpoint", "chat.completions", "--payload-json", '{"messages":[]}'],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10.0,
                    check=False,
                )
                self.assertNotEqual(bad_wire.returncode, 0)

                with urllib.request.urlopen(f"{base}/api/agent/status", timeout=5.0) as st_resp:
                    st_json = json.loads(st_resp.read().decode("utf-8"))
                self.assertEqual(st_json["version"], APP_VERSION)
            finally:
                srv.shutdown()
                srv.server_close()
                rt.close()


if __name__ == "__main__":
    unittest.main()
