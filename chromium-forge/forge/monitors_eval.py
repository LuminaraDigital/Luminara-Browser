"""Clean-room Web Monitors, CAS Playbook Revisions & Multi-Provider Search Eval (`forge/monitors_eval.py`).

Synthesizes `perplexityai/perplexity-py` (`v0.48.1`) and `perplexityai/search_evals`
into pure Python `>=3.11` stdlib:
1. **CAS-Versioned Playbook Revisions** (`perplexity-py/api.md` `skills.update(expected_revision=...)`):
   - Immutable numbered snapshots (`revision_num = 1, 2, ...`) in SQLite WAL `playbook_revisions`.
   - Enforces Compare-And-Swap (`expected_revision == latest_revision`) on updates and deletes,
     plus deterministic 1-click rollback to any historical revision.
2. **Fenced Web Monitors** (`perplexity-py/resources/monitors` + `SPACE` `lease_epoch`):
   - SQLite WAL `web_monitors` & `monitor_runs` with SSRF-validated target/webhook URLs,
     monotonic `lease_epoch` fencing, canonical content SHA-256 diffing (`UNCHANGED` vs `CHANGED`),
     and `LUM-*` signed receipts.
3. **Exact `Decimal` CostLedger & Search/Extraction Eval Harness** (`search_evals/costs.py` + `graders.py`):
   - `USD_QUANT = Decimal("0.000001")` (`ROUND_HALF_UP`), cached/uncached token accounting,
     deduplicated search/tool call fees, Perplexity 14-endpoint wire contract validation, and
     deterministic citation/factuality grading across providers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
import contextlib
import difflib
import hashlib
import html
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import ssl
import threading
import time
from typing import Any
import urllib.parse

from .action_ledger import ActionLedger
from .cdp_client import CDPBridge, CDPError, validate_navigation_url
from .extractor import build_dom_snapshot_js, extract_structured_page
from .luminara_automation import PlaybookMemory
from .luminara_security import DEFAULT_REDACTOR, LuminaraRedactor
from .search_eval_runner import (
    BUILTIN_EVAL_CASES,
    MODEL_PRICES_USD_PER_1M,
    PERPLEXITY_SDK_ENDPOINTS,
    USD_QUANT,
    WEB_SEARCH_CALL_USD,
    AttemptCostRecord,
    EvalCostLedger,
    execute_search_eval_suite,
    grade_factuality_and_citations,
    usd_quantize,
    validate_perplexity_wire_payload,
)

ENCODING = "utf-8"
_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")


class RevisionConflictError(ValueError):
    """Raised when `expected_revision` does not match `latest_revision` (CAS failure)."""


def _is_global_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        for inner in (ip.ipv4_mapped, ip.sixtofour, ip.teredo[1] if ip.teredo else None):
            if inner is not None:
                ip = inner
                break
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_NET:
        return False
    return bool(
        ip.is_global
        and not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    )


def validate_public_webhook_url(url: str) -> str:
    """Validate outbound webhook URL against loopback, RFC1918, CGNAT, and metadata SSRF."""
    checked = validate_navigation_url(url)
    if checked == "about:blank":
        raise CDPError("about:blank is not a valid webhook URL")
    parsed = urllib.parse.urlsplit(checked)
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise CDPError(f"Blocked non-public webhook host: {host!r}")
    try:
        ipaddress.ip_address(host)
        is_literal_ip = True
    except ValueError:
        is_literal_ip = False
    if is_literal_ip and not _is_global_public_ip(host):
        raise CDPError(f"Blocked non-global webhook IP address: {host}")
    return checked


def post_ssrf_pinned_webhook(url: str, payload: dict[str, Any], *, timeout: float = 5.0) -> dict[str, Any]:
    """Resolve DNS, verify ALL A/AAAA records are global public IPs, and POST directly to pinned IP (zero redirects)."""
    checked = validate_public_webhook_url(url)
    parsed = urllib.parse.urlsplit(checked)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    port = parsed.port or (443 if scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise CDPError(f"Webhook DNS resolution failed for {host!r}: {exc}") from exc
    resolved_ips = sorted({str(info[4][0]) for info in infos if info and info[4]})
    if not resolved_ips or not all(_is_global_public_ip(ip_s) for ip_s in resolved_ips):
        raise CDPError(f"Blocked webhook DNS rebinding / private IP resolution for {host!r}: {resolved_ips}")

    pinned_ip = resolved_ips[0]
    path_q = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    body_bytes = json.dumps(payload, ensure_ascii=False).encode(ENCODING)
    host_hdr = f"{host}:{port}" if parsed.port else host
    raw_sock = socket.create_connection((pinned_ip, port), timeout=timeout)
    try:
        sock = (
            ssl.create_default_context().wrap_socket(raw_sock, server_hostname=host)
            if scheme == "https"
            else raw_sock
        )
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.sock = sock
        conn.request(
            "POST",
            path_q,
            body=body_bytes,
            headers={"Host": host_hdr, "Content-Type": "application/json", "User-Agent": "LuminaraMonitor/3.1"},
        )
        resp = conn.getresponse()
        resp.read(4096)
        status_code = int(resp.status)
    finally:
        try:
            raw_sock.close()
        except OSError:
            pass
    return {"dispatched": 200 <= status_code < 300, "http_status": status_code, "pinned_ip": pinned_ip}


def _slice_html_by_selector(html_src: str, selector: str) -> str:
    sel = (selector or "body").strip()
    if not sel or sel.lower() in ("body", "html", "*"):
        return html_src
    if sel.startswith("#") and re.match(r"^#[A-Za-z0-9_\-]+$", sel):
        esc_id = re.escape(sel[1:])
        m = re.search(rf'(?is)<([a-z0-9]+)\b[^>]*\bid=["\']?{esc_id}["\']?[^>]*>(.*?)</\1>', html_src)
        return m.group(0) if m else ""
    if sel.startswith(".") and re.match(r"^\.[A-Za-z0-9_\-]+$", sel):
        esc_cls = re.escape(sel[1:])
        m = re.search(rf'(?is)<([a-z0-9]+)\b[^>]*\bclass=["\'][^"\']*\b{esc_cls}\b[^"\']*["\'][^>]*>(.*?)</\1>', html_src)
        return m.group(0) if m else ""
    if re.match(r"^[a-zA-Z][a-zA-Z0-9\-]*$", sel):
        esc_tag = re.escape(sel)
        matches = [m.group(0) for m in re.finditer(rf"(?is)<{esc_tag}\b[^>]*>.*?</{esc_tag}>", html_src)]
        return "\n".join(matches) if matches else ""
    return html_src


def _visible_text_from_html(html_src: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style|noscript|template)\b[^>]*>.*?</\1>", " ", html_src or "")
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    return re.sub(r"\s+", " ", html.unescape(cleaned)).strip()


class MonitorEvalEngine:
    """SQLite WAL store + execution engine for Web Monitors, CAS Playbook Revisions, and Search Evals."""

    def __init__(
        self,
        db_path: Path,
        *,
        cdp: CDPBridge | None = None,
        ledger: ActionLedger | None = None,
        playbooks: PlaybookMemory | None = None,
        redactor: LuminaraRedactor | None = None,
    ) -> None:
        self.db_path = db_path.resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cdp = cdp
        self.ledger = ledger
        self.playbooks = playbooks
        self.redactor = redactor or DEFAULT_REDACTOR
        self._lock = threading.Lock()
        self._last_eval_report: dict[str, Any] | None = None
        self._init_schema()
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS playbook_revisions (
                    revision_id TEXT PRIMARY KEY,
                    playbook_id TEXT NOT NULL,
                    revision_num INTEGER NOT NULL,
                    domain TEXT NOT NULL,
                    goal TEXT NOT NULL DEFAULT '',
                    steps_json TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    created_at_ms INTEGER NOT NULL,
                    UNIQUE(playbook_id, revision_num)
                ) STRICT;

                CREATE TABLE IF NOT EXISTS web_monitors (
                    monitor_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    name TEXT NOT NULL,
                    target_url TEXT NOT NULL,
                    extract_selector TEXT NOT NULL DEFAULT 'body',
                    interval_sec INTEGER NOT NULL DEFAULT 3600,
                    webhook_url TEXT NOT NULL DEFAULT '',
                    lease_owner TEXT NOT NULL DEFAULT '',
                    lease_expires_ms INTEGER NOT NULL DEFAULT 0,
                    lease_epoch INTEGER NOT NULL DEFAULT 0,
                    last_content_sha256 TEXT NOT NULL DEFAULT '',
                    last_snapshot_text TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at_ms INTEGER NOT NULL
                ) STRICT;

                CREATE TABLE IF NOT EXISTS monitor_runs (
                    run_id TEXT PRIMARY KEY,
                    monitor_id TEXT NOT NULL REFERENCES web_monitors(monitor_id) ON DELETE CASCADE,
                    started_at_ms INTEGER NOT NULL,
                    finished_at_ms INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    diff_summary TEXT NOT NULL,
                    receipt_id TEXT NOT NULL
                ) STRICT;

                CREATE INDEX IF NOT EXISTS idx_mon_runs_mid ON monitor_runs(monitor_id, started_at_ms DESC);
                """
            )

    # ---- CAS Playbook Revisions (`perplexity-py` `skills` pattern) ----
    def _insert_playbook_revision_locked(
        self,
        conn: sqlite3.Connection,
        pid: str,
        *,
        domain: str,
        goal: str,
        clean_steps: list[dict[str, Any]],
        expected_revision: str | None,
    ) -> dict[str, Any]:
        steps_str = json.dumps(clean_steps, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(steps_str.encode(ENCODING)).hexdigest()
        now_ms = int(time.time() * 1000)
        latest = conn.execute(
            "SELECT * FROM playbook_revisions WHERE playbook_id = ? ORDER BY revision_num DESC LIMIT 1",
            (pid,),
        ).fetchone()
        latest_rev_id = str(latest["revision_id"]) if (latest and not latest["deleted"]) else None
        if expected_revision is not None and expected_revision != latest_rev_id:
            raise RevisionConflictError(
                f"CAS conflict for {pid}: expected_revision={expected_revision!r} != latest_revision={latest_rev_id!r}"
            )
        next_num = (int(latest["revision_num"]) + 1) if latest else 1
        rev_id = f"rev-{next_num}-{digest[:10]}"
        conn.execute(
            """
            INSERT INTO playbook_revisions(revision_id, playbook_id, revision_num, domain, goal, steps_json, sha256, deleted, created_at_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (rev_id, pid, next_num, self.redactor.redact_text(domain)[:120], self.redactor.redact_text(goal)[:200], steps_str, digest, now_ms),
        )
        return {
            "playbook_id": pid,
            "latest_revision": rev_id,
            "revision_num": next_num,
            "sha256": digest,
            "step_count": len(clean_steps),
        }

    def snapshot_playbook_revision(
        self,
        playbook_id: str,
        *,
        domain: str = "",
        goal: str = "",
        steps: list[dict[str, Any]] | None = None,
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        pid = re.sub(r"[^a-zA-Z0-9._\-]+", "_", (playbook_id or "").strip())[:100]
        if not pid:
            raise ValueError("playbook_id is required")
        explicit_steps = steps is not None
        if steps is None and self.playbooks is not None:
            pb = self.playbooks.get_playbook(pid)
            if pb:
                domain = domain or str(pb.get("domain") or "")
                goal = goal or str(pb.get("goal_example") or pb.get("goal") or "")
                steps = list(pb.get("steps") or [])
        clean_steps = self.redactor.redact_payload(steps or [])

        with self._lock, self._connect() as conn:
            snap = self._insert_playbook_revision_locked(
                conn,
                pid,
                domain=domain,
                goal=goal,
                clean_steps=clean_steps,
                expected_revision=expected_revision,
            )
            if explicit_steps and self.playbooks is not None:
                self.playbooks.put_playbook(pid, domain=domain or "local", goal=goal, steps=clean_steps)
        return snap

    def list_playbook_revisions(self, playbook_id: str) -> list[dict[str, Any]]:
        pid = re.sub(r"[^a-zA-Z0-9._\-]+", "_", (playbook_id or "").strip())[:100]
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM playbook_revisions WHERE playbook_id = ? ORDER BY revision_num DESC",
                (pid,),
            ).fetchall()
        return [
            {
                "revision_id": r["revision_id"],
                "playbook_id": r["playbook_id"],
                "revision_num": int(r["revision_num"]),
                "domain": r["domain"],
                "goal": r["goal"],
                "sha256": r["sha256"],
                "steps": json.loads(r["steps_json"]),
                "created_at_ms": int(r["created_at_ms"]),
            }
            for r in rows
            if not r["deleted"]
        ]

    def rollback_playbook(self, playbook_id: str, target_revision: str, *, expected_revision: str) -> dict[str, Any]:
        pid = re.sub(r"[^a-zA-Z0-9._\-]+", "_", (playbook_id or "").strip())[:100]
        with self._lock, self._connect() as conn:
            latest = conn.execute(
                "SELECT * FROM playbook_revisions WHERE playbook_id = ? AND deleted = 0 ORDER BY revision_num DESC LIMIT 1",
                (pid,),
            ).fetchone()
            if not latest:
                raise ValueError(f"Playbook {pid!r} has no revisions")
            if latest["revision_id"] != expected_revision:
                raise RevisionConflictError(
                    f"Rollback CAS mismatch: expected {expected_revision!r}, current is {latest['revision_id']!r}"
                )
            target = conn.execute(
                "SELECT * FROM playbook_revisions WHERE playbook_id = ? AND revision_id = ? AND deleted = 0",
                (pid, target_revision),
            ).fetchone()
            if not target:
                raise ValueError(f"Target revision {target_revision!r} not found")
            steps = self.redactor.redact_payload(json.loads(target["steps_json"]))
            domain = str(target["domain"] or "")
            goal = str(target["goal"] or "")
            snap = self._insert_playbook_revision_locked(
                conn,
                pid,
                domain=domain,
                goal=goal,
                clean_steps=steps,
                expected_revision=expected_revision,
            )
            if self.playbooks is not None:
                self.playbooks.put_playbook(pid, domain=domain or "local", goal=goal, steps=steps)
        return {"ok": True, "rolled_back_to": target_revision, **snap}

    # ---- Fenced Web Monitors ----
    def create_monitor(
        self,
        *,
        name: str,
        target_url: str,
        workspace_id: str = "default",
        extract_selector: str = "body",
        interval_sec: int = 3600,
        webhook_url: str = "",
    ) -> dict[str, Any]:
        clean_url = validate_navigation_url(target_url)
        if clean_url == "about:blank":
            raise CDPError("Monitor target_url cannot be about:blank")
        clean_webhook = validate_public_webhook_url(webhook_url) if webhook_url.strip() else ""
        mid = f"MON-{secrets.token_hex(5).upper()}"
        now_ms = int(time.time() * 1000)
        clean_name = self.redactor.redact_text((name or clean_url).strip())[:120]
        clean_sel = (extract_selector or "body").strip()[:120] or "body"
        eff_int = max(60, min(86_400 * 7, int(interval_sec)))

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO web_monitors(
                    monitor_id, workspace_id, name, target_url, extract_selector, interval_sec, webhook_url, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (mid, workspace_id[:48], clean_name, clean_url, clean_sel, eff_int, clean_webhook, now_ms),
            )
        return {
            "ok": True,
            "monitor_id": mid,
            "name": clean_name,
            "target_url": clean_url,
            "extract_selector": clean_sel,
            "interval_sec": eff_int,
            "has_webhook": bool(clean_webhook),
        }

    def list_monitors(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            if workspace_id and workspace_id not in ("*", "all"):
                rows = conn.execute(
                    "SELECT * FROM web_monitors WHERE workspace_id = ? ORDER BY created_at_ms DESC",
                    (workspace_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM web_monitors ORDER BY created_at_ms DESC").fetchall()
        return [
            {
                "monitor_id": r["monitor_id"],
                "workspace_id": r["workspace_id"],
                "name": r["name"],
                "target_url": r["target_url"],
                "extract_selector": r["extract_selector"],
                "interval_sec": int(r["interval_sec"]),
                "has_webhook": bool(r["webhook_url"]),
                "lease_epoch": int(r["lease_epoch"]),
                "last_content_sha256": r["last_content_sha256"],
                "enabled": bool(r["enabled"]),
                "created_at_ms": int(r["created_at_ms"]),
            }
            for r in rows
        ]

    def run_monitor(
        self,
        monitor_id: str,
        *,
        worker_id: str = "monitor-worker",
        injected_html: str | None = None,
        webhook_sender: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Acquire fenced `lease_epoch`, extract structured text, diff against prior SHA-256, and record run."""
        mid = (monitor_id or "").strip()
        started_ms = int(time.time() * 1000)
        with self._lock, self._connect() as conn:
            mon = conn.execute("SELECT * FROM web_monitors WHERE monitor_id = ?", (mid,)).fetchone()
            if not mon:
                raise ValueError(f"Monitor {mid!r} not found")
            if not int(mon["enabled"]):
                raise ValueError(f"Monitor {mid!r} is disabled")
            if mon["lease_owner"] and mon["lease_owner"] != worker_id and int(mon["lease_expires_ms"]) > started_ms:
                raise PermissionError(f"Monitor {mid} is actively leased by {mon['lease_owner']}")
            epoch = int(mon["lease_epoch"]) + 1
            conn.execute(
                "UPDATE web_monitors SET lease_owner = ?, lease_expires_ms = ?, lease_epoch = ? WHERE monitor_id = ?",
                (worker_id, started_ms + 30_000, epoch, mid),
            )
            target_url = str(mon["target_url"])
            extract_sel = str(mon["extract_selector"] or "body")
            webhook_url = str(mon["webhook_url"] or "")
            prev_sha = str(mon["last_content_sha256"] or "")
            prev_text = str(mon["last_snapshot_text"] or "")

        try:
            if injected_html is not None:
                scoped_html = _slice_html_by_selector(injected_html, extract_sel)
            elif self.cdp is not None and self.cdp.is_alive():
                tab = self.cdp.open_tab(target_url, background=True)
                try:
                    if extract_sel and extract_sel.lower() not in ("body", "html", "*"):
                        sel_json = json.dumps(extract_sel)
                        scoped_val = self.cdp.evaluate_js(
                            tab["target_id"],
                            f"(() => {{ const n = document.querySelector({sel_json}); return n ? n.outerHTML : ''; }})()",
                        )
                        scoped_html = str(scoped_val or "")
                    else:
                        snap = self.cdp.evaluate_js(tab["target_id"], build_dom_snapshot_js(show_badges=False, agent_label=""))
                        scoped_html = snap.get("outer_html", "") if isinstance(snap, dict) else ""
                finally:
                    try:
                        self.cdp.close_tab(tab["target_id"])
                    except Exception:  # noqa: BLE001
                        pass
            else:
                raise CDPError("CDP browser offline; start Luminara Browser before running live web monitor")
        except Exception:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "UPDATE web_monitors SET lease_expires_ms = 0 WHERE monitor_id = ? AND lease_epoch = ?",
                    (mid, epoch),
                )
            raise

        ext = extract_structured_page(scoped_html or "", target_url)
        canonical_doc = {
            "selector": extract_sel,
            "title": ext.get("title", ""),
            "headings": ext.get("headings", []),
            "rows": ext.get("rows", []),
            "main_text": ext.get("main_text", ""),
            "visible_text": _visible_text_from_html(scoped_html or "")[:4000],
        }
        norm_text = self.redactor.redact_text(
            json.dumps(canonical_doc, sort_keys=True, indent=2, ensure_ascii=False)
        )[:8000]
        cur_sha = hashlib.sha256(norm_text.encode(ENCODING)).hexdigest()
        if not prev_sha:
            status = "INITIALIZED"
            diff_summary = f"Initial baseline captured ({len(ext.get('rows', []))} entities)"
        elif prev_sha == cur_sha:
            status = "UNCHANGED"
            diff_summary = "No structural delta detected"
        else:
            status = "CHANGED"
            diff_lines = list(
                difflib.unified_diff(
                    prev_text.splitlines(),
                    norm_text.splitlines(),
                    lineterm="",
                    n=1,
                )
            )
            diff_summary = " | ".join(ln for ln in diff_lines[2:8])[:300] or "Content SHA-256 changed"

        rec_id = ""
        if self.ledger is not None:
            rec = self.ledger.record(worker_id, "monitor_run", "", {"monitor_id": mid, "status": status}, summary=f"Monitor {mid}: {status}")
            rec_id = rec["receipt_id"]

        finished_ms = int(time.time() * 1000)
        run_id = f"MRUN-{finished_ms}-{cur_sha[:8].upper()}"
        with self._lock, self._connect() as conn:
            cur_row = conn.execute("SELECT lease_epoch FROM web_monitors WHERE monitor_id = ?", (mid,)).fetchone()
            if not cur_row or int(cur_row["lease_epoch"]) != epoch:
                raise RevisionConflictError(f"Stale monitor lease_epoch {epoch} superseded during run")
            conn.execute(
                """
                UPDATE web_monitors
                SET last_content_sha256 = ?, last_snapshot_text = ?, lease_expires_ms = 0
                WHERE monitor_id = ? AND lease_epoch = ?
                """,
                (cur_sha, norm_text, mid, epoch),
            )
            conn.execute(
                """
                INSERT INTO monitor_runs(run_id, monitor_id, started_at_ms, finished_at_ms, status, content_sha256, diff_summary, receipt_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, mid, started_ms, finished_ms, status, cur_sha, diff_summary, rec_id),
            )

        out: dict[str, Any] = {
            "ok": True,
            "run_id": run_id,
            "monitor_id": mid,
            "lease_epoch": epoch,
            "status": status,
            "content_sha256": cur_sha,
            "diff_summary": diff_summary,
            "receipt_id": rec_id,
        }
        if status == "CHANGED" and webhook_url:
            sender = webhook_sender or post_ssrf_pinned_webhook
            wh_payload = {
                "monitor_id": mid,
                "run_id": run_id,
                "status": status,
                "target_url": target_url,
                "content_sha256": cur_sha,
                "diff_summary": diff_summary,
                "receipt_id": rec_id,
            }
            try:
                out["webhook"] = sender(webhook_url, wh_payload)
            except Exception as exc:  # noqa: BLE001
                out["webhook"] = {"dispatched": False, "error": self.redactor.redact_text(str(exc))[:200]}
        return out

    def run_due_monitors(self, *, now_ms: int | None = None) -> list[dict[str, Any]]:
        """Poll and run enabled monitors whose interval has elapsed when live CDP is available."""
        if self.cdp is None or not self.cdp.is_alive():
            return []
        cur_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT m.monitor_id, m.interval_sec,
                       COALESCE((SELECT MAX(r.finished_at_ms) FROM monitor_runs r WHERE r.monitor_id = m.monitor_id), 0) AS last_fin_ms
                FROM web_monitors m
                WHERE m.enabled = 1 AND m.lease_expires_ms <= ?
                """,
                (cur_ms,),
            ).fetchall()
        due_ids = [
            str(r["monitor_id"])
            for r in rows
            if (cur_ms - int(r["last_fin_ms"])) >= int(r["interval_sec"]) * 1000
        ]
        results: list[dict[str, Any]] = []
        for mid in due_ids:
            try:
                results.append(self.run_monitor(mid, worker_id="luminara-scheduler"))
            except Exception:  # noqa: BLE001
                continue
        return results

    def list_monitor_runs(self, monitor_id: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
        lim = max(1, min(100, int(limit)))
        with self._lock, self._connect() as conn:
            if monitor_id:
                rows = conn.execute(
                    "SELECT * FROM monitor_runs WHERE monitor_id = ? ORDER BY started_at_ms DESC LIMIT ?",
                    (monitor_id, lim),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM monitor_runs ORDER BY started_at_ms DESC LIMIT ?", (lim,)).fetchall()
        return [dict(r) for r in rows]

    def delete_monitor(self, monitor_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM web_monitors WHERE monitor_id = ?", ((monitor_id or "").strip(),))
            return cur.rowcount > 0

    # ---- Multi-Provider Search / Extraction Eval Suite ----
    def run_search_eval_suite(
        self,
        *,
        suite: str = "extraction",
        providers: list[str] | None = None,
        cases: list[dict[str, Any]] | None = None,
        provider_caller: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        report = execute_search_eval_suite(
            suite=suite,
            providers=providers,
            cases=cases,
            provider_caller=provider_caller,
        )
        with self._lock:
            self._last_eval_report = report
        return report

    def latest_scorecard(self) -> dict[str, Any]:
        with self._lock:
            if self._last_eval_report is not None:
                return self._last_eval_report
        return self.run_search_eval_suite()
