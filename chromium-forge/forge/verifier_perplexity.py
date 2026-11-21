"""REA Stage 7 Verification for Perplexity AI Suite (`OBL-15` .. `OBL-21`) (`forge/verifier_perplexity.py`).

Verifies every clean-room subsystem reconstructed from the 7 Perplexity AI targets
with deterministic static, cryptographic, pixel-diff, SQLite WAL, and architectural checks.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from .action_ledger import ActionLedger
from .arch_ratchet import run_architecture_ratchet
from .kernel_spec_audit import MoEAllToAllConfig, SplitPhaseDispatchValidator, audit_pplx_kernels_tree, validate_all_to_all_topology
from .knowledge_graph import KnowledgeWorkspaceStore
from .luminara_automation import PlaybookMemory
from .luminara_crypto import EphemeralSessionSigner
from .models import ObligationResult
from .monitors_eval import (
    AttemptCostRecord,
    EvalCostLedger,
    MonitorEvalEngine,
    RevisionConflictError,
    validate_perplexity_wire_payload,
)
from .sequence_guard import SequenceGuard, verify_casebundle
from .vrt_isolation import VRTIsolationManager, compare_png_bytes, encode_rgba_png

ENCODING = "utf-8"


def _load_committed_rea_summary(forge_root: Path) -> dict[str, object]:
    for cand in (
        forge_root / "rea_perplexity_evidence.json",
        Path(__file__).resolve().parent / "rea_evidence" / "rea_perplexity_evidence.json",
    ):
        if cand.is_file():
            return json.loads(cand.read_text(encoding=ENCODING))
    return {"targets": [], "residual_unknowns": []}


def _target_evidence_ids(summary: dict[str, object], slug: str) -> list[str]:
    targets = summary.get("targets")
    if not isinstance(targets, list):
        return []
    for item in targets:
        if isinstance(item, dict) and item.get("slug") == slug:
            evs = item.get("rea_evidence") or []
            return [str(e.get("evidence_id")) for e in evs if isinstance(e, dict) and e.get("evidence_id")]
    return []


def run_perplexity_rea_obligations(forge_root: Path) -> list[ObligationResult]:
    """Execute fail-closed `OBL-15` .. `OBL-21` checks across all 7 Perplexity AI reconstructions."""
    resolved_forge = forge_root.resolve()
    staging_root = resolved_forge.parent / "_rea_targets" / "perplexity"
    rea_summary = _load_committed_rea_summary(resolved_forge)
    out: list[ObligationResult] = []

    # ---- OBL-15: perplexityai/numbat (Sequence Guard + Signed Forensic Casebundle) ----
    numbat_evs = _target_evidence_ids(rea_summary, "numbat")
    with tempfile.TemporaryDirectory(prefix="lum_obl15_") as td:
        signer = EphemeralSessionSigner(b"N" * 32)
        guard = SequenceGuard(Path(td), signer=signer)
        # Disordered timestamps must never fabricate a chain
        guard.evaluate_step(agent_id="a1", tool_name="browser_vault", params={"action": "fill", "origin": "https://bank.example"}, ts_ms=5000)
        dis = guard.evaluate_step(agent_id="a1", tool_name="browser_open_tab", params={"url": "https://evil.example"}, ts_ms=4000)
        # Separate agent partition must not cross-contaminate
        iso = guard.evaluate_step(agent_id="a2", tool_name="browser_open_tab", params={"url": "https://evil.example"}, ts_ms=6000)
        # Ordered cross-origin exfil chain in same partition triggers PAUSED_SEQUENCE_BLOCK
        guard.evaluate_step(agent_id="a3", tool_name="browser_vault", params={"action": "fill", "origin": "https://portal.example"}, ts_ms=10_000)
        blk = guard.evaluate_step(agent_id="a3", tool_name="browser_open_tab", params={"url": "https://drop.attacker.example"}, ts_ms=12_000)
        exp = guard.export_casebundle()
        ver_ok = verify_casebundle(Path(exp["bundle_path"]), signer=signer)
        wrong_signer = EphemeralSessionSigner(b"X" * 32)
        ver_bad = verify_casebundle(Path(exp["bundle_path"]), signer=wrong_signer)
        obl15_ok = (
            bool(numbat_evs)
            and not dis["blocked"]
            and not iso["blocked"]
            and blk["blocked"]
            and blk["status"] == "PAUSED_SEQUENCE_BLOCK"
            and ver_ok["valid"]
            and ver_ok["signature_verified"]
            and not ver_bad["valid"]
        )
    out.append(
        ObligationResult(
            obligation_id="OBL-15",
            title="Numbat Partitioned Sequence Correlator, Pre-Action Chain Block & Signed Casebundle",
            confidence="observed",
            upstream_evidence=f"perplexityai/numbat internal/sequence/sequence.go + casebundle/build.go; REA {','.join(numbat_evs[:2])}",
            passed=obl15_ok,
            details="Verified session partitioning, disordered-clock safety, CHAIN-01 cross-origin block, and LUM-SIG-V2 casebundle verification.",
            metrics={"rea_evidence_count": len(numbat_evs), "casebundle_verified": ver_ok["valid"]},
        )
    )

    # ---- OBL-16: perplexityai/SPACE (Architecture Pattern Ratchet + Monotonic Lease Epoch Fencing) ----
    space_evs = _target_evidence_ids(rea_summary, "SPACE")
    ratchet = run_architecture_ratchet(resolved_forge)
    with tempfile.TemporaryDirectory(prefix="lum_obl16_") as td:
        kg = KnowledgeWorkspaceStore(Path(td) / "kg.sqlite3")
        l1 = kg.acquire_fenced_lease("sbx-01", "worker-a", ttl_ms=10_000, now_ms=1000)
        contended_rejected = False
        try:
            kg.acquire_fenced_lease("sbx-01", "worker-b", ttl_ms=10_000, now_ms=2000)
        except PermissionError:
            contended_rejected = True
        l2 = kg.acquire_fenced_lease("sbx-01", "worker-b", ttl_ms=10_000, now_ms=15_000)
        stale_fenced = not kg.verify_fenced_epoch("sbx-01", "worker-a", l1["lease_epoch"], now_ms=16_000)
        active_valid = kg.verify_fenced_epoch("sbx-01", "worker-b", l2["lease_epoch"], now_ms=16_000)
    obl16_ok = (
        bool(space_evs)
        and ratchet["ok"]
        and l1["lease_epoch"] == 1
        and l2["lease_epoch"] == 2
        and contended_rejected
        and stale_fenced
        and active_valid
    )
    out.append(
        ObligationResult(
            obligation_id="OBL-16",
            title="SPACE Architecture Pattern Ratchet (<1,000L, Zero-Dep, Layer Guard) & Lease Epoch Fencing",
            confidence="observed",
            upstream_evidence=f"perplexityai/SPACE ARCHITECTURE.toml + state/reconciliation; REA {','.join(space_evs[:1])}",
            passed=obl16_ok,
            details=f"Verified {ratchet['scanned_file_count']} files (max {ratchet['max_observed_lines']}L < 1,000L), 0 layer/XSS leaks, and monotonic lease_epoch fencing.",
            metrics={"max_observed_lines": ratchet["max_observed_lines"], "largest_file": ratchet["largest_file"]},
        )
    )

    # ---- OBL-17: perplexityai/codescythe (Two-Set File Reachability & Dead-Export Gate) ----
    cs_evs = _target_evidence_ids(rea_summary, "codescythe")
    with tempfile.TemporaryDirectory(prefix="lum_obl17_") as td:
        fake_forge = Path(td) / "chromium-forge"
        (fake_forge / "forge").mkdir(parents=True)
        (Path(td) / "pyproject.toml").write_text("[project]\nname='x'\ndependencies=[]\n", encoding=ENCODING)
        (fake_forge / "forge" / "__init__.py").write_text("", encoding=ENCODING)
        (fake_forge / "forge" / "cli.py").write_text("def main():\n    return 0\n", encoding=ENCODING)
        (fake_forge / "forge" / "orphan_dead.py").write_text("def unused_fn():\n    return 1\n", encoding=ENCODING)
        neg_ratchet = run_architecture_ratchet(fake_forge)
    obl17_ok = (
        bool(cs_evs)
        and ratchet["unreachable_files"] == []
        and len(ratchet["unreferenced_exports"]) <= ratchet["unreferenced_exports_cap"]
        and "orphan_dead" in neg_ratchet["unreachable_files"]
    )
    out.append(
        ObligationResult(
            obligation_id="OBL-17",
            title="Codescythe Two-Set Dead-File & Export Reachability Analyzer",
            confidence="observed",
            upstream_evidence=f"perplexityai/codescythe ARCHITECTURE.md; REA {','.join(cs_evs[:2])}",
            passed=obl17_ok,
            details=f"Verified {ratchet['reachable_module_count']}/{ratchet['forge_module_count']} forge modules reachable and synthetic orphan module caught.",
            metrics={"reachable_modules": ratchet["reachable_module_count"], "unreferenced_exports": len(ratchet["unreferenced_exports"])},
        )
    )

    # ---- OBL-18: perplexityai/rules_web_e2e (Hermetic Origin Lock & Pure-Stdlib PNG VRT) ----
    e2e_evs = _target_evidence_ids(rea_summary, "rules_web_e2e")
    base_rgba = bytearray([20, 30, 40, 255] * 16)
    cand_rgba = bytearray(base_rgba)
    cand_rgba[0:4] = b"\xf0\x20\x20\xff"  # Mutate 1 of 16 pixels (6.25%)
    png_a = encode_rgba_png(4, 4, base_rgba)
    png_b = encode_rgba_png(4, 4, cand_rgba)
    cmp_same = compare_png_bytes(png_a, png_a, max_mismatch_ratio=0.0)
    cmp_diff = compare_png_bytes(png_a, png_b, max_mismatch_ratio=0.01)

    class _DummyMux:
        def subscribe(self, *_a: object) -> object:
            return lambda: None

    class _DummyCDP:
        mux = _DummyMux()

        def _pick_target_id(self, tid: str | None) -> str:
            return tid or "tab-1"

        def run_session(self, *_a: object, **_kw: object) -> list[object]:
            return []

    with tempfile.TemporaryDirectory(prefix="lum_obl18_") as td:
        vrt_mgr = VRTIsolationManager(_DummyCDP(), Path(td))  # type: ignore[arg-type]
        vrt_mgr.lock_origins("tab-1", ["https://allowed.example.org"])
        allow_ok = vrt_mgr.is_request_allowed("tab-1", "https://allowed.example.org/api/data")
        inline_ok = vrt_mgr.is_request_allowed("tab-1", "data:image/png;base64,AA==")
        third_party_blocked = not vrt_mgr.is_request_allowed("tab-1", "https://tracker.evil.example/pixel.gif")
        vrt_mgr.close()

    obl18_ok = (
        bool(e2e_evs)
        and cmp_same["passed"]
        and cmp_same["diff_pixels"] == 0
        and not cmp_diff["passed"]
        and cmp_diff["diff_pixels"] == 1
        and cmp_diff["diff_bounding_box"] == {"min_x": 0, "min_y": 0, "max_x": 0, "max_y": 0}
        and allow_ok
        and inline_ok
        and third_party_blocked
    )
    out.append(
        ObligationResult(
            obligation_id="OBL-18",
            title="Hermetic Declared-Origin Network Lock & Pure-Stdlib RFC 2083 PNG Visual Regression",
            confidence="observed",
            upstream_evidence=f"perplexityai/rules_web_e2e runtime/isolation.ts + visuals.ts; REA {','.join(e2e_evs[:1])}",
            passed=obl18_ok,
            details="Verified pure-stdlib PNG encode/decode/diff bounding-box math and declared-origin third-party egress blocking.",
            metrics={"single_pixel_mismatch_ratio": cmp_diff["mismatch_ratio"], "third_party_blocked": third_party_blocked},
        )
    )

    # ---- OBL-19: perplexityai/perplexity-py (14-Endpoint Wire Contract, Fenced Monitors & CAS Playbook Revisions) ----
    pplx_py_evs = _target_evidence_ids(rea_summary, "perplexity-py")
    with tempfile.TemporaryDirectory(prefix="lum_obl19_") as td:
        ledger = ActionLedger(Path(td) / "ledger.jsonl")
        pb_mem = PlaybookMemory(Path(td) / "playbooks")
        eng = MonitorEvalEngine(Path(td) / "mon.sqlite3", ledger=ledger, playbooks=pb_mem)
        mon = eng.create_monitor(name="Spec Watch", target_url="https://spec.example.org/v1", extract_selector="#main")
        r_init = eng.run_monitor(mon["monitor_id"], injected_html='<html><body><div id="main"><h1>v1.0</h1></div></body></html>')
        r_same = eng.run_monitor(mon["monitor_id"], injected_html='<html><body><div id="main"><h1>v1.0</h1></div><div>noise</div></body></html>')
        r_chg = eng.run_monitor(mon["monitor_id"], injected_html='<html><body><div id="main"><h1>v2.0</h1></div></body></html>')

        rev1 = eng.snapshot_playbook_revision("pb-billing", domain="example.org", goal="billing checkout", steps=[{"action": "click", "index": 1}])
        rev2 = eng.snapshot_playbook_revision(
            "pb-billing",
            domain="example.org",
            goal="billing checkout",
            steps=[{"action": "click", "index": 2}],
            expected_revision=rev1["latest_revision"],
        )
        cas_caught = False
        try:
            eng.snapshot_playbook_revision("pb-billing", steps=[], expected_revision=rev1["latest_revision"])
        except RevisionConflictError:
            cas_caught = True
        rolled = eng.rollback_playbook("pb-billing", rev1["latest_revision"], expected_revision=rev2["latest_revision"])
        restored_pb = pb_mem.get_playbook("pb-billing")
        wire_ok = validate_perplexity_wire_payload(
            "decisions.create",
            {"model": "pplx-decider-v1.1-27b", "state": "ok", "questions": {"q": {"type": "noul"}}},
        )
    obl19_ok = (
        bool(pplx_py_evs)
        and r_init["status"] == "INITIALIZED"
        and r_same["status"] == "UNCHANGED"
        and r_chg["status"] == "CHANGED"
        and cas_caught
        and rolled["revision_num"] == 3
        and restored_pb is not None
        and restored_pb["steps"] == [{"action": "click", "index": 1}]
        and wire_ok["configured_sdk_endpoints"] == 14
    )
    out.append(
        ObligationResult(
            obligation_id="OBL-19",
            title="Perplexity 14-Endpoint Wire Schema, Fenced Web Monitors & CAS Playbook Revisions",
            confidence="observed",
            upstream_evidence=f"perplexityai/perplexity-py api.md + .stats.yml; REA {','.join(pplx_py_evs[:1])}",
            passed=obl19_ok,
            details="Verified selector-scoped INITIALIZED->UNCHANGED->CHANGED transitions, CAS conflict rejection, PlaybookMemory disk rollback, and 14 SDK endpoints.",
            metrics={"sdk_endpoints": wire_ok["configured_sdk_endpoints"], "revisions_tested": rolled["revision_num"]},
        )
    )

    # ---- OBL-20: perplexityai/search_evals (Decimal CostLedger & Citation/Factuality Eval Suite) ----
    sevals_evs = _target_evidence_ids(rea_summary, "search_evals")
    cl = EvalCostLedger()
    cl.record(
        "attempt-1",
        AttemptCostRecord(
            input_tokens=1000,
            cached_input_tokens=400,
            output_tokens=200,
            search_calls=1,
            model="gpt-5.5",
            dedupe_fees={"container-a": 0.03},
        ),
    )
    cl.record(
        "attempt-2",
        AttemptCostRecord(
            input_tokens=500,
            cached_input_tokens=0,
            output_tokens=100,
            search_calls=0,
            model="gpt-5.5",
            dedupe_fees={"container-a": 0.03},
        ),
    )
    cost_sum = cl.summary()
    with tempfile.TemporaryDirectory(prefix="lum_obl20_") as td:
        ev_engine = MonitorEvalEngine(Path(td) / "eval.sqlite3")
        unkeyed_rep = ev_engine.run_search_eval_suite(providers=["luminara"])
        mock_rep = ev_engine.run_search_eval_suite(
            providers=["luminara", "perplexity"],
            provider_caller=lambda _p, _m, c: {
                "answer": " ".join(c["expected_facts"]),
                "citations": [c["fixture_url"]],
                "input_tokens": 500,
                "cached_input_tokens": 100,
                "output_tokens": 80,
                "search_calls": 1,
            },
        )
    # Expected math: uncached_in=(600+500)*$5/1M=$0.0055, cached_in=400*$0.5/1M=$0.0002, out=300*$30/1M=$0.009, search=$0.01, dedup_container=$0.03 => $0.0547
    obl20_ok = (
        bool(sevals_evs)
        and cost_sum["known_cost_usd"] == 0.0547
        and unkeyed_rep["ok"]
        and unkeyed_rep["scorecards"][0]["mean_f1"] == 1.0
        and all(sc["cases_passed"] == sc["total_cases"] and sc["mean_f1"] == 1.0 for sc in mock_rep["scorecards"])
    )
    out.append(
        ObligationResult(
            obligation_id="OBL-20",
            title="Search Evals Exact Decimal CostLedger (Deduplicated Containers) & Citation F1 Grader",
            confidence="observed",
            upstream_evidence=f"perplexityai/search_evals search_evals/costs.py:12-109 + suites/graders.py; REA {','.join(sevals_evs[:1])}",
            passed=obl20_ok,
            details="Verified exact 6-decimal ROUND_HALF_UP token/search/container deduplication ($0.054700) and honest provider/zero-LLM F1 grading.",
            metrics={"verified_cost_usd": cost_sum["known_cost_usd"], "providers_evaluated": len(mock_rep["scorecards"])},
        )
    )

    # ---- OBL-21: perplexityai/pplx-kernels (MoE All-to-All Symmetric Heap & Split-Phase Barrier Audit) ----
    kern_evs = _target_evidence_ids(rea_summary, "pplx-kernels")
    kern_audit = audit_pplx_kernels_tree(staging_root if staging_root.is_dir() else None)
    bad_topo = validate_all_to_all_topology(
        MoEAllToAllConfig(
            mode="intranode",
            max_num_tokens=64,
            num_experts=16,
            experts_per_token=2,
            rank=0,
            world_size=4,
            dp_size=4,  # Invalid: world_size // dp_size == 1 (must be > 1)
            hidden_dim=4096,
            hidden_dim_bytes=4096,
        )
    )
    bad_sm_caught = False
    try:
        SplitPhaseDispatchValidator(has_scales=False).step_combine(do_send=True, do_recv=True)
    except ValueError:
        bad_sm_caught = True
    obl21_ok = bool(kern_evs) and kern_audit["ok"] and not bad_topo["valid"] and bad_sm_caught and bool(kern_audit["residual_unknowns"])
    out.append(
        ObligationResult(
            obligation_id="OBL-21",
            title="MoE All-to-All NVSHMEM Symmetric Heap Alignment, Split-Phase State Machine & CUDA Unknowns",
            confidence="observed",
            upstream_evidence=f"perplexityai/pplx-kernels src/pplx_kernels/all_to_all.py:27-120 + csrc/all_to_all/*.cu; REA {','.join(kern_evs[:1])}",
            passed=obl21_ok,
            details="Verified 128B NVSHMEM symmetric heap math, split-phase send/recv state transitions, invalid dp_size rejection, and explicit CUDA SASS ResidualUnknown.",
            metrics={
                "symmetric_heap_bytes_per_rank": kern_audit["reference_deepseek_v3_topology"]["symmetric_heap_bytes_per_rank"],
                "residual_unknowns_recorded": len(kern_audit["residual_unknowns"]),
            },
        )
    )

    return out
