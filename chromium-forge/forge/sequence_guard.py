"""Clean-room Behavioral Sequence Correlator & Forensic Casebundle Engine (`forge/sequence_guard.py`).

Reconstructs the core endpoint-security primitives of `perplexityai/numbat` (`v0.3.0`)
in pure Python `>=3.11` stdlib for Luminara Browser co-browsing agents:
1. **Partitioned Deterministic Sequence Tracker** (`numbat/internal/sequence/sequence.go`):
   - Partitions activity strictly by `(agent_id, workspace_id, session_id)` so independent
     sessions never cross-contaminate chains.
   - Pure function of event timestamps (`ts_ms`) and event order: disordered or expired
     windows resolve to non-match, never fabricated chains.
   - Bounded per-partition ring (`max_events = 256`) and LRU partition cap (`max_sessions = 512`),
     retaining only redacted identity/tag projections (zero raw secret storage).
2. **Command & Payload Normalizer** (`numbat/internal/hook` + `rules/{chains,exfil,tamper}`):
   - Tokenizes shell/pipeline payloads via `shlex` + regex idioms to classify `secret_touch`,
     `vault_access`, `dom_recon`, `external_egress`, `guardrail_tamper`, and `reverse_tunnel`.
3. **Self-Verifying Forensic Casebundles** (`numbat/internal/casebundle/{build,verify}.go`):
   - Writes tamper-evident `CASE-<id>.zip` archives containing sorted NDJSON (`findings.ndjson`,
     `events.ndjson`, `enforcements.ndjson`) + `manifest.json` SHA-256 digests + `LUM-SIG-V2`
     HMAC authenticity signature when a session signer is supplied.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import shlex
import threading
import time
from typing import Any
import urllib.parse
import zipfile

from .http_base import atomic_write_private
from .luminara_crypto import EphemeralSessionSigner
from .luminara_security import DEFAULT_REDACTOR, LuminaraRedactor

ENCODING = "utf-8"
MAX_CASEBUNDLE_MEMBER_BYTES = 16 * 1024 * 1024
MAX_STORED_FINDINGS = 500
MAX_EMITTED_SIGNATURES = 2048

_SECRET_PATTERN_RE = re.compile(
    r"(?i)(?:\.env\b|id_rsa|id_ed25519|vault\.json|local_ui_key|document\.cookie|localStorage|sessionStorage|authorization\s*:|bearer\s+[a-z0-9._\-]{8,}|aws_secret|api[_-]?key)"
)
_REVERSE_TUNNEL_RE = re.compile(
    r"(?i)(?:/dev/tcp/|nc\s+-e|bash\s+-i|powershell[^\n]*-enc|invoke-webrequest[^\n]*-method\s+post|curl\s+[^\n]*(?:-d\s*@|--data-binary\s*@)|ngrok\s+tcp|cloudflared\s+tunnel)"
)
_TAMPER_PATTERN_RE = re.compile(
    r"(?i)(?:disable_guard|unlock_origins|guardrails_off|rm\s+-rf\s+.*action_ledger|clear_block)"
)


def _extract_origin(url: str) -> str:
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    return ""


def resolve_effective_url(params: dict[str, Any], target_url: str = "") -> str:
    """Extract the most specific destination or origin URL from tool arguments."""
    for key in ("url", "origin", "start_url", "webhook_url", "target_url"):
        val = params.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    urls = params.get("urls")
    if isinstance(urls, list) and urls:
        first = urls[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    return (target_url or "").strip()


def classify_event_tags(tool_name: str, params: dict[str, Any], target_url: str = "") -> set[str]:
    """Derive deterministic Numbat-style capability tags from an MCP/REST tool invocation."""
    tags: set[str] = set()
    t = (tool_name or "").strip().lower()
    act = str(params.get("action") or "").strip().lower()
    blob = " ".join(
        str(params.get(k) or "")
        for k in ("script", "text", "url", "start_url", "webhook_url", "target_url", "goal", "prompt_text", "tool_name", "query")
    )
    # Tokenize command-like strings via shlex without failing on unbalanced quotes
    try:
        tokens = shlex.split(blob[:2000], posix=True)
    except ValueError:
        tokens = blob[:2000].split()
    norm_blob = " ".join(tokens) if tokens else blob[:2000]

    if t in (
        "browser_snapshot",
        "browser_perception_axtree",
        "browser_extract_structured",
        "browser_generative_ui",
        "webmcp_list_tools",
    ) or (t == "browser_outline" and act in ("", "snapshot", "diff", "grep")):
        tags.add("dom_recon")
    if t == "browser_vault" and act in ("fill", "enter_totp"):
        tags.add("vault_access")
        tags.add("secret_touch")
    if _SECRET_PATTERN_RE.search(blob) or _SECRET_PATTERN_RE.search(norm_blob):
        tags.add("secret_touch")
    if _REVERSE_TUNNEL_RE.search(blob) or _REVERSE_TUNNEL_RE.search(norm_blob):
        tags.add("reverse_tunnel")
    if (
        _TAMPER_PATTERN_RE.search(blob)
        or (t == "browser_mutation_guard" and act == "disable")
        or (t == "browser_vrt_isolation" and act == "unlock_origins")
    ):
        tags.add("guardrail_tamper")

    method_hint = str(params.get("method") or "").upper()
    is_outbound_action = (
        t in ("browser_open_tab", "webmcp_call_tool", "browser_exec_pipeline", "browser_bulk_extract")
        or (t == "browser_act" and act in ("click", "type", "navigate"))
        or (t == "browser_outline" and act in ("click", "type"))
        or (t == "browser_run_goal" and bool(params.get("start_url")))
        or (t == "browser_monitors" and act in ("create", "run_now") and bool(params.get("webhook_url")))
        or method_hint in ("POST", "PUT", "PATCH", "DELETE")
    )
    if is_outbound_action:
        tags.add("state_or_net_action")

    egress_url = resolve_effective_url(params, target_url)
    egress_host = (urllib.parse.urlparse(egress_url).hostname or "").lower().rstrip(".")
    is_loopback = egress_host in ("", "127.0.0.1", "localhost", "::1")
    if is_outbound_action and bool(egress_url) and not is_loopback:
        tags.add("external_egress")
    return tags


@dataclass(frozen=True)
class SequenceRule:
    rule_id: str
    title: str
    severity: str
    steps: tuple[str, ...]
    within_events: int
    within_ms: int
    require_distinct_origin: bool = False
    enforce_block: bool = True


BUILTIN_SEQUENCE_RULES: tuple[SequenceRule, ...] = (
    SequenceRule(
        rule_id="CHAIN-01",
        title="Vault or Secret Touch Followed by Cross-Origin Egress",
        severity="CRITICAL",
        steps=("secret_touch", "external_egress"),
        within_events=12,
        within_ms=300_000,
        require_distinct_origin=True,
        enforce_block=True,
    ),
    SequenceRule(
        rule_id="CHAIN-02",
        title="Multi-Origin DOM Recon Sweep Followed by External Egress",
        severity="HIGH",
        steps=("dom_recon", "dom_recon", "external_egress"),
        within_events=16,
        within_ms=180_000,
        require_distinct_origin=True,
        enforce_block=False,
    ),
    SequenceRule(
        rule_id="CHAIN-03",
        title="Guardrail Tamper Followed by External Egress",
        severity="CRITICAL",
        steps=("guardrail_tamper", "external_egress"),
        within_events=10,
        within_ms=300_000,
        require_distinct_origin=False,
        enforce_block=True,
    ),
    SequenceRule(
        rule_id="CHAIN-04",
        title="Reverse Shell or File-Exfil Command Idiom Detected",
        severity="CRITICAL",
        steps=("reverse_tunnel",),
        within_events=1,
        within_ms=60_000,
        require_distinct_origin=False,
        enforce_block=True,
    ),
)


class SequenceGuard:
    """Partitioned multi-step sequence detector and forensic casebundle builder."""

    def __init__(
        self,
        outputs_dir: Path,
        *,
        redactor: LuminaraRedactor | None = None,
        signer: EphemeralSessionSigner | None = None,
        max_events: int = 256,
        max_sessions: int = 512,
    ) -> None:
        self.outputs_dir = outputs_dir.resolve()
        self.casebundles_dir = self.outputs_dir / "casebundles"
        self.casebundles_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.outputs_dir / "sequence_guard_state.json"
        self.redactor = redactor or DEFAULT_REDACTOR
        self.signer = signer
        self.max_events = max(16, max_events, *(r.within_events for r in BUILTIN_SEQUENCE_RULES))
        self.max_sessions = max(16, max_sessions)
        self._lock = threading.Lock()
        self._partitions: OrderedDict[str, deque[dict[str, Any]]] = OrderedDict()
        self._emitted_chains: OrderedDict[str, None] = OrderedDict()
        self._findings: list[dict[str, Any]] = []
        self._enforcements: list[dict[str, Any]] = []
        self._all_events: deque[dict[str, Any]] = deque(maxlen=2048)
        self._blocked_partitions: dict[str, dict[str, Any]] = {}
        self._load_state()

    def _load_state(self) -> None:
        if not self.state_path.is_file():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding=ENCODING))
            if not isinstance(raw, dict):
                return
            if isinstance(raw.get("blocked_partitions"), dict):
                self._blocked_partitions = {
                    str(k): v for k, v in raw["blocked_partitions"].items() if isinstance(v, dict)
                }
            if isinstance(raw.get("findings"), list):
                self._findings = [x for x in raw["findings"][-MAX_STORED_FINDINGS:] if isinstance(x, dict)]
            if isinstance(raw.get("enforcements"), list):
                self._enforcements = [x for x in raw["enforcements"][-MAX_STORED_FINDINGS:] if isinstance(x, dict)]
            if isinstance(raw.get("recent_events"), list):
                for ev in raw["recent_events"][-512:]:
                    if isinstance(ev, dict):
                        self._all_events.append(ev)
        except Exception:  # noqa: BLE001
            pass

    def _save_state_locked(self) -> None:
        payload = {
            "schema": "luminara.sequence_state.v1",
            "blocked_partitions": self._blocked_partitions,
            "findings": self._findings[-MAX_STORED_FINDINGS:],
            "enforcements": self._enforcements[-MAX_STORED_FINDINGS:],
            "recent_events": list(self._all_events)[-512:],
        }
        try:
            atomic_write_private(self.state_path, json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def active_daemon_block(self) -> dict[str, Any] | None:
        """Return the earliest active `PAUSED_SEQUENCE_BLOCK` finding if any agent session is latched."""
        with self._lock:
            if not self._blocked_partitions:
                return None
            return next(iter(self._blocked_partitions.values()))

    @staticmethod
    def _partition_key(agent_id: str, workspace_id: str, session_id: str) -> str:
        a = (agent_id or "default-agent").strip()
        w = (workspace_id or "default").strip()
        s = (session_id or "live").strip()
        return f"{a}\x00{w}\x00{s}"

    def evaluate_step(
        self,
        *,
        agent_id: str,
        tool_name: str,
        params: dict[str, Any] | None = None,
        target_url: str = "",
        workspace_id: str = "default",
        session_id: str = "live",
        ts_ms: int | None = None,
    ) -> dict[str, Any]:
        """Record one projected event into its partition ring and evaluate all chain rules."""
        safe_params = params if isinstance(params, dict) else {}
        now_ms = int(ts_ms if ts_ms is not None else time.time() * 1000)
        eff_url = resolve_effective_url(safe_params, target_url)
        origin = _extract_origin(eff_url)
        tags = sorted(classify_event_tags(tool_name, safe_params, eff_url))
        pkey = self._partition_key(agent_id, workspace_id, session_id)
        ev_seed = f"{pkey}|{now_ms}|{tool_name}|{origin}|{','.join(tags)}|{secrets.token_hex(4)}"
        ev_id = "EV-" + hashlib.sha256(ev_seed.encode(ENCODING)).hexdigest()[:16].upper()

        projected_event = {
            "event_id": ev_id,
            "partition_hash": hashlib.sha256(pkey.encode(ENCODING)).hexdigest()[:16],
            "agent_id": self.redactor.redact_text(agent_id)[:80],
            "workspace_id": self.redactor.redact_text(workspace_id)[:64],
            "session_id": self.redactor.redact_text(session_id)[:64],
            "ts_ms": now_ms,
            "tool_name": self.redactor.redact_text(tool_name)[:80],
            "origin": self.redactor.redact_text(origin)[:200],
            "tags": tags,
        }

        matched_findings: list[dict[str, Any]] = []
        blocked = False
        state_dirty = False
        with self._lock:
            if pkey in self._blocked_partitions:
                active_blk = self._blocked_partitions[pkey]
                return {
                    "ok": False,
                    "blocked": True,
                    "status": "PAUSED_SEQUENCE_BLOCK",
                    "event": projected_event,
                    "findings": [active_blk],
                }

            ring = self._partitions.get(pkey)
            if ring is None:
                if len(self._partitions) >= self.max_sessions:
                    self._partitions.popitem(last=False)
                ring = deque(maxlen=self.max_events)
                self._partitions[pkey] = ring
            else:
                self._partitions.move_to_end(pkey)

            # Disordered timestamp check (Numbat determinism: never match disordered clocks)
            disordered = bool(ring and now_ms < ring[-1]["ts_ms"])
            ring.append(projected_event)
            self._all_events.append(projected_event)

            if not disordered:
                window = list(ring)
                for rule in BUILTIN_SEQUENCE_RULES:
                    chain = self._match_canonical_chain(window, rule)
                    if chain is None:
                        continue
                    chain_sig = f"{rule.rule_id}:{','.join(c['event_id'] for c in chain)}"
                    if chain_sig in self._emitted_chains:
                        continue
                    if len(self._emitted_chains) >= MAX_EMITTED_SIGNATURES:
                        self._emitted_chains.popitem(last=False)
                    self._emitted_chains[chain_sig] = None
                    case_id = f"CASE-{now_ms}-{hashlib.sha256(chain_sig.encode(ENCODING)).hexdigest()[:8].upper()}"
                    finding = {
                        "finding_id": f"FND-{hashlib.sha256(chain_sig.encode(ENCODING)).hexdigest()[:12].upper()}",
                        "case_id": case_id,
                        "rule_id": rule.rule_id,
                        "title": rule.title,
                        "severity": rule.severity,
                        "agent_id": projected_event["agent_id"],
                        "ts_ms": now_ms,
                        "cited_event_ids": [c["event_id"] for c in chain],
                        "origins": [c["origin"] for c in chain if c["origin"]],
                        "enforced_block": rule.enforce_block,
                    }
                    self._findings.append(finding)
                    if len(self._findings) > MAX_STORED_FINDINGS:
                        del self._findings[:-MAX_STORED_FINDINGS]
                    matched_findings.append(finding)
                    state_dirty = True
                    if rule.enforce_block:
                        blocked = True
                        enf = {
                            "enforcement_id": f"ENF-{finding['finding_id'][4:]}",
                            "case_id": case_id,
                            "finding_id": finding["finding_id"],
                            "decision": "PAUSED_SEQUENCE_BLOCK",
                            "ts_ms": now_ms,
                        }
                        self._enforcements.append(enf)
                        if len(self._enforcements) > MAX_STORED_FINDINGS:
                            del self._enforcements[:-MAX_STORED_FINDINGS]
                        self._blocked_partitions[pkey] = finding

            if state_dirty:
                self._save_state_locked()

        return {
            "ok": not blocked,
            "blocked": blocked,
            "status": "PAUSED_SEQUENCE_BLOCK" if blocked else ("WARN_SEQUENCE_FINDING" if matched_findings else "OK"),
            "event": projected_event,
            "findings": matched_findings,
        }

    @staticmethod
    def _match_canonical_chain(window: list[dict[str, Any]], rule: SequenceRule) -> list[dict[str, Any]] | None:
        final_ev = window[-1]
        if rule.steps[-1] not in final_ev["tags"]:
            return None
        if len(rule.steps) == 1:
            return [final_ev]
        if rule.require_distinct_origin and not final_ev["origin"]:
            return None

        slice_start = max(0, len(window) - rule.within_events)
        candidates = [
            ev for ev in window[slice_start:] if 0 <= (final_ev["ts_ms"] - ev["ts_ms"]) <= rule.within_ms
        ]
        if len(candidates) < len(rule.steps) or candidates[-1]["event_id"] != final_ev["event_id"]:
            return None

        # Earliest valid event per step prior to final_ev (enforcing distinct-origin on step 0)
        chosen: list[dict[str, Any]] = []
        cursor = 0
        prior_steps = rule.steps[:-1]
        for step_idx, step_tag in enumerate(prior_steps):
            found: dict[str, Any] | None = None
            while cursor < len(candidates) - 1:
                cand = candidates[cursor]
                cursor += 1
                if step_tag not in cand["tags"]:
                    continue
                if step_idx == 0 and rule.require_distinct_origin and cand["origin"] and cand["origin"] == final_ev["origin"]:
                    continue
                found = cand
                break
            if found is None:
                return None
            chosen.append(found)
        chosen.append(final_ev)

        if rule.require_distinct_origin:
            first_origin = chosen[0]["origin"]
            last_origin = chosen[-1]["origin"]
            if not last_origin or (first_origin and first_origin == last_origin):
                return None
        return chosen

    def clear_block(self, *, agent_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if not agent_id:
                cleared = len(self._blocked_partitions)
                self._blocked_partitions.clear()
            else:
                prefix = f"{agent_id.strip()}\x00"
                keys = [k for k in self._blocked_partitions if k.startswith(prefix)]
                for k in keys:
                    self._blocked_partitions.pop(k, None)
                cleared = len(keys)
            if cleared > 0:
                self._save_state_locked()
        return {"ok": True, "cleared_blocks": cleared}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tracked_partitions": len(self._partitions),
                "active_blocks": list(self._blocked_partitions.values()),
                "findings_count": len(self._findings),
                "recent_findings": self._findings[-20:],
                "rules": [
                    {"rule_id": r.rule_id, "title": r.title, "severity": r.severity, "enforce_block": r.enforce_block}
                    for r in BUILTIN_SEQUENCE_RULES
                ],
            }

    def export_casebundle(self, case_id: str | None = None) -> dict[str, Any]:
        """Build a deterministic, self-verifying `CASE-*.zip` forensic bundle (safe-by-default redacted)."""
        with self._lock:
            if case_id:
                findings = [f for f in self._findings if f["case_id"] == case_id]
                if not findings:
                    raise ValueError(f"No findings found for case_id {case_id!r}")
                eff_case_id = case_id
            elif self._findings:
                eff_case_id = str(self._findings[-1]["case_id"])
                findings = [f for f in self._findings if f["case_id"] == eff_case_id]
            else:
                eff_case_id = f"CASE-{int(time.time() * 1000)}-SNAPSHOT"
                findings = []
            cited_ids = {eid for f in findings for eid in f.get("cited_event_ids", [])}
            events = (
                [e for e in self._all_events if e["event_id"] in cited_ids]
                if cited_ids
                else list(self._all_events)[-50:]
            )
            enforcements = [en for en in self._enforcements if en["case_id"] == eff_case_id]

        safe_slug = re.sub(r"[^A-Za-z0-9._\-]+", "_", eff_case_id)[:80]
        zip_path = self.casebundles_dir / f"{safe_slug}.zip"

        def _ndjson_bytes(records: list[dict[str, Any]], sort_key: str) -> bytes:
            ordered = sorted(self.redactor.redact_payload(records), key=lambda r: str(r.get(sort_key) or ""))
            lines = [json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for r in ordered]
            return ("\n".join(lines) + ("\n" if lines else "")).encode(ENCODING)

        members = {
            "findings.ndjson": _ndjson_bytes(findings, "finding_id"),
            "events.ndjson": _ndjson_bytes(events, "event_id"),
            "enforcements.ndjson": _ndjson_bytes(enforcements, "enforcement_id"),
        }
        file_digests = {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in sorted(members.items())
        }
        manifest: dict[str, Any] = {
            "schema": "luminara.casebundle.v1",
            "case_id": eff_case_id,
            "evidence_mode": "redacted",
            "created_at_ms": int(time.time() * 1000),
            "counts": {
                "findings": len(findings),
                "events": len(events),
                "enforcements": len(enforcements),
            },
            "files": file_digests,
        }
        canonical_manifest = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode(ENCODING)
        manifest_digest = hashlib.sha256(canonical_manifest).hexdigest()
        manifest["manifest_sha256"] = manifest_digest
        if self.signer is not None:
            manifest["signature"] = self.signer.sign_receipt_digest(manifest_digest)

        manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(ENCODING)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", manifest_bytes)
            for name, data in sorted(members.items()):
                zf.writestr(name, data)

        return {
            "ok": True,
            "case_id": eff_case_id,
            "bundle_file": zip_path.name,
            "bundle_path": str(zip_path),
            "manifest_sha256": manifest_digest,
            "signed": self.signer is not None,
            "counts": manifest["counts"],
        }


def _read_bounded_zip_member(zf: zipfile.ZipFile, name: str) -> bytes:
    with zf.open(name, "r") as fp:
        raw = fp.read(MAX_CASEBUNDLE_MEMBER_BYTES + 1)
    if len(raw) > MAX_CASEBUNDLE_MEMBER_BYTES:
        raise ValueError(f"Decompressed member exceeds {MAX_CASEBUNDLE_MEMBER_BYTES} byte cap: {name!r}")
    return raw


def verify_casebundle(bundle_path: Path, *, signer: EphemeralSessionSigner | None = None) -> dict[str, Any]:
    """Offline integrity & optional HMAC authenticity verification of a `CASE-*.zip` bundle."""
    if not bundle_path.is_file():
        return {"valid": False, "error": f"Bundle not found: {bundle_path}"}

    try:
        with zipfile.ZipFile(bundle_path, "r") as zf:
            names = zf.namelist()
            if len(names) != len(set(names)):
                return {"valid": False, "error": "Duplicate archive member names rejected"}
            for name in names:
                if name.startswith(("/", "\\")) or ".." in Path(name).parts or ":" in name or "/" in name or "\\" in name:
                    return {"valid": False, "error": f"Unsafe archive member path: {name!r}"}
                info = zf.getinfo(name)
                if info.file_size > MAX_CASEBUNDLE_MEMBER_BYTES:
                    return {"valid": False, "error": f"Member exceeds size cap: {name!r}"}
            if "manifest.json" not in names:
                return {"valid": False, "error": "Missing manifest.json"}

            manifest = json.loads(_read_bounded_zip_member(zf, "manifest.json").decode(ENCODING))
            if not isinstance(manifest, dict):
                return {"valid": False, "error": "manifest.json must be a JSON object"}
            files_spec = manifest.get("files")
            if not isinstance(files_spec, dict) or not files_spec:
                return {"valid": False, "error": "Invalid files map in manifest.json"}
            expected_members = {"manifest.json"} | set(files_spec.keys())
            if set(names) != expected_members:
                return {"valid": False, "error": "Archive contains undeclared or missing members"}

            unsigned_copy = {k: v for k, v in manifest.items() if k not in ("manifest_sha256", "signature")}
            expected_manifest_sha = hashlib.sha256(
                json.dumps(unsigned_copy, sort_keys=True, separators=(",", ":")).encode(ENCODING)
            ).hexdigest()
            if expected_manifest_sha != manifest.get("manifest_sha256"):
                return {"valid": False, "error": "manifest_sha256 mismatch"}

            sig = manifest.get("signature")
            sig_verified = False
            if signer is not None:
                if not isinstance(sig, str) or not signer.verify_receipt_signature(expected_manifest_sha, sig):
                    return {"valid": False, "error": "Invalid or missing LUM-SIG-V2 casebundle signature"}
                sig_verified = True

            for fname, meta in files_spec.items():
                if not isinstance(meta, dict):
                    return {"valid": False, "error": f"Invalid file metadata for {fname}"}
                raw = _read_bounded_zip_member(zf, fname)
                if len(raw) != int(meta.get("bytes", -1)) or hashlib.sha256(raw).hexdigest() != meta.get("sha256"):
                    return {"valid": False, "error": f"Digest mismatch on {fname}"}
                for ln in io.StringIO(raw.decode(ENCODING)):
                    if ln.strip():
                        json.loads(ln)
    except (zipfile.BadZipFile, OSError, UnicodeDecodeError, ValueError, KeyError) as exc:
        return {"valid": False, "error": f"Malformed casebundle archive: {exc}"}

    return {
        "valid": True,
        "case_id": manifest.get("case_id"),
        "manifest_sha256": expected_manifest_sha,
        "signature_verified": sig_verified,
        "counts": manifest.get("counts", {}),
    }
