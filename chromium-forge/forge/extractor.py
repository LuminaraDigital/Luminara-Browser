"""Clean-room OBL-10 & OBL-13: Set-of-Marks DOM Indexer, Structured Extractor & Generative UI Synthesizer.

Hardened production upgrades:
- Clears stale `[data-luminara-idx]` markers on re-snapshot (eliminating post-scroll ghost clicks).
- Uses Trusted-Types-safe `document.createElement` + `textContent` for the Co-Presence HUD (zero `innerHTML` XSS).
- Preserves nested inline tags (`<b>`, `<span>`, `<code>`, `<a>`) inside headings and paragraphs in `_StructuredDOMParser`.
- Unions columns across all extracted rows and guards CSV cells against spreadsheet formula injection (`=`, `+`, `-`, `@`).
"""

from __future__ import annotations

import csv
from html.parser import HTMLParser
import io
import json
import re
from typing import Any

DOM_SNAPSHOT_JS_TEMPLATE = r"""
(() => {
  const showBadges = __SHOW_BADGES__;
  const agentLabel = __AGENT_LABEL__;
  document.querySelectorAll('.__luminara_som_badge, #__luminara_agent_hud').forEach(e => e.remove());
  document.querySelectorAll('[data-luminara-idx]').forEach(e => e.removeAttribute('data-luminara-idx'));

  function cssPath(el) {
    if (el.id && /^[a-zA-Z][\w-]*$/.test(el.id)) return '#' + CSS.escape(el.id);
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 5) {
      let seg = cur.tagName.toLowerCase();
      if (cur.id && /^[a-zA-Z][\w-]*$/.test(cur.id)) {
        parts.unshift('#' + CSS.escape(cur.id));
        break;
      }
      const parent = cur.parentElement;
      if (parent) {
        const sibs = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
        if (sibs.length > 1) seg += `:nth-of-type(${sibs.indexOf(cur) + 1})`;
      }
      parts.unshift(seg);
      cur = parent;
    }
    return parts.join(' > ');
  }

  const interactiveSel = [
    'a[href]', 'button', 'input:not([type="hidden"])', 'select', 'textarea',
    'summary', '[role="button"]', '[role="link"]', '[role="tab"]', '[role="menuitem"]',
    '[contenteditable="true"]', '[onclick]'
  ].join(',');

  const candidates = Array.from(document.querySelectorAll(interactiveSel));
  const elements = [];
  let idx = 1;

  for (const el of candidates) {
    if (idx > 80) break;
    if (el.getAttribute('aria-hidden') === 'true') continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none' || parseFloat(style.opacity || '1') === 0) continue;
    const inViewport = rect.bottom >= 0 && rect.right >= 0 && rect.top <= window.innerHeight && rect.left <= window.innerWidth;
    if (!inViewport) continue;

    el.setAttribute('data-luminara-idx', String(idx));
    const tag = el.tagName.toLowerCase();
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('title') || '').trim().replace(/\s+/g, ' ').slice(0, 90);
    elements.push({
      index: idx,
      tag,
      type: el.getAttribute('type') || '',
      role: el.getAttribute('role') || tag,
      text,
      href: el.getAttribute('href') || '',
      placeholder: el.getAttribute('placeholder') || '',
      selector: cssPath(el),
      x: Math.round(rect.left + rect.width / 2),
      y: Math.round(rect.top + rect.height / 2),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      is_input: ['input', 'textarea', 'select'].includes(tag) || el.isContentEditable
    });

    if (showBadges) {
      const badge = document.createElement('div');
      badge.className = '__luminara_som_badge';
      badge.textContent = String(idx);
      badge.style.cssText = `position:fixed;left:${Math.max(0, Math.round(rect.left))}px;top:${Math.max(0, Math.round(rect.top) - 16)}px;z-index:2147483646;background:#10b981;color:#06110c;font:700 10px/1.2 Consolas,monospace;padding:1px 5px;border-radius:4px;pointer-events:none;box-shadow:0 2px 6px rgba(0,0,0,0.45);`;
      document.documentElement.appendChild(badge);
    }
    idx++;
  }

  if (showBadges && agentLabel) {
    const hud = document.createElement('div');
    hud.id = '__luminara_agent_hud';
    hud.style.cssText = 'position:fixed;bottom:14px;right:14px;z-index:2147483647;background:rgba(15,18,25,0.92);color:#ecfdf5;border:1px solid rgba(16,185,129,0.55);border-radius:999px;padding:6px 12px;font:600 11px/1.2 -apple-system,Segoe UI,sans-serif;display:flex;align-items:center;gap:8px;box-shadow:0 8px 24px rgba(0,0,0,0.4);backdrop-filter:blur(8px);';
    const dot = document.createElement('span');
    dot.style.cssText = 'width:7px;height:7px;border-radius:50%;background:#10b981;box-shadow:0 0 8px #10b981;';
    const lbl = document.createElement('span');
    lbl.textContent = `${agentLabel} · ${elements.length} targets indexed`;
    hud.append(dot, lbl);
    document.documentElement.appendChild(hud);
  }

  // Detect standard authentication / human verification gates (never bypass — report for HITL handoff!)
  const bodyLower = (document.body ? document.body.innerText : '').slice(0, 4000).toLowerCase();
  const hasPasswordInput = Boolean(document.querySelector('input[type="password"]'));
  const hasChallengeFrame = Boolean(
    document.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], #cf-challenge-running, [data-sitekey]')
  );
  let gateType = null;
  if (hasChallengeFrame || /verify you are human|security check|enable javascript and cookies to continue/i.test(bodyLower)) {
    gateType = 'human_verification_gate';
  } else if (hasPasswordInput && /sign in|log in|two-factor|verification code|2fa/i.test(bodyLower)) {
    gateType = 'login_or_mfa_wall';
  }

  return {
    url: location.href,
    title: document.title,
    viewport: { width: window.innerWidth, height: window.innerHeight, scrollY: Math.round(window.scrollY) },
    gate_detected: gateType,
    elements,
    outer_html: document.documentElement ? document.documentElement.outerHTML.slice(0, 250000) : ''
  };
})()
"""


def build_dom_snapshot_js(show_badges: bool = True, agent_label: str = "Luminara Agent") -> str:
    return DOM_SNAPSHOT_JS_TEMPLATE.replace(
        "__SHOW_BADGES__", "true" if show_badges else "false"
    ).replace("__AGENT_LABEL__", json.dumps(str(agent_label)[:64]))


def build_dom_action_js(action: str, index: int | None = None, selector: str | None = None, text: str = "") -> str:
    """Build safe in-page DOM action script (click, type, select, scroll, clear_hud) with cursor pulse."""
    safe_idx = int(index) if index is not None else None
    target_expr = (
        f"document.querySelector('[data-luminara-idx=\"{safe_idx}\"]')"
        if safe_idx is not None
        else f"document.querySelector({json.dumps(selector or '')})"
    )
    return f"""
(() => {{
  const act = {json.dumps(action)};
  if (act === 'clear_hud') {{
    document.querySelectorAll('.__luminara_som_badge, #__luminara_agent_hud').forEach(e => e.remove());
    document.querySelectorAll('[data-luminara-idx]').forEach(e => e.removeAttribute('data-luminara-idx'));
    return {{ ok: true, action: 'clear_hud' }};
  }}
  if (act === 'scroll') {{
    window.scrollBy({{ top: Math.round(window.innerHeight * 0.75), behavior: 'instant' }});
    return {{ ok: true, action: 'scroll', scrollY: Math.round(window.scrollY) }};
  }}
  let el = null;
  try {{
    el = {target_expr};
  }} catch (err) {{
    return {{ ok: false, error: 'Invalid CSS selector: ' + String(err) }};
  }}
  if (!el) return {{ ok: false, error: 'Target element not found in live DOM' }};
  el.scrollIntoView({{ block: 'center', inline: 'center', behavior: 'instant' }});
  const rect = el.getBoundingClientRect();

  const ring = document.createElement('div');
  ring.style.cssText = `position:fixed;left:${{rect.left - 4}}px;top:${{rect.top - 4}}px;width:${{rect.width + 8}}px;height:${{rect.height + 8}}px;border:2px solid #10b981;border-radius:8px;z-index:2147483647;pointer-events:none;transition:opacity 0.45s ease;`;
  document.documentElement.appendChild(ring);
  setTimeout(() => {{ ring.style.opacity = '0'; setTimeout(() => ring.remove(), 450); }}, 350);

  if (act === 'click') {{
    el.focus();
    el.click();
    return {{ ok: true, action: 'click', tag: el.tagName.toLowerCase(), x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + rect.height / 2) }};
  }}
  if (act === 'type' || act === 'select') {{
    el.focus();
    const val = {json.dumps(text)};
    if (el.tagName === 'SELECT') {{
      el.value = val;
    }} else {{
      const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      const desc = Object.getOwnPropertyDescriptor(proto, 'value');
      if (desc && desc.set) desc.set.call(el, val);
      else el.value = val;
    }}
    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    return {{ ok: true, action: act, length: val.length }};
  }}
  return {{ ok: false, error: 'Unsupported DOM action: ' + act }};
}})()
"""


class _StructuredDOMParser(HTMLParser):
    """Pure-stdlib clean-room HTML structure extractor preserving inline text inside blocks."""

    SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "template", "iframe"})
    BLOCK_TEXT_TAGS = frozenset({"title", "h1", "h2", "h3", "h4", "p"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._active_block = ""
        self._buf: list[str] = []
        self.title = ""
        self.description = ""
        self.headings: list[str] = []
        self.paragraphs: list[str] = []
        self.links: list[dict[str, str]] = []
        self._link_href: str | None = None
        self._link_buf: list[str] = []
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._cur_table: list[list[str]] = []
        self._cur_row: list[str] = []
        self._in_cell = False
        self._cell_buf: list[str] = []
        self.lists: list[list[str]] = []
        self._cur_list: list[str] | None = None
        self._in_li = False
        self._li_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return

        attr_map = {k.lower(): (v or "") for k, v in attrs}
        # Prune elements explicitly marked hidden in HTML attributes (defends against hidden DOM prompt injection!)
        style_low = attr_map.get("style", "").lower().replace(" ", "")
        if (
            "hidden" in attr_map
            or attr_map.get("aria-hidden", "").lower() == "true"
            or "display:none" in style_low
            or "visibility:hidden" in style_low
            or "opacity:0" in style_low
            or "font-size:0" in style_low
        ):
            self._skip_depth += 1
            self._hidden_tag_stack.append(t)
            return

        if t == "meta" and attr_map.get("name", "").lower() == "description":
            self.description = attr_map.get("content", "").strip()
        elif t in self.BLOCK_TEXT_TAGS:
            self._active_block = t
            self._buf = []
        elif t == "a" and attr_map.get("href", "").startswith(("http://", "https://")):
            self._link_href = attr_map["href"]
            self._link_buf = []
        elif t == "table" and len(self.tables) < 6:
            self._in_table = True
            self._cur_table = []
        elif t == "tr" and self._in_table:
            self._cur_row = []
        elif t in ("td", "th") and self._in_table:
            self._in_cell = True
            self._cell_buf = []
        elif t in ("ul", "ol") and len(self.lists) < 10 and self._cur_list is None:
            self._cur_list = []
        elif t == "li" and self._cur_list is not None:
            self._in_li = True
            self._li_buf = []

    @property
    def _hidden_tag_stack(self) -> list[str]:
        if not hasattr(self, "_hidden_stack_list"):
            self._hidden_stack_list: list[str] = []
        return self._hidden_stack_list

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._active_block:
            self._buf.append(data)
        if self._link_href is not None:
            self._link_buf.append(data)
        if self._in_cell:
            self._cell_buf.append(data)
        if self._in_li:
            self._li_buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._hidden_tag_stack and self._hidden_tag_stack[-1] == t:
            self._hidden_tag_stack.pop()
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth > 0:
            return

        if t == self._active_block:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if t == "title" and text and not self.title:
                self.title = text
            elif t in ("h1", "h2", "h3", "h4") and text and len(self.headings) < 30:
                self.headings.append(text)
            elif t == "p" and len(text) > 15 and len(self.paragraphs) < 40:
                self.paragraphs.append(text)
            self._active_block = ""
            self._buf = []

        if t == "a" and self._link_href is not None:
            ltxt = re.sub(r"\s+", " ", "".join(self._link_buf)).strip()
            if ltxt and len(self.links) < 50:
                self.links.append({"text": ltxt[:80], "url": self._link_href})
            self._link_href = None
        elif t in ("td", "th") and self._in_cell:
            cell = re.sub(r"\s+", " ", "".join(self._cell_buf)).strip()
            self._cur_row.append(cell[:300])
            self._in_cell = False
        elif t == "tr" and self._in_table:
            if any(self._cur_row) and len(self._cur_table) < 60:
                self._cur_table.append(self._cur_row)
        elif t == "table" and self._in_table:
            if self._cur_table:
                self.tables.append(self._cur_table)
            self._in_table = False
        elif t == "li" and self._in_li and self._cur_list is not None:
            item = re.sub(r"\s+", " ", "".join(self._li_buf)).strip()
            if item and len(self._cur_list) < 25:
                self._cur_list.append(item[:240])
            self._in_li = False
        elif t in ("ul", "ol") and self._cur_list is not None:
            if self._cur_list:
                self.lists.append(self._cur_list)
            self._cur_list = None


def extract_structured_page(html_source: str, source_url: str = "") -> dict[str, Any]:
    """Parse raw HTML into structured tables, rows, headings, lists, links, and main_text."""
    parser = _StructuredDOMParser()
    parser.feed(html_source or "")

    rows: list[dict[str, Any]] = []
    for tbl in parser.tables:
        if len(tbl) >= 2 and len(tbl[0]) >= 2:
            headers = [h or f"col_{i + 1}" for i, h in enumerate(tbl[0])]
            for r in tbl[1:]:
                if len(r) == len(headers):
                    row_dict = {headers[i]: r[i] for i in range(len(headers))}
                    row_dict["_source_url"] = source_url
                    rows.append(row_dict)

    if not rows and parser.lists:
        for idx, item in enumerate(parser.lists[0][:30], start=1):
            rows.append({"rank": idx, "item": item, "page": parser.title or source_url, "_source_url": source_url})
    if not rows and parser.links:
        for idx, lnk in enumerate(parser.links[:25], start=1):
            rows.append({"index": idx, "title": lnk["text"], "url": lnk["url"], "_source_url": source_url})
    if not rows:
        rows.append(
            {
                "title": parser.title or source_url or "Untitled Page",
                "summary": parser.description or (parser.paragraphs[0] if parser.paragraphs else ""),
                "headings_count": len(parser.headings),
                "links_count": len(parser.links),
                "_source_url": source_url,
            }
        )

    return {
        "url": source_url,
        "title": parser.title,
        "description": parser.description,
        "headings": parser.headings,
        "main_text": "\n\n".join(parser.paragraphs)[:12000],
        "tables": parser.tables,
        "lists": parser.lists,
        "links": parser.links,
        "rows": rows[:60],
    }


_CURRENCY_RE = re.compile(r"^\s*([$€£¥]|AUD|USD)\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE)
_PERCENT_RE = re.compile(r"^\s*(-?[0-9]+(?:\.[0-9]+)?)\s*%\s*$")
_NUMBER_RE = re.compile(r"^\s*(-?[0-9][0-9,]*(?:\.[0-9]+)?)\s*$")
_KEY_METRIC_TERMS = ("price", "cost", "score", "rating", "stars", "views", "users", "count", "total", "revenue", "latency", "rank")
_CSV_FORMULA_RE = re.compile(r"^[=+\-@\t\r]")


def classify_attribute_widget(name: str, value: Any) -> tuple[str, float | None, int]:
    """Return `(widget_type, numeric_value, priority_score)` matching `attributeIntelligence`."""
    lname = name.lower()
    if lname.startswith("_"):
        return ("meta", None, -50)

    sval = str(value).strip() if value is not None else ""
    bonus = 20 if any(t in lname for t in _KEY_METRIC_TERMS) else 0

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        widget = "currency" if ("price" in lname or "cost" in lname) else "number"
        return (widget, float(value), 75 + bonus)

    m_cur = _CURRENCY_RE.match(sval)
    if m_cur:
        return ("currency", float(m_cur.group(2).replace(",", "")), 90 + bonus)

    m_pct = _PERCENT_RE.match(sval)
    if m_pct:
        return ("percentage", float(m_pct.group(1)), 80 + bonus)

    m_num = _NUMBER_RE.match(sval)
    if m_num:
        return ("number", float(m_num.group(1).replace(",", "")), 65 + bonus)

    if sval.startswith(("http://", "https://")):
        return ("url", None, 35)
    if len(sval) > 120:
        return ("long_text", None, 25)
    return ("short_text", None, 50 + bonus)


def synthesize_generative_ui(rows: list[dict[str, Any]], title: str = "Extracted Workspace") -> dict[str, Any]:
    """Transform extracted rows into `EntityStore` entities, `SummaryBar` KPIs, and view specs."""
    entities: list[dict[str, Any]] = []
    numeric_buckets: dict[str, list[float]] = {}

    for idx, row in enumerate(rows[:60], start=1):
        attrs: list[dict[str, Any]] = []
        pub_id = ""
        for k, v in row.items():
            widget, num_val, score = classify_attribute_widget(str(k), v)
            if not pub_id and widget == "short_text" and v:
                pub_id = str(v)[:70]
            if num_val is not None and widget != "meta":
                numeric_buckets.setdefault(str(k), []).append(num_val)
            attrs.append(
                {
                    "name": str(k),
                    "value": v,
                    "widget": widget,
                    "numeric_value": num_val,
                    "score": score,
                    "category": "meta" if widget == "meta" else ("detail" if widget == "long_text" else "key"),
                    "editable": widget != "meta",
                }
            )
        attrs.sort(key=lambda a: a["score"], reverse=True)
        entities.append(
            {
                "id": f"ent_{idx:03d}",
                "type": "Item",
                "public_identifier": pub_id or f"Record #{idx}",
                "attributes": attrs,
            }
        )

    summary_bar: dict[str, Any] | None = None
    if numeric_buckets:
        m_name, vals = max(numeric_buckets.items(), key=lambda kv: len(kv[1]))
        if vals:
            avg_val = sum(vals) / len(vals)
            summary_bar = {
                "metric_name": m_name,
                "count": len(vals),
                "min": round(min(vals), 2),
                "max": round(max(vals), 2),
                "avg": round(avg_val, 2),
                "spread_pct": round(((max(vals) - min(vals)) / avg_val * 100.0) if avg_val else 0.0, 1),
            }

    recommended_view = "table" if len(entities) >= 4 else ("comparison" if len(entities) >= 2 else "stack")
    return {
        "title": title,
        "entity_count": len(entities),
        "recommended_view": recommended_view,
        "summary_bar": summary_bar,
        "entities": entities,
    }


def _safe_csv_cell(val: Any) -> str:
    s = "" if val is None else str(val)
    if _CSV_FORMULA_RE.match(s):
        s = "'" + s
    return s


def format_extracted_rows(rows: list[dict[str, Any]], fmt: str = "json") -> str:
    fmt = fmt.lower()
    if fmt == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False)
    if not rows:
        return ""
    seen_cols: list[str] = []
    for r in rows:
        for k in r.keys():
            if not k.startswith("_") and k not in seen_cols:
                seen_cols.append(k)
    cols = seen_cols or list(rows[0].keys())

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\r\n")
        writer.writeheader()
        for r in rows:
            writer.writerow({c: _safe_csv_cell(r.get(c, "")) for c in cols})
        return buf.getvalue()
    if fmt in ("md", "markdown"):
        esc_md = lambda v: str(v if v is not None else "").replace("\r", " ").replace("\n", " ").replace("|", "\\|")
        header = "| " + " | ".join(esc_md(c) for c in cols) + " |"
        sep = "| " + " | ".join("---" for _ in cols) + " |"
        body = ["| " + " | ".join(esc_md(r.get(c, "")) for c in cols) + " |" for r in rows]
        return "\n".join([header, sep, *body])
    return "\n".join(" — ".join(f"{c}: {r.get(c, '')}" for c in cols) for r in rows)
