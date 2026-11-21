"""SQLite WAL + FTS5 Cross-Tab Knowledge Graph, Workspaces & Tab Hibernation (`forge/knowledge_graph.py`).

Pure Python stdlib (`sqlite3`) persistent memory engine for Luminara Browser:
1. Named **Tab Workspaces** (`Research`, `Engineering`, `Trading`, custom) with time-travel
   snapshots of open tabs and pinned URLs.
2. **Cross-Tab FTS5 Knowledge Graph**: Indexes extracted entities, structured table rows,
   and page citations with source URL + CSS selector + `LUM-*` receipt provenance.
3. **TabLifecycleManager**: Automatically freezes idle background tabs via Chromium CDP
   `Page.setWebLifecycleState(state="frozen")` (never freezing pinned, active, or agent-leased
   tabs) to slash multi-tab RAM footprint below stock Chrome.
"""

from __future__ import annotations

from collections.abc import Iterator
import contextlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any

from .cdp_client import CDPBridge, is_internal_browser_url
from .luminara_security import DEFAULT_REDACTOR, LuminaraRedactor

_WORKSPACE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._\-]{1,48}$")


class KnowledgeWorkspaceStore:
    """Thread-safe SQLite WAL + FTS5 store for Workspaces and Cross-Tab Knowledge Entities."""

    def __init__(self, db_path: Path, *, redactor: LuminaraRedactor | None = None) -> None:
        self.db_path = db_path.resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.redactor = redactor or DEFAULT_REDACTOR
        self._lock = threading.Lock()
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
            conn.execute("PRAGMA synchronous=NORMAL")
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
                CREATE TABLE IF NOT EXISTS workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    pinned_urls_json TEXT NOT NULL DEFAULT '[]',
                    tabs_snapshot_json TEXT NOT NULL DEFAULT '[]',
                    updated_at_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    url TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    entity_name TEXT NOT NULL DEFAULT '',
                    entity_text TEXT NOT NULL DEFAULT '',
                    entity_json TEXT NOT NULL DEFAULT '{}',
                    selector TEXT NOT NULL DEFAULT '',
                    receipt_id TEXT NOT NULL DEFAULT '',
                    created_at_ms INTEGER NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                    entity_name,
                    entity_text,
                    title,
                    url,
                    content='knowledge_entities',
                    content_rowid='id'
                );

                CREATE TRIGGER IF NOT EXISTS kg_ai AFTER INSERT ON knowledge_entities BEGIN
                    INSERT INTO knowledge_fts(rowid, entity_name, entity_text, title, url)
                    VALUES (new.id, new.entity_name, new.entity_text, new.title, new.url);
                END;

                CREATE TRIGGER IF NOT EXISTS kg_ad AFTER DELETE ON knowledge_entities BEGIN
                    INSERT INTO knowledge_fts(knowledge_fts, rowid, entity_name, entity_text, title, url)
                    VALUES ('delete', old.id, old.entity_name, old.entity_text, old.title, old.url);
                END;

                CREATE TRIGGER IF NOT EXISTS kg_au AFTER UPDATE ON knowledge_entities BEGIN
                    INSERT INTO knowledge_fts(knowledge_fts, rowid, entity_name, entity_text, title, url)
                    VALUES ('delete', old.id, old.entity_name, old.entity_text, old.title, old.url);
                    INSERT INTO knowledge_fts(rowid, entity_name, entity_text, title, url)
                    VALUES (new.id, new.entity_name, new.entity_text, new.title, new.url);
                END;

                CREATE TABLE IF NOT EXISTS resource_leases (
                    resource_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    lease_epoch INTEGER NOT NULL,
                    expires_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                ) STRICT;
                """
            )
            now_ms = int(time.time() * 1000)
            for wid, name, desc in (
                ("research", "Research", "Deep web synthesis & Generative UI matrices"),
                ("engineering", "Engineering", "Docs, repos, DevTools & WebMCP workflows"),
                ("default", "Default", "General human + AI co-browsing workspace"),
            ):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO workspaces(workspace_id, name, description, updated_at_ms)
                    VALUES (?, ?, ?, ?)
                    """,
                    (wid, name, desc, now_ms),
                )

    def upsert_workspace(
        self,
        workspace_id: str,
        *,
        name: str | None = None,
        description: str = "",
        pinned_urls: list[str] | None = None,
        tabs_snapshot: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        wid = (workspace_id or "").strip().lower()
        if not _WORKSPACE_ID_RE.match(wid):
            raise ValueError(f"Invalid workspace_id {workspace_id!r}")
        now_ms = int(time.time() * 1000)
        with self._lock, self._connect() as conn:
            existing = conn.execute("SELECT * FROM workspaces WHERE workspace_id = ?", (wid,)).fetchone()
            final_name = self.redactor.redact_text((name or (existing["name"] if existing else wid.title())).strip())[:80]
            final_desc = self.redactor.redact_text(description if description else (existing["description"] if existing else ""))
            raw_pinned = pinned_urls if pinned_urls is not None else json.loads(existing["pinned_urls_json"] if existing else "[]")
            raw_tabs = tabs_snapshot if tabs_snapshot is not None else json.loads(existing["tabs_snapshot_json"] if existing else "[]")
            final_pinned = self.redactor.redact_payload(raw_pinned)
            final_tabs = self.redactor.redact_payload(raw_tabs)
            conn.execute(
                """
                INSERT INTO workspaces(workspace_id, name, description, pinned_urls_json, tabs_snapshot_json, updated_at_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    pinned_urls_json = excluded.pinned_urls_json,
                    tabs_snapshot_json = excluded.tabs_snapshot_json,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (
                    wid,
                    final_name,
                    final_desc[:240],
                    json.dumps(final_pinned, ensure_ascii=False),
                    json.dumps(final_tabs, ensure_ascii=False),
                    now_ms,
                ),
            )
        return self.get_workspace(wid) or {}

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id.strip().lower(),)).fetchone()
            if not row:
                return None
            cnt = conn.execute(
                "SELECT COUNT(*) AS c FROM knowledge_entities WHERE workspace_id = ?",
                (row["workspace_id"],),
            ).fetchone()["c"]
            return {
                "workspace_id": row["workspace_id"],
                "name": row["name"],
                "description": row["description"],
                "pinned_urls": json.loads(row["pinned_urls_json"]),
                "tabs_snapshot": json.loads(row["tabs_snapshot_json"]),
                "entity_count": int(cnt),
                "updated_at_ms": int(row["updated_at_ms"]),
            }

    def list_workspaces(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT w.*, COUNT(ke.id) AS entity_count
                FROM workspaces w
                LEFT JOIN knowledge_entities ke ON ke.workspace_id = w.workspace_id
                GROUP BY w.workspace_id
                ORDER BY w.updated_at_ms DESC
                """
            ).fetchall()
        return [
            {
                "workspace_id": r["workspace_id"],
                "name": r["name"],
                "description": r["description"],
                "pinned_urls": json.loads(r["pinned_urls_json"]),
                "tabs_snapshot": json.loads(r["tabs_snapshot_json"]),
                "entity_count": int(r["entity_count"] or 0),
                "updated_at_ms": int(r["updated_at_ms"]),
            }
            for r in rows
        ]

    def index_entities(
        self,
        *,
        workspace_id: str = "default",
        url: str,
        title: str = "",
        rows: list[dict[str, Any]],
        receipt_id: str = "",
    ) -> int:
        """Index extracted structured rows into the cross-tab FTS5 knowledge graph (scrubbed at rest)."""
        if not rows:
            return 0
        wid = (workspace_id or "").strip().lower() or "default"
        if not _WORKSPACE_ID_RE.match(wid):
            raise ValueError(f"Invalid workspace_id {workspace_id!r}")
        clean_url = self.redactor.redact_text(url or "")[:500]
        clean_title = self.redactor.redact_text(title or "")[:200]
        clean_rows = self.redactor.redact_payload(rows[:200])
        now_ms = int(time.time() * 1000)
        inserted = 0
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO workspaces(workspace_id, name, description, updated_at_ms)
                VALUES (?, ?, '', ?)
                """,
                (wid, wid.replace("_", " ").replace("-", " ").title()[:80], now_ms),
            )
            for item in clean_rows:
                if not isinstance(item, dict):
                    continue
                ename = str(
                    item.get("name")
                    or item.get("title")
                    or item.get("item")
                    or next((v for v in item.values() if isinstance(v, str) and v.strip()), "")
                )[:160]
                etext = " ".join(f"{k}: {v}" for k, v in item.items() if v not in (None, ""))[:1200]
                selector = str(item.get("_selector") or item.get("selector") or "")[:160]
                serialized = json.dumps(item, ensure_ascii=False)
                if len(serialized) > 2400:
                    compacted = {str(k)[:64]: (v[:280] if isinstance(v, str) else v) for k, v in list(item.items())[:25]}
                    serialized = json.dumps(compacted, ensure_ascii=False)
                    if len(serialized) > 2400:
                        serialized = json.dumps({"name": ename, "summary": etext[:1800]}, ensure_ascii=False)
                conn.execute(
                    """
                    DELETE FROM knowledge_entities
                    WHERE workspace_id = ? AND url = ? AND entity_name = ? AND entity_text = ?
                    """,
                    (wid, clean_url, ename, etext),
                )
                conn.execute(
                    """
                    INSERT INTO knowledge_entities(
                        workspace_id, url, title, entity_name, entity_text, entity_json, selector, receipt_id, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        wid,
                        clean_url,
                        clean_title,
                        ename,
                        etext,
                        serialized,
                        selector,
                        receipt_id[:80],
                        now_ms,
                    ),
                )
                inserted += 1
        return inserted

    def search_knowledge(
        self,
        query: str,
        *,
        workspace_id: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Execute a safe FTS5 BM25-ranked search across all indexed tabs and entities."""
        tokens = re.findall(r"\w+", query or "")
        if not tokens:
            return []
        fts_expr = " AND ".join(f'"{t}"*' for t in tokens[:8])
        lim = max(1, min(100, int(limit)))
        norm_ws = (workspace_id or "").strip().lower()
        filter_ws = norm_ws if norm_ws and norm_ws not in ("all", "*") else None
        with self._lock, self._connect() as conn:
            if filter_ws:
                rows = conn.execute(
                    """
                    SELECT ke.*, bm25(knowledge_fts) AS rank
                    FROM knowledge_fts
                    JOIN knowledge_entities ke ON ke.id = knowledge_fts.rowid
                    WHERE knowledge_fts MATCH ? AND ke.workspace_id = ?
                    ORDER BY rank ASC, ke.created_at_ms DESC
                    LIMIT ?
                    """,
                    (fts_expr, filter_ws, lim),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT ke.*, bm25(knowledge_fts) AS rank
                    FROM knowledge_fts
                    JOIN knowledge_entities ke ON ke.id = knowledge_fts.rowid
                    WHERE knowledge_fts MATCH ?
                    ORDER BY rank ASC, ke.created_at_ms DESC
                    LIMIT ?
                    """,
                    (fts_expr, lim),
                ).fetchall()
            if not rows and any(ord(ch) > 127 for ch in (query or "")):
                like_conds = " AND ".join(
                    "(ke.entity_name LIKE ? ESCAPE '\\' OR ke.entity_text LIKE ? ESCAPE '\\' OR ke.title LIKE ? ESCAPE '\\')"
                    for _ in tokens[:8]
                )
                like_args: list[Any] = []
                for t in tokens[:8]:
                    esc = "%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                    like_args.extend([esc, esc, esc])
                ws_clause = " AND ke.workspace_id = ?" if filter_ws else ""
                if filter_ws:
                    like_args.append(filter_ws)
                like_args.append(lim)
                rows = conn.execute(
                    f"""
                    SELECT ke.*, 0.0 AS rank
                    FROM knowledge_entities ke
                    WHERE {like_conds}{ws_clause}
                    ORDER BY ke.created_at_ms DESC
                    LIMIT ?
                    """,
                    tuple(like_args),
                ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                parsed_entity = json.loads(r["entity_json"])
            except Exception:  # noqa: BLE001
                parsed_entity = {"text": r["entity_text"]}
            out.append(
                {
                    "id": int(r["id"]),
                    "workspace_id": r["workspace_id"],
                    "url": r["url"],
                    "title": r["title"],
                    "entity_name": r["entity_name"],
                    "entity_text": r["entity_text"],
                    "entity": parsed_entity,
                    "selector": r["selector"],
                    "receipt_id": r["receipt_id"],
                    "created_at_ms": int(r["created_at_ms"]),
                }
            )
        return out

    def acquire_fenced_lease(
        self,
        resource_id: str,
        owner_id: str,
        *,
        ttl_ms: int = 30_000,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        """SPACE-style monotonic fencing-token (`lease_epoch`) checkout with automatic expiry reconciliation."""
        rid = (resource_id or "").strip()[:160]
        oid = (owner_id or "").strip()[:120]
        if not rid or not oid:
            raise ValueError("resource_id and owner_id must be non-empty")
        cur_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        eff_ttl = max(1000, min(3_600_000, int(ttl_ms)))
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM resource_leases WHERE resource_id = ?", (rid,)).fetchone()
            if row and row["owner_id"] and row["owner_id"] != oid and int(row["expires_at_ms"]) > cur_ms:
                raise PermissionError(
                    f"Resource {rid!r} is actively leased by {row['owner_id']!r} (epoch {row['lease_epoch']})"
                )
            next_epoch = (int(row["lease_epoch"]) + 1) if row else 1
            exp_ms = cur_ms + eff_ttl
            conn.execute(
                """
                INSERT INTO resource_leases(resource_id, owner_id, lease_epoch, expires_at_ms, updated_at_ms)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(resource_id) DO UPDATE SET
                    owner_id = excluded.owner_id,
                    lease_epoch = excluded.lease_epoch,
                    expires_at_ms = excluded.expires_at_ms,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (rid, oid, next_epoch, exp_ms, cur_ms),
            )
        return {"resource_id": rid, "owner_id": oid, "lease_epoch": next_epoch, "expires_at_ms": exp_ms}

    def verify_fenced_epoch(self, resource_id: str, owner_id: str, expected_epoch: int, *, now_ms: int | None = None) -> bool:
        """Fail closed if a newer worker epoch superseded this lease or the lease expired."""
        cur_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM resource_leases WHERE resource_id = ?", ((resource_id or "").strip(),)).fetchone()
            if not row:
                return False
            return (
                row["owner_id"] == (owner_id or "").strip()
                and int(row["lease_epoch"]) == int(expected_epoch)
                and int(row["expires_at_ms"]) > cur_ms
            )


class TabLifecycleManager:
    """Freezes idle background tabs via CDP `Page.setWebLifecycleState` to cut RAM footprint."""

    def __init__(self, cdp: CDPBridge) -> None:
        self.cdp = cdp
        self._lock = threading.Lock()
        self._pinned: set[str] = set()
        self._frozen: set[str] = set()
        self._last_active: dict[str, float] = {}

    def touch_tab(self, target_id: str) -> None:
        with self._lock:
            self._last_active[target_id] = time.time()
            self._frozen.discard(target_id)

    def pin_tab(self, target_id: str, pinned: bool = True) -> None:
        with self._lock:
            if pinned:
                self._pinned.add(target_id)
            else:
                self._pinned.discard(target_id)

    def evaluate_candidates(
        self,
        tabs: list[dict[str, Any]],
        *,
        active_target_id: str | None = None,
        min_idle_sec: float = 0.0,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Partition tabs into `(freeze_eligible, protected)` respecting leases, pins, and active tab."""
        now = time.time()
        eligible: list[dict[str, Any]] = []
        protected: list[dict[str, Any]] = []
        with self._lock:
            pinned_copy = set(self._pinned)
            last_copy = dict(self._last_active)

        for idx, tab in enumerate(tabs):
            tid = str(tab.get("target_id") or "")
            url = str(tab.get("url") or "")
            reason = ""
            if not tid:
                continue
            if tid == active_target_id or (active_target_id is None and idx == 0):
                reason = "active_tab"
            elif tid in pinned_copy:
                reason = "pinned"
            elif tab.get("lease") or self.cdp.leases.get_active(tid):
                reason = "agent_leased"
            elif is_internal_browser_url(url, cdp_port=self.cdp.port):
                reason = "internal_ui"
            elif min_idle_sec > 0 and (now - last_copy.get(tid, 0.0)) < min_idle_sec:
                reason = "recently_active"

            if reason:
                protected.append({"target_id": tid, "url": url, "reason": reason})
            else:
                eligible.append({"target_id": tid, "url": url})
        return eligible, protected

    def hibernate_idle_tabs(
        self,
        *,
        active_target_id: str | None = None,
        min_idle_sec: float = 0.0,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Freeze all eligible background tabs using `Page.setWebLifecycleState('frozen')`."""
        tabs = self.cdp.list_tabs(include_extensions=False)
        eligible, protected = self.evaluate_candidates(
            tabs,
            active_target_id=active_target_id,
            min_idle_sec=min_idle_sec,
        )
        frozen_now: list[str] = []
        errors: list[dict[str, str]] = []
        if not dry_run:
            for item in eligible:
                tid = item["target_id"]
                try:
                    self.cdp.run_session(
                        tid,
                        [("Page.enable", {}), ("Page.setWebLifecycleState", {"state": "frozen"})],
                        timeout=5.0,
                    )
                    with self._lock:
                        self._frozen.add(tid)
                    frozen_now.append(tid)
                except Exception as exc:  # noqa: BLE001
                    errors.append({"target_id": tid, "error": str(exc)})
        else:
            frozen_now = [item["target_id"] for item in eligible]

        total = len(tabs)
        return {
            "ok": True,
            "dry_run": dry_run,
            "total_tabs": total,
            "frozen_count": len(frozen_now),
            "protected_count": len(protected),
            "freeze_ratio": round(len(frozen_now) / total, 3) if total else 0.0,
            "frozen_target_ids": frozen_now,
            "protected": protected,
            "errors": errors,
        }

    def wake_tab(self, target_id: str) -> dict[str, Any]:
        self.cdp.run_session(
            target_id,
            [("Page.enable", {}), ("Page.setWebLifecycleState", {"state": "active"})],
            timeout=5.0,
        )
        self.touch_tab(target_id)
        return {"ok": True, "target_id": target_id, "state": "active"}

    def snapshot_workspace(self, store: KnowledgeWorkspaceStore, workspace_id: str, name: str | None = None) -> dict[str, Any]:
        tabs = self.cdp.list_tabs(include_extensions=False) if self.cdp.is_alive() else []
        compact = [{"target_id": t["target_id"], "title": t.get("title", ""), "url": t.get("url", "")} for t in tabs]
        return store.upsert_workspace(workspace_id, name=name, tabs_snapshot=compact)
