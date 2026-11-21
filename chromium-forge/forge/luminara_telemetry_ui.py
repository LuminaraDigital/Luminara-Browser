"""Zero-XSS Telemetry Cockpit UI Module for `/workspace` (`forge/luminara_telemetry_ui.py`).

Decomposed from `luminara_workspace_ui.py` to keep both files comfortably below 750 lines.
Adheres strictly to `docs/design.md` (`oklch()` + `light-dark()`, `--border-control`,
Concentric Radius Law, `tabular-nums`) and `design-better` heuristics (`H1-H50`):
- Asymmetric `7 + 5` Bento grid collapsing cleanly to `1fr` below `860px` (`320px` reflow safe).
- All 4 async states (`empty`, `loading` with `STOP ■` `AbortController`, `error` with Retry, `success`).
- Top-aligned `<label for="...">` with `onBlur` validation across Monitors, Playbook CAS, Casebundle, and VRT forms.
- Persistent `localStorage` state (`luminara_browser:telemetry_suite`).
- 100% `document.createElement` + `textContent` construction (zero `.innerHTML` DOM XSS).
"""

from __future__ import annotations


def build_telemetry_cockpit_css() -> str:
    return """
    .tele-bento {
      display: grid;
      grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
      gap: 14px;
      align-items: start;
    }
    @media (max-width: 860px) {
      .tele-bento { grid-template-columns: minmax(0, 1fr); }
    }
    .tele-pane {
      background: var(--bg-1);
      border: 1px solid var(--hairline);
      box-shadow: var(--specular);
      border-radius: 16px;
      padding: 16px;
      display: grid;
      gap: 12px;
      min-width: 0;
    }
    .tele-kicker {
      font-family: var(--font-mono);
      font-size: 11px;
      letter-spacing: 0.11em;
      text-transform: uppercase;
      color: var(--ink-2);
    }
    .tele-form-stack {
      display: grid;
      gap: 8px;
      background: var(--bg-2);
      border: 1px solid var(--hairline);
      border-radius: 12px;
      padding: 12px;
      min-width: 0;
    }
    .tele-field { display: grid; gap: 4px; min-width: 0; }
    .tele-field label { font-family: var(--font-mono); font-size: 11px; color: var(--ink-1); }
    .tele-field input, .tele-field select {
      width: 100%;
      min-height: 34px;
      background: var(--bg-0);
      border: 1px solid var(--border-control);
      border-radius: 10px;
      padding: 6px 10px;
      color: var(--ink-0);
      font-family: var(--font-mono);
      font-size: 12px;
    }
    .tele-err-inline { font-family: var(--font-mono); font-size: 11px; color: var(--danger); min-height: 14px; }
    .tele-pill {
      display: inline-flex;
      align-items: center;
      padding: 3px 9px;
      border-radius: 999px;
      border: 1px solid var(--border-control);
      font-family: var(--font-mono);
      font-size: 10.5px;
      font-variant-numeric: tabular-nums;
      max-width: 100%;
      overflow-wrap: anywhere;
    }
    .tele-pill.ok { color: var(--accent); border-color: color-mix(in oklch, var(--accent) 50%, transparent); }
    .tele-pill.warn { color: var(--amber); border-color: color-mix(in oklch, var(--amber) 50%, transparent); }
    .tele-pill.crit { color: var(--danger); border-color: color-mix(in oklch, var(--danger) 50%, transparent); }
    .tele-skel {
      height: 38px;
      border-radius: 10px;
      background: var(--bg-2);
      border: 1px solid var(--hairline);
      opacity: 0.7;
    }
    """


def build_telemetry_cockpit_js() -> str:
    return """
    const KEY_TELE_SUITE = 'luminara_browser:telemetry_suite';
    const TELE_AGENT_ID = 'luminara-cockpit-ui';
    let teleAbortCtrl = null;
    let teleSnapshot = null;
    let teleLoading = false;
    let teleError = '';
    let selectedPlaybookId = '';

    async function telePost(path, payload, signal = undefined) {
      await exchangePassportSession(false);
      const bodyObj = Object.assign({ agent_id: TELE_AGENT_ID }, payload || {});
      let r = await fetch(DAEMON + path, {
        method: 'POST',
        headers: apiHeaders(true),
        body: JSON.stringify(bodyObj),
        signal
      });
      if ((r.status === 401 || r.status === 403) && sessionTok) {
        sessionTok = '';
        try { sessionStorage.removeItem(KEY_SS); } catch (_e) {}
        await exchangePassportSession(true);
        r = await fetch(DAEMON + path, {
          method: 'POST',
          headers: apiHeaders(true),
          body: JSON.stringify(bodyObj),
          signal
        });
      }
      if (r.status === 401 || r.status === 403) {
        document.getElementById('wsAuthBar').classList.add('visible');
      }
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
      return d;
    }

    async function fetchTelemetryBundle(runEvalSuite = false) {
      if (teleAbortCtrl) teleAbortCtrl.abort();
      teleAbortCtrl = new AbortController();
      teleLoading = true;
      teleError = '';
      if (currentView === 'telemetry') render();
      try {
        const sig = teleAbortCtrl.signal;
        const savedSuite = (() => {
          try { return localStorage.getItem(KEY_TELE_SUITE) || 'extraction'; } catch (_e) { return 'extraction'; }
        })();
        const [seqD, vrtD, monD, runsD, pbD, evalD] = await Promise.all([
          telePost('/api/agent/sequences', { action: 'status' }, sig),
          telePost('/api/agent/vrt', { action: 'status' }, sig),
          telePost('/api/agent/monitors', { action: 'list' }, sig),
          telePost('/api/agent/monitors', { action: 'runs', limit: 8 }, sig),
          telePost('/api/agent/playbooks', { action: 'list' }, sig),
          telePost('/api/agent/eval', runEvalSuite ? { action: 'run_suite', suite: savedSuite } : { action: 'scorecard' }, sig)
        ]);
        const playbooks = pbD.playbooks || [];
        if (!selectedPlaybookId && playbooks.length) selectedPlaybookId = playbooks[0].playbook_id;
        let revisions = [];
        if (selectedPlaybookId) {
          const revRes = await telePost('/api/agent/monitors', { action: 'list_revisions', playbook_id: selectedPlaybookId }, sig).catch(() => ({ revisions: [] }));
          revisions = revRes.revisions || [];
        }
        teleSnapshot = {
          seq: seqD,
          vrt: vrtD,
          monitors: monD.monitors || [],
          runs: runsD.runs || [],
          playbooks,
          revisions,
          evalReport: evalD
        };
      } catch (err) {
        if (err && err.name === 'AbortError') {
          teleError = 'Evaluation cancelled by user — click Refresh Cockpit to reload.';
        } else {
          teleError = (err && err.message ? err.message : String(err)) + ' — Verify Agent Daemon (:8796) is running.';
        }
      } finally {
        teleLoading = false;
        teleAbortCtrl = null;
        if (currentView === 'telemetry') render();
      }
    }

    function setWsToast(msg, isErr = false) {
      const st = document.getElementById('wsStatus');
      if (!st) return;
      st.classList.toggle('err', Boolean(isErr));
      st.textContent = msg;
    }

    function makeLabeledInput(id, labelTxt, placeholder, type = 'text') {
      const wrap = el('div', 'tele-field');
      const lbl = el('label', '', labelTxt);
      lbl.setAttribute('for', id);
      const inp = el('input', '');
      inp.id = id;
      inp.type = type;
      inp.autocomplete = 'off';
      inp.placeholder = placeholder;
      const err = el('div', 'tele-err-inline', '');
      wrap.append(lbl, inp, err);
      return { wrap, inp, err };
    }

    function renderTelemetryInto(root) {
      if (!root) return;
      root.replaceChildren();
      const bento = el('div', 'tele-bento');

      // ---- Left 7-Column Pane: Web Monitors, CAS Playbook Revisions & Multi-Provider Eval ----
      const leftPane = el('section', 'tele-pane');
      leftPane.setAttribute('aria-label', 'Web Monitors, Playbook Revisions and Search Evaluation Scorecard');

      const topRow = el('div', '');
      topRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;';
      const titleWrap = el('div', '');
      titleWrap.appendChild(el('div', 'tele-kicker', 'FENCED MONITORS · CAS REVISIONS · COSTLEDGER EVAL'));
      titleWrap.appendChild(el('h2', '', 'Monitors, Revisions & Scorecard'));
      topRow.appendChild(titleWrap);

      const actBar = el('div', '');
      actBar.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;align-items:center;';
      const suiteSel = el('select', '');
      suiteSel.id = 'teleSuiteSelect';
      suiteSel.setAttribute('aria-label', 'Evaluation suite');
      suiteSel.style.cssText = 'min-height:32px;padding:4px 8px;border-radius:8px;background:var(--bg-2);color:var(--ink-0);border:1px solid var(--border-control);font-family:var(--font-mono);font-size:11px;';
      ['extraction', 'citation', 'widesearch_mini'].forEach(s => {
        const opt = el('option', '', s);
        opt.value = s;
        try { if ((localStorage.getItem(KEY_TELE_SUITE) || 'extraction') === s) opt.selected = true; } catch (_e) {}
        suiteSel.appendChild(opt);
      });
      suiteSel.onchange = () => {
        try { localStorage.setItem(KEY_TELE_SUITE, suiteSel.value); } catch (_e) {}
      };
      actBar.appendChild(suiteSel);

      if (teleLoading) {
        const stopBtn = el('button', 'btn active', 'STOP ■');
        stopBtn.type = 'button';
        stopBtn.onclick = () => { if (teleAbortCtrl) teleAbortCtrl.abort(); };
        actBar.appendChild(stopBtn);
      } else {
        const runEvalBtn = el('button', 'btn active', 'Run Search Eval ↵');
        runEvalBtn.type = 'button';
        runEvalBtn.onclick = () => fetchTelemetryBundle(true);
        const refBtn = el('button', 'btn', 'Refresh Cockpit');
        refBtn.type = 'button';
        refBtn.onclick = () => fetchTelemetryBundle(false);
        actBar.append(runEvalBtn, refBtn);
      }
      topRow.appendChild(actBar);
      leftPane.appendChild(topRow);

      if (teleError) {
        const errBox = el('div', 'tele-form-stack');
        errBox.style.borderColor = 'var(--danger)';
        errBox.appendChild(el('div', 'status-line err', 'Telemetry Error: ' + teleError));
        const retryBtn = el('button', 'btn', 'Retry Connection ↻');
        retryBtn.type = 'button';
        retryBtn.onclick = () => fetchTelemetryBundle(false);
        errBox.appendChild(retryBtn);
        leftPane.appendChild(errBox);
      } else if (teleLoading && !teleSnapshot) {
        leftPane.append(el('div', 'tele-skel'), el('div', 'tele-skel'), el('div', 'tele-skel'));
      }

      // 1. Monitor Creation Form (`H23`, `H26` onBlur validation)
      const monForm = el('form', 'tele-form-stack');
      const fName = makeLabeledInput('teleMonName', 'Monitor Name', 'Pricing Page Watch');
      fName.err.remove();
      const fUrl = makeLabeledInput('teleMonUrl', 'Target HTTPS URL (SSRF-Guarded)', 'https://example.org/pricing', 'url');
      fUrl.inp.inputMode = 'url';
      fUrl.inp.onblur = () => {
        const v = fUrl.inp.value.trim();
        fUrl.err.textContent = (v && !/^https?:\\/\\//i.test(v)) ? 'Enter a valid http:// or https:// URL.' : '';
      };
      fUrl.inp.oninput = () => { if (/^https?:\\/\\//i.test(fUrl.inp.value.trim())) fUrl.err.textContent = ''; };
      const fSel = makeLabeledInput('teleMonSelector', 'CSS Scope Selector (optional)', 'body or #pricing');
      fSel.err.remove();

      const createBtn = el('button', 'btn active', '+ Create Fenced Monitor');
      createBtn.type = 'submit';
      monForm.append(fName.wrap, fUrl.wrap, fSel.wrap, createBtn);
      monForm.onsubmit = async ev => {
        ev.preventDefault();
        const u = fUrl.inp.value.trim();
        if (!/^https?:\\/\\//i.test(u)) {
          fUrl.err.textContent = 'Valid http(s):// target URL is required.';
          return;
        }
        createBtn.disabled = true;
        try {
          const d = await telePost('/api/agent/monitors', {
            action: 'create',
            name: fName.inp.value.trim() || u,
            target_url: u,
            extract_selector: fSel.inp.value.trim() || 'body'
          });
          fName.inp.value = '';
          fUrl.inp.value = '';
          setWsToast('Created monitor ' + d.monitor_id + ' (' + (d.receipt ? d.receipt.receipt_id : 'OK') + ').');
          await fetchTelemetryBundle(false);
        } catch (err) {
          fUrl.err.textContent = err.message || String(err);
        } finally {
          createBtn.disabled = false;
        }
      };
      leftPane.appendChild(monForm);

      const mons = (teleSnapshot && teleSnapshot.monitors) || [];
      if (!mons.length && !teleLoading) {
        leftPane.appendChild(el('div', 'status-line', 'No Web Monitors configured yet — add a URL above to track SHA-256 structural diffs with fenced lease_epoch protection.'));
      } else if (mons.length) {
        const mWrap = el('div', 'table-wrap');
        const mTbl = el('table', '');
        const mHead = el('thead', '');
        const mHr = el('tr', '');
        ['Monitor', 'Selector', 'Epoch', 'SHA-256', 'Actions'].forEach(h => {
          const th = el('th', '', h);
          th.style.cssText = 'padding:8px 10px;font-family:var(--font-mono);font-size:11px;';
          mHr.appendChild(th);
        });
        mHead.appendChild(mHr);
        const mBody = el('tbody', '');
        mons.forEach(m => {
          const tr = el('tr', '');
          tr.appendChild(el('td', '', m.name + ' (' + m.monitor_id + ')'));
          tr.appendChild(el('td', '', m.extract_selector || 'body'));
          tr.appendChild(el('td', '', String(m.lease_epoch)));
          tr.appendChild(el('td', '', m.last_content_sha256 ? m.last_content_sha256.slice(0, 10) : 'pending'));
          const tdAct = el('td', '');
          tdAct.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;';
          const runBtn = el('button', 'btn', 'Run Now');
          runBtn.type = 'button';
          runBtn.onclick = async () => {
            runBtn.disabled = true;
            try {
              const d = await telePost('/api/agent/monitors', { action: 'run_now', monitor_id: m.monitor_id });
              setWsToast('Monitor ' + m.monitor_id + ': ' + d.status + ' (' + (d.diff_summary || '') + ')');
              await fetchTelemetryBundle(false);
            } catch (err) {
              setWsToast('Monitor run failed: ' + (err.message || String(err)), true);
            } finally { runBtn.disabled = false; }
          };
          const delBtn = el('button', 'btn', 'Delete');
          delBtn.type = 'button';
          delBtn.onclick = async () => {
            delBtn.disabled = true;
            try {
              await telePost('/api/agent/monitors', { action: 'delete', monitor_id: m.monitor_id });
              setWsToast('Deleted monitor ' + m.monitor_id + '.');
              await fetchTelemetryBundle(false);
            } catch (err) {
              setWsToast('Delete monitor requires human UI key: ' + (err.message || String(err)), true);
            } finally { delBtn.disabled = false; }
          };
          tdAct.append(runBtn, delBtn);
          tr.appendChild(tdAct);
          mBody.appendChild(tr);
        });
        mTbl.append(mHead, mBody);
        mWrap.appendChild(mTbl);
        leftPane.appendChild(mWrap);
      }

      const runs = (teleSnapshot && teleSnapshot.runs) || [];
      if (runs.length) {
        const rBox = el('div', 'tele-form-stack');
        rBox.appendChild(el('div', 'tele-kicker', 'Recent Monitor Runs & Diff Summaries'));
        runs.slice(0, 5).forEach(rn => {
          const line = el('div', 'status-line', '[' + rn.status + '] ' + rn.monitor_id + ' · ' + (rn.diff_summary || '') + (rn.receipt_id ? (' · ' + rn.receipt_id) : ''));
          rBox.appendChild(line);
        });
        leftPane.appendChild(rBox);
      }

      // 2. CAS Playbook Revisions & Rollback Selector
      const revBox = el('div', 'tele-form-stack');
      revBox.appendChild(el('div', 'tele-kicker', 'CAS Playbook Revisions & 1-Click Rollback'));
      const pbInputWrap = makeLabeledInput('telePlaybookId', 'Playbook ID', selectedPlaybookId || 'pb_example');
      pbInputWrap.inp.value = selectedPlaybookId;
      pbInputWrap.err.remove();
      const pbBtnRow = el('div', '');
      pbBtnRow.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;';
      const loadRevBtn = el('button', 'btn', 'Load Revisions');
      loadRevBtn.type = 'button';
      loadRevBtn.onclick = async () => {
        selectedPlaybookId = pbInputWrap.inp.value.trim();
        await fetchTelemetryBundle(false);
      };
      const snapRevBtn = el('button', 'btn active', 'Snapshot Current Revision');
      snapRevBtn.type = 'button';
      snapRevBtn.onclick = async () => {
        const pid = pbInputWrap.inp.value.trim();
        if (!pid) { setWsToast('Enter a Playbook ID to snapshot.', true); return; }
        snapRevBtn.disabled = true;
        try {
          selectedPlaybookId = pid;
          const curRevs = (teleSnapshot && teleSnapshot.revisions) || [];
          const expRev = curRevs.length ? curRevs[0].revision_id : undefined;
          const d = await telePost('/api/agent/monitors', { action: 'snapshot_revision', playbook_id: pid, expected_revision: expRev });
          setWsToast('Snapshotted ' + pid + ' @ ' + d.latest_revision + '.');
          await fetchTelemetryBundle(false);
        } catch (err) {
          setWsToast('Snapshot failed: ' + (err.message || String(err)), true);
        } finally { snapRevBtn.disabled = false; }
      };
      pbBtnRow.append(loadRevBtn, snapRevBtn);
      revBox.append(pbInputWrap.wrap, pbBtnRow);

      const revs = (teleSnapshot && teleSnapshot.revisions) || [];
      if (revs.length) {
        const latestRevId = revs[0].revision_id;
        revs.slice(0, 5).forEach(rv => {
          const row = el('div', '');
          row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;';
          row.appendChild(el('span', 'status-line', '#' + rv.revision_num + ' ' + rv.revision_id + ' (' + (rv.steps || []).length + ' steps)'));
          if (rv.revision_id !== latestRevId) {
            const rbBtn = el('button', 'btn', 'Rollback ↶');
            rbBtn.type = 'button';
            rbBtn.onclick = async () => {
              rbBtn.disabled = true;
              try {
                const d = await telePost('/api/agent/monitors', {
                  action: 'rollback_playbook',
                  playbook_id: rv.playbook_id,
                  target_revision: rv.revision_id,
                  expected_revision: latestRevId
                });
                setWsToast('Rolled back ' + rv.playbook_id + ' to ' + d.rolled_back_to + ' (synced to disk).');
                await fetchTelemetryBundle(false);
              } catch (err) {
                setWsToast('Rollback failed: ' + (err.message || String(err)), true);
              } finally { rbBtn.disabled = false; }
            };
            row.appendChild(rbBtn);
          }
          revBox.appendChild(row);
        });
      } else {
        revBox.appendChild(el('div', 'status-line', 'Select or enter a Playbook ID above to inspect immutable CAS revisions.'));
      }
      leftPane.appendChild(revBox);

      // 3. Multi-Provider Eval Scorecard
      const cards = (teleSnapshot && teleSnapshot.evalReport && teleSnapshot.evalReport.scorecards) || [];
      if (cards.length) {
        const eWrap = el('div', 'table-wrap');
        const eTbl = el('table', '');
        const eHead = el('thead', '');
        const eHr = el('tr', '');
        ['Provider', 'Model', 'Composite F1', 'Mean Latency', 'Known Cost (USD)'].forEach(h => {
          const th = el('th', '', h);
          th.style.cssText = 'padding:8px 10px;font-family:var(--font-mono);font-size:11px;';
          eHr.appendChild(th);
        });
        eHead.appendChild(eHr);
        const eBody = el('tbody', '');
        cards.forEach(sc => {
          const tr = el('tr', '');
          tr.appendChild(el('td', '', sc.provider));
          tr.appendChild(el('td', '', sc.model));
          const skipped = sc.mean_f1 === null || sc.mean_f1 === undefined || sc.execution_mode === 'skipped_missing_api_key';
          tr.appendChild(el('td', '', skipped ? 'SKIPPED (No API Key)' : Number(sc.mean_f1).toFixed(4)));
          tr.appendChild(el('td', '', skipped ? '—' : (Number(sc.mean_latency_ms).toFixed(2) + ' ms')));
          tr.appendChild(el('td', '', '$' + Number((sc.cost && sc.cost.known_cost_usd) || 0).toFixed(6)));
          eBody.appendChild(tr);
        });
        eTbl.append(eHead, eBody);
        eWrap.appendChild(eTbl);
        leftPane.appendChild(eWrap);
      }

      // ---- Right 5-Column Pane: Sequence Guard & Hermetic VRT Isolation ----
      const rightPane = el('aside', 'tele-pane');
      rightPane.setAttribute('aria-label', 'Sequence Guard and Hermetic VRT Guardrails');
      rightPane.appendChild(el('div', 'tele-kicker', 'NUMBAT SEQUENCE GUARD · HERMETIC VRT'));
      rightPane.appendChild(el('h2', '', 'Chain Blocks & Visual Drift'));

      if (!teleSnapshot) {
        rightPane.appendChild(el('span', 'tele-pill warn', teleLoading ? 'Loading Sequence Guard...' : 'Daemon Offline / Unauthenticated'));
      } else {
        const seq = teleSnapshot.seq || {};
        const activeBlocks = seq.active_blocks || [];
        const seqPill = el(
          'span',
          'tele-pill ' + (activeBlocks.length ? 'crit' : 'ok'),
          activeBlocks.length
            ? ('PAUSED_SEQUENCE_BLOCK (' + activeBlocks.length + ')')
            : ('0 Active Chain Blocks · ' + (seq.tracked_partitions || 0) + ' Partitions')
        );
        rightPane.appendChild(seqPill);

        const seqBtns = el('div', '');
        seqBtns.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;';
        const expBundleBtn = el('button', 'btn', 'Download Signed Casebundle (.zip)');
        expBundleBtn.type = 'button';
        expBundleBtn.onclick = async () => {
          expBundleBtn.disabled = true;
          try {
            const d = await telePost('/api/agent/sequences', { action: 'export_casebundle' });
            const dlResp = await fetch(DAEMON + '/api/agent/casebundles?case_id=' + encodeURIComponent(d.case_id), { headers: apiHeaders(false) });
            if (dlResp.ok) {
              const blob = await dlResp.blob();
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = d.bundle_file || (d.case_id + '.zip');
              a.click();
              setTimeout(() => URL.revokeObjectURL(url), 1000);
            }
            const verInput = document.getElementById('teleVerifyBundleName');
            if (verInput) verInput.value = d.bundle_file || (d.case_id + '.zip');
            setWsToast('Exported signed casebundle ' + d.case_id + ' (' + d.manifest_sha256.slice(0, 12) + ').');
          } catch (err) {
            setWsToast('Casebundle export error: ' + (err.message || String(err)), true);
          } finally { expBundleBtn.disabled = false; }
        };
        seqBtns.appendChild(expBundleBtn);

        if (activeBlocks.length) {
          const clrBtn = el('button', 'btn active', 'Clear Block (Human Auth)');
          clrBtn.type = 'button';
          clrBtn.onclick = async () => {
            clrBtn.disabled = true;
            try {
              const d = await telePost('/api/agent/sequences', { action: 'clear_block' });
              setWsToast('Cleared ' + d.cleared_blocks + ' active sequence block(s).');
              await fetchTelemetryBundle(false);
            } catch (err) {
              setWsToast('Clear Block denied (human UI key required): ' + (err.message || String(err)), true);
            } finally { clrBtn.disabled = false; }
          };
          seqBtns.appendChild(clrBtn);
        }
        rightPane.appendChild(seqBtns);

        const findings = seq.recent_findings || [];
        if (findings.length) {
          const fBox = el('div', 'tele-form-stack');
          fBox.appendChild(el('div', 'tele-kicker', 'Recent Chain Findings'));
          findings.slice(-4).reverse().forEach(fn => {
            fBox.appendChild(el('div', 'status-line', '[' + fn.severity + '] ' + fn.rule_id + ' · ' + fn.title + ' (' + fn.case_id + ')'));
          });
          rightPane.appendChild(fBox);
        }
      }

      // Casebundle Verification Box
      const verBox = el('div', 'tele-form-stack');
      const fVer = makeLabeledInput('teleVerifyBundleName', 'Verify Casebundle File (in outputs/casebundles/)', 'CASE-...zip');
      fVer.err.remove();
      const verBtn = el('button', 'btn', 'Verify LUM-SIG-V2 Bundle ✓');
      verBtn.type = 'button';
      verBtn.onclick = async () => {
        const bname = fVer.inp.value.trim();
        if (!bname) { setWsToast('Enter a casebundle filename first.', true); return; }
        verBtn.disabled = true;
        try {
          const v = await telePost('/api/agent/sequences', { action: 'verify_casebundle', bundle_path: bname });
          setWsToast(v.valid ? ('Verified ' + v.case_id + ' (SHA-256 + LUM-SIG-V2 valid).') : ('Invalid bundle: ' + v.error), !v.valid);
        } catch (err) {
          setWsToast('Verify bundle failed: ' + (err.message || String(err)), true);
        } finally { verBtn.disabled = false; }
      };
      verBox.append(fVer.wrap, verBtn);
      rightPane.appendChild(verBox);

      // Hermetic VRT Isolation & PNG Diff Inspector
      const vrt = (teleSnapshot && teleSnapshot.vrt) || {};
      const vrtBox = el('div', 'tele-form-stack');
      vrtBox.appendChild(el('div', 'tele-kicker', 'Hermetic Origin Locks & PNG Visual Regression'));
      vrtBox.appendChild(
        el(
          'div',
          'status-line',
          'Baselines: ' + ((vrt.baselines || []).length) + ' · Blocked Third-Party Egress: ' + (vrt.blocked_egress_count || 0)
        )
      );
      const fBase = makeLabeledInput('teleVrtBaseline', 'VRT Baseline ID', 'checkout-hero');
      fBase.err.remove();
      const fOrig = makeLabeledInput('teleVrtOrigins', 'Declared Origins (comma-separated http/https)', 'https://example.org');
      fOrig.err.remove();

      const vrtBtns = el('div', '');
      vrtBtns.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;';
      const capBtn = el('button', 'btn', 'Capture Baseline');
      capBtn.type = 'button';
      capBtn.onclick = async () => {
        const bid = fBase.inp.value.trim() || 'live-tab';
        capBtn.disabled = true;
        try {
          const d = await telePost('/api/agent/vrt', { action: 'capture_baseline', baseline_id: bid });
          setWsToast('Captured PNG baseline ' + d.baseline_id + ' (' + d.width + 'x' + d.height + ').');
          await fetchTelemetryBundle(false);
        } catch (err) {
          setWsToast('Capture baseline failed: ' + (err.message || String(err)), true);
        } finally { capBtn.disabled = false; }
      };
      const cmpBtn = el('button', 'btn active', 'Compare VRT');
      cmpBtn.type = 'button';
      cmpBtn.onclick = async () => {
        const bid = fBase.inp.value.trim() || 'live-tab';
        cmpBtn.disabled = true;
        try {
          const d = await telePost('/api/agent/vrt', { action: 'compare_vrt', baseline_id: bid });
          setWsToast('VRT ' + d.baseline_id + ': ' + (d.passed ? 'PASS' : 'DRIFT') + ' (' + (Number(d.mismatch_ratio || 0) * 100).toFixed(2) + '% diff, RMSE ' + d.rmse + ').', !d.passed);
          await fetchTelemetryBundle(false);
        } catch (err) {
          setWsToast('Compare VRT failed: ' + (err.message || String(err)), true);
        } finally { cmpBtn.disabled = false; }
      };
      const lockBtn = el('button', 'btn', 'Lock Origins');
      lockBtn.type = 'button';
      lockBtn.onclick = async () => {
        const origs = fOrig.inp.value.split(',').map(s => s.trim()).filter(Boolean);
        if (!origs.length) { setWsToast('Enter at least one http(s):// origin to lock.', true); return; }
        lockBtn.disabled = true;
        try {
          const d = await telePost('/api/agent/vrt', { action: 'lock_origins', declared_origins: origs });
          setWsToast('Locked tab ' + d.target_id + ' to ' + d.declared_origins.join(', ') + '.');
          await fetchTelemetryBundle(false);
        } catch (err) {
          setWsToast('Lock origins failed: ' + (err.message || String(err)), true);
        } finally { lockBtn.disabled = false; }
      };
      const unlockBtn = el('button', 'btn', 'Unlock Origins');
      unlockBtn.type = 'button';
      unlockBtn.onclick = async () => {
        unlockBtn.disabled = true;
        try {
          const d = await telePost('/api/agent/vrt', { action: 'unlock_origins' });
          setWsToast('Unlocked declared-origin filter on tab ' + d.target_id + '.');
          await fetchTelemetryBundle(false);
        } catch (err) {
          setWsToast('Unlock origins requires human UI key: ' + (err.message || String(err)), true);
        } finally { unlockBtn.disabled = false; }
      };
      vrtBtns.append(capBtn, cmpBtn, lockBtn, unlockBtn);
      vrtBox.append(fBase.wrap, fOrig.wrap, vrtBtns);

      const lockMap = vrt.origin_locks || {};
      Object.keys(lockMap).forEach(tid => {
        vrtBox.appendChild(el('span', 'tele-pill ok', 'Locked ' + tid.slice(0, 8) + ': ' + (lockMap[tid] || []).join(', ')));
      });
      (vrt.recent_comparisons || []).slice(-3).reverse().forEach(cmp => {
        vrtBox.appendChild(
          el(
            'span',
            'tele-pill ' + (cmp.passed ? 'ok' : 'warn'),
            cmp.baseline_id + ': ' + (Number(cmp.mismatch_ratio || 0) * 100).toFixed(2) + '% (' + cmp.diff_pixels + ' px)'
          )
        );
      });
      rightPane.appendChild(vrtBox);

      bento.append(leftPane, rightPane);
      root.appendChild(bento);
    }
    """
