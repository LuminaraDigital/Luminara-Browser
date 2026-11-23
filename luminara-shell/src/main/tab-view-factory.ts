import path from "node:path";
import { WebContentsView } from "electron";
import type { TabRecord } from "../shared/types";
import { attachWindowShortcuts, type ShortcutHost } from "./window-shortcuts";
import { attachTabContextMenu } from "./tab-context-menu";

export function isAllowedWebNavigation(url: string, allowDataHtml: boolean): boolean {
  if (url === "about:blank") return true;
  if (allowDataHtml && url.startsWith("data:text/html")) return true;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

export interface TabViewFactoryOpts {
  record: TabRecord;
  partition: string;
  webPreloadPath: string;
  shortcutHost: ShortcutHost;
  allowDataHtml: boolean;
  isRecordingTab: (tabId: string) => boolean;
  onOpenNewTab: (spaceId: string, url: string, background: boolean) => void;
  onRecordedNavStep: (tabId: string, url: string) => void;
  onCaptureMemory: (tabId: string) => void;
  onChanged: () => void;
  onToast: (message: string) => void;
}

export function createManagedWebView(opts: TabViewFactoryOpts): WebContentsView {
  const { record } = opts;
  const view = new WebContentsView({
    webPreferences: {
      partition: opts.partition,
      preload: path.resolve(opts.webPreloadPath),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true
    }
  });

  const wc = view.webContents;
  attachWindowShortcuts(wc, opts.shortcutHost, false);
  attachTabContextMenu(wc, {
    spaceId: record.spaceId,
    onOpenLinkNewTab: opts.onOpenNewTab
  });

  wc.setWindowOpenHandler(({ url, disposition }) => {
    if (isAllowedWebNavigation(url, false)) {
      opts.onOpenNewTab(record.spaceId, url, disposition === "background-tab");
    }
    return { action: "deny" };
  });

  wc.on("will-navigate", (ev, url) => {
    if (!isAllowedWebNavigation(url, opts.allowDataHtml)) ev.preventDefault();
  });

  wc.on("did-start-loading", () => {
    record.loading = true;
    opts.onChanged();
  });

  wc.on("did-finish-load", () => {
    if (opts.isRecordingTab(record.id) && !wc.isDestroyed()) {
      wc.send("luminara:teach-toggle", true);
    }
  });

  wc.on("did-stop-loading", () => {
    record.loading = false;
    record.canGoBack = wc.navigationHistory.canGoBack();
    record.canGoForward = wc.navigationHistory.canGoForward();
    opts.onChanged();
    opts.onCaptureMemory(record.id);
  });

  wc.on("did-fail-load", (_ev, code, desc, url, isMainFrame) => {
    if (!isMainFrame || code === -3) return;
    record.loading = false;
    opts.onChanged();
    opts.onToast(`Could not load ${url || record.url}: ${desc}`);
  });

  wc.on("render-process-gone", (_ev, details) => {
    record.loading = false;
    opts.onChanged();
    opts.onToast(`Tab renderer stopped (${details.reason}). Click Reload to recover.`);
  });

  wc.on("page-title-updated", (_ev, title) => {
    record.title = title || record.title;
    opts.onChanged();
  });

  wc.on("page-favicon-updated", (_ev, favicons) => {
    if (favicons.length > 0) {
      record.faviconUrl = favicons[0];
      opts.onChanged();
    }
  });

  wc.on("did-navigate", (_ev, url) => {
    record.url = url;
    record.canGoBack = wc.navigationHistory.canGoBack();
    record.canGoForward = wc.navigationHistory.canGoForward();
    if (opts.isRecordingTab(record.id)) opts.onRecordedNavStep(record.id, url);
    opts.onChanged();
  });

  wc.on("did-navigate-in-page", (_ev, url) => {
    record.url = url;
    record.canGoBack = wc.navigationHistory.canGoBack();
    record.canGoForward = wc.navigationHistory.canGoForward();
    opts.onChanged();
  });

  return view;
}
