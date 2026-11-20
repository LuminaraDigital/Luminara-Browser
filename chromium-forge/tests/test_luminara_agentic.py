"""Automated REA Phase 2 Test Suite (`OBL-08` .. `OBL-14`) for Luminara Browser (`tests/test_luminara_agentic.py`)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import time
import unittest

from forge.agent_engine import ActionLedger, AgentGoalRunner, PerDomainThrottle
from forge.cdp_client import CDPError, TabLeaseManager
from forge.extractor import (
    classify_attribute_widget,
    extract_structured_page,
    format_extracted_rows,
    synthesize_generative_ui,
)
from forge.luminara_ui import (
    build_luminara_newtab_html,
    build_luminara_workspace_html,
    write_copilot_extension,
)
from forge.models import ForkProfile
from forge.verifier import run_rea_verification_suite

FORGE_ROOT = Path(__file__).resolve().parent.parent
STUDIO_ROOT = FORGE_ROOT.parent
CORE_REPO = STUDIO_ROOT / "ungoogled-chromium"
WIN_REPO = STUDIO_ROOT / "ungoogled-chromium-windows"


class TestLuminaraAgenticObligations(unittest.TestCase):
    def test_obl08_luminara_workspace_pages_and_mv3_copilot(self) -> None:
        prof = ForkProfile()
        self.assertEqual(prof.brand_name, "Luminara Browser")
        self.assertEqual(prof.slug, "luminara-browser")

        nt = build_luminara_newtab_html(prof, "file:///workspace.html")
        ws = build_luminara_workspace_html(prof, "file:///newtab.html")
        self.assertIn("luminara_browser:todos", nt)
        self.assertIn("luminara_browser:settings", nt)
        self.assertIn("PAUSED_HUMAN_HANDOFF", nt)
        self.assertIn("luminara_browser:command_history", ws)
        self.assertIn("MAX_HISTORY = 50", ws)

        with tempfile.TemporaryDirectory() as tmp:
            cop = Path(tmp) / "copilot"
            write_copilot_extension(cop, prof, "file:///workspace.html")
            manifest = json.loads((cop / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["manifest_version"], 3)
            self.assertIn("sidePanel", manifest["permissions"])
            self.assertTrue((cop / "sidepanel.html").exists())
            self.assertTrue((cop / "sidepanel.js").exists())

    def test_obl09_tab_lease_collision_and_human_override(self) -> None:
        mgr = TabLeaseManager()
        mgr.acquire("tab-1", agent_id="luminara-worker-a", ttl_sec=60.0)
        with self.assertRaises(CDPError):
            mgr.acquire("tab-1", agent_id="luminara-worker-b", ttl_sec=60.0)
        # Same agent re-acquiring refreshes cleanly
        mgr.acquire("tab-1", agent_id="luminara-worker-a", ttl_sec=60.0)
        # Human takeover immediately preempts active lease
        mgr.force_human_override("tab-1")
        self.assertIsNone(mgr.get_active("tab-1"))

    def test_obl11_untrusted_dom_framing_and_heuristic_planner(self) -> None:
        snap = {
            "url": "https://example.com",
            "title": "Example",
            "elements": [
                {"index": 1, "tag": "input", "role": "textbox", "text": "", "is_input": True},
                {"index": 2, "tag": "button", "role": "button", "text": "Search Catalog", "is_input": False},
            ],
        }
        framed = AgentGoalRunner.wrap_untrusted_dom(snap)
        self.assertTrue(framed.startswith("<untrusted_page_data>"))
        self.assertTrue(framed.endswith("</untrusted_page_data>"))

        step1 = AgentGoalRunner._heuristic_plan("Type 'Luminara' and click Search Catalog", snap, [])
        self.assertEqual(step1["action"], "type")
        self.assertEqual(step1["index"], 1)
        self.assertEqual(step1["text"], "Luminara")

        step2 = AgentGoalRunner._heuristic_plan(
            "Type 'Luminara' and click Search Catalog",
            snap,
            [{"action": "type", "index": 1}],
        )
        self.assertEqual(step2["action"], "click")
        self.assertEqual(step2["index"], 2)

    def test_obl12_per_domain_throttle_parallel_isolation(self) -> None:
        throttle = PerDomainThrottle(initial_delay=0.30)
        self.assertNotEqual(throttle.bucket_lock_id("one.example"), throttle.bucket_lock_id("two.example"))
        # Prime both domains once
        throttle.wait("https://one.example/a")
        throttle.wait("https://two.example/a")

        t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(throttle.wait, "https://one.example/b")
            f2 = pool.submit(throttle.wait, "https://two.example/b")
            f1.result()
            f2.result()
        elapsed = time.monotonic() - t0
        # Global lock bug would take >= 0.60s; per-domain locks run concurrently in ~0.30s
        self.assertLess(elapsed, 0.52)

    def test_obl13_extractor_and_generative_ui_domain_agnostic(self) -> None:
        html_doc = """
        <html><head><title>GPU Matrix</title></head><body>
        <table>
          <tr><th>Model</th><th>Price</th><th>VRAM</th></tr>
          <tr><td>H100</td><td>$28,500</td><td>80</td></tr>
          <tr><td>B200</td><td>$38,000</td><td>192</td></tr>
        </table>
        </body></html>
        """
        ext = extract_structured_page(html_doc, "https://hw.example/gpus")
        self.assertEqual(len(ext["rows"]), 2)
        w_type, num_val, _ = classify_attribute_widget("Price", "$28,500")
        self.assertEqual(w_type, "currency")
        self.assertEqual(num_val, 28500.0)

        gen = synthesize_generative_ui(ext["rows"], title="GPU Matrix")
        self.assertEqual(gen["entity_count"], 2)
        self.assertIsNotNone(gen["summary_bar"])
        self.assertEqual(gen["summary_bar"]["min"], 28500.0)
        self.assertEqual(gen["summary_bar"]["max"], 38000.0)

        md = format_extracted_rows(ext["rows"], "md")
        self.assertIn("| Model | Price | VRAM |", md)

    def test_obl14_verifiable_lum_receipts_and_full_14_obligation_suite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ActionLedger(Path(tmp) / "ledger.jsonl")
            rec = ledger.record("luminara-agent", "snapshot", "tab-9", {"show_badges": True}, summary="Indexed DOM")
            self.assertTrue(rec["receipt_id"].startswith("LUM-"))
            self.assertEqual(len(rec["sha256"]), 64)
            self.assertEqual(len(ledger.recent(5)), 1)

        from forge.verifier_agentic import find_chromium_binary

        prof = ForkProfile()
        report = run_rea_verification_suite(CORE_REPO, WIN_REPO, FORGE_ROOT, prof, write_report=False)
        self.assertEqual(report["total_count"], 14)
        if find_chromium_binary(FORGE_ROOT, prof) is not None:
            self.assertTrue(
                report["all_obligations_passed"],
                f"Failed obligations: {[o for o in report['obligations'] if not o['passed']]}",
            )
        else:
            # Fresh CI clone without gitignored dist/chrome.exe: OBL-01..OBL-08 must all pass (8/8)
            static_obls = report["obligations"][:8]
            self.assertTrue(
                all(o["passed"] for o in static_obls),
                f"Failed static obligations: {[o for o in static_obls if not o['passed']]}",
            )


if __name__ == "__main__":
    unittest.main()
