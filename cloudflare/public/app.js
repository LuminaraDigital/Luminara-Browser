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
})();
