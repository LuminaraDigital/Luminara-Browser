(() => {
  const STORAGE_KEY = 'luminara_portal:page_count';
  const slider = document.getElementById('pageSlider');
  const countOut = document.getElementById('pageCountOut');
  const calcOut = document.getElementById('tokenCalcOut');
  const copyStatus = document.getElementById('copyStatus');
  const btnCopy = document.getElementById('btnCopyMcp');

  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && Number(saved) >= 1 && Number(saved) <= 50) {
      slider.value = String(Number(saved));
    }
  } catch (_e) {}

  function updateCalc() {
    const n = Number(slider.value) || 12;
    countOut.textContent = String(n);
    const raw = n * 2457;
    const som = n * 79;
    calcOut.textContent = `Raw HTML: ${raw.toLocaleString()} tokens vs Luminara Set-of-Marks: ${som.toLocaleString()} tokens (${(raw - som).toLocaleString()} tokens saved)`;
    try {
      localStorage.setItem(STORAGE_KEY, String(n));
    } catch (_e) {}
  }

  if (slider) {
    slider.addEventListener('input', updateCalc);
    updateCalc();
  }

  if (btnCopy) {
    btnCopy.addEventListener('click', async () => {
      const txt = document.getElementById('mcpSnippet').textContent;
      try {
        await navigator.clipboard.writeText(txt);
        copyStatus.textContent = 'Copied MCP v2 configuration to clipboard.';
      } catch (_e) {
        copyStatus.textContent = 'Select the JSON snippet above and press Ctrl+C to copy manually.';
      }
    });
  }

  const healthEl = document.getElementById('edgeHealthBadge');
  const dlBtn = document.getElementById('btnDownloadRelease');
  if (dlBtn) {
    fetch('/.well-known/agent.json')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d && typeof d.repository === 'string' && /^https:\/\/github\.com\//i.test(d.repository)) {
          dlBtn.href = d.repository.replace(/\/+$/, '') + '/releases/latest';
        }
      })
      .catch(() => {});
  }
  if (healthEl) {
    fetch('/api/health')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status))))
      .then((d) => {
        healthEl.textContent = `● Edge Active · v${d.version || '3.1.0'} · ${d.mcp_tool_count || 28} MCP Tools (${d.colo || 'edge'})`;
      })
      .catch(() => {
        healthEl.textContent = '○ Static Preview Mode · Local Daemon target 127.0.0.1:8796';
      });
  }

  // Interactive 3D Volumetric Metallic Gold Luminara Digital Emblem
  const canvas = document.getElementById('portalLogoCanvas');
  if (!canvas) return;
  const reduced = Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const st = {
    rotX: -0.22, rotY: 0.34, velX: 0, velY: 0, targetX: 0, targetY: 0,
    lightX: 0.25, lightY: 0.35, targetLightX: 0.25, targetLightY: 0.35,
    cursorX: 0, cursorY: 0, dragging: false, lastPx: 0, lastPy: 0, downX: 0, downY: 0,
    pulse: 0.05, pulseX: 0.5, pulseY: 0.53, glOk: false, rafId: 0, startMs: performance.now(),
  };
  let gl = null, prog = null, tex = null, locs = {}, ctx2d = null, loadedImg = null, keyedImg = null;

  function keyBlack(img) {
    if (keyedImg) return keyedImg;
    const c = document.createElement('canvas');
    c.width = img.naturalWidth || 512;
    c.height = img.naturalHeight || 512;
    const g = c.getContext('2d');
    if (!g) return img;
    g.drawImage(img, 0, 0, c.width, c.height);
    try {
      const id = g.getImageData(0, 0, c.width, c.height);
      const d = id.data;
      for (let i = 0; i < d.length; i += 4) {
        const lum = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
        const t = Math.max(0, Math.min(1, (lum - 18) / 38));
        d[i + 3] = Math.round(t * t * (3 - 2 * t) * 255);
      }
      g.putImageData(id, 0, 0);
      keyedImg = c;
      return c;
    } catch (_e) { return img; }
  }

  function initGL() {
    try {
      gl = canvas.getContext('webgl', { alpha: true, antialias: true, premultipliedAlpha: true });
      if (!gl || gl.isContextLost()) return false;
      const vsSrc = 'attribute vec2 a_pos; varying vec2 v_ndc; void main(){ v_ndc=a_pos; gl_Position=vec4(a_pos,0.0,1.0); }';
      const fsSrc = [
        '#ifdef GL_FRAGMENT_PRECISION_HIGH',
        'precision highp float;',
        '#else',
        'precision mediump float;',
        '#endif',
        'varying vec2 v_ndc; uniform sampler2D u_tex; uniform float u_time; uniform vec2 u_rot;',
        'uniform vec2 u_light; uniform vec2 u_cursor; uniform float u_pulse; uniform vec2 u_pulseOrigin;',
        'mat3 rx(float a){float c=cos(a),s=sin(a);return mat3(1.,0.,0.,0.,c,-s,0.,s,c);}',
        'mat3 ry(float a){float c=cos(a),s=sin(a);return mat3(c,0.,s,0.,1.,0.,-s,0.,c);}',
        'float lm(vec3 c){return dot(c,vec3(.299,.587,.114));}',
        'float sh(vec2 u){return (u.x<0.||u.x>1.||u.y<0.||u.y>1.)?0.:lm(texture2D(u_tex,u).rgb);}',
        'void main(){',
        '  vec2 p=v_ndc; mat3 invR=rx(-u_rot.x)*ry(-u_rot.y);',
        '  vec3 lro=invR*vec3(0.,0.,2.38), lrd=normalize(invR*normalize(vec3(p,-1.78)));',
        '  vec3 bMin=vec3(-.91,-.91,-.065), bMax=vec3(.91,.91,.065);',
        '  vec3 invD=1./(abs(lrd)+vec3(1e-6))*sign(lrd+vec3(1e-9));',
        '  vec3 t0=(bMin-lro)*invD, t1=(bMax-lro)*invD;',
        '  float tN=max(max(min(t0,t1).x,min(t0,t1).y),max(min(t0,t1).z,0.));',
        '  float tF=min(min(max(t0,t1).x,max(t0,t1).y),max(t0,t1).z);',
        '  float ds=lrd.z<0.?1.:-1.; bool hit=false; vec2 hUv=vec2(0.); float hD=0.,hL=0.; vec3 hT=vec3(0.);',
        '  if(tF>tN){ for(int i=0;i<20;i++){ float f=float(i)/19.; vec3 hp=lro+lrd*mix(tN,tF,f);',
        '    vec2 uv=vec2(hp.x,-hp.y)/1.82+.5; if(uv.x<0.||uv.x>1.||uv.y<0.||uv.y>1.) continue;',
        '    vec3 c=texture2D(u_tex,uv).rgb; float lum=lm(c);',
        '    if(((i==0)?smoothstep(.085,.24,lum):smoothstep(.11,.28,lum))>.35){hit=true;hUv=uv;hD=f;hT=c;hL=lum;break;}',
        '  }}',
        '  vec3 bg=vec3(0.); float ba=0.;',
        '  for(int k=0;k<8;k++){ float fk=float(k), ang=u_time*(.28+.05*mod(fk,3.))+fk*.7854;',
        '    vec2 mp=vec2(cos(ang),sin(ang)*.85)*(.68+.22*sin(fk*1.9+u_time*.4))+u_cursor*.04;',
        '    float sp=exp(-dot(p-mp,p-mp)*2400.)*(.45+.55*sin(u_time*2.4+fk*2.1));',
        '    bg+=vec3(1.,.84,.46)*sp*.72; ba+=sp*.62; }',
        '  if(!hit){ float aB=clamp(ba,0.,1.); gl_FragColor=vec4(bg*aB,aB); return; }',
        '  float e=1./340.; float gX=(sh(hUv-vec2(e,0.))-sh(hUv+vec2(e,0.)))*ds, gY=(sh(hUv+vec2(0.,e))-sh(hUv-vec2(0.,e)))*ds;',
        '  vec3 N=normalize(hD>.02?vec3(gX*4.5,gY*4.5,ds*.25):vec3(gX*2.8,gY*2.8,ds*.92));',
        '  vec3 V=normalize(-lrd), L1=normalize(invR*normalize(vec3(u_light*1.45,1.35))), H1=normalize(L1+V);',
        '  vec3 gold=mix(hT*vec3(1.08,1.01,.88),vec3(.95,.79,.42),.16);',
        '  vec3 col=gold*(.44+.72*max(dot(N,L1),0.)+.22*pow(max(dot(N,H1),0.),8.))*(hD>.02?mix(.68,.34,hD):1.);',
        '  col+=vec3(1.,.93,.70)*pow(max(dot(N,H1),0.),38.)*(hD>.02?.42:.95);',
        '  col+=vec3(.42,.88,.76)*pow(1.-max(dot(N,V),0.),2.6)*.22;',
        '  float sw=mod(u_time*.26,1.65)*2.1-.8;',
        '  col+=vec3(1.,.95,.78)*exp(-pow((hUv.x*.82+hUv.y*.58-sw)*11.,2.))*smoothstep(.18,.75,hL)*.52;',
        '  vec2 ec=vec2(.5,.528)+vec2(u_cursor.x*.016,-u_cursor.y*.012);',
        '  col+=vec3(1.,.94,.74)*exp(-dot(hUv-ec,hUv-ec)*2600.)*(.55+.45*sin(u_time*2.6))*.55;',
        '  if(u_pulse<1.35){ float w=exp(-pow((length(hUv-u_pulseOrigin)-u_pulse*.88)*20.,2.))*(1.-smoothstep(0.,1.35,u_pulse));',
        '    col+=vec3(1.,.91,.62)*w*.95; }',
        '  float a=clamp(smoothstep(.075,.22,hL),0.,1.);',
        '  gl_FragColor=vec4(col*a+bg*(1.-a)*.45,max(a,clamp(ba*.5,0.,1.)));',
        '}',
      ].join('\n');
      const cmp = (t, s) => {
        const sh = gl.createShader(t);
        gl.shaderSource(sh, s);
        gl.compileShader(sh);
        if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) { gl.deleteShader(sh); return null; }
        return sh;
      };
      const vs = cmp(gl.VERTEX_SHADER, vsSrc), fs = cmp(gl.FRAGMENT_SHADER, fsSrc);
      if (!vs || !fs) return false;
      prog = gl.createProgram();
      gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog);
      gl.deleteShader(vs); gl.deleteShader(fs);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return false;
      const buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), gl.STATIC_DRAW);
      const pLoc = gl.getAttribLocation(prog, 'a_pos');
      gl.enableVertexAttribArray(pLoc); gl.vertexAttribPointer(pLoc, 2, gl.FLOAT, false, 0, 0);
      tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      if (loadedImg) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, loadedImg);
      else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0,0,0,0]));
      locs = {
        tex: gl.getUniformLocation(prog, 'u_tex'), time: gl.getUniformLocation(prog, 'u_time'),
        rot: gl.getUniformLocation(prog, 'u_rot'), light: gl.getUniformLocation(prog, 'u_light'),
        cursor: gl.getUniformLocation(prog, 'u_cursor'), pulse: gl.getUniformLocation(prog, 'u_pulse'),
        pulseOrigin: gl.getUniformLocation(prog, 'u_pulseOrigin'),
      };
      gl.useProgram(prog); gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.uniform1i(locs.tex, 0);
      st.glOk = true;
      return true;
    } catch (_e) { return false; }
  }

  canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); st.glOk = false; });
  canvas.addEventListener('webglcontextrestored', () => { if (initGL()) schedule(); });
  if (!initGL()) ctx2d = canvas.getContext('2d');

  const img = new Image();
  img.decoding = 'async';
  img.onload = () => {
    loadedImg = img;
    if (st.glOk && gl && !gl.isContextLost() && tex) {
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
    }
    schedule();
  };
  img.src = '/luminara-logo.webp';

  let prevMs = performance.now();
  function schedule() { if (!document.hidden && !st.rafId) { prevMs = performance.now(); st.rafId = requestAnimationFrame(frame); } }
  function pulse(ox = 0.5, oy = 0.53) { st.pulse = 0; st.pulseX = ox; st.pulseY = oy; st.velY += 0.08; schedule(); }
  function spin360() { st.targetY += Math.PI * 2; pulse(); }

  canvas.addEventListener('pointerdown', (e) => {
    st.dragging = true; st.lastPx = st.downX = e.clientX; st.lastPy = st.downY = e.clientY;
    try { canvas.setPointerCapture(e.pointerId); } catch (_err) {}
    schedule();
  });
  canvas.addEventListener('pointermove', (e) => {
    const r = canvas.getBoundingClientRect();
    st.cursorX = Math.max(-1, Math.min(1, ((e.clientX - r.left) / Math.max(1, r.width)) * 2 - 1));
    st.cursorY = Math.max(-1, Math.min(1, -(((e.clientY - r.top) / Math.max(1, r.height)) * 2 - 1)));
    st.targetLightX = st.cursorX * 0.9; st.targetLightY = st.cursorY * 0.9;
    if (st.dragging) {
      st.targetY += (e.clientX - st.lastPx) * 0.012;
      st.targetX = Math.max(-1.15, Math.min(1.15, st.targetX + (e.clientY - st.lastPy) * 0.011));
      st.lastPx = e.clientX; st.lastPy = e.clientY;
    } else {
      st.targetY = Math.round(st.targetY / (Math.PI * 2)) * (Math.PI * 2) + st.cursorX * 0.34;
      st.targetX = -st.cursorY * 0.28;
    }
    schedule();
  });
  const endDrag = (e) => {
    if (!st.dragging) return;
    st.dragging = false;
    if (Math.hypot(e.clientX - st.downX, e.clientY - st.downY) < 7) {
      const r = canvas.getBoundingClientRect();
      pulse((e.clientX - r.left) / Math.max(1, r.width), (e.clientY - r.top) / Math.max(1, r.height));
    }
  };
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);
  canvas.addEventListener('pointerleave', () => {
    if (!st.dragging) { st.targetX = 0; st.targetY = Math.round(st.targetY / (Math.PI * 2)) * (Math.PI * 2); st.targetLightX = 0.25; st.targetLightY = 0.35; schedule(); }
  });

  const btnP = document.getElementById('btnPortalPulse');
  const btnS = document.getElementById('btnPortalSpin');
  const stage = document.getElementById('portalLogoStage');
  if (btnP) btnP.addEventListener('click', () => pulse());
  if (btnS) btnS.addEventListener('click', spin360);
  if (stage) stage.addEventListener('keydown', (e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); pulse(); } });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) schedule(); else if (st.rafId) { cancelAnimationFrame(st.rafId); st.rafId = 0; } });

  function frame(nowMs) {
    st.rafId = 0;
    if (document.hidden) return;
    const dt = Math.min(0.05, Math.max(0.001, (nowMs - prevMs) / 1000));
    prevMs = nowMs;
    const elapsed = (nowMs - st.startMs) / 1000;
    const idleY = (!st.dragging && !reduced) ? Math.sin(elapsed * 1.15) * 0.14 : 0;
    const idleX = (!st.dragging && !reduced) ? Math.cos(elapsed * 0.85) * 0.07 : 0;
    const damp = Math.pow(st.dragging ? 0.72 : 0.84, dt * 60);
    st.velX = (st.velX + ((st.targetX + idleX) - st.rotX) * (st.dragging ? 18 : 7.5) * dt) * damp;
    st.velY = (st.velY + ((st.targetY + idleY) - st.rotY) * (st.dragging ? 18 : 7.5) * dt) * damp;
    st.rotX += st.velX; st.rotY += st.velY;
    st.lightX += (st.targetLightX - st.lightX) * Math.min(1, dt * 8);
    st.lightY += (st.targetLightY - st.lightY) * Math.min(1, dt * 8);
    if (st.pulse < 2.0) st.pulse += dt * 1.25;

    const cw = canvas.clientWidth, ch = canvas.clientHeight;
    if (cw && ch) {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.max(64, Math.min(1024, Math.round(cw * dpr)));
      const h = Math.max(64, Math.min(1024, Math.round(ch * dpr)));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      if (st.glOk && gl && !gl.isContextLost() && prog) {
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.uniform1f(locs.time, reduced ? 0 : elapsed);
        gl.uniform2f(locs.rot, st.rotX, st.rotY);
        gl.uniform2f(locs.light, st.lightX, st.lightY);
        gl.uniform2f(locs.cursor, st.cursorX, st.cursorY);
        gl.uniform1f(locs.pulse, st.pulse);
        gl.uniform2f(locs.pulseOrigin, st.pulseX, st.pulseY);
        gl.drawArrays(gl.TRIANGLES, 0, 6);
      } else if (ctx2d && loadedImg) {
        const src = keyBlack(loadedImg);
        ctx2d.clearRect(0, 0, canvas.width, canvas.height);
        const s = Math.min(canvas.width, canvas.height) * 0.92;
        ctx2d.drawImage(src, (canvas.width - s) / 2, (canvas.height - s) / 2, s, s);
        canvas.style.transform = `perspective(820px) rotateX(${(st.rotX * 57.29578).toFixed(2)}deg) rotateY(${(st.rotY * 57.29578).toFixed(2)}deg)`;
      }
    }
    const settled = reduced && !st.dragging && st.pulse >= 2.0 && Math.abs(st.velX) < 0.0005 && Math.abs(st.velY) < 0.0005;
    if (!settled) st.rafId = requestAnimationFrame(frame);
  }
  schedule();
})();
