import { ipcRenderer, webFrame } from "electron";

let teachRecording = false;

const SENSITIVE_FIELD_RE =
  /(pass(word|wd)?|secret|token|otp|pin|ssn|cvv|cvc|card|credit|cc-)/i;

function isSensitiveElement(el: Element | null): boolean {
  if (!el) return false;
  if (el instanceof HTMLInputElement) {
    const t = (el.type || "").toLowerCase();
    if (t === "password" || t === "hidden") return true;
    const hints = `${el.name} ${el.id} ${el.autocomplete} ${el.placeholder}`;
    if (SENSITIVE_FIELD_RE.test(hints)) return true;
  }
  if (el instanceof HTMLTextAreaElement) {
    const hints = `${el.name} ${el.id} ${el.placeholder}`;
    if (SENSITIVE_FIELD_RE.test(hints)) return true;
  }
  return false;
}

function escapeAttr(val: string): string {
  return CSS.escape(val.slice(0, 48));
}

function nthOfTypeSelector(el: Element): string {
  const tag = el.tagName.toLowerCase();
  const parent = el.parentElement;
  if (!parent) return tag;
  const siblings = Array.from(parent.children).filter((c) => c.tagName === el.tagName);
  const idx = siblings.indexOf(el) + 1;
  const selfPart = siblings.length > 1 ? `${tag}:nth-of-type(${idx})` : tag;
  if (parent.id) return `#${CSS.escape(parent.id)} > ${selfPart}`;
  return `${parent.tagName.toLowerCase()} > ${selfPart}`;
}

function buildStableSelector(el: Element): string {
  if (el.id) return `#${CSS.escape(el.id)}`;
  const tag = el.tagName.toLowerCase();
  const aria = el.getAttribute("aria-label");
  if (aria) return `${tag}[aria-label="${escapeAttr(aria)}"]`;
  const name = el.getAttribute("name");
  if (name) return `${tag}[name="${escapeAttr(name)}"]`;
  const role = el.getAttribute("role");
  if (role) return `${tag}[role="${escapeAttr(role)}"]`;
  return nthOfTypeSelector(el);
}

function extractLabel(el: Element): string {
  const aria = el.getAttribute("aria-label");
  if (aria) return aria.trim().slice(0, 64);
  if (el instanceof HTMLInputElement && el.placeholder) {
    return el.placeholder.trim().slice(0, 64);
  }
  const text = (el.textContent || "").replace(/\s+/g, " ").trim();
  if (text) return text.slice(0, 64);
  return el.tagName.toLowerCase();
}

function installWebMcpShim(): void {
  const shimSource = `(() => {
    if (navigator.modelContext) return;
    const registry = new Map();
    const discoverFormTools = () => {
      const forms = Array.from(document.querySelectorAll('form')).slice(0, 12);
      return forms.map((form, idx) => {
        const name = form.getAttribute('name') || form.getAttribute('id') || form.getAttribute('aria-label') || ('form_' + (idx + 1));
        const fields = Array.from(form.querySelectorAll('input,select,textarea'))
          .filter((el) => (el.getAttribute('type') || '').toLowerCase() !== 'password')
          .map((el) => el.getAttribute('name') || el.getAttribute('aria-label') || el.tagName.toLowerCase())
          .slice(0, 8);
        return {
          name: 'form:' + name,
          description: 'Semantic form (' + fields.join(', ') + ')',
          source: 'semantic-form'
        };
      });
    };
    const api = {
      registerTool(tool) {
        if (!tool || typeof tool.name !== 'string') return;
        registry.set(tool.name, {
          name: tool.name,
          description: String(tool.description || ''),
          source: 'webmcp'
        });
      },
      unregisterTool(name) {
        registry.delete(name);
      },
      provideContext(ctx) {
        if (ctx && Array.isArray(ctx.tools)) {
          for (const t of ctx.tools) api.registerTool(t);
        }
      },
      listTools() {
        return [...Array.from(registry.values()), ...discoverFormTools()];
      }
    };
    try {
      Object.defineProperty(navigator, 'modelContext', {
        value: api,
        configurable: false,
        writable: false
      });
    } catch {
      // Non-configurable navigator in restricted frames
    }
  })();`;
  void webFrame.executeJavaScript(shimSource).catch(() => undefined);
}

// Install immediately before early inline page scripts run
installWebMcpShim();

document.addEventListener(
  "click",
  (event) => {
    if (!teachRecording) return;
    const target =
      event.target instanceof Element
        ? event.target.closest("a,button,input,select,[role='button']") ?? event.target
        : null;
    if (!target || isSensitiveElement(target)) return;
    ipcRenderer.send("web:recorded-step", {
      action: "click",
      label: extractLabel(target),
      selector: buildStableSelector(target),
      valuePreview: "",
      url: window.location.href,
      timestamp: Date.now()
    });
  },
  true
);

document.addEventListener(
  "change",
  (event) => {
    if (!teachRecording) return;
    const target = event.target instanceof Element ? event.target : null;
    if (!target || isSensitiveElement(target)) return;
    let valuePreview = "";
    if (
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement
    ) {
      valuePreview = String(target.value || "").slice(0, 64);
    }
    ipcRenderer.send("web:recorded-step", {
      action: "input",
      label: extractLabel(target),
      selector: buildStableSelector(target),
      valuePreview,
      url: window.location.href,
      timestamp: Date.now()
    });
  },
  true
);

document.addEventListener(
  "submit",
  (event) => {
    if (!teachRecording) return;
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    ipcRenderer.send("web:recorded-step", {
      action: "submit",
      label: extractLabel(target),
      selector: buildStableSelector(target),
      valuePreview: "",
      url: window.location.href,
      timestamp: Date.now()
    });
  },
  true
);

ipcRenderer.on("luminara:teach-toggle", (_event, enabled: boolean) => {
  teachRecording = Boolean(enabled);
});
