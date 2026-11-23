"""Agent presence shield: shows that an agent is working on a tab and holds the person's input.

Each page-changing agent action calls `PresenceShield.hold`. That (re)installs a small banner in
the page and blocks the person's clicks and keystrokes so they cannot collide with the agent
mid-action. The person takes the tab back with the banner's button or the Escape key.

Everything fails open: the shield expires on its own if the daemon stops refreshing it, and a
page that tampers with it can only unblock the person or stop the agent, never the reverse.
"""

from __future__ import annotations

from typing import Any

from .cdp_client import TabLeaseManager

HOLD_TTL_MS = 20_000  # shield clears itself this long after the agent's last action
ACTION_WINDOW_MS = 1_500  # the agent's own input events pass during this window

_HOLD_JS = """
((label, ttlMs, windowMs) => {
  const KEY = '__luminaraPresence';
  let st = window[KEY];
  if (st && st.takenOver) {
    st.takenOver = false;
    return { taken_over: true };
  }
  if (!st || !st.active) {
    st = window[KEY] = { active: true, takenOver: false, expires: 0, passUntil: 0 };
    const BLOCKED = ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click', 'dblclick', 'auxclick',
      'contextmenu', 'keydown', 'keypress', 'keyup', 'beforeinput', 'paste', 'drop', 'touchstart', 'touchend'];
    const release = (byPerson) => {
      st.active = false;
      st.takenOver = byPerson;
      for (const type of BLOCKED) window.removeEventListener(type, guard, true);
      clearInterval(st.timer);
      if (st.host) st.host.remove();
    };
    const guard = (ev) => {
      if (!ev.isTrusted) return;
      if (ev.type === 'keydown' && ev.key === 'Escape') {
        release(true);
        ev.stopImmediatePropagation();
        ev.preventDefault();
        return;
      }
      const path = ev.composedPath ? ev.composedPath() : [];
      if (st.host && (ev.target === st.host || st.host.contains(ev.target) || path.includes(st.host))) return;
      if (Date.now() < st.passUntil) return;
      ev.stopImmediatePropagation();
      ev.preventDefault();
    };
    for (const type of BLOCKED) window.addEventListener(type, guard, true);
    st.timer = setInterval(() => { if (Date.now() > st.expires) release(false); }, 1000);
    st.release = release;

    const existing = document.getElementById('__luminara_presence_host');
    if (existing) existing.remove();

    const host = document.createElement('div');
    host.id = '__luminara_presence_host';
    host.style.cssText = 'all:initial;position:fixed;bottom:18px;left:50%;transform:translateX(-50%);'
      + 'z-index:2147483647;pointer-events:auto;max-width:calc(100vw - 24px);';

    const lightMirror = document.createElement('span');
    lightMirror.id = '__luminara_presence';
    lightMirror.hidden = true;
    lightMirror.setAttribute('aria-hidden', 'true');
    host.appendChild(lightMirror);

    const root = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;
    const style = document.createElement('style');
    style.textContent = [
      ':host { color-scheme: dark light; }',
      '.pill { display:inline-flex; align-items:center; gap:10px; max-width:100%; padding:6px 6px 6px 14px;',
      '  border-radius:999px; background:rgba(20,21,25,0.92); color:#F6F5F0;',
      '  border:1px solid rgba(60,208,163,0.45); backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px);',
      '  box-shadow:inset 0 1px 0 rgba(255,255,255,0.10), 0 14px 36px -10px rgba(0,0,0,0.55);',
      '  font:500 12.5px/1.3 "Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }',
      '.dot { width:8px; height:8px; border-radius:999px; flex-shrink:0; background:#3CD0A3;',
      '  box-shadow:0 0 10px rgba(60,208,163,0.75); animation:lumPulse 2.2s ease-in-out infinite; }',
      '.msg { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }',
      '.take { all:unset; cursor:pointer; flex-shrink:0; padding:6px 13px; border-radius:999px;',
      '  background:#3CD0A3; color:#081C15; font:600 12px/1.2 "Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;',
      '  transition:transform 130ms cubic-bezier(0.16,1,0.3,1), filter 130ms ease; }',
      '.take:hover { filter:brightness(1.06); transform:translateY(-1px); }',
      '.take:active { transform:scale(0.97); }',
      '.take:focus-visible { outline:2px solid #F6F5F0; outline-offset:2px; }',
      '@media (prefers-color-scheme: light) {',
      '  .pill { background:rgba(250,249,246,0.95); color:#1C1E24; border-color:rgba(17,122,94,0.42);',
      '    box-shadow:0 2px 6px rgba(28,30,36,0.08), 0 14px 32px -12px rgba(28,30,36,0.22); }',
      '  .dot { background:#117A5E; box-shadow:0 0 8px rgba(17,122,94,0.5); }',
      '  .take { background:#117A5E; color:#FFFFFF; }',
      '  .take:focus-visible { outline-color:#1C1E24; }',
      '}',
      '@keyframes lumPulse { 0%,100% { opacity:0.75; transform:scale(0.92); } 50% { opacity:1; transform:scale(1.08); } }',
      '@media (prefers-reduced-motion: reduce) { .dot, .take { animation:none !important; transition:none !important; } }'
    ].join('\\n');

    const pill = document.createElement('div');
    pill.className = 'pill';
    pill.setAttribute('role', 'status');
    pill.setAttribute('aria-live', 'polite');
    const dot = document.createElement('span');
    dot.className = 'dot';
    dot.setAttribute('aria-hidden', 'true');
    const text = document.createElement('span');
    text.className = 'msg';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'take';
    button.textContent = 'Take over (Esc)';
    button.addEventListener('click', (ev) => { if (ev.isTrusted) release(true); });
    pill.append(dot, text, button);
    root.append(style, pill);

    st.host = host;
    st.banner = pill;
    st.text = text;
    st.lightMirror = lightMirror;
    (document.body || document.documentElement).appendChild(host);
  }
  if (st.host && !st.host.isConnected) {
    (document.body || document.documentElement).appendChild(st.host);
  }
  const msg = label + ' is working here. Your input is paused.';
  if (st.text) st.text.textContent = msg;
  if (st.lightMirror) st.lightMirror.textContent = msg;
  st.expires = Date.now() + ttlMs;
  st.passUntil = Date.now() + windowMs;
  return { taken_over: false };
})
"""

_CLEAR_JS = """
(() => {
  const st = window.__luminaraPresence;
  if (st && st.active) {
    if (typeof st.release === 'function') st.release(false);
    else { st.expires = 0; st.takenOver = false; }
  }
  const host = document.getElementById('__luminara_presence_host');
  if (host) host.remove();
  const legacy = document.getElementById('__luminara_presence');
  if (legacy) legacy.remove();
  return true;
})()
"""


class PresenceShield:
    def __init__(self, cdp: Any, leases: TabLeaseManager) -> None:
        self.cdp = cdp
        self.leases = leases

    def hold(self, target_id: str, agent_id: str) -> None:
        """Refresh the shield before an agent action; raises if the person took the tab back in the page."""
        label = "".join(ch for ch in agent_id if ch.isalnum() or ch in "-_ .")[:40] or "An agent"
        try:
            state = self.cdp.evaluate_js(target_id, f"{_HOLD_JS}({label!r}, {HOLD_TTL_MS}, {ACTION_WINDOW_MS})")
        except Exception:  # noqa: BLE001 - no shield (restricted page, mid-navigation) must never block the action
            return
        if isinstance(state, dict) and state.get("taken_over"):
            self.leases.force_human_override(target_id, agent_id)
            self.leases.check_allowed(target_id, agent_id)  # raises PersonControlError, once per agent

    def clear(self, target_id: str) -> None:
        try:
            self.cdp.evaluate_js(target_id, _CLEAR_JS)
        except Exception:  # noqa: BLE001
            pass
