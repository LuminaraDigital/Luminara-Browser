"""Interactive 3D Metallic Gold Logo & Desktop Startup Splash (`forge/luminara_logo3d.py`).

Self-contained, offline-first WebGL volumetric extruded-relief 3D logo engine with:
- Raymarched 20-slice 3D extrusion from the Luminara Digital emblem (front, beveled walls, and back for 360 deg spin).
- Real-time Sobel normal-mapped metallic gold PBR lighting, cursor-tracked specular & eye catchlight, and click energy pulse.
- Smooth Canvas 2D + CSS 3D fallback when WebGL is unavailable (e.g., `--disable-gpu` or reduced motion).
- Desktop startup loading splash overlay synchronized with Agent Daemon boot telemetry + persistent Hero 3D mini-emblem.
- Strict MV3 CSP compliance: zero external CDNs, zero `.innerHTML`, zero `eval`.
"""

from __future__ import annotations

import base64
from functools import lru_cache
import html
from pathlib import Path

from .luminara_copilot_ext import _js_json

_UI_DIR = Path(__file__).resolve().parent / "ui"
_LOGO_WEBP = _UI_DIR / "luminara-logo.webp"
_LOGO_PNG = _UI_DIR / "luminara-logo.png"


@lru_cache(maxsize=1)
def get_logo_data_uri() -> str:
    """Return the Luminara Digital emblem as an inline data URI (WebP preferred, PNG fallback)."""
    if _LOGO_WEBP.is_file():
        b64 = base64.b64encode(_LOGO_WEBP.read_bytes()).decode("ascii")
        return f"data:image/webp;base64,{b64}"
    if _LOGO_PNG.is_file():
        b64 = base64.b64encode(_LOGO_PNG.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    return ""


def get_logo_icon_png(size: int) -> bytes | None:
    """Return pre-rendered Luminara Digital emblem PNG bytes for MV3 extension icons (pure stdlib)."""
    icon_path = _UI_DIR / f"icon{size}.png"
    if icon_path.is_file():
        return icon_path.read_bytes()
    return None


LOGO_3D_CSS = """
    .lum-splash {
      position: fixed; inset: 0; z-index: 10000;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      gap: 18px; padding: clamp(16px, 3vw, 32px);
      background:
        radial-gradient(640px 440px at 50% 44%, oklch(0.32 0.065 82 / 0.24), transparent 68%),
        radial-gradient(880px 520px at 50% 100%, oklch(0.24 0.05 162 / 0.14), transparent 72%),
        #050608;
      color: oklch(0.95 0.012 85);
      opacity: 1; transform: scale(1); filter: blur(0px);
      transition: opacity 280ms cubic-bezier(0.4, 0, 1, 1), transform 280ms cubic-bezier(0.4, 0, 1, 1), filter 280ms cubic-bezier(0.4, 0, 1, 1);
    }
    .lum-splash.hidden {
      opacity: 0; transform: scale(1.03); filter: blur(6px);
      pointer-events: none; visibility: hidden;
    }
    .lum-splash-stage {
      position: relative; width: min(370px, 76vw, 48vh); aspect-ratio: 1 / 1;
      display: grid; place-items: center; cursor: grab; touch-action: none; user-select: none;
      animation: lumStageEnter 620ms cubic-bezier(0.16, 1, 0.3, 1) both;
    }
    .lum-splash-stage:active { cursor: grabbing; }
    .lum-splash-halo {
      position: absolute; inset: 10%; border-radius: 50%; pointer-events: none;
      background: radial-gradient(circle, oklch(0.79 0.12 84 / 0.22) 0%, oklch(0.75 0.11 84 / 0.06) 48%, transparent 72%);
      filter: blur(18px); animation: lumHaloBreath 4.2s ease-in-out infinite;
    }
    .lum-logo-canvas {
      position: relative; z-index: 2; width: 100%; height: 100%; display: block; border-radius: 50%;
    }
    .lum-splash-meta {
      width: min(440px, 90vw); display: flex; flex-direction: column; align-items: center; gap: 11px;
      text-align: center; animation: lumMetaEnter 520ms 120ms cubic-bezier(0.16, 1, 0.3, 1) both;
    }
    .lum-splash-kicker {
      font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase;
      color: oklch(0.84 0.095 84);
    }
    .lum-splash-status {
      font-family: var(--font-mono); font-size: 12px; color: oklch(0.76 0.015 85);
      min-height: 18px; font-variant-numeric: tabular-nums;
    }
    .lum-splash-track {
      width: 100%; height: 4px; border-radius: 999px; overflow: hidden;
      background: oklch(1 0 0 / 0.09); border: 1px solid oklch(0.82 0.09 84 / 0.2);
    }
    .lum-splash-bar {
      width: 14%; height: 100%; border-radius: 999px;
      background: linear-gradient(90deg, oklch(0.68 0.11 76), oklch(0.88 0.11 88), oklch(0.76 0.15 162));
      box-shadow: 0 0 14px oklch(0.82 0.11 84 / 0.55);
      transition: width 260ms cubic-bezier(0.16, 1, 0.3, 1);
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
      color: oklch(0.64 0.02 84);
    }
    .hero-brand-wrap { display: flex; align-items: center; gap: 16px; min-width: 0; }
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
    """Return semantic HTML for the full-viewport interactive 3D startup loading splash."""
    brand_esc = html.escape(brand_name)
    ver_esc = html.escape(chromium_version)
    return f"""  <div class="lum-splash" id="luminaraSplash" role="dialog" aria-modal="true" aria-label="{brand_esc} 3D Startup Experience">
    <div class="lum-splash-stage" id="splashLogoStage" tabindex="0" aria-label="Interactive 3D {brand_esc} Emblem — drag to rotate, click to pulse">
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
        f'<canvas class="lum-logo-canvas" id="heroLogoCanvas" width="160" height="160"></canvas>'
        f"</div>"
    )


def build_logo_3d_js() -> str:
    """Return self-contained vanilla JS for the WebGL 3D extruded gold logo + startup splash lifecycle."""
    logo_uri_js = _js_json(get_logo_data_uri())
    return f"""
    // === LUMINARA DIGITAL 3D VOLUMETRIC GOLD LOGO ENGINE & STARTUP SPLASH ===
    const LUMINARA_LOGO_URI = {logo_uri_js};
    const REDUCED_MOTION = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const _logoImageCache = {{ img: null, ready: false, cbs: [] }};

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
      img.src = LUMINARA_LOGO_URI;
      _logoImageCache.img = img;
    }}

    function createLuminara3DLogo(canvas, opts) {{
      const cfg = Object.assign({{
        interactive: true,
        introSweep: false,
        slices: 20,
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

      function initWebGL() {{
        try {{
          gl = canvas.getContext('webgl', {{ alpha: true, antialias: true, premultipliedAlpha: false, powerPreference: 'high-performance' }})
            || canvas.getContext('experimental-webgl', {{ alpha: true, antialias: true }});
          if (!gl) return false;

          const vsSrc = [
            'attribute vec2 a_pos;',
            'varying vec2 v_ndc;',
            'void main() {{ v_ndc = a_pos; gl_Position = vec4(a_pos, 0.0, 1.0); }}'
          ].join('\\n');

          const fsSrc = [
            'precision highp float;',
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
            '  float dirSign = lrd.z < 0.0 ? 1.0 : -1.0;',
            '  float zStart = dirSign * halfT;',
            '  float zEnd = -dirSign * halfT;',
            '  const int STEPS = 20;',
            '  vec4 outCol = vec4(0.0);',
            '  bool hit = false;',
            '  vec2 hitUv = vec2(0.0);',
            '  float hitDepth = 0.0;',
            '  vec3 hitTex = vec3(0.0);',
            '  float hitLum = 0.0;',
            '  for (int i = 0; i < STEPS; i++) {{',
            '    float f = float(i) / float(STEPS - 1);',
            '    float z = mix(zStart, zEnd, f);',
            '    float t = (z - lro.z) / (abs(lrd.z) < 0.0001 ? 0.0001 : lrd.z);',
            '    if (t <= 0.0) continue;',
            '    vec3 hp = lro + lrd * t;',
            '    vec2 uv = vec2(hp.x, -hp.y) / 1.82 + 0.5;',
            '    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) continue;',
            '    vec3 c = texture2D(u_tex, uv).rgb;',
            '    float lum = luma(c);',
            '    float bevelMask = (i == 0) ? smoothstep(0.085, 0.24, lum) : smoothstep(0.11, 0.28, lum);',
            '    if (bevelMask > 0.35) {{',
            '      hit = true; hitUv = uv; hitDepth = f; hitTex = c; hitLum = lum;',
            '      break;',
            '    }}',
            '  }}',
            '',
            '  // Subtle orbiting 3D gold dust motes in background',
            '  vec3 bgGlow = vec3(0.0);',
            '  float bgAlpha = 0.0;',
            '  for (int k = 0; k < 10; k++) {{',
            '    float fk = float(k);',
            '    float ang = u_time * (0.28 + 0.05 * mod(fk, 3.0)) + fk * 0.6283;',
            '    float rad = 0.68 + 0.24 * sin(fk * 1.9 + u_time * 0.4);',
            '    vec2 mp = vec2(cos(ang), sin(ang) * 0.85) * rad + u_cursor * 0.04;',
            '    float d = length(p - mp);',
            '    float spark = exp(-d * d * 2400.0) * (0.45 + 0.55 * sin(u_time * 2.4 + fk * 2.1));',
            '    bgGlow += vec3(1.0, 0.84, 0.46) * spark * 0.65;',
            '    bgAlpha += spark * 0.55;',
            '  }}',
            '',
            '  if (!hit) {{',
            '    if (u_pulse < 1.35) {{',
            '      float pr = u_pulse * 0.95;',
            '      float pd = length((p * 0.5 + 0.5) - vec2(u_pulseOrigin.x, 1.0 - u_pulseOrigin.y));',
            '      float ring = exp(-pow((pd - pr) * 26.0, 2.0)) * (1.0 - smoothstep(0.0, 1.35, u_pulse));',
            '      bgGlow += vec3(1.0, 0.86, 0.48) * ring * 0.52;',
            '      bgAlpha += ring * 0.42;',
            '    }}',
            '    gl_FragColor = vec4(bgGlow, clamp(bgAlpha, 0.0, 1.0));',
            '    return;',
            '  }}',
            '',
            '  // Sobel 3x3 normal estimation for sculpted gold bevels',
            '  float eps = 1.0 / 340.0;',
            '  float hL = sampleH(hitUv - vec2(eps, 0.0));',
            '  float hR = sampleH(hitUv + vec2(eps, 0.0));',
            '  float hU = sampleH(hitUv - vec2(0.0, eps));',
            '  float hD = sampleH(hitUv + vec2(0.0, eps));',
            '  vec3 N = normalize(vec3((hL - hR) * 2.8, (hD - hU) * 2.8, dirSign * 0.92));',
            '  if (hitDepth > 0.02) {{',
            '    N = normalize(vec3((hL - hR) * 4.5, (hD - hU) * 4.5, dirSign * 0.25));',
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
            '  float alpha = smoothstep(0.075, 0.22, hitLum);',
            '  gl_FragColor = vec4(col + bgGlow * 0.35, clamp(alpha, 0.0, 1.0));',
            '}}'
          ].join('\\n');

          function compile(type, src) {{
            const s = gl.createShader(type);
            gl.shaderSource(s, src);
            gl.compileShader(s);
            if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) return null;
            return s;
          }}
          const vs = compile(gl.VERTEX_SHADER, vsSrc);
          const fs = compile(gl.FRAGMENT_SHADER, fsSrc);
          if (!vs || !fs) return false;
          prog = gl.createProgram();
          gl.attachShader(prog, vs);
          gl.attachShader(prog, fs);
          gl.linkProgram(prog);
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
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0,0,0,0]));

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
          gl.enable(gl.BLEND);
          gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
          state.glOk = true;
          return true;
        }} catch (_e) {{
          return false;
        }}
      }}

      if (!initWebGL()) {{
        ctx2d = canvas.getContext('2d');
      }}

      withLuminaraLogoImage((img) => {{
        loadedImg = img;
        if (state.glOk && gl && tex) {{
          gl.bindTexture(gl.TEXTURE_2D, tex);
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
        }}
      }});

      function resizeCanvas() {{
        const rect = canvas.getBoundingClientRect();
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const w = Math.max(64, Math.round((rect.width || canvas.width || 256) * dpr));
        const h = Math.max(64, Math.round((rect.height || canvas.height || 256) * dpr));
        if (canvas.width !== w || canvas.height !== h) {{
          canvas.width = w;
          canvas.height = h;
        }}
      }}

      function triggerPulse(ox, oy) {{
        state.pulseTime = 0.0;
        state.pulseOriginX = typeof ox === 'number' ? ox : 0.5;
        state.pulseOriginY = typeof oy === 'number' ? oy : 0.53;
        state.velX += (Math.random() - 0.5) * 0.06;
        state.velY += 0.08;
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
          }}
        }});
        canvas.addEventListener('wheel', (e) => {{
          e.preventDefault();
          state.targetZoom = Math.max(0.84, Math.min(1.26, state.targetZoom - e.deltaY * 0.00055));
          if (cfg.onInteract) cfg.onInteract('zoom');
        }}, {{ passive: false }});
      }}

      let prevMs = performance.now();
      function frame(nowMs) {{
        if (!state.active) return;
        const dt = Math.min(0.05, Math.max(0.001, (nowMs - prevMs) / 1000));
        prevMs = nowMs;
        const elapsed = (nowMs - state.startMs) / 1000;

        // Ambient 3D floating breathing when idle
        const idleY = (!state.dragging && !REDUCED_MOTION) ? Math.sin(elapsed * 1.15) * 0.14 : 0;
        const idleX = (!state.dragging && !REDUCED_MOTION) ? Math.cos(elapsed * 0.85) * 0.07 : 0;
        const stiffness = state.dragging ? 18.0 : 7.5;
        const damping = state.dragging ? 0.72 : 0.84;

        state.velX = (state.velX + ((state.targetX + idleX) - state.rotX) * stiffness * dt) * damping;
        state.velY = (state.velY + ((state.targetY + idleY) - state.rotY) * stiffness * dt) * damping;
        state.rotX += state.velX;
        state.rotY += state.velY;
        state.zoom += (state.targetZoom - state.zoom) * Math.min(1, dt * 7.0);
        state.lightX += (state.targetLightX - state.lightX) * Math.min(1, dt * 8.0);
        state.lightY += (state.targetLightY - state.lightY) * Math.min(1, dt * 8.0);
        if (state.pulseTime < 2.0) state.pulseTime += dt * 1.25;

        resizeCanvas();
        if (state.glOk && gl && prog) {{
          gl.viewport(0, 0, canvas.width, canvas.height);
          gl.clearColor(0, 0, 0, 0);
          gl.clear(gl.COLOR_BUFFER_BIT);
          gl.useProgram(prog);
          gl.activeTexture(gl.TEXTURE0);
          gl.bindTexture(gl.TEXTURE_2D, tex);
          gl.uniform1i(locs.tex, 0);
          gl.uniform1f(locs.time, REDUCED_MOTION ? 0.0 : elapsed);
          gl.uniform2f(locs.rot, state.rotX, state.rotY);
          gl.uniform1f(locs.zoom, state.zoom);
          gl.uniform2f(locs.light, state.lightX, state.lightY);
          gl.uniform2f(locs.cursor, state.cursorX, state.cursorY);
          gl.uniform1f(locs.pulse, state.pulseTime);
          gl.uniform2f(locs.pulseOrigin, state.pulseOriginX, state.pulseOriginY);
          gl.uniform1f(locs.thickness, cfg.thickness);
          gl.drawArrays(gl.TRIANGLES, 0, 6);
        }} else if (ctx2d && loadedImg) {{
          const w = canvas.width, h = canvas.height;
          ctx2d.clearRect(0, 0, w, h);
          const s = Math.min(w, h) * 0.92 * state.zoom;
          ctx2d.save();
          ctx2d.translate(w / 2, h / 2);
          ctx2d.drawImage(loadedImg, -s / 2, -s / 2, s, s);
          ctx2d.restore();
          canvas.style.transform = 'perspective(820px) rotateX(' + (state.rotX * 26).toFixed(2) + 'deg) rotateY(' + (state.rotY * 26).toFixed(2) + 'deg)';
        }}
        state.rafId = requestAnimationFrame(frame);
      }}

      state.rafId = requestAnimationFrame(frame);
      return {{
        pulse: () => triggerPulse(0.5, 0.53),
        spin360: triggerSpin360,
        setActive: (flag) => {{
          if (flag && !state.active) {{
            state.active = true;
            prevMs = performance.now();
            state.rafId = requestAnimationFrame(frame);
          }} else if (!flag && state.active) {{
            state.active = false;
            cancelAnimationFrame(state.rafId);
          }}
        }},
        isWebGL: () => state.glOk,
      }};
    }}

    (function initLuminaraStartupExperience() {{
      const splashEl = document.getElementById('luminaraSplash');
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

      let userInteracted = false;
      let bootDone = false;
      let autoDismissTimer = null;

      function setProgress(pct, label) {{
        if (barEl) barEl.style.width = Math.max(0, Math.min(100, pct)) + '%';
        if (trackEl) trackEl.setAttribute('aria-valuenow', String(Math.round(pct)));
        if (statusEl && label) statusEl.textContent = label;
      }}

      const splashEngine = createLuminara3DLogo(splashCanvas, {{
        interactive: true,
        introSweep: true,
        thickness: 0.135,
        onInteract: (kind) => {{
          userInteracted = true;
          if (autoDismissTimer) {{ clearTimeout(autoDismissTimer); autoDismissTimer = null; }}
          if (hintEl) hintEl.textContent = 'INTERACTIVE 3D MODE ACTIVE · PRESS ENTER OR CLICK "ENTER COMMAND DECK"';
          if (kind === 'drag' && statusEl && bootDone) statusEl.textContent = '3D ORBIT ACTIVE · ENGINE READY';
        }},
      }});

      const heroEngine = createLuminara3DLogo(heroCanvas, {{
        interactive: true,
        introSweep: false,
        thickness: 0.11,
      }});

      function closeSplash() {{
        if (!splashEl || splashEl.classList.contains('hidden')) return;
        splashEl.classList.add('hidden');
        try {{ sessionStorage.setItem('luminara_splash_seen', '1'); }} catch (_e) {{}}
        if (autoDismissTimer) {{ clearTimeout(autoDismissTimer); autoDismissTimer = null; }}
        setTimeout(() => {{ if (splashEngine) splashEngine.setActive(false); }}, 320);
      }}

      function openSplash() {{
        if (!splashEl) return;
        userInteracted = true;
        if (autoDismissTimer) {{ clearTimeout(autoDismissTimer); autoDismissTimer = null; }}
        splashEl.classList.remove('hidden');
        if (splashEngine) {{
          splashEngine.setActive(true);
          splashEngine.pulse();
        }}
        setProgress(100, '3D EMBLEM SHOWCASE · ENGINE ONLINE');
      }}

      const forceSplash = window.location.hash === '#splash';
      let alreadySeen = false;
      try {{ alreadySeen = sessionStorage.getItem('luminara_splash_seen') === '1'; }} catch (_e) {{}}
      if (alreadySeen && !forceSplash) {{
        if (splashEl) splashEl.classList.add('hidden');
        if (splashEngine) splashEngine.setActive(false);
      }} else {{
        setTimeout(() => setProgress(42, 'ARMING PRIVACY SHIELD v3 & FARBLING ENGINE...'), 380);
        setTimeout(() => {{
          if (!bootDone) setProgress(76, 'CONNECTING MULTIPLEXED CDP & AGENT DAEMON...');
        }}, 920);
      }}

      window.__luminaraSplashNotifyDaemon = function(ok, st) {{
        if (bootDone) return;
        bootDone = true;
        const tabCount = (st && Array.isArray(st.tabs)) ? st.tabs.length : 0;
        const msg = ok
          ? ('AGENT DAEMON ONLINE · ' + tabCount + ' TAB(S) · ZERO GOOGLE TELEMETRY')
          : 'OFFLINE VAULT MODE READY · ZERO GOOGLE TELEMETRY';
        setProgress(100, msg);
        if (!alreadySeen && !forceSplash && !userInteracted && !navigator.webdriver) {{
          autoDismissTimer = setTimeout(() => {{
            if (!userInteracted) closeSplash();
          }}, 1900);
        }}
      }};

      if (btnEnter) btnEnter.addEventListener('click', closeSplash);
      if (btnPulse) btnPulse.addEventListener('click', () => {{
        userInteracted = true;
        if (autoDismissTimer) {{ clearTimeout(autoDismissTimer); autoDismissTimer = null; }}
        if (splashEngine) splashEngine.pulse();
      }});
      if (btnSpin) btnSpin.addEventListener('click', () => {{
        userInteracted = true;
        if (autoDismissTimer) {{ clearTimeout(autoDismissTimer); autoDismissTimer = null; }}
        if (splashEngine) splashEngine.spin360();
      }});
      if (heroWrap) {{
        heroWrap.addEventListener('dblclick', openSplash);
        heroWrap.addEventListener('keydown', (e) => {{
          if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); openSplash(); }}
        }});
      }}
      const btnReplayIntro = document.getElementById('btnReplayIntro');
      if (btnReplayIntro) btnReplayIntro.addEventListener('click', openSplash);
      document.addEventListener('keydown', (e) => {{
        if (!splashEl || splashEl.classList.contains('hidden')) return;
        if (e.key === 'Escape' || e.key === 'Enter') {{ e.preventDefault(); closeSplash(); }}
      }});
      window.__luminaraLogo3D = {{ openSplash, closeSplash, splashEngine, heroEngine }};
    }})();
"""


__all__ = [
    "LOGO_3D_CSS",
    "build_logo_3d_hero_badge_html",
    "build_logo_3d_js",
    "build_logo_3d_splash_html",
    "get_logo_data_uri",
    "get_logo_icon_png",
]
