import crypto from "node:crypto";
import { BaseWindow, WebContentsView, type WebContents } from "electron";
import type { BotProfile, StageLayoutRect, TabRecord, WebSkill } from "../shared/types";
import { PrivacyShieldManager } from "./privacy-shield";
import { MutationFirewallManager } from "./mutation-firewall";
import type { PageSnapshot } from "./bot-brain";
import { PAGE_EXTRACT_SCRIPT, buildReplayScript } from "./page-scripts";
import { attachSessionGuards } from "./session-guards";
import type { ShortcutHost } from "./window-shortcuts";
import { createManagedWebView } from "./tab-view-factory";

interface LiveTabEntry {
  record: TabRecord;
  view: WebContentsView | null;
}

export class TabManager {
  private readonly win: BaseWindow;
  private readonly webPreloadPath: string;
  private readonly shield: PrivacyShieldManager;
  private readonly firewall: MutationFirewallManager;
  private readonly shortcutHost: ShortcutHost;
  private readonly allowDataHtml: boolean;
  private readonly tabs = new Map<string, LiveTabEntry>();
  private readonly webContentsToTabId = new Map<number, string>();
  private readonly guardedSessions = new Set<string>();
  private mountedViewIds = new Set<string>();
  private activeMutationTabId: string | null = null;
  private activeMutationBot: { id: string; name: string; color: string } | null = null;
  private recordingTabId: string | null = null;
  private onChanged: () => void;
  private onPageLoaded: (spaceId: string, url: string, title: string, excerpt: string) => void;
  private onOpenNewTab: (spaceId: string, url: string, background: boolean) => void;
  private onRecordedNavStep: (tabId: string, url: string) => void;
  private onRecordingCleared: (tabId: string) => void;
  private onToast: (message: string) => void;

  constructor(opts: {
    win: BaseWindow;
    webPreloadPath: string;
    shield: PrivacyShieldManager;
    firewall: MutationFirewallManager;
    shortcutHost: ShortcutHost;
    allowDataHtml?: boolean;
    onChanged: () => void;
    onPageLoaded: (spaceId: string, url: string, title: string, excerpt: string) => void;
    onOpenNewTab: (spaceId: string, url: string, background: boolean) => void;
    onRecordedNavStep: (tabId: string, url: string) => void;
    onRecordingCleared: (tabId: string) => void;
    onToast: (message: string) => void;
  }) {
    this.win = opts.win;
    this.webPreloadPath = opts.webPreloadPath;
    this.shield = opts.shield;
    this.firewall = opts.firewall;
    this.shortcutHost = opts.shortcutHost;
    this.allowDataHtml = Boolean(opts.allowDataHtml);
    this.onChanged = opts.onChanged;
    this.onPageLoaded = opts.onPageLoaded;
    this.onOpenNewTab = opts.onOpenNewTab;
    this.onRecordedNavStep = opts.onRecordedNavStep;
    this.onRecordingCleared = opts.onRecordingCleared;
    this.onToast = opts.onToast;
  }

  public listTabs(): TabRecord[] {
    return Array.from(this.tabs.values()).map((entry) => ({
      ...entry.record,
      blockedCount: this.shield.getTabBlockedCount(entry.record.id)
    }));
  }

  public getTab(tabId: string | null): TabRecord | null {
    if (!tabId) return null;
    const entry = this.tabs.get(tabId);
    if (!entry) return null;
    return { ...entry.record, blockedCount: this.shield.getTabBlockedCount(tabId) };
  }

  public getTabWebContents(tabId: string | null): WebContents | null {
    if (!tabId) return null;
    const wc = this.tabs.get(tabId)?.view?.webContents ?? null;
    return wc && !wc.isDestroyed() ? wc : null;
  }

  public getTabIdForWebContents(wcId: number): string | null {
    return this.webContentsToTabId.get(wcId) ?? null;
  }

  public setActiveMutationTab(tabId: string | null, bot: BotProfile | null): void {
    this.activeMutationTabId = tabId;
    this.activeMutationBot = bot ? { id: bot.id, name: bot.name, color: bot.color } : null;
  }

  public openTab(spaceId: string, url: string, bot: BotProfile | null = null): TabRecord {
    const id = `tab_${crypto.randomUUID().slice(0, 8)}`;
    let title = "New Tab";
    try {
      title = new URL(url).hostname.replace(/^www\./, "") || "New Tab";
    } catch {
      title = url.slice(0, 32) || "New Tab";
    }
    const record: TabRecord = {
      id,
      spaceId,
      url,
      title,
      faviconUrl: "",
      loading: true,
      canGoBack: false,
      canGoForward: false,
      hibernated: false,
      botId: bot?.id ?? null,
      botName: bot?.name ?? null,
      botColor: bot?.color ?? null,
      blockedCount: 0,
      webMcpTools: [],
      lastActiveAt: Date.now()
    };

    const view = this.createWebView(record);
    this.tabs.set(id, { record, view });
    void view.webContents.loadURL(url).catch(() => undefined);
    this.onChanged();
    return { ...record };
  }

  public ensureAwake(tabId: string, skipInitialLoad = false): boolean {
    const entry = this.tabs.get(tabId);
    if (!entry) return false;
    entry.record.lastActiveAt = Date.now();
    if (!entry.view || entry.record.hibernated) {
      entry.record.hibernated = false;
      entry.record.loading = true;
      const view = this.createWebView(entry.record);
      entry.view = view;
      if (!skipInitialLoad) {
        void view.webContents.loadURL(entry.record.url).catch(() => undefined);
      }
      this.onChanged();
    }
    return true;
  }

  public waitForTabLoad(tabId: string, timeoutMs = 8000): Promise<void> {
    const wc = this.getTabWebContents(tabId);
    if (!wc || !wc.isLoading()) return Promise.resolve();
    return new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (!wc.isDestroyed()) {
          wc.removeListener("did-stop-loading", finish);
          wc.removeListener("did-fail-load", finish);
          wc.removeListener("destroyed", finish);
        }
        resolve();
      };
      const timer = setTimeout(finish, timeoutMs);
      wc.once("did-stop-loading", finish);
      wc.once("did-fail-load", finish);
      wc.once("destroyed", finish);
    });
  }

  public hibernateTab(tabId: string): boolean {
    const entry = this.tabs.get(tabId);
    if (!entry || entry.record.hibernated) return false;
    this.firewall.cancelTab(tabId);
    this.detachViewIfMounted(tabId, entry.view);
    this.destroyView(entry);
    entry.record.hibernated = true;
    entry.record.loading = false;
    if (this.recordingTabId === tabId) {
      this.recordingTabId = null;
      this.onRecordingCleared(tabId);
    }
    this.onChanged();
    return true;
  }

  public closeTab(tabId: string): boolean {
    const entry = this.tabs.get(tabId);
    if (!entry) return false;
    this.firewall.cancelTab(tabId);
    this.detachViewIfMounted(tabId, entry.view);
    this.destroyView(entry);
    this.shield.removeTab(tabId);
    this.tabs.delete(tabId);
    if (this.recordingTabId === tabId) {
      this.recordingTabId = null;
      this.onRecordingCleared(tabId);
    }
    this.onChanged();
    return true;
  }

  public navigateTab(tabId: string, url: string): TabRecord | null {
    const entry = this.tabs.get(tabId);
    if (!entry) return null;
    entry.record.url = url;
    this.shield.resetTabCount(tabId);
    this.ensureAwake(tabId, true);
    if (entry.view && !entry.view.webContents.isDestroyed()) {
      void entry.view.webContents.loadURL(url).catch(() => undefined);
    }
    this.onChanged();
    return this.getTab(tabId);
  }

  public navAction(tabId: string, action: "back" | "forward" | "reload" | "stop"): void {
    const wc = this.getTabWebContents(tabId);
    if (!wc) return;
    if (action === "back" && wc.navigationHistory.canGoBack()) wc.navigationHistory.goBack();
    else if (action === "forward" && wc.navigationHistory.canGoForward()) wc.navigationHistory.goForward();
    else if (action === "reload") {
      this.shield.resetTabCount(tabId);
      wc.reload();
    } else if (action === "stop") wc.stop();
  }

  public findInTab(tabId: string, text: string, forward = true): void {
    const wc = this.getTabWebContents(tabId);
    if (!wc) return;
    const trimmed = text.trim();
    if (!trimmed) wc.stopFindInPage("clearSelection");
    else wc.findInPage(trimmed, { forward });
  }

  public stopFindInTab(tabId: string): void {
    this.getTabWebContents(tabId)?.stopFindInPage("clearSelection");
  }

  public syncLayout(rect: StageLayoutRect): void {
    const desiredIds: string[] = [];
    if (rect.visible && rect.width > 40 && rect.height > 40 && rect.activeTabId) {
      this.ensureAwake(rect.activeTabId);
      desiredIds.push(rect.activeTabId);
      if (rect.splitTabId && rect.splitTabId !== rect.activeTabId && this.tabs.has(rect.splitTabId)) {
        this.ensureAwake(rect.splitTabId);
        desiredIds.push(rect.splitTabId);
      }
    }

    for (const mountedId of Array.from(this.mountedViewIds)) {
      if (!desiredIds.includes(mountedId)) {
        this.detachViewIfMounted(mountedId, this.tabs.get(mountedId)?.view ?? null);
      }
    }
    if (desiredIds.length === 0) return;

    const x = Math.max(0, Math.round(rect.x));
    const y = Math.max(0, Math.round(rect.y));
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));

    if (desiredIds.length === 1) {
      const entry = this.tabs.get(desiredIds[0]);
      if (entry?.view) {
        this.attachView(desiredIds[0], entry.view);
        entry.view.setBounds({ x, y, width, height });
      }
      return;
    }

    const gutter = 2;
    const leftWidth = Math.floor((width - gutter) / 2);
    const rightWidth = width - leftWidth - gutter;
    const left = this.tabs.get(desiredIds[0]);
    const right = this.tabs.get(desiredIds[1]);
    if (left?.view) {
      this.attachView(desiredIds[0], left.view);
      left.view.setBounds({ x, y, width: leftWidth, height });
    }
    if (right?.view) {
      this.attachView(desiredIds[1], right.view);
      right.view.setBounds({ x: x + leftWidth + gutter, y, width: rightWidth, height });
    }
  }

  public setRecordingTab(tabId: string | null): void {
    if (this.recordingTabId && this.recordingTabId !== tabId) {
      this.getTabWebContents(this.recordingTabId)?.send("luminara:teach-toggle", false);
    }
    this.recordingTabId = tabId;
    if (tabId) this.getTabWebContents(tabId)?.send("luminara:teach-toggle", true);
  }

  public async readTabSnapshot(tabId: string): Promise<PageSnapshot | null> {
    const entry = this.tabs.get(tabId);
    if (!entry) return null;
    let domain = entry.record.url;
    try {
      domain = new URL(entry.record.url).hostname.replace(/^www\./, "");
    } catch {
      // keep raw
    }
    const base: PageSnapshot = {
      tabId,
      url: entry.record.url,
      title: entry.record.title,
      domain,
      textExcerpt: "",
      wordCount: 0,
      prices: [],
      ratings: [],
      headings: [],
      webMcpTools: entry.record.webMcpTools,
      botName: entry.record.botName,
      hibernated: entry.record.hibernated
    };
    const wc = this.getTabWebContents(tabId);
    if (!wc || entry.record.hibernated) return base;

    try {
      const data = (await wc.executeJavaScript(PAGE_EXTRACT_SCRIPT, true)) as Partial<PageSnapshot>;
      const tools = data.webMcpTools ?? [];
      entry.record.webMcpTools = tools;
      return {
        ...base,
        title: data.title || entry.record.title,
        textExcerpt: data.textExcerpt ?? "",
        wordCount: data.wordCount ?? 0,
        prices: data.prices ?? [],
        ratings: data.ratings ?? [],
        headings: data.headings ?? [],
        webMcpTools: tools,
        hibernated: false
      };
    } catch {
      return base;
    }
  }

  public async replaySkillOnTab(
    skill: WebSkill,
    tabId: string
  ): Promise<{ ok: boolean; message: string }> {
    this.ensureAwake(tabId);
    await this.waitForTabLoad(tabId, 5000);
    const wc = this.getTabWebContents(tabId);
    if (!wc) return { ok: false, message: "Open a live web tab before replaying a skill." };
    try {
      const ran = (await wc.executeJavaScript(buildReplayScript(skill.steps), true)) as number;
      return { ok: true, message: `Replayed ${ran}/${skill.steps.length} steps from "${skill.name}".` };
    } catch {
      return { ok: false, message: "Could not replay skill on the current page." };
    }
  }

  public disposeAll(): void {
    for (const tabId of Array.from(this.tabs.keys())) this.closeTab(tabId);
  }

  private destroyView(entry: LiveTabEntry): void {
    if (!entry.view) return;
    const wc = entry.view.webContents;
    this.webContentsToTabId.delete(wc.id);
    if (!wc.isDestroyed()) {
      wc.removeAllListeners();
      wc.close({ waitForBeforeUnload: false });
    }
    entry.view = null;
  }

  private createWebView(record: TabRecord): WebContentsView {
    const partition = `persist:luminara-space-${record.spaceId}`;
    this.ensureSessionGuards(partition);
    const view = createManagedWebView({
      record,
      partition,
      webPreloadPath: this.webPreloadPath,
      shortcutHost: this.shortcutHost,
      allowDataHtml: this.allowDataHtml,
      isRecordingTab: (id) => this.recordingTabId === id,
      onOpenNewTab: this.onOpenNewTab,
      onRecordedNavStep: this.onRecordedNavStep,
      onCaptureMemory: (id) => void this.captureMemoryAfterLoad(id),
      onChanged: this.onChanged,
      onToast: this.onToast
    });
    this.webContentsToTabId.set(view.webContents.id, record.id);
    return view;
  }

  private async captureMemoryAfterLoad(tabId: string): Promise<void> {
    const snap = await this.readTabSnapshot(tabId);
    const entry = this.tabs.get(tabId);
    if (!snap || !entry) return;
    if (snap.webMcpTools.length > 0) {
      entry.record.webMcpTools = snap.webMcpTools;
      this.onChanged();
    }
    this.onPageLoaded(entry.record.spaceId, snap.url, snap.title, snap.textExcerpt);
  }

  private ensureSessionGuards(partition: string): void {
    if (this.guardedSessions.has(partition)) return;
    this.guardedSessions.add(partition);
    attachSessionGuards(partition, {
      shield: this.shield,
      firewall: this.firewall,
      resolveTabByWebContents: (wcId) => {
        const id = this.webContentsToTabId.get(wcId);
        return id ? (this.tabs.get(id)?.record ?? null) : null;
      },
      getActiveMutationState: () => ({
        tabId: this.activeMutationTabId,
        bot: this.activeMutationBot
      }),
      onBlockedChange: this.onChanged,
      onToast: this.onToast
    });
  }

  private attachView(tabId: string, view: WebContentsView): void {
    if (this.mountedViewIds.has(tabId) || this.win.isDestroyed()) return;
    this.win.contentView.addChildView(view);
    this.mountedViewIds.add(tabId);
  }

  private detachViewIfMounted(tabId: string, view: WebContentsView | null): void {
    if (!this.mountedViewIds.has(tabId)) return;
    if (view && !this.win.isDestroyed()) {
      try {
        this.win.contentView.removeChildView(view);
      } catch {
        // already detached
      }
    }
    this.mountedViewIds.delete(tabId);
  }
}
