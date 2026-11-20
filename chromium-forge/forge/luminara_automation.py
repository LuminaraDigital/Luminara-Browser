"""Luminara Browser Automation Primitives (`forge/luminara_automation.py`).

Clean-room, zero-dependency implementation of:
1. `TrajectoryCompressor`: Context-window optimizer that preserves initial and recent steps
   while strictly enforcing `max_chars` across intermediate history.
2. `PlaybookMemory`: Self-improving domain-keyed procedural memory (`outputs/playbooks/`)
   with SHA-256 integrity verification and zero-LLM-call deterministic `replay_playbook()`.
3. `PipelineSandboxRunner`: Single-turn multi-step co-browsing workflow engine (`browser_exec_pipeline`)
   hardened with lexical-closure isolation (`__slots__ = ()`), `format`/`Pow`/`FunctionDef` AST
   guards, bounded `range` (`<= 1000`), and automatic `PAUSED_HUMAN_HANDOFF` enforcement.

License: MIT — Luminara Engineering.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Any
import urllib.parse

from .cdp_client import CDPBridge, CDPError
from .extractor import build_dom_action_js, build_dom_snapshot_js
from .http_base import safe_join
from .luminara_security import atomic_write_private

ENCODING = "utf-8"
MAX_SANDBOX_RANGE = 1000
MAX_SEQ_REPEAT = 10000
_DOMAIN_SLUG_RE = re.compile(r"[^a-z0-9._\-]+")
_GOAL_STOPWORDS = frozenset(
    {"the", "and", "for", "into", "from", "with", "that", "this", "page", "tab", "browser", "please", "then"}
)


class TrajectoryCompressor:
    """Compresses multi-step co-browsing trajectories into a strictly bounded character budget."""

    @staticmethod
    def compress_steps(
        steps: list[dict[str, Any]],
        *,
        protect_head: int = 1,
        protect_tail: int = 3,
        max_chars: int = 1600,
    ) -> list[dict[str, Any]]:
        if not steps:
            return []
        total = len(steps)
        if total <= protect_head + protect_tail:
            return TrajectoryCompressor._trim_fields(steps, max_chars=max_chars)

        head = TrajectoryCompressor._trim_fields(steps[:protect_head], max_chars=max(160, max_chars // 4))
        tail = TrajectoryCompressor._trim_fields(steps[total - protect_tail :], max_chars=max(240, max_chars // 2))
        middle = steps[protect_head : total - protect_tail]

        condensed_actions = [
            f"#{s.get('step', '?')}:{s.get('action', '?')}"
            + (f"[{s['index']}]" if s.get("index") is not None else "")
            for s in middle
        ]
        summary_entry = {
            "step": f"{protect_head + 1}..{total - protect_tail}",
            "action": "compressed_history",
            "reason": f"Compacted {len(middle)} intermediate steps: {', '.join(condensed_actions)[:200]}",
        }
        combined = [*head, summary_entry, *tail]
        while len(combined) > 1 and len(json.dumps(combined, ensure_ascii=False)) > max_chars:
            # Drop oldest tail item (preserving head + summary + newest step) until within budget
            drop_idx = 2 if len(combined) > 2 else 0
            combined.pop(drop_idx)
        return combined

    @staticmethod
    def _trim_fields(steps: list[dict[str, Any]], max_chars: int = 1600) -> list[dict[str, Any]]:
        trimmed: list[dict[str, Any]] = []
        for s in steps:
            item: dict[str, Any] = {
                "step": s.get("step"),
                "action": s.get("action"),
            }
            if s.get("index") is not None:
                item["index"] = s["index"]
            if s.get("text"):
                item["text"] = str(s["text"])[:60]
            if s.get("url"):
                item["url"] = str(s["url"])[:100]
            if s.get("reason"):
                item["reason"] = str(s["reason"])[:90]
            trimmed.append(item)
        while len(trimmed) > 1 and len(json.dumps(trimmed, ensure_ascii=False)) > max_chars:
            trimmed.pop(0)
        if trimmed and len(json.dumps(trimmed, ensure_ascii=False)) > max_chars:
            trimmed[0]["reason"] = str(trimmed[0].get("reason") or "")[:32]
            trimmed[0].pop("url", None)
        return trimmed


def _extract_domain_key(url: str) -> str:
    parsed = urllib.parse.urlparse((url or "").strip())
    host = (parsed.hostname or "local").strip().lower().rstrip(".")
    slug = _DOMAIN_SLUG_RE.sub("_", host).strip("._-")
    return (slug or "local")[:64]


def _goal_tokens(goal: str) -> set[str]:
    return {
        tok
        for tok in re.findall(r"[a-z0-9]{3,}", (goal or "").lower())
        if tok not in _GOAL_STOPWORDS
    }


def _compute_playbook_sha256(steps: list[dict[str, Any]]) -> str:
    canonical = json.dumps(steps, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode(ENCODING)).hexdigest()


class PlaybookMemory:
    """Domain-keyed procedural memory that learns, verifies, and replays multi-step workflows."""

    def __init__(self, playbooks_dir: Path) -> None:
        self.playbooks_dir = playbooks_dir.resolve()
        self.playbooks_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _domain_file(self, domain_key: str) -> Path:
        raw = (domain_key or "local").strip()
        if "://" in raw or "/" in raw:
            raw = _extract_domain_key(raw)
        clean_key = _DOMAIN_SLUG_RE.sub("_", raw.lower()).strip("._-") or "local"
        return safe_join(self.playbooks_dir, f"{clean_key[:64]}.json")

    @staticmethod
    def verify_entry(pb: dict[str, Any]) -> bool:
        steps = pb.get("steps")
        expected = pb.get("sha256")
        if not isinstance(steps, list) or not isinstance(expected, str) or not expected:
            return False
        return secrets.compare_digest(_compute_playbook_sha256(steps), expected)

    def record_successful_run(
        self,
        *,
        url: str,
        goal: str,
        steps: list[dict[str, Any]],
        snapshot_elements: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Distill a completed multi-step run into an origin/domain-keyed playbook."""
        actionable = [s for s in steps if s.get("action") in ("navigate", "type", "click", "scroll", "select")]
        if not actionable:
            return None

        domain_key = _extract_domain_key(url)
        el_by_idx = {int(e["index"]): e for e in (snapshot_elements or []) if "index" in e}

        distilled_steps: list[dict[str, Any]] = []
        for s in actionable[:15]:
            idx = s.get("index")
            fallback_el = el_by_idx.get(int(idx)) if idx is not None and str(idx).isdigit() else None
            step_spec: dict[str, Any] = {
                "action": s["action"],
                "index": idx,
                "selector": str(s.get("selector") or (fallback_el.get("selector", "") if fallback_el else ""))[:180],
                "tag": str(s.get("tag") or (fallback_el.get("tag", "") if fallback_el else ""))[:32],
                "target_text": str(s.get("target_text") or (fallback_el.get("text", "") if fallback_el else ""))[:90],
                "text": str(s.get("text") or "")[:120],
                "url": str(s.get("url") or "")[:240],
                "reason": str(s.get("reason") or "")[:120],
            }
            distilled_steps.append(step_spec)

        tokens = sorted(_goal_tokens(goal))
        pb_id_seed = f"{domain_key}:{'-'.join(tokens[:8])}:{len(distilled_steps)}"
        playbook_id = "pb_" + hashlib.sha256(pb_id_seed.encode(ENCODING)).hexdigest()[:12]
        digest = _compute_playbook_sha256(distilled_steps)

        with self._lock:
            path = self._domain_file(domain_key)
            store: dict[str, Any] = {"domain": domain_key, "playbooks": {}}
            if path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding=ENCODING))
                    if isinstance(loaded, dict) and isinstance(loaded.get("playbooks"), dict):
                        store = loaded
                except Exception:  # noqa: BLE001
                    pass

            existing = store["playbooks"].get(playbook_id, {})
            record = {
                "playbook_id": playbook_id,
                "domain": domain_key,
                "goal_example": goal[:180],
                "goal_tokens": tokens,
                "steps": distilled_steps,
                "sha256": digest,
                "success_count": int(existing.get("success_count", 0)) + 1,
                "last_verified_ms": int(time.time() * 1000),
            }
            store["playbooks"][playbook_id] = record
            atomic_write_private(path, json.dumps(store, indent=2, ensure_ascii=False) + "\n")
            return record

    def get_playbook(self, playbook_id: str) -> dict[str, Any] | None:
        for pb in self.list_playbooks():
            if pb.get("playbook_id") == playbook_id and self.verify_entry(pb):
                return pb
        return None

    def match_playbook(self, url: str, goal: str, min_overlap: float = 0.6) -> dict[str, Any] | None:
        """Find the highest-confidence SHA-256 verified playbook for `url` and `goal` (or across all domains if `url` is omitted)."""
        target_tokens = _goal_tokens(goal)
        if not target_tokens:
            return None

        clean_url = (url or "").strip()
        if clean_url:
            domain_key = _extract_domain_key(clean_url)
            with self._lock:
                path = self._domain_file(domain_key)
                if not path.exists():
                    return None
                try:
                    store = json.loads(path.read_text(encoding=ENCODING))
                except Exception:  # noqa: BLE001
                    return None
            playbooks_map = store.get("playbooks", {})
            candidates = list(playbooks_map.values()) if isinstance(playbooks_map, dict) else []
        else:
            candidates = self.list_playbooks()

        best_pb: dict[str, Any] | None = None
        best_score = 0.0
        for pb in candidates:
            if not isinstance(pb, dict) or not self.verify_entry(pb):
                continue
            pb_tokens = set(pb.get("goal_tokens") or [])
            if not pb_tokens:
                continue
            union_len = len(target_tokens | pb_tokens)
            score = len(target_tokens & pb_tokens) / union_len if union_len else 0.0
            if score >= min_overlap and score > best_score:
                best_score = score
                best_pb = pb
        return best_pb

    @staticmethod
    def _resolve_live_target(step: dict[str, Any], elements: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Resolve a playbook step against live DOM elements (`selector` -> `tag+target_text` -> `index`)."""
        want_sel = str(step.get("selector") or "").strip()
        want_tag = str(step.get("tag") or "").strip().lower()
        want_txt = str(step.get("target_text") or "").strip().lower()
        want_idx = step.get("index")

        if want_sel:
            for el in elements:
                if el.get("selector") == want_sel:
                    return el
        if want_txt:
            for el in elements:
                el_tag = str(el.get("tag") or "").lower()
                el_txt = str(el.get("text") or "").strip().lower()
                if (not want_tag or el_tag == want_tag) and el_txt == want_txt:
                    return el
        if want_idx is not None:
            for el in elements:
                if el.get("index") == want_idx and (not want_tag or str(el.get("tag") or "").lower() == want_tag):
                    return el
        return None

    def replay_playbook(
        self,
        playbook: dict[str, Any],
        *,
        cdp: CDPBridge,
        ledger: Any,
        target_id: str | None = None,
        agent_id: str = "luminara-playbook",
        allow_file: bool = False,
    ) -> dict[str, Any]:
        """Execute a verified playbook in 0 LLM calls; pause on HITL gates or report DOM drift cleanly."""
        if not self.verify_entry(playbook):
            raise ValueError(f"Playbook {playbook.get('playbook_id')!r} failed SHA-256 integrity verification")

        resolved_tid = cdp._pick_target_id(target_id)
        cdp.leases.check_allowed(resolved_tid, agent_id)
        executed_steps: list[dict[str, Any]] = []

        for seq, step in enumerate(playbook.get("steps", []), start=1):
            snap = cdp.evaluate_js(resolved_tid, build_dom_snapshot_js(show_badges=True, agent_label=agent_id))
            if not isinstance(snap, dict):
                raise CDPError("Empty DOM snapshot during playbook replay")
            gate = snap.get("gate_detected")
            if gate:
                return {
                    "ok": True,
                    "status": "PAUSED_HUMAN_HANDOFF",
                    "gate_type": gate,
                    "target_id": resolved_tid,
                    "url": snap.get("url", ""),
                    "playbook_id": playbook["playbook_id"],
                    "steps": executed_steps,
                }

            act = str(step.get("action") or "")
            if act == "navigate" and step.get("url"):
                nav_url = str(step["url"]).strip()
                cdp.navigate(resolved_tid, nav_url, settle_sec=0.5, allow_file=allow_file and nav_url.lower().startswith("file:///"))
                exec_res: dict[str, Any] = {"ok": True, "url": nav_url}
                resolved_idx = None
                resolved_sel = ""
            elif act == "scroll":
                exec_res = cdp.evaluate_js(resolved_tid, build_dom_action_js("scroll")) or {"ok": True}
                resolved_idx = None
                resolved_sel = ""
                time.sleep(0.2)
            elif act in ("click", "type", "select"):
                matched_el = self._resolve_live_target(step, snap.get("elements", []))
                if matched_el is None and not step.get("selector"):
                    return {
                        "ok": False,
                        "status": "DOM_DRIFT",
                        "reason": f"Element for step #{seq} ({act}) not found in live DOM",
                        "target_id": resolved_tid,
                        "playbook_id": playbook["playbook_id"],
                        "steps": executed_steps,
                    }
                resolved_idx = int(matched_el["index"]) if matched_el is not None else None
                resolved_sel = str(matched_el.get("selector") if matched_el is not None else step.get("selector") or "")
                exec_res = (
                    cdp.evaluate_js(
                        resolved_tid,
                        build_dom_action_js(
                            act,
                            index=resolved_idx,
                            selector=resolved_sel if resolved_idx is None else None,
                            text=str(step.get("text") or ""),
                        ),
                    )
                    or {}
                )
                if not exec_res.get("ok"):
                    return {
                        "ok": False,
                        "status": "DOM_DRIFT",
                        "reason": str(exec_res.get("error") or f"Step #{seq} failed"),
                        "target_id": resolved_tid,
                        "playbook_id": playbook["playbook_id"],
                        "steps": executed_steps,
                    }
                time.sleep(0.25)
            else:
                continue

            rec = ledger.record(
                agent_id=agent_id,
                action=f"playbook_{act}",
                target_id=resolved_tid,
                params={"playbook_id": playbook["playbook_id"], "step": seq, "index": resolved_idx},
                status="OK",
                summary=f"Replayed {playbook['playbook_id']} step #{seq} ({act})",
            )
            executed_steps.append(
                {
                    "step": seq,
                    "action": act,
                    "index": resolved_idx,
                    "selector": resolved_sel,
                    "tag": step.get("tag", ""),
                    "target_text": step.get("target_text", ""),
                    "text": step.get("text", ""),
                    "url": step.get("url", ""),
                    "reason": step.get("reason", "Playbook replay"),
                    "result": exec_res,
                    "receipt_id": rec["receipt_id"],
                }
            )

        return {
            "ok": True,
            "status": "COMPLETED",
            "target_id": resolved_tid,
            "playbook_id": playbook["playbook_id"],
            "steps": executed_steps,
        }

    def list_playbooks(self, domain: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            files = (
                [self._domain_file(domain)]
                if domain
                else sorted(self.playbooks_dir.glob("*.json"))
            )
            results: list[dict[str, Any]] = []
            for fpath in files:
                if not fpath.exists():
                    continue
                try:
                    data = json.loads(fpath.read_text(encoding=ENCODING))
                    pbs = data.get("playbooks", {})
                    if isinstance(pbs, dict):
                        results.extend(v for v in pbs.values() if isinstance(v, dict) and self.verify_entry(v))
                except Exception:  # noqa: BLE001
                    continue
        results.sort(key=lambda x: x.get("last_verified_ms", 0), reverse=True)
        return results

    def delete_playbook(self, playbook_id: str) -> bool:
        with self._lock:
            for fpath in self.playbooks_dir.glob("*.json"):
                try:
                    data = json.loads(fpath.read_text(encoding=ENCODING))
                    pbs = data.get("playbooks", {})
                    if isinstance(pbs, dict) and playbook_id in pbs:
                        del pbs[playbook_id]
                        atomic_write_private(fpath, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
                        return True
                except Exception:  # noqa: BLE001
                    continue
        return False


class _PipelineGatePause(Exception):
    """Internal control-flow signal raised when any sandboxed step hits a HITL gate."""

    def __init__(self, gate_type: str) -> None:
        super().__init__(gate_type)
        self.gate_type = gate_type


_DISALLOWED_AST_NODES = (
    ast.AugAssign,
    ast.Import,
    ast.ImportFrom,
    ast.With,
    ast.AsyncWith,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Delete,
    ast.Global,
    ast.Nonlocal,
    ast.Raise,
    ast.Try,
    ast.Yield,
    ast.YieldFrom,
    ast.Lambda,
    ast.While,
)

_DISALLOWED_BINOPS = (ast.Pow, ast.LShift, ast.RShift)
_FORBIDDEN_ATTR_NAMES = frozenset({"format", "format_map"})


def _bounded_range(*args: int) -> range:
    r = range(*args)
    if len(r) > MAX_SANDBOX_RANGE:
        raise ValueError(f"Sandbox range() length {len(r)} exceeds {MAX_SANDBOX_RANGE} limit")
    return r


_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": _bounded_range,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    "True": True,
    "False": False,
    "None": None,
}

_ALLOWED_RPC_METHODS = frozenset(
    {"open_tab", "close_tab", "snapshot", "act", "extract", "generative_ui", "dialog", "wait", "emit"}
)


def validate_pipeline_ast(script: str, max_nodes: int = 400) -> ast.Module:
    """Validate that a Python pipeline script contains zero imports, escapes, or CPU/RAM bombs."""
    if not script or not script.strip():
        raise ValueError("Pipeline script must be non-empty")
    if len(script) > 16000:
        raise ValueError("Pipeline script exceeds 16 KiB limit")

    tree = ast.parse(script, mode="exec")
    node_count = 0
    for node in ast.walk(tree):
        node_count += 1
        if node_count > max_nodes:
            raise ValueError(f"Pipeline script exceeds complexity limit ({max_nodes} AST nodes)")
        if isinstance(node, _DISALLOWED_AST_NODES):
            raise ValueError(f"Forbidden Python construct in pipeline sandbox: {type(node).__name__}")
        if isinstance(node, _DISALLOWED_BINOPS):
            raise ValueError(f"Forbidden operator in pipeline sandbox: {type(node).__name__}")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            has_bounded_int = False
            for side in (node.left, node.right):
                if isinstance(side, ast.BinOp) and isinstance(side.op, ast.Mult):
                    raise ValueError("Chained sequence multiplication is forbidden in pipeline sandbox")
                if isinstance(side, ast.Constant) and isinstance(side.value, int):
                    if abs(side.value) > MAX_SEQ_REPEAT:
                        raise ValueError(f"Multiplication factor exceeds {MAX_SEQ_REPEAT} limit")
                    has_bounded_int = True
            if not has_bounded_int:
                raise ValueError("Multiplication in pipeline sandbox requires an explicit integer constant <= 10000")
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            if len(node.generators) > 2:
                raise ValueError("Comprehension nesting exceeds maximum depth of 2")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError(f"Forbidden private/dunder identifier in pipeline sandbox: {node.id!r}")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in _FORBIDDEN_ATTR_NAMES:
                raise ValueError(f"Forbidden attribute access in pipeline sandbox: {node.attr!r}")
    return tree


class _LuminaraRPCFacade:
    """Zero-dict (`__slots__ = ()`) facade delegating strictly to lexical-closure callables."""

    __slots__ = (
        "act",
        "close_tab",
        "dialog",
        "emit",
        "extract",
        "generative_ui",
        "open_tab",
        "snapshot",
        "wait",
    )

    def __init__(self, methods: dict[str, Callable[..., Any]]) -> None:
        for k, fn in methods.items():
            object.__setattr__(self, k, fn)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("luminara RPC facade is immutable")


def _build_closure_rpc(
    dispatcher: Callable[[str, dict[str, Any]], dict[str, Any]],
    *,
    rpc_token: str,
    agent_id: str,
    max_calls: int = 25,
) -> tuple[_LuminaraRPCFacade, Callable[[], tuple[int, list[dict[str, Any]], list[Any]]]]:
    """Construct an object-capability `luminara` proxy holding zero references on `self`."""
    bounded_max = max(1, min(50, max_calls))
    state_count = 0
    call_log: list[dict[str, Any]] = []
    emitted: list[Any] = []

    def _invoke(token: str, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        nonlocal state_count
        if not rpc_token or not secrets.compare_digest(token.encode(ENCODING), rpc_token.encode(ENCODING)):
            raise PermissionError("Invalid pipeline RPC session token")
        if state_count >= bounded_max:
            raise RuntimeError(f"Pipeline RPC call budget exceeded ({bounded_max} calls)")
        state_count += 1
        t0 = time.monotonic()
        res = dispatcher(tool_name, {**args, "agent_id": agent_id})
        call_log.append(
            {
                "step": state_count,
                "tool": tool_name,
                "duration_ms": round((time.monotonic() - t0) * 1000, 1),
                "receipt_id": (res.get("receipt") or {}).get("receipt_id", "") if isinstance(res, dict) else "",
            }
        )
        snap = res.get("snapshot") if isinstance(res, dict) else None
        if isinstance(snap, dict) and snap.get("gate_detected"):
            emitted.append(res)
            raise _PipelineGatePause(str(snap["gate_detected"]))
        if isinstance(res, dict) and res.get("status") == "PAUSED_HUMAN_HANDOFF":
            emitted.append(res)
            raise _PipelineGatePause(str(res.get("gate_type") or "login_or_mfa_wall"))
        return res

    def open_tab(url: str, background: bool = True) -> dict[str, Any]:
        return _invoke(rpc_token, "browser_open_tab", {"url": url, "background": background})

    def close_tab(target_id: str) -> dict[str, Any]:
        return _invoke(rpc_token, "browser_close_tab", {"target_id": target_id})

    def snapshot(target_id: str | None = None, show_badges: bool = True, frame_id: str | None = None, include_frames: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {"show_badges": show_badges, "include_frames": include_frames}
        if target_id:
            payload["target_id"] = target_id
        if frame_id:
            payload["frame_id"] = frame_id
        return _invoke(rpc_token, "browser_snapshot", payload)

    def act(
        action: str,
        *,
        target_id: str | None = None,
        index: int | None = None,
        selector: str | None = None,
        text: str = "",
        url: str = "",
        frame_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": action, "text": text, "url": url}
        if target_id:
            payload["target_id"] = target_id
        if index is not None:
            payload["index"] = int(index)
        if selector:
            payload["selector"] = selector
        if frame_id:
            payload["frame_id"] = frame_id
        return _invoke(rpc_token, "browser_act", payload)

    def extract(target_id: str | None = None, fmt: str = "json", format: str | None = None) -> dict[str, Any]:  # noqa: A002
        payload: dict[str, Any] = {"format": format or fmt}
        if target_id:
            payload["target_id"] = target_id
        return _invoke(rpc_token, "browser_extract_structured", payload)

    def generative_ui(target_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if target_id:
            payload["target_id"] = target_id
        return _invoke(rpc_token, "browser_generative_ui", payload)

    def dialog(action: str = "status", target_id: str | None = None, prompt_text: str = "", dialog_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": action, "prompt_text": prompt_text}
        if target_id:
            payload["target_id"] = target_id
        if dialog_id:
            payload["dialog_id"] = dialog_id
        return _invoke(rpc_token, "browser_dialog", payload)

    def wait(seconds: float = 0.25) -> dict[str, Any]:
        bounded = max(0.0, min(5.0, float(seconds)))
        time.sleep(bounded)
        return {"ok": True, "slept_sec": bounded}

    def emit(data: Any) -> Any:
        emitted.append(data)
        return data

    facade = _LuminaraRPCFacade(
        {
            "open_tab": open_tab,
            "close_tab": close_tab,
            "snapshot": snapshot,
            "act": act,
            "extract": extract,
            "generative_ui": generative_ui,
            "dialog": dialog,
            "wait": wait,
            "emit": emit,
        }
    )
    return facade, lambda: (state_count, call_log, emitted)


class PipelineSandboxRunner:
    """Executes multi-step browser pipelines in a single turn with zero LLM round-trip overhead."""

    def __init__(self, dispatcher: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
        self._dispatcher = dispatcher

    def run_pipeline(
        self,
        *,
        steps: list[dict[str, Any]] | None = None,
        script: str | None = None,
        max_calls: int = 25,
        agent_id: str = "luminara-pipeline",
    ) -> dict[str, Any]:
        session_token = secrets.token_hex(16)
        facade, read_state = _build_closure_rpc(
            self._dispatcher,
            rpc_token=session_token,
            agent_id=agent_id,
            max_calls=max_calls,
        )

        try:
            if steps is not None:
                if not isinstance(steps, list) or not steps:
                    raise ValueError("Declarative `steps` must be a non-empty list")
                for raw_step in steps:
                    if not isinstance(raw_step, dict):
                        raise ValueError("Each declarative pipeline step must be an object")
                    op = str(raw_step.get("op") or raw_step.get("action") or "").strip()
                    if op not in _ALLOWED_RPC_METHODS:
                        raise ValueError(f"Unsupported pipeline op {op!r}; allowed: {sorted(_ALLOWED_RPC_METHODS)}")
                    skip_keys = {"op"} if op == "act" else {"op", "action"}
                    kwargs = {k: v for k, v in raw_step.items() if k not in skip_keys}
                    if op == "act" and "action" not in kwargs:
                        raise ValueError("Declarative `act` step requires an `action` field")
                    res = getattr(facade, op)(**kwargs)
                    if op != "emit":
                        facade.emit(res)

            elif script is not None:
                tree = validate_pipeline_ast(script)
                compiled = compile(tree, filename="<luminara_pipeline>", mode="exec")
                sandbox_ns: dict[str, Any] = {"__builtins__": dict(_SAFE_BUILTINS), "luminara": facade}
                exec(compiled, sandbox_ns)  # noqa: S102
                count_now, _, emitted_now = read_state()
                if "result" in sandbox_ns and not emitted_now:
                    facade.emit(sandbox_ns["result"])
            else:
                raise ValueError("browser_exec_pipeline requires either `steps` or `script`")
        except _PipelineGatePause as pause:
            calls_exec, call_log, outputs = read_state()
            return {
                "ok": True,
                "status": "PAUSED_HUMAN_HANDOFF",
                "gate_type": pause.gate_type,
                "calls_executed": calls_exec,
                "call_log": call_log,
                "outputs": outputs,
            }

        calls_exec, call_log, outputs = read_state()
        return {
            "ok": True,
            "status": "COMPLETED",
            "calls_executed": calls_exec,
            "call_log": call_log,
            "outputs": outputs,
        }
