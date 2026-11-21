"""Interactive 3D Metallic Gold Logo & Desktop Startup Splash (`forge/luminara_logo3d.py`).

Self-contained, offline-first WebGL volumetric extruded-relief 3D logo engine with:
- Ray-AABB 20-step volumetric extrusion (clean at grazing 90 deg angles & full 360 deg spin).
- Real-time 4-tap beveled metallic gold PBR lighting, cursor-tracked specular & eye glint, click shockwave pulse.
- Alpha-keyed Canvas 2D + CSS 3D fallback (`--disable-gpu` / context-lost / reduced-motion safe).
- Once-per-desktop-session startup splash (`chrome.storage.session` on MV3, `sessionStorage` fallback) + Hero 3D emblem.
- Pure Python stdlib runtime, strict MV3 CSP compliance (zero external CDNs, zero `.innerHTML`, zero `eval`).
"""

from __future__ import annotations

import base64
from functools import lru_cache
import html
from pathlib import Path

from .luminara_copilot_ext import _js_json, make_solid_emerald_png

_UI_DIR = Path(__file__).resolve().parent / "ui"
_LOGO_WEBP = _UI_DIR / "luminara-logo.webp"
_LOGO_PNG = _UI_DIR / "luminara-logo.png"


@lru_cache(maxsize=1)
def get_logo_data_uri() -> str:
    """Return the Luminara Digital emblem as an inline data URI (WebP preferred, PNG fallback)."""
    if _LOGO_WEBP.is_file():
        return "data:image/webp;base64," + base64.b64encode(_LOGO_WEBP.read_bytes()).decode("ascii")
    if _LOGO_PNG.is_file():
        return "data:image/png;base64," + base64.b64encode(_LOGO_PNG.read_bytes()).decode("ascii")
    return ""


def get_logo_icon_png(size: int) -> bytes | None:
    """Return pre-rendered Luminara Digital emblem PNG bytes for MV3 extension icons (pure stdlib)."""
    icon_path = _UI_DIR / f"icon{size}.png"
    return icon_path.read_bytes() if icon_path.is_file() else None


@lru_cache(maxsize=1)
def get_logo_favicon_data_uri() -> str:
    """Return compact 48x48 PNG data URI for `<link rel="icon">` across local & extension pages."""
    raw = get_logo_icon_png(48) or get_logo_icon_png(16) or make_solid_emerald_png(16)
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def write_extension_icons(ext_dir: Path) -> None:
    """Write canonical branded 16/48/128 PNG icons into an MV3 extension's `icons/` folder."""
    icons_dir = ext_dir / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    for px in (16, 48, 128):
        (icons_dir / f"icon{px}.png").write_bytes(get_logo_icon_png(px) or make_solid_emerald_png(px))


LOGO_3D_CSS = """
    .lum-splash {
      position: fixed; inset: 0; z-index: 10000; overflow-y: auto;
      display: flex; flex-direction: column; align-items: center; justify-content: safe center;
      gap: 18px; padding: clamp(16px, 3vw, 32px);
      background:
        radial-gradient(640px 440px at 50% 44%, oklch(0.32 0.065 82 / 0.24), transparent 68%),
        radial-gradient(880px 520px at 50% 100%, oklch(0.24 0.05 162 / 0.14), transparent 72%),
        #050608;
      color: oklch(0.95 0.012 85);
      opacity: 1; transform: scale(1); filter: blur(0px);
      transition: opacity 260ms cubic-bezier(0.4, 0, 1, 1), transform 260ms cubic-bezier(0.4, 0, 1, 1), filter 260ms cubic-bezier(0.4, 0, 1, 1);
    }
    .lum-splash.hidden {
      opacity: 0; transform: scale(1.03); filter: blur(6px);
      pointer-events: none; visibility: hidden;
    }
    .lum-splash-stage {
      position: relative; width: min(370px, 76vw, 46vh); aspect-ratio: 1 / 1; flex-shrink: 0;
      display: grid; place-items: center; cursor: grab; touch-action: none; user-select: none;
      animation: lumStageEnter 600ms cubic-bezier(0.16, 1, 0.3, 1) both;
    }
    .lum-splash-stage:active { cursor: grabbing; }
    .lum-splash-halo {
      position: absolute; inset: 10%; border-radius: 50%; pointer-events: none;
      background: radial-gradient(circle, oklch(0.79 0.12 84 / 0.24) 0%, oklch(0.75 0.11 84 / 0.07) 48%, transparent 72%);
      filter: blur(18px); animation: lumHaloBreath 4.2s ease-in-out infinite;
    }
    .lum-logo-canvas {
      position: relative; z-index: 2; width: 100%; height: 100%; display: block; border-radius: 50%;
    }
    .lum-splash-meta {
      width: min(440px, 90vw); display: flex; flex-direction: column; align-items: center; gap: 11px;
      text-align: center; animation: lumMetaEnter 500ms 100ms cubic-bezier(0.16, 1, 0.3, 1) both;
    }
    .lum-splash-kicker {
      font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.13em; text-transform: uppercase;
      color: oklch(0.84 0.095 84); overflow-wrap: anywhere;
    }
    .lum-splash-status {
      font-family: var(--font-mono); font-size: 12px; color: oklch(0.78 0.015 85);
      min-height: 18px; font-variant-numeric: tabular-nums;
    }
    .lum-splash-track {
      width: 100%; height: 4px; border-radius: 999px; overflow: hidden;
      background: oklch(1 0 0 / 0.09); border: 1px solid oklch(0.82 0.09 84 / 0.22);
    }
    .lum-splash-bar {
      width: 14%; height: 100%; border-radius: 999px;
      background: linear-gradient(90deg, oklch(0.68 0.11 76), oklch(0.88 0.11 88), oklch(0.76 0.15 162));
      box-shadow: 0 0 14px oklch(0.82 0.11 84 / 0.55);
      transition: width 240ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    .lum-splash-actions {
      display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 10px; margin-top: 4px;
    }
    .lum-btn-gold {
      min-height: 38px; padding: 8px 18px; border-radius: 10px; cursor: pointer;
      font-family: var(--font-mono); font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
      color: #090a0d; border: 1px solid oklch(0.88 0.1 86);
      background: linear-gradient(135deg, oklch(0.89 0.095 88), oklch(0.74 0.115 78));
      box-shadow: 0 6px 22px oklch(0.78 0.11 84 / 0.28), inset 0 1px 0 oklch(1 0 0 / 0.45);
      transition: transform 140ms cubic-bezier(0.16, 1, 0.3, 1), filter 140ms ease;
    }
    .lum-btn-gold:hover { transform: translateY(-1px); filter: brightness(1.06); }
    .lum-btn-gold:active { transform: translateY(0) scale(0.98); }
    .lum-btn-subtle {
      min-height: 38px; padding: 8px 14px; border-radius: 10px; cursor: pointer;
      font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase;
      color: oklch(0.84 0.04 84); background: oklch(1 0 0 / 0.04); border: 1px solid oklch(0.82 0.08 84 / 0.26);
      transition: border-color 140ms ease, background 140ms ease;
    }
    .lum-btn-subtle:hover { border-color: oklch(0.86 0.1 84 / 0.6); background: oklch(1 0 0 / 0.08); }
    .lum-splash-hint {
      font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.09em; text-transform: uppercase;
      color: oklch(0.67 0.02 84);
    }
    .hero-brand-wrap { display: flex; align-items: center; gap: 16px; min-width: 0; }
    .hero-brand-copy { min-width: 0; overflow-wrap: anywhere; }
    .hero-logo-3d {
      position: relative; width: 72px; height: 72px; flex-shrink: 0; border-radius: 50%;
      background: radial-gradient(circle, oklch(0.2 0.04 84 / 0.45), #06070a 74%);
      border: 1px solid oklch(0.82 0.09 84 / 0.35);
      box-shadow: 0 8px 24px oklch(0 0 0 / 0.38), inset 0 1px 0 oklch(0.9 0.08 86 / 0.25);
      cursor: grab; touch-action: none; overflow: hidden;
      transition: border-color 160ms ease, box-shadow 160ms ease;
    }
    .hero-logo-3d:hover {
      border-color: oklch(0.86 0.11 86 / 0.72);
      box-shadow: 0 10px 28px oklch(0.78 0.11 84 / 0.24), inset 0 1px 0 oklch(0.92 0.09 86 / 0.35);
    }
    .hero-logo-3d:active { cursor: grabbing; }
    @keyframes lumStageEnter {
      from { opacity: 0; transform: scale(0.92) translateY(10px); filter: blur(6px); }
      to { opacity: 1; transform: scale(1) translateY(0); filter: blur(0px); }
    }
    @keyframes lumMetaEnter {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes lumHaloBreath {
      0%, 100% { transform: scale(0.97); opacity: 0.78; }
      50% { transform: scale(1.05); opacity: 1; }
    }
"""


def build_logo_3d_splash_html(
    brand_name: str,
    chromium_version: str,
    agent_port: int,
    cdp_port: int,
) -> str:
    """Return semantic HTML for the interactive 3D startup loading splash (hidden by default for zero Ctrl+T FOUC)."""
    brand_esc = html.escape(brand_name)
    ver_esc = html.escape(chromium_version)
    return f"""  <div class="lum-splash hidden" id="luminaraSplash" role="dialog" aria-modal="true" aria-label="{brand_esc} 3D Startup Experience">
    <div class="lum-splash-stage" id="splashLogoStage" tabindex="0" role="button" aria-label="Interactive 3D {brand_esc} Emblem — drag to rotate, click or press Space to pulse">
      <div class="lum-splash-halo" aria-hidden="true"></div>
      <canvas class="lum-logo-canvas" id="splashLogoCanvas" width="512" height="512"></canvas>
    </div>
    <div class="lum-splash-meta">
      <div class="lum-splash-kicker">LUMINARA DIGITAL · CHROMIUM {ver_esc} · CDP :{cdp_port} · MCP :{agent_port}</div>
      <div class="lum-splash-status" id="splashStatusText">INITIALIZING 3D ENGINE &amp; PRIVACY SHIELD v3...</div>
      <div class="lum-splash-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="14" id="splashProgressTrack">
        <div class="lum-splash-bar" id="splashProgressBar"></div>
      </div>
      <div class="lum-splash-actions">
        <button class="lum-btn-gold" type="button" id="btnEnterDeck">Enter Command Deck ↵</button>
        <button class="lum-btn-subtle" type="button" id="btnPulseLogo">Pulse ✦</button>
        <button class="lum-btn-subtle" type="button" id="btnSpinLogo">360° Spin ↻</button>
      </div>
      <div class="lum-splash-hint" id="splashHintText">DRAG TO ORBIT · MOVE CURSOR TO LIGHT · CLICK TO PULSE · SCROLL TO ZOOM</div>
    </div>
  </div>"""


def build_logo_3d_hero_badge_html(brand_name: str) -> str:
    """Return the persistent interactive 3D mini-emblem placed inside the Command Deck hero."""
    brand_esc = html.escape(brand_name)
    return (
        f'<div class="hero-logo-3d" id="heroLogo3dWrap" title="Interactive 3D {brand_esc} Logo — drag to tilt, click to pulse, double-click for full 3D splash" '
        f'tabindex="0" role="button" aria-label="Interactive 3D {brand_esc} Emblem">'
        f'<canvas class="lum-logo-canvas" id="heroLogoCanvas" width="144" height="144"></canvas>'
        f"</div>"
    )


def build_logo_3d_js() -> str:
    """Return self-contained vanilla JS for the WebGL 3D extruded gold logo + startup splash lifecycle."""
    logo_uri_js = _js_json(get_logo_data_uri())
    return f"""
    // === LUMINARA DIGITAL 3D VOLUMETRIC GOLD LOGO ENGINE & STARTUP SPLASH ===
    const LUMINARA_LOGO_URI = {logo_uri_js};
    const REDUCED_MOTION = Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    const _logoImageCache = {{ img: null, ready: false, keyedCanvas: null, cbs: [] }};

    function withLuminaraLogoImage(cb) {{
      if (!LUMINARA_LOGO_URI) return;
      if (_logoImageCache.ready && _logoImageCache.img) {{ cb(_logoImageCache.img); return; }}
      _logoImageCache.cbs.push(cb);
      if (_logoImageCache.img) return;
      const img = new Image();
      img.decoding = 'async';
      img.onload = () => {{
        _logoImageCache.ready = true;
        const list = _logoImageCache.cbs.splice(0);
        list.forEach(fn => fn(img));
      }};
      img.onerror = () => {{
        _logoImageCache.img = null;
        _logoImageCache.cbs.length = 0;
      }};
      img.src = LUMINARA_LOGO_URI;
      _logoImageCache.img = img;
    }}

    function getAlphaKeyedLogoCanvas(img) {{
      if (_logoImageCache.keyedCanvas) return _logoImageCache.keyedCanvas;
      const c = document.createElement('canvas');
      c.width = img.naturalWidth || 512;
      c.height = img.naturalHeight || 512;
      const g = c.getContext('2d');
      if (!g) return img;
      g.drawImage(img, 0, 0, c.width, c.height);
      try {{
        const id = g.getImageData(0, 0, c.width, c.height);
        const d = id.data;
        for (let i = 0; i < d.length; i += 4) {{
          const lum = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
          const t = Math.max(0, Math.min(1, (lum - 18) / 38));
          d[i + 3] = Math.round(t * t * (3 - 2 * t) * 255);
        }}
        g.putImageData(id, 0, 0);
        _logoImageCache.keyedCanvas = c;
        return c;
      }} catch (_e) {{
        return img;
      }}
    }}

    function createLuminara3DLogo(canvas, opts) {{
      const cfg = Object.assign({{
        interactive: true,
        zoomable: false,
        introSweep: false,
        thickness: 0.125,
        onInteract: null,
      }}, opts || {{}});
      if (!canvas) return null;

      const state = {{
        rotX: cfg.introSweep ? -0.44 : 0.0,
        rotY: cfg.introSweep ? 0.62 : 0.0,
        velX: 0, velY: 0,
        targetX: 0, targetY: 0,
        zoom: cfg.introSweep ? 0.91 : 1.0,
        targetZoom: 1.0,
        lightX: 0.25, lightY: 0.35,
        targetLightX: 0.25, targetLightY: 0.35,
        cursorX: 0, cursorY: 0,
        dragging: false,
        lastPx: 0, lastPy: 0,
        downX: 0, downY: 0,
        pulseTime: 0.05,
        pulseOriginX: 0.5, pulseOriginY: 0.53,
        active: true,
        glOk: false,
        startMs: performance.now(),
        rafId: 0,
      }};

      let gl = null;
      let prog = null;
      let tex = null;
      let locs = {{}};
      let ctx2d = null;
      let loadedImg = null;
      let dirty = true;

      function initWebGL() {{
        try {{
          gl = canvas.getContext('webgl', {{ alpha: true, antialias: true, premultipliedAlpha: true, powerPreference: 'high-performance' }});
          if (!gl || gl.isContextLost()) return false;

          const vsSrc = [
            'attribute vec2 a_pos;',
            'varying vec2 v_ndc;',
            'void main() {{ v_ndc = a_pos; gl_Position = vec4(a_pos, 0.0, 1.0); }}'
          ].join('\\n');

          const fsSrc = [
            '#ifdef GL_FRAGMENT_PRECISION_HIGH',
            'precision highp float;',
            '#else',
            'precision mediump float;',
            '#endif',
            'varying vec2 v_ndc;',
            'uniform sampler2D u_tex;',
            'uniform float u_time;',
            'uniform vec2 u_rot;',
            'uniform float u_zoom;',
            'uniform vec2 u_light;',
            'uniform vec2 u_cursor;',
            'uniform float u_pulse;',
            'uniform vec2 u_pulseOrigin;',
            'uniform float u_thickness;',
            '',
            'mat3 rotX(float a) {{ float c = cos(a), s = sin(a); return mat3(1.0,0.0,0.0, 0.0,c,-s, 0.0,s,c); }}',
            'mat3 rotY(float a) {{ float c = cos(a), s = sin(a); return mat3(c,0.0,s, 0.0,1.0,0.0, -s,0.0,c); }}',
            'float luma(vec3 c) {{ return dot(c, vec3(0.299, 0.587, 0.114)); }}',
            '',
            'float sampleH(vec2 uv) {{',
            '  if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) return 0.0;',
            '  return luma(texture2D(u_tex, uv).rgb);',
            '}}',
            '',
            'void main() {{',
            '  vec2 p = v_ndc;',
            '  float camZ = 2.38 / max(u_zoom, 0.5);',
            '  vec3 ro = vec3(0.0, 0.0, camZ);',
            '  vec3 rd = normalize(vec3(p.x, p.y, -1.78));',
            '  mat3 invR = rotX(-u_rot.x) * rotY(-u_rot.y);',
            '  vec3 lro = invR * ro;',
            '  vec3 lrd = normalize(invR * rd);',
            '  float halfT = u_thickness * 0.5;',
            '  vec3 bMin = vec3(-0.91, -0.91, -halfT);',
            '  vec3 bMax = vec3(0.91, 0.91, halfT);',
            '  vec3 invD = 1.0 / (abs(lrd) + vec3(1e-6)) * sign(lrd + vec3(1e-9));',
            '  vec3 t0 = (bMin - lro) * invD;',
            '  vec3 t1 = (bMax - lro) * invD;',
            '  vec3 tSmall = min(t0, t1);',
            '  vec3 tBig = max(t0, t1);',
            '  float tNear = max(max(tSmall.x, tSmall.y), max(tSmall.z, 0.0));',
            '  float tFar = min(min(tBig.x, tBig.y), tBig.z);',
            '  float dirSign = lrd.z < 0.0 ? 1.0 : -1.0;',
            '',
            '  bool hit = false;',
            '  vec2 hitUv = vec2(0.0);',
            '  float hitDepth = 0.0;',
            '  vec3 hitTex = vec3(0.0);',
            '  float hitLum = 0.0;',
            '  if (tFar > tNear) {{',
            '    const int STEPS = 20;',
            '    for (int i = 0; i < STEPS; i++) {{',
            '      float f = float(i) / float(STEPS - 1);',
            '      float t = mix(tNear, tFar, f);',
            '      vec3 hp = lro + lrd * t;',
            '      vec2 uv = vec2(hp.x, -hp.y) / 1.82 + 0.5;',
            '      if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) continue;',
            '      vec3 c = texture2D(u_tex, uv).rgb;',
            '      float lum = luma(c);',
            '      float bevelMask = (i == 0) ? smoothstep(0.085, 0.24, lum) : smoothstep(0.11, 0.28, lum);',
            '      if (bevelMask > 0.35) {{',
            '        hit = true; hitUv = uv; hitDepth = f; hitTex = c; hitLum = lum;',
            '        break;',
            '      }}',
            '    }}',
            '  }}',
            '',
            '  // Subtle orbiting 3D gold dust motes in background (premultiplied output)',
            '  vec3 bgGlow = vec3(0.0);',
            '  float bgAlpha = 0.0;',
            '  for (int k = 0; k < 10; k++) {{',
            '    float fk = float(k);',
            '    float ang = u_time * (0.28 + 0.05 * mod(fk, 3.0)) + fk * 0.6283;',
            '    float rad = 0.68 + 0.24 * sin(fk * 1.9 + u_time * 0.4);',
            '    vec2 mp = vec2(cos(ang), sin(ang) * 0.85) * rad + u_cursor * 0.04;',
            '    float d = length(p - mp);',
            '    float spark = exp(-d * d * 2400.0) * (0.45 + 0.55 * sin(u_time * 2.4 + fk * 2.1));',
            '    bgGlow += vec3(1.0, 0.84, 0.46) * spark * 0.72;',
            '    bgAlpha += spark * 0.62;',
            '  }}',
            '',
            '  if (!hit) {{',
            '    if (u_pulse < 1.35) {{',
            '      float pr = u_pulse * 0.88;',
            '      float planeT = (0.0 - lro.z) / (abs(lrd.z) < 0.02 ? (lrd.z < 0.0 ? -0.02 : 0.02) : lrd.z);',
            '      vec3 pp = lro + lrd * max(planeT, 0.0);',
            '      vec2 pUv = vec2(pp.x, -pp.y) / 1.82 + 0.5;',
            '      float pd = length(pUv - u_pulseOrigin);',
            '      float ring = exp(-pow((pd - pr) * 22.0, 2.0)) * (1.0 - smoothstep(0.0, 1.35, u_pulse));',
            '      bgGlow += vec3(1.0, 0.86, 0.48) * ring * 0.58;',
            '      bgAlpha += ring * 0.48;',
            '    }}',
            '    float aBg = clamp(bgAlpha, 0.0, 1.0);',
            '    gl_FragColor = vec4(bgGlow * aBg, aBg);',
            '    return;',
            '  }}',
            '',
            '  // 4-tap central-difference normal estimation for sculpted gold bevels',
            '  float eps = 1.0 / 340.0;',
            '  float hL = sampleH(hitUv - vec2(eps, 0.0));',
            '  float hR = sampleH(hitUv + vec2(eps, 0.0));',
            '  float hU = sampleH(hitUv - vec2(0.0, eps));',
            '  float hD = sampleH(hitUv + vec2(0.0, eps));',
            '  vec3 N = normalize(vec3((hL - hR) * 2.8 * dirSign, (hD - hU) * 2.8 * dirSign, dirSign * 0.92));',
            '  if (hitDepth > 0.02) {{',
            '    N = normalize(vec3((hL - hR) * 4.5 * dirSign, (hD - hU) * 4.5 * dirSign, dirSign * 0.25));',
            '  }}',
            '  vec3 V = normalize(-lrd);',
            '  vec3 L1 = normalize(invR * normalize(vec3(u_light.x * 1.45, u_light.y * 1.45, 1.35)));',
            '  vec3 L2 = normalize(invR * normalize(vec3(-0.9, -0.75, 0.75)));',
            '  vec3 H1 = normalize(L1 + V);',
            '  float diff1 = max(dot(N, L1), 0.0);',
            '  float spec1 = pow(max(dot(N, H1), 0.0), 38.0);',
            '  float broad = pow(max(dot(N, H1), 0.0), 8.0);',
            '  float rim = pow(1.0 - max(dot(N, V), 0.0), 2.6);',
            '  float diff2 = max(dot(N, L2), 0.0);',
            '',
            '  // Metallic 24k champagne gold base + extruded wall depth shading',
            '  vec3 goldBase = mix(hitTex * vec3(1.08, 1.01, 0.88), vec3(0.95, 0.79, 0.42), 0.16);',
            '  float wallShade = hitDepth > 0.02 ? mix(0.68, 0.34, hitDepth) : 1.0;',
            '  vec3 col = goldBase * (0.44 + 0.72 * diff1 + 0.22 * broad) * wallShade;',
            '  col += vec3(1.0, 0.93, 0.70) * spec1 * (hitDepth > 0.02 ? 0.42 : 0.95);',
            '  col += vec3(0.42, 0.88, 0.76) * (rim * 0.22 + diff2 * 0.11);',
            '',
            '  // Animated liquid-gold specular sheen sweep',
            '  float sweepCycle = mod(u_time * 0.26, 1.65);',
            '  float sweepPos = sweepCycle * 2.1 - 0.8;',
            '  float sweepCoord = hitUv.x * 0.82 + hitUv.y * 0.58;',
            '  float sheen = exp(-pow((sweepCoord - sweepPos) * 11.0, 2.0)) * smoothstep(0.18, 0.75, hitLum);',
            '  col += vec3(1.0, 0.95, 0.78) * sheen * 0.52;',
            '',
            '  // Interactive Eye pupil catchlight tracking cursor',
            '  vec2 eyeCenter = vec2(0.50, 0.528) + vec2(u_cursor.x * 0.016, -u_cursor.y * 0.012);',
            '  float eyeDist = length(hitUv - eyeCenter);',
            '  float eyeGlow = exp(-eyeDist * eyeDist * 2600.0) * (0.55 + 0.45 * sin(u_time * 2.6));',
            '  col += vec3(1.0, 0.94, 0.74) * eyeGlow * 0.55;',
            '',
            '  // Interactive click shockwave energy pulse',
            '  if (u_pulse < 1.35) {{',
            '    float pr = u_pulse * 0.88;',
            '    float pd = length(hitUv - u_pulseOrigin);',
            '    float wave = exp(-pow((pd - pr) * 20.0, 2.0)) * (1.0 - smoothstep(0.0, 1.35, u_pulse));',
            '    col += vec3(1.0, 0.91, 0.62) * wave * 0.95;',
            '  }}',
            '',
            '  float alpha = clamp(smoothstep(0.075, 0.22, hitLum), 0.0, 1.0);',
            '  vec3 premul = col * alpha + bgGlow * (1.0 - alpha) * 0.45;',
            '  gl_FragColor = vec4(premul, max(alpha, clamp(bgAlpha * 0.5, 0.0, 1.0)));',
            '}}'
          ].join('\\n');

          function compile(type, src) {{
            const s = gl.createShader(type);
            gl.shaderSource(s, src);
            gl.compileShader(s);
            if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {{ gl.deleteShader(s); return null; }}
            return s;
          }}
          const vs = compile(gl.VERTEX_SHADER, vsSrc);
          const fs = compile(gl.FRAGMENT_SHADER, fsSrc);
          if (!vs || !fs) return false;
          prog = gl.createProgram();
          gl.attachShader(prog, vs);
          gl.attachShader(prog, fs);
          gl.linkProgram(prog);
          gl.deleteShader(vs);
          gl.deleteShader(fs);
          if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return false;

          const buf = gl.createBuffer();
          gl.bindBuffer(gl.ARRAY_BUFFER, buf);
          gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), gl.STATIC_DRAW);
          const posLoc = gl.getAttribLocation(prog, 'a_pos');
          gl.enableVertexAttribArray(posLoc);
          gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

          tex = gl.createTexture();
          gl.bindTexture(gl.TEXTURE_2D, tex);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
          if (loadedImg) {{
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, loadedImg);
          }} else {{
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0,0,0,0]));
          }}

          locs = {{
            tex: gl.getUniformLocation(prog, 'u_tex'),
            time: gl.getUniformLocation(prog, 'u_time'),
            rot: gl.getUniformLocation(prog, 'u_rot'),
            zoom: gl.getUniformLocation(prog, 'u_zoom'),
            light: gl.getUniformLocation(prog, 'u_light'),
            cursor: gl.getUniformLocation(prog, 'u_cursor'),
            pulse: gl.getUniformLocation(prog, 'u_pulse'),
            pulseOrigin: gl.getUniformLocation(prog, 'u_pulseOrigin'),
            thickness: gl.getUniformLocation(prog, 'u_thickness'),
          }};
          gl.useProgram(prog);
          gl.activeTexture(gl.TEXTURE0);
          gl.bindTexture(gl.TEXTURE_2D, tex);
          gl.uniform1i(locs.tex, 0);
          gl.uniform1f(locs.thickness, cfg.thickness);
          state.glOk = true;
          dirty = true;
          return true;
        }} catch (_e) {{
          return false;
        }}
      }}

      canvas.addEventListener('webglcontextlost', (e) => {{
        e.preventDefault();
        state.glOk = false;
      }});
      canvas.addEventListener('webglcontextrestored', () => {{
        if (initWebGL()) scheduleFrame();
      }});

      if (!initWebGL()) {{
        ctx2d = canvas.getContext('2d');
      }}

      withLuminaraLogoImage((img) => {{
        loadedImg = img;
        if (state.glOk && gl && !gl.isContextLost() && tex) {{
          gl.bindTexture(gl.TEXTURE_2D, tex);
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
        }}
        dirty = true;
        scheduleFrame();
      }});

      function resizeCanvas() {{
        const cw = canvas.clientWidth;
        const ch = canvas.clientHeight;
        if (!cw || !ch) return false;
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const w = Math.max(64, Math.min(1024, Math.round(cw * dpr)));
        const h = Math.max(64, Math.min(1024, Math.round(ch * dpr)));
        if (canvas.width !== w || canvas.height !== h) {{
          canvas.width = w;
          canvas.height = h;
          dirty = true;
        }}
        return true;
      }}

      function scheduleFrame() {{
        if (state.active && !document.hidden && !state.rafId) {{
          prevMs = performance.now();
          state.rafId = requestAnimationFrame(frame);
        }}
      }}

      function triggerPulse(ox, oy) {{
        state.pulseTime = 0.0;
        state.pulseOriginX = typeof ox === 'number' ? ox : 0.5;
        state.pulseOriginY = typeof oy === 'number' ? oy : 0.53;
        state.velX += (Math.random() - 0.5) * 0.06;
        state.velY += 0.08;
        dirty = true;
        scheduleFrame();
      }}

      function triggerSpin360() {{
        state.targetY += Math.PI * 2;
        triggerPulse(0.5, 0.53);
      }}

      if (cfg.interactive) {{
        canvas.addEventListener('pointerdown', (e) => {{
          state.dragging = true;
          state.lastPx = e.clientX;
          state.lastPy = e.clientY;
          state.downX = e.clientX;
          state.downY = e.clientY;
          try {{ canvas.setPointerCapture(e.pointerId); }} catch (_err) {{}}
          if (cfg.onInteract) cfg.onInteract('drag');
          dirty = true;
          scheduleFrame();
        }});
        canvas.addEventListener('pointermove', (e) => {{
          const rect = canvas.getBoundingClientRect();
          const nx = ((e.clientX - rect.left) / Math.max(1, rect.width)) * 2 - 1;
          const ny = -(((e.clientY - rect.top) / Math.max(1, rect.height)) * 2 - 1);
          state.cursorX = Math.max(-1, Math.min(1, nx));
          state.cursorY = Math.max(-1, Math.min(1, ny));
          state.targetLightX = state.cursorX * 0.9;
          state.targetLightY = state.cursorY * 0.9;
          if (state.dragging) {{
            const dx = e.clientX - state.lastPx;
            const dy = e.clientY - state.lastPy;
            state.lastPx = e.clientX;
            state.lastPy = e.clientY;
            state.targetY += dx * 0.012;
            state.targetX = Math.max(-1.15, Math.min(1.15, state.targetX + dy * 0.011));
          }} else {{
            state.targetY = Math.round(state.targetY / (Math.PI * 2)) * (Math.PI * 2) + state.cursorX * 0.34;
            state.targetX = -state.cursorY * 0.28;
          }}
          dirty = true;
          scheduleFrame();
        }});
        const endDrag = (e) => {{
          if (!state.dragging) return;
          state.dragging = false;
          const moved = Math.hypot(e.clientX - state.downX, e.clientY - state.downY);
          if (moved < 7) {{
            const rect = canvas.getBoundingClientRect();
            const ux = Math.max(0, Math.min(1, (e.clientX - rect.left) / Math.max(1, rect.width)));
            const uy = Math.max(0, Math.min(1, (e.clientY - rect.top) / Math.max(1, rect.height)));
            triggerPulse(ux, uy);
            if (cfg.onInteract) cfg.onInteract('pulse');
          }}
        }};
        canvas.addEventListener('pointerup', endDrag);
        canvas.addEventListener('pointercancel', endDrag);
        canvas.addEventListener('pointerleave', () => {{
          if (!state.dragging) {{
            state.targetX = 0;
            state.targetY = Math.round(state.targetY / (Math.PI * 2)) * (Math.PI * 2);
            state.targetLightX = 0.25;
            state.targetLightY = 0.35;
            dirty = true;
            scheduleFrame();
          }}
        }});
        if (cfg.zoomable) {{
          canvas.addEventListener('wheel', (e) => {{
            e.preventDefault();
            state.targetZoom = Math.max(0.84, Math.min(1.26, state.targetZoom - e.deltaY * 0.00055));
            if (cfg.onInteract) cfg.onInteract('zoom');
            dirty = true;
            scheduleFrame();
          }}, {{ passive: false }});
        }}
      }}

      let prevMs = performance.now();
      function frame(nowMs) {{
        state.rafId = 0;
        if (!state.active || document.hidden) return;
        const dt = Math.min(0.05, Math.max(0.001, (nowMs - prevMs) / 1000));
        prevMs = nowMs;
        const elapsed = (nowMs - state.startMs) / 1000;

        const idleY = (!state.dragging && !REDUCED_MOTION) ? Math.sin(elapsed * 1.15) * 0.14 : 0;
        const idleX = (!state.dragging && !REDUCED_MOTION) ? Math.cos(elapsed * 0.85) * 0.07 : 0;
        const stiffness = state.dragging ? 18.0 : 7.5;
        const damp = Math.pow(state.dragging ? 0.72 : 0.84, dt * 60);

        state.velX = (state.velX + ((state.targetX + idleX) - state.rotX) * stiffness * dt) * damp;
        state.velY = (state.velY + ((state.targetY + idleY) - state.rotY) * stiffness * dt) * damp;
        state.rotX += state.velX;
        state.rotY += state.velY;
        state.zoom += (state.targetZoom - state.zoom) * Math.min(1, dt * 7.0);
        state.lightX += (state.targetLightX - state.lightX) * Math.min(1, dt * 8.0);
        state.lightY += (state.targetLightY - state.lightY) * Math.min(1, dt * 8.0);
        if (state.pulseTime < 2.0) state.pulseTime += dt * 1.25;

        if (resizeCanvas()) {{
          if (state.glOk && gl && !gl.isContextLost() && prog) {{
            gl.viewport(0, 0, canvas.width, canvas.height);
            gl.clearColor(0, 0, 0, 0);
            gl.clear(gl.COLOR_BUFFER_BIT);
            gl.uniform1f(locs.time, REDUCED_MOTION ? 0.0 : elapsed);
            gl.uniform2f(locs.rot, state.rotX, state.rotY);
            gl.uniform1f(locs.zoom, state.zoom);
            gl.uniform2f(locs.light, state.lightX, state.lightY);
            gl.uniform2f(locs.cursor, state.cursorX, state.cursorY);
            gl.uniform1f(locs.pulse, state.pulseTime);
            gl.uniform2f(locs.pulseOrigin, state.pulseOriginX, state.pulseOriginY);
            gl.drawArrays(gl.TRIANGLES, 0, 6);
          }} else if (ctx2d && loadedImg) {{
            const w = canvas.width, h = canvas.height;
            const src = getAlphaKeyedLogoCanvas(loadedImg);
            ctx2d.clearRect(0, 0, w, h);
            const s = Math.min(w, h) * 0.92 * state.zoom;
            ctx2d.save();
            ctx2d.translate(w / 2, h / 2);
            ctx2d.drawImage(src, -s / 2, -s / 2, s, s);
            ctx2d.restore();
            canvas.style.transform = 'perspective(820px) rotateX(' + (state.rotX * 57.29578).toFixed(2) + 'deg) rotateY(' + (state.rotY * 57.29578).toFixed(2) + 'deg)';
          }}
        }}
        const settled = REDUCED_MOTION && !state.dragging && state.pulseTime >= 2.0
          && Math.abs(state.velX) < 0.0005 && Math.abs(state.velY) < 0.0005
          && Math.abs(state.targetX - state.rotX) < 0.002 && Math.abs(state.targetY - state.rotY) < 0.002;
        dirty = false;
        if (!settled) {{
          state.rafId = requestAnimationFrame(frame);
        }}
      }}

      scheduleFrame();
      return {{
        pulse: () => triggerPulse(0.5, 0.53),
        spin360: triggerSpin360,
        setActive: (flag) => {{
          if (flag && !state.active) {{
            state.active = true;
            dirty = true;
            scheduleFrame();
          }} else if (!flag && state.active) {{
            state.active = false;
            if (state.rafId) {{ cancelAnimationFrame(state.rafId); state.rafId = 0; }}
          }}
        }},
        isWebGL: () => Boolean(state.glOk && gl && !gl.isContextLost()),
      }};
    }}

    (function initLuminaraStartupExperience() {{
      const splashEl = document.getElementById('luminaraSplash');
      const splashStage = document.getElementById('splashLogoStage');
      const splashCanvas = document.getElementById('splashLogoCanvas');
      const heroCanvas = document.getElementById('heroLogoCanvas');
      const heroWrap = document.getElementById('heroLogo3dWrap');
      const barEl = document.getElementById('splashProgressBar');
      const trackEl = document.getElementById('splashProgressTrack');
      const statusEl = document.getElementById('splashStatusText');
      const hintEl = document.getElementById('splashHintText');
      const btnEnter = document.getElementById('btnEnterDeck');
      const btnPulse = document.getElementById('btnPulseLogo');
      const btnSpin = document.getElementById('btnSpinLogo');

      let splashEngine = null;
      let userInteracted = false;
      let bootDone = false;
      let splashOpen = false;
      let prevFocus = null;
      let autoDismissTimer = null;
      let closeTimer = null;
      let bootTimer1 = null;
      let bootTimer2 = null;
      let maxProgress = 0;

      function cancelTimers(markInteracted) {{
        if (markInteracted) userInteracted = true;
        if (autoDismissTimer) {{ clearTimeout(autoDismissTimer); autoDismissTimer = null; }}
        if (bootTimer1) {{ clearTimeout(bootTimer1); bootTimer1 = null; }}
        if (bootTimer2) {{ clearTimeout(bootTimer2); bootTimer2 = null; }}
      }}

      function setProgress(pct, label, force) {{
        const next = Math.max(0, Math.min(100, pct));
        if (!force && next < maxProgress) return;
        maxProgress = next;
        if (barEl) barEl.style.width = next + '%';
        if (trackEl) trackEl.setAttribute('aria-valuenow', String(Math.round(next)));
        if (statusEl && label) statusEl.textContent = label;
      }}

      function ensureSplashEngine(introSweep) {{
        if (splashEngine) return splashEngine;
        splashEngine = createLuminara3DLogo(splashCanvas, {{
          interactive: true,
          zoomable: true,
          introSweep: Boolean(introSweep),
          thickness: 0.135,
          onInteract: (kind) => {{
            cancelTimers(true);
            if (hintEl) hintEl.textContent = 'INTERACTIVE 3D MODE ACTIVE · PRESS ESC OR CLICK "ENTER COMMAND DECK"';
            if (kind === 'drag' && statusEl && bootDone) statusEl.textContent = '3D ORBIT ACTIVE · ENGINE READY';
          }},
        }});
        return splashEngine;
      }}

      const heroEngine = createLuminara3DLogo(heroCanvas, {{
        interactive: true,
        zoomable: false,
        introSweep: false,
        thickness: 0.11,
      }});

      function closeSplash() {{
        if (!splashEl || splashEl.classList.contains('hidden')) return;
        splashOpen = false;
        splashEl.classList.add('hidden');
        cancelTimers(false);
        try {{ sessionStorage.setItem('luminara_splash_seen', '1'); }} catch (_e) {{}}
        if (heroEngine) heroEngine.setActive(!document.hidden);
        if (closeTimer) clearTimeout(closeTimer);
        closeTimer = setTimeout(() => {{
          closeTimer = null;
          if (splashEl.classList.contains('hidden') && splashEngine) splashEngine.setActive(false);
        }}, 300);
        const restore = (prevFocus && document.contains(prevFocus)) ? prevFocus : document.getElementById('omniInput');
        prevFocus = null;
        if (restore && typeof restore.focus === 'function') restore.focus();
      }}

      function showSplash(opts) {{
        if (!splashEl) return;
        const isStartup = Boolean(opts && opts.startup);
        if (closeTimer) {{ clearTimeout(closeTimer); closeTimer = null; }}
        prevFocus = document.activeElement;
        splashOpen = true;
        splashEl.classList.remove('hidden');
        if (heroEngine) heroEngine.setActive(false);
        const eng = ensureSplashEngine(isStartup);
        if (eng) {{
          eng.setActive(true);
          if (!isStartup) eng.pulse();
        }}
        if (isStartup) {{
          maxProgress = 14;
          setProgress(14, 'INITIALIZING 3D ENGINE & PRIVACY SHIELD v3...', true);
          bootTimer1 = setTimeout(() => {{ if (!bootDone) setProgress(42, 'ARMING PRIVACY SHIELD v3 & FARBLING ENGINE...'); }}, 360);
          bootTimer2 = setTimeout(() => {{ if (!bootDone) setProgress(76, 'CONNECTING MULTIPLEXED CDP & AGENT DAEMON...'); }}, 900);
        }} else {{
          cancelTimers(true);
          setProgress(100, '3D EMBLEM SHOWCASE · ENGINE ONLINE', true);
        }}
        if (btnEnter && typeof btnEnter.focus === 'function') btnEnter.focus();
      }}

      function openSplash() {{ showSplash({{ startup: false }}); }}

      const rawHash = (typeof INITIAL_HASH === 'string' && INITIAL_HASH) ? INITIAL_HASH : (window.location.hash || '');
      const forceSplash = /(?:^#|&)splash(?:=|&|$)/i.test(rawHash);
      const hasChromeSession = typeof chrome !== 'undefined' && chrome.storage && chrome.storage.session && typeof chrome.storage.session.get === 'function';

      function decideStartupSplash(alreadySeen) {{
        if (!alreadySeen || forceSplash) {{
          if (hasChromeSession && !forceSplash) {{
            try {{ chrome.storage.session.set({{ luminara_splash_seen: true }}); }} catch (_e) {{}}
          }}
          try {{ sessionStorage.setItem('luminara_splash_seen', '1'); }} catch (_e) {{}}
          showSplash({{ startup: true }});
          if (bootDone && !forceSplash && !userInteracted && !navigator.webdriver) {{
            autoDismissTimer = setTimeout(() => {{ if (!userInteracted) closeSplash(); }}, 1900);
          }}
        }}
      }}

      if (hasChromeSession && !forceSplash) {{
        chrome.storage.session.get('luminara_splash_seen', (res) => {{
          decideStartupSplash(Boolean(res && res.luminara_splash_seen));
        }});
      }} else {{
        let seen = false;
        try {{ seen = sessionStorage.getItem('luminara_splash_seen') === '1'; }} catch (_e) {{}}
        decideStartupSplash(seen);
      }}

      window.__luminaraSplashNotifyDaemon = function(ok, st) {{
        if (bootDone) return;
        bootDone = true;
        if (bootTimer1) {{ clearTimeout(bootTimer1); bootTimer1 = null; }}
        if (bootTimer2) {{ clearTimeout(bootTimer2); bootTimer2 = null; }}
        const tabCount = (st && typeof st.open_tabs === 'number')
          ? st.open_tabs
          : ((st && Array.isArray(st.tabs)) ? st.tabs.length : 0);
        const msg = ok
          ? ('AGENT DAEMON ONLINE · ' + tabCount + ' TAB(S) · ZERO GOOGLE TELEMETRY')
          : 'STANDALONE PRIVACY MODE READY · ZERO GOOGLE TELEMETRY';
        setProgress(100, msg, true);
        if (splashOpen && !forceSplash && !userInteracted && !navigator.webdriver) {{
          autoDismissTimer = setTimeout(() => {{ if (!userInteracted) closeSplash(); }}, 1900);
        }}
      }};

      if (btnEnter) btnEnter.addEventListener('click', closeSplash);
      if (btnPulse) btnPulse.addEventListener('click', () => {{
        cancelTimers(true);
        const eng = ensureSplashEngine(false);
        if (eng) eng.pulse();
      }});
      if (btnSpin) btnSpin.addEventListener('click', () => {{
        cancelTimers(true);
        const eng = ensureSplashEngine(false);
        if (eng) eng.spin360();
      }});
      if (splashStage) {{
        splashStage.addEventListener('keydown', (e) => {{
          if (e.key === ' ' || e.key === 'Enter') {{
            e.preventDefault();
            e.stopPropagation();
            cancelTimers(true);
            const eng = ensureSplashEngine(false);
            if (eng) eng.pulse();
          }}
        }});
      }}
      if (heroWrap) {{
        heroWrap.addEventListener('dblclick', openSplash);
        heroWrap.addEventListener('keydown', (e) => {{
          if (e.key === 'Enter' || e.key === ' ') {{
            e.preventDefault();
            e.stopPropagation();
            openSplash();
          }}
        }});
      }}
      const btnReplayIntro = document.getElementById('btnReplayIntro');
      if (btnReplayIntro) btnReplayIntro.addEventListener('click', openSplash);

      document.addEventListener('keydown', (e) => {{
        if (!splashEl || splashEl.classList.contains('hidden')) return;
        const paletteOpen = Boolean(document.getElementById('__luminara_cmd_palette'));
        if (e.key === 'Escape' && !paletteOpen) {{
          e.preventDefault();
          closeSplash();
          return;
        }}
        if (e.key === 'Enter' && !paletteOpen) {{
          const tgt = e.target;
          if (!tgt || !tgt.closest || !tgt.closest('button, a, input, textarea, [role="button"]')) {{
            e.preventDefault();
            closeSplash();
          }}
          return;
        }}
        if (e.key === 'Tab') {{
          const focusables = Array.from(splashEl.querySelectorAll('button, [tabindex="0"]'));
          if (!focusables.length) return;
          const idx = focusables.indexOf(document.activeElement);
          e.preventDefault();
          const next = e.shiftKey
            ? focusables[(idx <= 0 ? focusables.length : idx) - 1]
            : focusables[(idx + 1) % focusables.length];
          next.focus();
        }}
      }});

      document.addEventListener('visibilitychange', () => {{
        const vis = !document.hidden;
        if (splashEngine) splashEngine.setActive(vis && splashOpen);
        if (heroEngine) heroEngine.setActive(vis && !splashOpen);
      }});

      window.__luminaraLogo3D = {{
        openSplash,
        closeSplash,
        get splashEngine() {{ return ensureSplashEngine(false); }},
        heroEngine,
      }};
    }})();
"""


__all__ = [
    "LOGO_3D_CSS",
    "build_logo_3d_hero_badge_html",
    "build_logo_3d_js",
    "build_logo_3d_splash_html",
    "get_logo_data_uri",
    "get_logo_favicon_data_uri",
    "get_logo_icon_png",
    "write_extension_icons",
]
