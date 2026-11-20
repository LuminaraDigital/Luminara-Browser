"""Hybrid Blink `AXTree` + Shadow-DOM + OOPIF Perception & Hardware Input (`forge/perception.py`).

Solves three core limitations of DOM-only scrapers:
1. Pierces open Shadow DOM roots (`el.shadowRoot`) and Site-Isolated OOPIFs via flattened CDP sessions.
2. Uses Chromium's native `Accessibility.getFullAXTree` semantic roles/names/states with `backendDOMNodeId`
   targeting (removing the hard 80-node ceiling and indexing up to 250+ semantic controls).
3. Dispatches compositor-level trusted hardware input (`Input.dispatchMouseEvent`, `Input.insertText`,
   `Input.dispatchKeyEvent`) after `DOM.scrollIntoViewIfNeeded`, ensuring React 19, Radix, Monaco,
   and ProseMirror editors accept actions identically to human keyboard/mouse input.
"""

from __future__ import annotations

import json
from typing import Any

from .cdp_client import CDPBridge, CDPError

INTERACTIVE_AX_ROLES = frozenset(
    {
        "button",
        "link",
        "textbox",
        "searchbox",
        "combobox",
        "listbox",
        "option",
        "checkbox",
        "radio",
        "switch",
        "slider",
        "spinbutton",
        "tab",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "treeitem",
        "gridcell",
    }
)


def parse_ax_tree_nodes(
    ax_nodes: list[dict[str, Any]],
    *,
    max_nodes: int = 250,
    frame_id: str = "",
    start_index: int = 1,
    oopif_target_id: str = "",
) -> list[dict[str, Any]]:
    """Distill raw CDP `Accessibility.getFullAXTree` nodes into compact interactive semantic targets."""
    elements: list[dict[str, Any]] = []
    idx = max(1, int(start_index))
    limit = idx + max(1, int(max_nodes)) - 1
    for node in ax_nodes:
        if idx > limit:
            break
        if node.get("ignored"):
            continue
        role_val = str((node.get("role") or {}).get("value") or "").lower()
        if role_val not in INTERACTIVE_AX_ROLES:
            continue

        name_val = str((node.get("name") or {}).get("value") or "").strip()
        val_obj = node.get("value") or {}
        cur_val = str(val_obj.get("value") or "").strip() if isinstance(val_obj, dict) else ""
        desc_val = str((node.get("description") or {}).get("value") or "").strip()

        props: dict[str, Any] = {}
        for prop in node.get("properties") or []:
            pname = str(prop.get("name") or "")
            pval = (prop.get("value") or {}).get("value")
            if pname in ("disabled", "focused", "checked", "expanded", "required", "readonly", "selected", "url"):
                props[pname] = pval

        if props.get("disabled") is True:
            continue

        backend_id = node.get("backendDOMNodeId")
        if not name_val and not cur_val and backend_id is None:
            continue

        elements.append(
            {
                "index": idx,
                "source": "axtree",
                "ax_node_id": str(node.get("nodeId") or ""),
                "backend_node_id": int(backend_id) if backend_id is not None else None,
                "frame_id": str(node.get("frameId") or frame_id),
                "role": role_val,
                "name": name_val[:120],
                "value": cur_val[:120],
                "description": desc_val[:120],
                "states": {k: v for k, v in props.items() if v not in (None, False, "")},
                "is_input": role_val in ("textbox", "searchbox", "combobox", "spinbutton", "slider"),
                **({"oopif_target_id": oopif_target_id} if oopif_target_id else {}),
            }
        )
        idx += 1
    return elements


def build_shadow_piercing_snapshot_js(*, max_elements: int = 250) -> str:
    """JS walker that recursively pierces open `shadowRoot` trees and same-origin iframes."""
    return f"""
(() => {{
  const MAX_EL = {int(max(20, min(500, max_elements)))};
  const interactiveSel = [
    'a[href]', 'button', 'input:not([type="hidden"])', 'select', 'textarea',
    'summary', '[role="button"]', '[role="link"]', '[role="tab"]', '[role="menuitem"]',
    '[role="checkbox"]', '[role="switch"]', '[role="combobox"]', '[contenteditable="true"]'
  ].join(',');

  const results = [];
  let shadowHostsVisited = 0;

  function collectFromRoot(root, win, offsetX, offsetY, shadowPath, framePath) {{
    if (!root || results.length >= MAX_EL) return;
    const nodes = root.querySelectorAll(interactiveSel);
    for (const el of nodes) {{
      if (results.length >= MAX_EL) break;
      if (el.closest && el.closest('[aria-hidden="true"], [hidden]')) continue;
      const rect = el.getBoundingClientRect();
      if (rect.width < 4 || rect.height < 4) continue;
      const style = win.getComputedStyle(el);
      if (style.visibility === 'hidden' || style.display === 'none' || parseFloat(style.opacity || '1') === 0) continue;
      const tag = el.tagName.toLowerCase();
      const label = String(
        el.getAttribute('aria-label') || el.innerText || el.value ||
        el.getAttribute('placeholder') || el.getAttribute('title') || ''
      ).trim().replace(/\\s+/g, ' ').slice(0, 120);
      results.push({{
        index: results.length + 1,
        source: shadowPath ? 'shadow_dom' : (framePath ? 'iframe' : 'dom'),
        tag,
        role: el.getAttribute('role') || tag,
        name: label,
        href: el.getAttribute('href') || '',
        shadow_path: shadowPath,
        frame_path: framePath,
        x: Math.round(rect.left + offsetX + rect.width / 2),
        y: Math.round(rect.top + offsetY + rect.height / 2),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        is_input: ['input', 'textarea', 'select'].includes(tag) || Boolean(el.isContentEditable)
      }});
    }}

    // Recursively pierce open Shadow DOM hosts
    const allEls = root.querySelectorAll('*');
    for (const host of allEls) {{
      if (results.length >= MAX_EL) break;
      if (host.shadowRoot) {{
        shadowHostsVisited++;
        const hostTag = host.tagName.toLowerCase() + (host.id ? '#' + host.id : '');
        const nextShadow = shadowPath ? `${{shadowPath}} >>> ${{hostTag}}` : hostTag;
        collectFromRoot(host.shadowRoot, win, offsetX, offsetY, nextShadow, framePath);
      }}
      if (host.tagName === 'IFRAME') {{
        try {{
          if (host.contentDocument && host.contentWindow) {{
            const fr = host.getBoundingClientRect();
            const fLabel = host.id ? '#' + host.id : (host.name || 'iframe');
            collectFromRoot(host.contentDocument, host.contentWindow, offsetX + fr.left, offsetY + fr.top, shadowPath, framePath ? `${{framePath}} > ${{fLabel}}` : fLabel);
          }}
        }} catch (_e) {{}}
      }}
    }}
  }}

  collectFromRoot(document, window, 0, 0, '', '');
  return {{
    url: location.href,
    title: document.title || '',
    shadow_hosts_pierced: shadowHostsVisited,
    elements: results
  }};
}})()
"""


class HybridPerceptionEngine:
    """Combines Chromium `AXTree`, Shadow-DOM piercing, and OOPIF flattening into one unified view."""

    def __init__(self, cdp: CDPBridge) -> None:
        self.cdp = cdp

    def capture_ax_snapshot(
        self,
        target_id: str | None = None,
        *,
        max_nodes: int = 250,
        include_shadow_dom: bool = True,
    ) -> dict[str, Any]:
        """Fetch native `Accessibility.getFullAXTree` + optional Shadow-DOM geometry enrichment."""
        resolved_tid = self.cdp._pick_target_id(target_id)
        ax_elements: list[dict[str, Any]] = []
        ax_raw_count = 0
        ax_error = ""

        try:
            _tid, res = self.cdp.run_session(
                resolved_tid,
                [
                    ("Accessibility.enable", {}),
                    ("Accessibility.getFullAXTree", {"depth": 12}),
                ],
                timeout=15.0,
            )
            nodes = (res[-1] or {}).get("nodes") or []
            ax_raw_count = len(nodes)
            ax_elements = parse_ax_tree_nodes(nodes, max_nodes=max_nodes)
        except Exception as exc:  # noqa: BLE001
            ax_error = str(exc)

        shadow_data: dict[str, Any] = {}
        if include_shadow_dom:
            try:
                js_res = self.cdp.evaluate_js(resolved_tid, build_shadow_piercing_snapshot_js(max_elements=max_nodes))
                if isinstance(js_res, dict):
                    shadow_data = js_res
            except Exception:  # noqa: BLE001
                shadow_data = {}

        # Also inspect cross-origin OOPIF targets if present
        oopif_elements: list[dict[str, Any]] = []
        frames = []
        try:
            frames = self.cdp.get_frame_tree(resolved_tid)
        except Exception:  # noqa: BLE001
            frames = []

        for fr in frames:
            if fr.get("is_cross_origin") and fr.get("frame_id"):
                oopif_tid = str(fr.get("oopif_target_id") or "")
                try:
                    if oopif_tid:
                        _tid, f_res = self.cdp.run_session(
                            oopif_tid,
                            [
                                ("Accessibility.enable", {}),
                                ("Accessibility.getFullAXTree", {"depth": 8}),
                            ],
                            timeout=6.0,
                        )
                    else:
                        _tid, f_res = self.cdp.run_session(
                            resolved_tid,
                            [("Accessibility.getFullAXTree", {"frameId": fr["frame_id"], "depth": 8})],
                            timeout=6.0,
                        )
                    f_nodes = (f_res[-1] or {}).get("nodes") or []
                    next_idx = len(ax_elements) + len(oopif_elements) + 1
                    oopif_elements.extend(
                        parse_ax_tree_nodes(
                            f_nodes,
                            max_nodes=40,
                            frame_id=fr["frame_id"],
                            start_index=next_idx,
                            oopif_target_id=oopif_tid,
                        )
                    )
                except Exception:  # noqa: BLE001
                    continue

        return {
            "target_id": resolved_tid,
            "url": shadow_data.get("url", ""),
            "title": shadow_data.get("title", ""),
            "ax_raw_node_count": ax_raw_count,
            "ax_interactive_count": len(ax_elements),
            "oopif_interactive_count": len(oopif_elements),
            "shadow_hosts_pierced": int(shadow_data.get("shadow_hosts_pierced") or 0),
            "elements": ax_elements if ax_elements else list(shadow_data.get("elements") or []),
            "shadow_elements": list(shadow_data.get("elements") or [])[:max_nodes],
            "oopif_elements": oopif_elements,
            "frames": frames,
            **({"ax_error": ax_error} if ax_error else {}),
        }

    def dispatch_hardware_click(
        self,
        target_id: str | None,
        *,
        backend_node_id: int | None = None,
        x: float | None = None,
        y: float | None = None,
    ) -> dict[str, Any]:
        """Resolve `backendDOMNodeId` box model (if provided) and dispatch real compositor mouse events."""
        resolved_tid = self.cdp._pick_target_id(target_id)
        click_x, click_y = x, y

        if backend_node_id is not None:
            _tid, res = self.cdp.run_session(
                resolved_tid,
                [
                    ("DOM.enable", {}),
                    ("DOM.scrollIntoViewIfNeeded", {"backendNodeId": int(backend_node_id)}),
                    ("DOM.getBoxModel", {"backendNodeId": int(backend_node_id)}),
                ],
                timeout=10.0,
            )
            model = (res[-1] or {}).get("model") or {}
            content_quad = model.get("content") or model.get("border") or []
            if len(content_quad) >= 8:
                xs = content_quad[0::2]
                ys = content_quad[1::2]
                click_x = sum(xs) / len(xs)
                click_y = sum(ys) / len(ys)

        if click_x is None or click_y is None:
            raise CDPError("Hardware click requires either backend_node_id or (x, y) coordinates")

        self.cdp.dispatch_mouse_click(resolved_tid, float(click_x), float(click_y))
        return {
            "ok": True,
            "target_id": resolved_tid,
            "mode": "compositor_hardware_click",
            "x": round(float(click_x), 1),
            "y": round(float(click_y), 1),
            "backend_node_id": backend_node_id,
        }

    def dispatch_hardware_type(
        self,
        target_id: str | None,
        text: str,
        *,
        backend_node_id: int | None = None,
        press_enter: bool = False,
    ) -> dict[str, Any]:
        """Focus target via compositor click/focus and emit native `Input.insertText` + optional Enter."""
        resolved_tid = self.cdp._pick_target_id(target_id)
        cmds: list[tuple[str, dict[str, Any]]] = []
        if backend_node_id is not None:
            cmds.extend(
                [
                    ("DOM.enable", {}),
                    ("DOM.scrollIntoViewIfNeeded", {"backendNodeId": int(backend_node_id)}),
                    ("DOM.focus", {"backendNodeId": int(backend_node_id)}),
                ]
            )
        cmds.append(("Input.insertText", {"text": text}))
        if press_enter:
            cmds.append(("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13}))
            cmds.append(("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13}))
        self.cdp.run_session(resolved_tid, cmds, timeout=12.0)
        return {
            "ok": True,
            "target_id": resolved_tid,
            "mode": "compositor_hardware_type",
            "chars_inserted": len(text),
            "press_enter": press_enter,
        }
