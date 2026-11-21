"""W3C WebMCP (`navigator.modelContext`) Runtime & Auto-Form Tool Compiler (`forge/webmcp.py`).

Implements the W3C Web Machine Learning CG WebMCP architecture inside Luminara Browser:
1. Imperative API (`navigator.modelContext.registerTool`, `unregisterTool`, `provideContext`):
   Allows web apps to expose structured JSON-Schema tools directly inside the user's live tab.
2. Declarative HTML API (`<form toolname="..." tooldescription="...">`) + Automatic Semantic
   Form Compiler: Synthesizes zero-vision-token typed MCP tools from standard HTML forms so
   agents can invoke structured page workflows in 1 deterministic call instead of 10+ DOM steps.
3. Permissions Policy Isolation: Cross-origin iframes cannot expose or execute tools unless
   explicitly allowed; all responses pass through `LuminaraRedactor` before leaving the daemon.
"""

from __future__ import annotations

import json
import re
from typing import Any
import urllib.parse

from .cdp_client import (
    _INTERNAL_CONTROL_PORTS,
    CDPBridge,
    CDPError,
    _is_loopback_or_unspecified_host,
    validate_navigation_url,
)

WEBMCP_BOOTSTRAP_JS = r"""
(() => {
  if (window.__luminaraWebMCP) return;
  const MAX_REGISTERED_TOOLS = 64;
  const registry = new Map();
  let pageContext = {};

  function cloneSchema(schema) {
    try { return JSON.parse(JSON.stringify(schema || { type: 'object', properties: {} })); }
    catch (_e) { return { type: 'object', properties: {} }; }
  }

  const api = {
    registerTool(spec) {
      if (!spec || typeof spec.name !== 'string' || !spec.name.trim()) {
        throw new TypeError('WebMCP registerTool requires a non-empty string name');
      }
      if (typeof spec.execute !== 'function') {
        throw new TypeError('WebMCP registerTool requires an execute() function');
      }
      const key = spec.name.trim().slice(0, 96);
      if (!registry.has(key) && registry.size >= MAX_REGISTERED_TOOLS) {
        throw new RangeError('WebMCP registry limit (64 tools) reached');
      }
      registry.set(key, {
        name: key,
        description: String(spec.description || '').slice(0, 400),
        inputSchema: cloneSchema(spec.inputSchema),
        readOnlyHint: Boolean(spec.annotations && spec.annotations.readOnlyHint),
        source: 'imperative',
        execute: spec.execute
      });
      return key;
    },
    unregisterTool(name) {
      return registry.delete(String(name || '').trim());
    },
    provideContext(ctx) {
      if (ctx && typeof ctx === 'object') {
        const clean = {};
        for (const [k, v] of Object.entries(ctx)) {
          if (k !== '__proto__' && k !== 'constructor' && k !== 'prototype' && k !== 'tools') {
            clean[k] = v;
          }
        }
        pageContext = Object.assign({}, pageContext, clean);
        if (Array.isArray(ctx.tools)) {
          for (const t of ctx.tools) api.registerTool(t);
        }
      }
    },
    clearContext() {
      registry.clear();
      pageContext = {};
    }
  };

  try {
    if (!('modelContext' in navigator)) {
      Object.defineProperty(navigator, 'modelContext', {
        value: api,
        configurable: true,
        enumerable: true
      });
    }
  } catch (_e) {}

  window.__luminaraWebMCP = {
    registry,
    getContext: () => pageContext,
    api
  };
})();
"""

_DISCOVER_WEBMCP_JS = WEBMCP_BOOTSTRAP_JS + r"""
(() => {
  const tools = [];
  const seen = new Set();

  // 1. Imperative tools registered via navigator.modelContext.registerTool()
  if (window.__luminaraWebMCP && window.__luminaraWebMCP.registry) {
    for (const [name, entry] of window.__luminaraWebMCP.registry.entries()) {
      seen.add(name);
      tools.push({
        name,
        description: entry.description || `Invoke imperative WebMCP tool ${name}`,
        inputSchema: entry.inputSchema || { type: 'object', properties: {} },
        source: 'imperative',
        readOnlyHint: Boolean(entry.readOnlyHint),
        origin: window.location.origin
      });
    }
  }

  // 2. Declarative <form toolname="..."> + Automatic Semantic Form Compilation
  const forms = Array.from(document.querySelectorAll('form')).slice(0, 20);
  forms.forEach((form, idx) => {
    const explicitName = (form.getAttribute('toolname') || '').trim();
    const fallbackBase = (form.id || form.getAttribute('name') || `form_${idx + 1}`)
      .toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '') || `form_${idx + 1}`;
    const toolName = explicitName || `page_form_${fallbackBase}`;
    if (seen.has(toolName)) return;

    const props = {};
    const required = [];
    const fields = Array.from(form.querySelectorAll('input, select, textarea'));
    for (const el of fields) {
      const type = (el.getAttribute('type') || el.tagName.toLowerCase()).toLowerCase();
      if (['hidden', 'submit', 'button', 'reset', 'image', 'password'].includes(type)) continue;
      const fname = (el.getAttribute('name') || el.id || '').trim();
      if (!fname) continue;
      const labelEl = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : el.closest('label');
      const desc = (
        el.getAttribute('toolparamdescription') ||
        (labelEl ? labelEl.innerText : '') ||
        el.getAttribute('aria-label') ||
        el.getAttribute('placeholder') ||
        fname
      ).trim().replace(/\s+/g, ' ').slice(0, 120);

      let jsonType = 'string';
      if (type === 'number' || type === 'range') jsonType = 'number';
      else if (type === 'checkbox') jsonType = 'boolean';

      if (type === 'radio' && props[fname]) {
        if (el.value) {
          props[fname].enum = props[fname].enum || [];
          if (!props[fname].enum.includes(el.value) && props[fname].enum.length < 30) props[fname].enum.push(el.value);
        }
        if (el.required && !required.includes(fname)) required.push(fname);
        continue;
      }

      const propSpec = { type: jsonType, description: desc };
      if (el.tagName === 'SELECT') {
        const opts = Array.from(el.options).map(o => o.value).filter(Boolean).slice(0, 30);
        if (opts.length) propSpec.enum = opts;
      } else if (type === 'radio' && el.value) {
        propSpec.enum = [el.value];
      }
      props[fname] = propSpec;
      if (el.required && !required.includes(fname)) required.push(fname);
    }

    if (Object.keys(props).length === 0 && !explicitName) return;
    seen.add(toolName);
    const desc = (
      form.getAttribute('tooldescription') ||
      form.getAttribute('aria-label') ||
      `Submit ${toolName} form (${(form.getAttribute('method') || 'GET').toUpperCase()} ${form.getAttribute('action') || location.pathname})`
    ).trim().slice(0, 240);

    const docBase = document.baseURI || location.href;
    let resolvedAction = docBase;
    try {
      const rawAct = form.getAttribute('action');
      resolvedAction = new URL(rawAct || docBase, docBase).href;
    } catch (_e) {
      resolvedAction = String(form.getAttribute('action') || '');
    }
    form.setAttribute('data-luminara-webmcp-tool', toolName);
    tools.push({
      name: toolName,
      description: desc,
      inputSchema: { type: 'object', properties: props, required },
      source: explicitName ? 'declarative_html' : 'synthesized_form',
      method: (form.getAttribute('method') || 'GET').toUpperCase(),
      action_url: resolvedAction,
      origin: window.location.origin
    });
  });

  return {
    origin: window.location.origin,
    url: location.href,
    title: document.title || '',
    webmcp_supported: Boolean(navigator.modelContext),
    tool_count: tools.length,
    tools
  };
})()
"""


def build_invoke_webmcp_tool_js(tool_name: str, arguments: dict[str, Any], *, auto_submit: bool = True) -> str:
    """Build in-page JS to invoke either an imperative WebMCP tool or a declarative/synthesized HTML form."""
    t_json = json.dumps(tool_name)
    a_json = json.dumps(arguments or {}, ensure_ascii=False)
    submit_flag = "true" if auto_submit else "false"
    return WEBMCP_BOOTSTRAP_JS + f"""
(async () => {{
  const toolName = {t_json};
  const args = {a_json};
  const autoSubmit = {submit_flag};

  // 1. Imperative registry match
  if (window.__luminaraWebMCP && window.__luminaraWebMCP.registry.has(toolName)) {{
    const entry = window.__luminaraWebMCP.registry.get(toolName);
    try {{
      const out = await Promise.resolve(entry.execute(args));
      return {{ ok: true, source: 'imperative', tool: toolName, result: out }};
    }} catch (err) {{
      return {{ ok: false, source: 'imperative', tool: toolName, error: String(err && err.message ? err.message : err) }};
    }}
  }}

  // 2. Declarative / synthesized form match
  let form = document.querySelector(`form[toolname="${{CSS.escape(toolName)}}"]`)
    || document.querySelector(`form[data-luminara-webmcp-tool="${{CSS.escape(toolName)}}"]`);
  if (!form) {{
    return {{ ok: false, error: 'webmcp_tool_not_found', tool: toolName }};
  }}

  const populated = [];
  for (const [k, v] of Object.entries(args)) {{
    const field = form.querySelector(`input[name="${{CSS.escape(k)}}"], select[name="${{CSS.escape(k)}}"], textarea[name="${{CSS.escape(k)}}"], input#${{CSS.escape(k)}}, select#${{CSS.escape(k)}}, textarea#${{CSS.escape(k)}}`);
    if (!field) continue;
    const ftype = (field.getAttribute('type') || '').toLowerCase();
    if (['password', 'hidden', 'file', 'submit', 'button', 'reset', 'image'].includes(ftype)) continue;
    let targetEl = field;
    if (ftype === 'radio') {{
      const radioMatch = form.querySelector(`input[type="radio"][name="${{CSS.escape(k)}}"][value="${{CSS.escape(String(v))}}"]`);
      if (!radioMatch) continue;
      radioMatch.checked = true;
      targetEl = radioMatch;
    }} else if (ftype === 'checkbox') {{
      field.checked = (typeof v === 'string') ? !['false', '0', 'no', 'off', ''].includes(v.trim().toLowerCase()) : Boolean(v);
    }} else {{
      if (field.tagName === 'SELECT') {{
        const sVal = String(v);
        const sLow = sVal.trim().toLowerCase();
        const opts = Array.from(field.options || []);
        const hit = opts.find(o => o.value === sVal) || opts.find(o => o.value.toLowerCase() === sLow || (o.text || '').trim().toLowerCase() === sLow);
        if (!hit) return {{ ok: false, error: 'invalid_select_option', field: k, tool: toolName }};
      }}
      const proto = field.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype
        : (field.tagName === 'SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype);
      const desc = Object.getOwnPropertyDescriptor(proto, 'value');
      if (desc && desc.set) desc.set.call(field, String(v));
      else field.value = String(v);
    }}
    targetEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
    targetEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
    populated.push(k);
  }}

  let submitted = false;
  if (autoSubmit) {{
    const rawAction = String(form.getAttribute('action') || '').trim();
    if (/^(?:javascript|vbscript|data|file|chrome|devtools|luminara):/i.test(rawAction)) {{
      return {{ ok: false, error: 'blocked_unsafe_form_action_scheme', tool: toolName }};
    }}
    const docBase = document.baseURI || location.href;
    let parsedAction;
    try {{
      parsedAction = new URL(rawAction || docBase, docBase);
    }} catch (_e) {{
      return {{ ok: false, error: 'invalid_form_action_url', tool: toolName }};
    }}
    if (!['http:', 'https:'].includes(parsedAction.protocol)) {{
      return {{ ok: false, error: 'blocked_unsafe_form_action_scheme', tool: toolName }};
    }}
    const actHost = parsedAction.hostname.replace(/\\.$/, '').toLowerCase();
    const curHost = location.hostname.replace(/\\.$/, '').toLowerCase();
    const isLoop = (h) => h === 'localhost' || h === '0.0.0.0' || h === '[::1]' || h === '::1' || h.startsWith('127.');
    if (actHost.startsWith('169.254.') || actHost.endsWith('.internal') || (!isLoop(curHost) && isLoop(actHost))) {{
      return {{ ok: false, error: 'blocked_ssrf_form_action_host', tool: toolName }};
    }}
    if (typeof form.checkValidity === 'function' && !form.checkValidity()) {{
      return {{ ok: false, error: 'form_validation_failed', tool: toolName }};
    }}
    if (typeof form.requestSubmit === 'function') {{
      form.requestSubmit();
    }} else {{
      form.dispatchEvent(new Event('submit', {{ bubbles: true, cancelable: true }}));
    }}
    submitted = true;
  }}
  return {{
    ok: true,
    source: form.hasAttribute('toolname') ? 'declarative_html' : 'synthesized_form',
    tool: toolName,
    populated_fields: populated,
    submitted
  }};
}})()
"""


_TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\-:]{0,95}$")


def validate_webmcp_arguments(schema: dict[str, Any] | None, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate and coerce `arguments` against a WebMCP tool `inputSchema` (`required`, `enum`, `type`)."""
    out = dict(arguments)
    if not isinstance(schema, dict):
        return out
    req_fields = schema.get("required")
    if isinstance(req_fields, list):
        for rkey in req_fields:
            if isinstance(rkey, str) and (rkey not in out or out[rkey] is None or out[rkey] == ""):
                raise ValueError(f"Missing required WebMCP argument: {rkey!r}")
    props = schema.get("properties")
    if not isinstance(props, dict):
        return out
    for k, val in list(out.items()):
        spec = props.get(k)
        if not isinstance(spec, dict) or val is None:
            continue
        expected_t = spec.get("type")
        if expected_t == "string" and not isinstance(val, str):
            raise ValueError(f"WebMCP argument {k!r} must be a string")
        elif expected_t == "boolean":
            if isinstance(val, str) and val.strip().lower() in ("true", "false"):
                val = val.strip().lower() == "true"
                out[k] = val
            elif not isinstance(val, bool):
                raise ValueError(f"WebMCP argument {k!r} must be a boolean")
        elif expected_t == "integer" and (isinstance(val, bool) or not isinstance(val, int)):
            raise ValueError(f"WebMCP argument {k!r} must be an integer")
        elif expected_t == "number" and (isinstance(val, bool) or not isinstance(val, (int, float))):
            raise ValueError(f"WebMCP argument {k!r} must be a number")
        elif expected_t == "array" and not isinstance(val, list):
            raise ValueError(f"WebMCP argument {k!r} must be an array")
        elif expected_t == "object" and not isinstance(val, dict):
            raise ValueError(f"WebMCP argument {k!r} must be an object")
        allowed_enum = spec.get("enum")
        if isinstance(allowed_enum, list) and allowed_enum and val not in allowed_enum:
            raise ValueError(f"WebMCP argument {k!r} must be one of {allowed_enum!r}")
    return out


class WebMCPBridge:
    """Discovers and invokes page-level W3C WebMCP tools over `CDPBridge`."""

    def __init__(self, cdp: CDPBridge) -> None:
        self.cdp = cdp

    def list_page_tools(self, target_id: str | None = None) -> dict[str, Any]:
        resolved_tid = self.cdp._pick_target_id(target_id)
        data = self.cdp.evaluate_js(resolved_tid, _DISCOVER_WEBMCP_JS)
        if not isinstance(data, dict):
            raise CDPError("Failed to inspect WebMCP tools on active tab")
        data["target_id"] = resolved_tid
        return data

    def call_page_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        target_id: str | None = None,
        auto_submit: bool = True,
    ) -> dict[str, Any]:
        cleaned = (tool_name or "").strip()
        if not _TOOL_NAME_RE.match(cleaned):
            raise ValueError(f"Invalid WebMCP tool name: {tool_name!r}")
        if arguments is not None and not isinstance(arguments, dict):
            raise ValueError("WebMCP arguments must be a JSON object")
        call_args = arguments or {}
        resolved_tid = self.cdp._pick_target_id(target_id)
        # Ensure discovery has stamped synthesized form anchors, validate inputSchema, and block SSRF
        disc = self.cdp.evaluate_js(resolved_tid, _DISCOVER_WEBMCP_JS)
        if isinstance(disc, dict):
            page_host = (urllib.parse.urlparse(str(disc.get("url") or "")).hostname or "").rstrip(".").lower()
            for item in disc.get("tools") or []:
                if isinstance(item, dict) and item.get("name") == cleaned:
                    call_args = validate_webmcp_arguments(item.get("inputSchema"), call_args)
                    if auto_submit and item.get("source") != "imperative":
                        act_url = str(item.get("action_url") or "")
                        if act_url:
                            validate_navigation_url(
                                act_url,
                                allow_file=False,
                                blocked_ports=_INTERNAL_CONTROL_PORTS | {self.cdp.port},
                            )
                            act_host = (urllib.parse.urlparse(act_url).hostname or "").rstrip(".").lower()
                            if page_host and not _is_loopback_or_unspecified_host(page_host) and _is_loopback_or_unspecified_host(act_host):
                                raise CDPError(f"Blocked cross-origin WebMCP form submission to loopback host: {act_host}")
                    break
        res = self.cdp.evaluate_js(
            resolved_tid,
            build_invoke_webmcp_tool_js(cleaned, call_args, auto_submit=auto_submit),
            await_promise=True,
        )
        if not isinstance(res, dict):
            raise CDPError(f"WebMCP tool {cleaned!r} returned non-object response")
        res["target_id"] = resolved_tid
        return res
