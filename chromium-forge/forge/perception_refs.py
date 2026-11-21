"""Stable-ref accessibility outline, outline diffing, settle detection and untrusted fencing.

Complements `forge/perception.py`: where the Set-of-Marks and AXTree snapshots hand out
per-snapshot indices, this module gives each control a ref (`e1`, `e2`, ...) that stays the
same for as long as the document does, so an agent can act on a ref it saw several calls ago
and can ask "what changed?" instead of re-reading the page.
"""

from __future__ import annotations

from collections.abc import Callable
import difflib
import json
import re
import secrets
import time
from typing import Any

from .perception import INTERACTIVE_AX_ROLES

# Roles that carry no meaning of their own: their children are lifted to the parent's depth.
_TRANSPARENT_ROLES = frozenset({"none", "generic", "presentation", "inlinetextbox", "linebreak", ""})
_TEXT_ROLES = frozenset({"statictext", "text"})
_MAX_LABEL = 160

# Counts DOM mutations in the page. Install and read happen in one evaluation, so a navigation
# that wipes the counter is visible as `fresh: true` rather than as a falsely quiet page.
SETTLE_PROBE_JS = """
(() => {
  const KEY = '__luminaraSettle';
  let st = window[KEY];
  const fresh = !st;
  if (fresh) {
    st = window[KEY] = { n: 0 };
    try {
      new MutationObserver((recs) => { st.n += recs.length; })
        .observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
    } catch (_e) {}
  }
  return { count: st.n, fresh, ready: document.readyState, url: location.href };
})()
"""


def fence_untrusted(text: str, origin: str = "") -> str:
    """Wrap page-derived text in markers a page cannot forge (the nonce is new on every call)."""
    nonce = secrets.token_hex(8)
    clean_origin = re.sub(r"[^\w.:/\-]", "", origin)[:120]
    return f"<<LUMINARA_UNTRUSTED_PAGE nonce={nonce} origin={clean_origin}>>\n{text}\n<<END_LUMINARA_UNTRUSTED_PAGE nonce={nonce}>>"


def _ax_value(node: dict[str, Any], key: str) -> str:
    raw = node.get(key)
    val = raw.get("value") if isinstance(raw, dict) else None
    return " ".join(str(val).split())[:_MAX_LABEL] if val not in (None, "") else ""


class RefRegistry:
    """Maps controls to refs that survive re-snapshots of the same document."""

    def __init__(self) -> None:
        self.doc_id = ""
        self._next = 1
        self._by_backend: dict[int, str] = {}
        self._identity: dict[str, tuple[str, str, int]] = {}  # ref -> (role, name, nth)
        self._live: dict[str, int] = {}  # ref -> backend id, as of the latest outline

    def assign_all(self, doc_id: str, controls: list[tuple[int, str, str]]) -> list[str]:
        """Refs for one outline pass, given `(backend_id, role, name)` per control in order.

        A new document invalidates every earlier ref. Within a document a control keeps its ref;
        a control whose node was re-created (framework re-render) inherits the ref of the vanished
        control that had the same role, name and position among its namesakes.
        """
        if doc_id != self.doc_id:
            self.doc_id = doc_id
            self._next = 1
            self._by_backend.clear()
            self._identity.clear()
        seen: dict[tuple[str, str], int] = {}
        identities: list[tuple[str, str, int]] = []
        for _backend_id, role, name in controls:
            nth = seen.get((role, name), 0)
            seen[(role, name)] = nth + 1
            identities.append((role, name, nth))
        present = {backend_id for backend_id, _role, _name in controls}
        # Only refs whose node is gone from this pass may be inherited, so two live nodes never share one.
        orphans = {
            ident: ref
            for ref, ident in self._identity.items()
            if self._live.get(ref) not in present
        }
        refs: list[str] = []
        live: dict[str, int] = {}
        for (backend_id, _role, _name), identity in zip(controls, identities):
            ref = self._by_backend.get(backend_id) or orphans.pop(identity, None)
            if ref is None or ref in live:
                ref = f"e{self._next}"
                self._next += 1
            self._by_backend[backend_id] = ref
            self._identity[ref] = identity
            live[ref] = backend_id
            refs.append(ref)
        self._live = live
        return refs

    def resolve(self, ref: str) -> int:
        """Backend node id for a ref from the latest outline; raises if the control is gone."""
        backend_id = self._live.get(str(ref).strip())
        if backend_id is None:
            raise ValueError(f"Unknown or stale ref {ref!r}: take a new outline snapshot")
        return backend_id


def render_ax_outline(
    nodes: list[dict[str, Any]],
    registry: RefRegistry,
    doc_id: str,
    *,
    interactive_only: bool = False,
    max_lines: int = 1200,
) -> list[str]:
    """Render raw `Accessibility.getFullAXTree` nodes as an indented outline with stable refs.

    Names and values are JSON-quoted, so page text can never be read as another line's ref.
    """
    controls: list[tuple[int, str, str]] = []
    control_lines: list[int] = []
    by_id = {str(n.get("nodeId")): n for n in nodes}
    child_ids = {cid for n in nodes for cid in (str(c) for c in n.get("childIds") or [])}
    roots = [n for n in nodes if str(n.get("nodeId")) not in child_ids]
    lines: list[str] = []
    # Explicit stack: accessibility trees can be deeper than Python's recursion limit allows.
    stack: list[tuple[dict[str, Any], int]] = [(n, 0) for n in reversed(roots)]
    visited: set[str] = set()
    while stack and len(lines) < max_lines:
        node, depth = stack.pop()
        nid = str(node.get("nodeId"))
        if nid in visited:
            continue
        visited.add(nid)
        role = _ax_value(node, "role").lower()
        name = _ax_value(node, "name")
        value = _ax_value(node, "value")
        backend_id = node.get("backendDOMNodeId")
        interactive = role in INTERACTIVE_AX_ROLES and backend_id is not None
        skip = bool(node.get("ignored")) or role in _TRANSPARENT_ROLES
        if not skip and role in _TEXT_ROLES:
            skip = interactive_only or not name
        elif not skip and interactive_only and not interactive:
            skip = True
        elif not skip and not interactive and not name:
            skip = True
        if not skip:
            line = f"{'  ' * depth}- {'text' if role in _TEXT_ROLES else role}"
            if name:
                line += f" {json.dumps(name, ensure_ascii=False)}"
            if value and value != name:
                line += f" value={json.dumps(value, ensure_ascii=False)}"
            if interactive:
                controls.append((int(backend_id), role, name))
                control_lines.append(len(lines))
            lines.append(line)
        child_depth = depth if skip else depth + 1
        for cid in reversed(node.get("childIds") or []):
            child = by_id.get(str(cid))
            if child is not None:
                stack.append((child, child_depth))
    for line_no, ref in zip(control_lines, registry.assign_all(doc_id, controls)):
        lines[line_no] += f" [ref={ref}]"
    return lines


def diff_outline(old: list[str], new: list[str], *, context: int = 1, max_lines: int = 200) -> dict[str, Any]:
    """Line diff between two outlines: `+` added, `-` removed, with a little unchanged context."""
    body = [ln for ln in difflib.unified_diff(old, new, lineterm="", n=max(0, context))][2:]
    added = sum(1 for ln in body if ln.startswith("+"))
    removed = sum(1 for ln in body if ln.startswith("-"))
    return {
        "changed": bool(added or removed),
        "added": added,
        "removed": removed,
        "lines": body[:max_lines],
        "truncated": len(body) > max_lines,
    }


def wait_settled(
    probe: Callable[[], Any],
    *,
    quiet_sec: float = 0.3,
    timeout_sec: float = 8.0,
    poll_sec: float = 0.1,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Block until the page is loaded and its DOM has stopped changing for `quiet_sec`.

    `probe` evaluates `SETTLE_PROBE_JS` and returns its result. A probe that fails (mid-navigation)
    or reports a fresh counter counts as activity.
    """
    start = clock()
    last_count: int | None = None
    quiet_since = start
    polls = 0
    while True:
        try:
            state = probe()
        except Exception:  # noqa: BLE001 - execution context torn down by a navigation
            state = None
        polls += 1
        now = clock()
        ok = isinstance(state, dict) and not state.get("fresh") and state.get("ready") == "complete"
        count = int(state.get("count") or 0) if isinstance(state, dict) else -1
        if not ok or count != last_count:
            quiet_since = now
        last_count = count
        if ok and now - quiet_since >= quiet_sec:
            return {"settled": True, "waited_ms": round((now - start) * 1000), "polls": polls}
        if now - start >= timeout_sec:
            return {"settled": False, "waited_ms": round((now - start) * 1000), "polls": polls}
        sleep(poll_sec)


class OutlinePerception:
    """Per-tab outline state: the ref registry and the last outline, used for diffs."""

    def __init__(self, cdp: Any) -> None:
        self.cdp = cdp
        self._tabs: dict[str, tuple[RefRegistry, list[str]]] = {}

    def forget(self, target_id: str) -> None:
        self._tabs.pop(target_id, None)

    def _capture(self, target_id: str | None, interactive_only: bool) -> tuple[str, str, list[str], list[str]]:
        tid, res = self.cdp.run_session(
            target_id,
            [("Page.getFrameTree", {}), ("Accessibility.enable", {}), ("Accessibility.getFullAXTree", {})],
            timeout=15.0,
        )
        frame = ((res[0] or {}).get("frameTree") or {}).get("frame") or {}
        doc_id = f"{frame.get('id', '')}:{frame.get('loaderId', '')}"
        registry, previous = self._tabs.get(tid) or (RefRegistry(), [])
        if registry.doc_id != doc_id:
            previous = []
        lines = render_ax_outline((res[-1] or {}).get("nodes") or [], registry, doc_id, interactive_only=interactive_only)
        self._tabs[tid] = (registry, lines)
        return tid, str(frame.get("url") or ""), previous, lines

    def snapshot(self, target_id: str | None = None, *, interactive_only: bool = False) -> dict[str, Any]:
        tid, url, _previous, lines = self._capture(target_id, interactive_only)
        return {
            "target_id": tid,
            "url": url,
            "line_count": len(lines),
            "ref_count": sum(1 for ln in lines if ln.endswith("]") and "[ref=e" in ln),
            "outline": fence_untrusted("\n".join(lines), url),
        }

    def diff(self, target_id: str | None = None, *, interactive_only: bool = False) -> dict[str, Any]:
        """Changes since the previous outline of this tab; a new document returns the full outline."""
        tid, url, previous, lines = self._capture(target_id, interactive_only)
        if not previous:
            return {"target_id": tid, "url": url, "new_document": True, "outline": fence_untrusted("\n".join(lines), url)}
        delta = diff_outline(previous, lines)
        delta["lines"] = fence_untrusted("\n".join(delta["lines"]), url)
        return {"target_id": tid, "url": url, "new_document": False, **delta}

    def grep(self, target_id: str | None, pattern: str, *, max_hits: int = 60) -> dict[str, Any]:
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from exc
        tid, url, _previous, lines = self._capture(target_id, False)
        hits = [ln.strip() for ln in lines if rx.search(ln)]
        return {
            "target_id": tid,
            "url": url,
            "hit_count": len(hits),
            "hits": fence_untrusted("\n".join(hits[:max_hits]), url),
        }

    def backend_node_for(self, target_id: str, ref: str) -> int:
        entry = self._tabs.get(target_id)
        if entry is None:
            raise ValueError("No outline for this tab yet: call browser_outline action=snapshot first")
        return entry[0].resolve(ref)

    def settle(self, target_id: str | None, *, quiet_sec: float = 0.3, timeout_sec: float = 8.0) -> dict[str, Any]:
        return wait_settled(
            lambda: self.cdp.evaluate_js(target_id, SETTLE_PROBE_JS),
            quiet_sec=quiet_sec,
            timeout_sec=timeout_sec,
        )
