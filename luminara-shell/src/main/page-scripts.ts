import type { RecordedStep } from "../shared/types";

export const PAGE_EXTRACT_SCRIPT = `(() => {
  const title = document.title || '';
  const rawText = (document.body ? document.body.innerText : '').slice(0, 60000);
  const bodyText = rawText.replace(/\\s+/g, ' ').trim();
  const words = bodyText ? bodyText.split(' ').length : 0;
  const priceMatches = bodyText.match(/(?:\\$|€|£|¥)\\s?\\d[\\d,]*(?:\\.\\d{1,2})?(?:\\s?\\/\\s?(?:mo|month|yr|year|seat))?/gi) || [];
  const ratingMatches = bodyText.match(/\\b[1-5](?:\\.\\d)?\\s?(?:\\/\\s?5|out of 5|stars|★)/gi) || [];
  const headings = Array.from(document.querySelectorAll('h1,h2'))
    .map((el) => (el.textContent || '').replace(/\\s+/g, ' ').trim())
    .filter((t) => t.length > 2 && t.length < 120)
    .slice(0, 6);
  let tools = [];
  try {
    if (navigator.modelContext && typeof navigator.modelContext.listTools === 'function') {
      tools = navigator.modelContext.listTools().map((t) => String(t.name || '')).filter(Boolean);
    }
  } catch {}
  return {
    title,
    textExcerpt: bodyText.slice(0, 1400),
    wordCount: words,
    prices: Array.from(new Set(priceMatches)).slice(0, 6),
    ratings: Array.from(new Set(ratingMatches)).slice(0, 4),
    headings,
    webMcpTools: Array.from(new Set(tools)).slice(0, 12)
  };
})()`;

export function buildReplayScript(steps: RecordedStep[]): string {
  const serialized = JSON.stringify(steps);
  return `(async () => {
    const steps = ${serialized};
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const inputSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    const areaSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
    let completed = 0;

    for (const step of steps) {
      try {
        if (step.action === 'navigate') {
          completed += 1;
          continue;
        }
        const el = document.querySelector(step.selector);
        if (!el) continue;

        if (step.action === 'click' && el instanceof HTMLElement) {
          el.focus();
          el.click();
          completed += 1;
        } else if (step.action === 'input') {
          if (el instanceof HTMLInputElement) {
            if ((el.type || '').toLowerCase() === 'password') continue;
            el.focus();
            if (inputSetter) inputSetter.call(el, step.valuePreview);
            else el.value = step.valuePreview;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            completed += 1;
          } else if (el instanceof HTMLTextAreaElement) {
            el.focus();
            if (areaSetter) areaSetter.call(el, step.valuePreview);
            else el.value = step.valuePreview;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            completed += 1;
          } else if (el instanceof HTMLSelectElement) {
            el.value = step.valuePreview;
            el.dispatchEvent(new Event('change', { bubbles: true }));
            completed += 1;
          }
        } else if (step.action === 'submit') {
          const form = el instanceof HTMLFormElement ? el : el.closest('form');
          if (form) {
            if (typeof form.requestSubmit === 'function') form.requestSubmit();
            else form.submit();
            completed += 1;
          }
        }
      } catch {
        // Continue remaining steps safely
      }
      await sleep(120);
    }
    return completed;
  })()`;
}
