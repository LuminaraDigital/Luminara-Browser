"""Append-Only SHA-256 Hash-Chained & HMAC-Signed Action Ledger (`forge/action_ledger.py`).

Extracted from `agent_engine.py` to keep every module focused and well below 1,000 lines.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time
from typing import Any

from .luminara_crypto import EphemeralSessionSigner
from .luminara_security import DEFAULT_REDACTOR, LuminaraRedactor

ENCODING = "utf-8"
GENESIS_PREV_HASH = "0" * 64


class ActionLedger:
    """Append-only SHA-256 hash-chained & HMAC-signed receipt log (`LUM-*`) with tamper verification."""

    def __init__(
        self,
        ledger_path: Path,
        redactor: LuminaraRedactor | None = None,
        signer: EphemeralSessionSigner | None = None,
    ) -> None:
        self.ledger_path = ledger_path
        self.redactor = redactor or DEFAULT_REDACTOR
        self.signer = signer
        self._lock = threading.Lock()
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._tail_hash = self._load_tail_hash()

    def _load_tail_hash(self) -> str:
        recent_items = self.recent(limit=1)
        if recent_items and isinstance(recent_items[0].get("sha256"), str):
            return recent_items[0]["sha256"]
        return GENESIS_PREV_HASH

    @staticmethod
    def _compute_digest(
        ts_ms: int,
        prev_sha256: str,
        agent_id: str,
        action: str,
        target_id: str,
        params: dict[str, Any],
        status: str,
        summary: str,
    ) -> str:
        canonical = json.dumps(
            {
                "ts_ms": ts_ms,
                "prev_sha256": prev_sha256,
                "agent_id": agent_id,
                "action": action,
                "target_id": target_id,
                "params": params,
                "status": status,
                "summary": summary,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode(ENCODING)
        return hashlib.sha256(canonical).hexdigest()

    def record(
        self,
        agent_id: str,
        action: str,
        target_id: str | None,
        params: dict[str, Any],
        status: str = "OK",
        summary: str = "",
    ) -> dict[str, Any]:
        clean_summary = self.redactor.redact_text(summary)[:240]
        clean_params = self.redactor.redact_payload(params if isinstance(params, dict) else {})
        clean_tid = target_id or ""
        with self._lock:
            ts_ms = int(time.time() * 1000)
            prev_hash = self._tail_hash
            digest = self._compute_digest(
                ts_ms=ts_ms,
                prev_sha256=prev_hash,
                agent_id=agent_id,
                action=action,
                target_id=clean_tid,
                params=clean_params,
                status=status,
                summary=clean_summary,
            )
            receipt: dict[str, Any] = {
                "receipt_id": f"LUM-{ts_ms}-{digest[:10].upper()}",
                "sha256": digest,
                "prev_sha256": prev_hash,
                "timestamp_ms": ts_ms,
                "agent_id": agent_id,
                "action": action,
                "target_id": clean_tid,
                "status": status,
                "summary": clean_summary,
                "params": clean_params,
            }
            if self.signer is not None:
                receipt["signature"] = self.signer.sign_receipt_digest(digest)
            created_new = not self.ledger_path.exists()
            with self.ledger_path.open("a", encoding=ENCODING, newline="\n") as fh:
                fh.write(json.dumps(receipt, ensure_ascii=False) + "\n")
            if created_new:
                try:
                    os.chmod(self.ledger_path, 0o600)
                except OSError:
                    pass
            self._tail_hash = digest
            return receipt

    def recent(self, limit: int = 40) -> list[dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        with self._lock:
            size = self.ledger_path.stat().st_size
            read_bytes = min(size, max(65536, limit * 2048))
            with self.ledger_path.open("rb") as fh:
                if size > read_bytes:
                    fh.seek(size - read_bytes)
                    raw_chunk = fh.read().decode(ENCODING, errors="replace")
                    lines = raw_chunk.splitlines()[1:]
                else:
                    lines = fh.read().decode(ENCODING, errors="replace").splitlines()

        parsed: list[dict[str, Any]] = []
        for raw in reversed(lines):
            if not raw.strip():
                continue
            try:
                parsed.append(json.loads(raw))
                if len(parsed) >= max(1, limit):
                    break
            except json.JSONDecodeError:
                continue
        return parsed

    def verify_ledger(self) -> dict[str, Any]:
        """Recompute every SHA-256 receipt, chain link, and HMAC signature from genesis."""
        if not self.ledger_path.exists():
            return {"valid": True, "checked_count": 0, "errors": []}
        with self._lock:
            lines = self.ledger_path.read_text(encoding=ENCODING).splitlines()

        expected_prev = GENESIS_PREV_HASH
        errors: list[str] = []
        checked = 0
        for line_no, raw in enumerate(lines, start=1):
            if not raw.strip():
                continue
            checked += 1
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"Line {line_no}: malformed JSON ({exc})")
                break
            if rec.get("prev_sha256") != expected_prev:
                errors.append(f"Line {line_no} ({rec.get('receipt_id')}): prev_sha256 chain break")
            recomputed = self._compute_digest(
                ts_ms=int(rec.get("timestamp_ms", 0)),
                prev_sha256=str(rec.get("prev_sha256", "")),
                agent_id=str(rec.get("agent_id", "")),
                action=str(rec.get("action", "")),
                target_id=str(rec.get("target_id", "")),
                params=rec.get("params") if isinstance(rec.get("params"), dict) else {},
                status=str(rec.get("status", "")),
                summary=str(rec.get("summary", "")),
            )
            expected_id = f"LUM-{rec.get('timestamp_ms')}-{recomputed[:10].upper()}"
            if rec.get("sha256") != recomputed or rec.get("receipt_id") != expected_id:
                errors.append(f"Line {line_no} ({rec.get('receipt_id')}): SHA-256 digest mismatch")
            sig = rec.get("signature")
            if self.signer is not None:
                if not isinstance(sig, str) or not self.signer.verify_receipt_signature(recomputed, sig):
                    errors.append(f"Line {line_no} ({rec.get('receipt_id')}): missing or invalid cryptographic signature")
            expected_prev = str(rec.get("sha256", ""))

        return {"valid": len(errors) == 0, "checked_count": checked, "head_sha256": expected_prev, "errors": errors}
