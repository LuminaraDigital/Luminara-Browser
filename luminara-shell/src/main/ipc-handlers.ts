import crypto from "node:crypto";
import { ipcMain, type IpcMainInvokeEvent } from "electron";
import type { BaseWindow, WebContentsView } from "electron";
import type {
  ApprovalDecision,
  ChatRequest,
  CoPresenceState,
  RecordedStep,
  RoutineItem,
  SettingsUpdate,
  ShellSnapshot,
  StageLayoutRect,
  ThemeMode
} from "../shared/types";
import type { PrivacyShieldManager } from "./privacy-shield";
import type { MutationFirewallManager } from "./mutation-firewall";
import type { LocalStore } from "./store";
import {
  BotBrain,
  buildLiveLensTable,
  detectOllamaModels,
  formatSearchUrl,
  sanitizeRecordedStep,
  validateHttpUrl
} from "./bot-brain";
import type { TabManager } from "./tab-manager";

export const IDLE_COPRESENCE: CoPresenceState = {
  active: false,
  tabId: null,
  botId: null,
  botName: "",
  botColor: "#16A095",
  activity: ""
};

export interface ShellRuntimeContext {
  getWindow: () => BaseWindow | null;
  getShellView: () => WebContentsView | null;
  store: LocalStore;
  shield: PrivacyShieldManager;
  firewall: MutationFirewallManager;
  brain: BotBrain;
  getTabManager: () => TabManager;
  getState: () => {
    activeSpaceId: string;
    activeTabId: string | null;
    splitTabId: string | null;
    recordingTabId: string | null;
    recordingSteps: RecordedStep[];
    coPresence: CoPresenceState;
  };
  setState: (
    patch: Partial<{
      activeSpaceId: string;
      activeTabId: string | null;
      splitTabId: string | null;
      recordingTabId: string | null;
      recordingSteps: RecordedStep[];
    }>
  ) => void;
  setCoPresence: (next: CoPresenceState) => void;
  buildSnapshot: () => ShellSnapshot;
  broadcastSnapshot: () => void;
  runRoutine: (id: string) => Promise<{ routine: RoutineItem; summary: string }>;
  resolveBg: (theme: ThemeMode) => string;
}

export function registerShellIpc(ctx: ShellRuntimeContext): void {
  function handleShell<A extends unknown[], R>(
    channel: string,
    fn: (ev: IpcMainInvokeEvent, ...args: A) => R
  ): void {
    ipcMain.handle(channel, (ev, ...args) => {
      const shellId = ctx.getShellView()?.webContents.id;
      if (!shellId || ev.sender.id !== shellId) throw new Error("Unauthorized IPC sender");
      return fn(ev, ...(args as A));
    });
  }

  handleShell("shell:get-snapshot", () => ctx.buildSnapshot());
  handleShell("shell:layout", (_ev, rect: StageLayoutRect) => {
    ctx.getTabManager().syncLayout(rect);
  });

  handleShell("spaces:create", (_ev, { name, accent }: { name: string; accent: string }) => {
    const space = ctx.store.createSpace(name, accent);
    ctx.setState({ activeSpaceId: space.id, activeTabId: null, splitTabId: null });
    ctx.broadcastSnapshot();
    return space;
  });

  handleShell("spaces:switch", (_ev, { spaceId }: { spaceId: string }) => {
    const spaceTabs = ctx.getTabManager().listTabs().filter((t) => t.spaceId === spaceId);
    ctx.setState({ activeSpaceId: spaceId, activeTabId: spaceTabs[0]?.id ?? null, splitTabId: null });
    ctx.broadcastSnapshot();
    return ctx.buildSnapshot();
  });

  handleShell(
    "tabs:open",
    (
      _ev,
      {
        spaceId,
        input,
        botId,
        background
      }: { spaceId: string; input: string; botId: string | null; background?: boolean }
    ) => {
      const url = formatSearchUrl(input, ctx.store.getPublicSettings().searchEngine);
      const bot = botId ? ctx.brain.getBot(botId) : null;
      const tab = ctx.getTabManager().openTab(spaceId || ctx.getState().activeSpaceId, url, bot);
      if (!background) {
        ctx.setState({ activeSpaceId: tab.spaceId, activeTabId: tab.id });
      }
      ctx.broadcastSnapshot();
      return tab;
    }
  );

  handleShell("tabs:activate", (_ev, { tabId }: { tabId: string | null }) => {
    const st = ctx.getState();
    if (!tabId) {
      ctx.setState({ activeTabId: null, splitTabId: null });
      ctx.broadcastSnapshot();
      return ctx.buildSnapshot();
    }
    ctx.getTabManager().ensureAwake(tabId);
    const tab = ctx.getTabManager().getTab(tabId);
    const targetSpace = tab?.spaceId ?? st.activeSpaceId;
    let nextSplit = st.splitTabId;
    if (targetSpace !== st.activeSpaceId) {
      nextSplit = null;
    } else if (tabId === st.splitTabId) {
      nextSplit = st.activeTabId && st.activeTabId !== tabId ? st.activeTabId : null;
    }
    ctx.setState({ activeTabId: tabId, activeSpaceId: targetSpace, splitTabId: nextSplit });
    ctx.broadcastSnapshot();
    return ctx.buildSnapshot();
  });

  handleShell("tabs:split", (_ev, { tabId }: { tabId: string | null }) => {
    const splitTabId = tabId && tabId !== ctx.getState().activeTabId ? tabId : null;
    if (splitTabId) ctx.getTabManager().ensureAwake(splitTabId);
    ctx.setState({ splitTabId });
    ctx.broadcastSnapshot();
    return ctx.buildSnapshot();
  });

  handleShell("tabs:close", (_ev, { tabId }: { tabId: string }) => {
    ctx.getTabManager().closeTab(tabId);
    const st = ctx.getState();
    const nextSplit = st.splitTabId === tabId ? null : st.splitTabId;
    let nextActive = st.activeTabId;
    if (st.activeTabId === tabId) {
      const remaining = ctx.getTabManager().listTabs().filter((t) => t.spaceId === st.activeSpaceId);
      nextActive = remaining[0]?.id ?? null;
    }
    ctx.setState({ activeTabId: nextActive, splitTabId: nextSplit });
    ctx.broadcastSnapshot();
    return ctx.buildSnapshot();
  });

  handleShell("tabs:hibernate", (_ev, { tabId }: { tabId: string }) => {
    const st = ctx.getState();
    ctx.setState({
      splitTabId: st.splitTabId === tabId ? null : st.splitTabId,
      activeTabId: st.activeTabId === tabId ? null : st.activeTabId
    });
    ctx.getTabManager().hibernateTab(tabId);
    ctx.broadcastSnapshot();
    return ctx.buildSnapshot();
  });

  handleShell("tabs:navigate", (_ev, { tabId, input }: { tabId: string; input: string }) => {
    const url = formatSearchUrl(input, ctx.store.getPublicSettings().searchEngine);
    return ctx.getTabManager().navigateTab(tabId, url);
  });

  handleShell(
    "tabs:nav-action",
    (_ev, { tabId, action }: { tabId: string; action: "back" | "forward" | "reload" | "stop" }) => {
      ctx.getTabManager().navAction(tabId, action);
    }
  );

  handleShell("tabs:find", (_ev, { tabId, text, forward }: { tabId: string; text: string; forward?: boolean }) => {
    ctx.getTabManager().findInTab(tabId, text, forward ?? true);
  });

  handleShell("tabs:stop-find", (_ev, { tabId }: { tabId: string }) => {
    ctx.getTabManager().stopFindInTab(tabId);
  });

  handleShell("shield:toggle", (_ev, { domain }: { domain: string }) => {
    ctx.shield.toggleDomain(domain);
    const activeTabId = ctx.getState().activeTabId;
    const activeTab = ctx.getTabManager().getTab(activeTabId);
    const status = ctx.shield.getStatus(activeTabId, activeTab?.url ?? "");
    ctx.broadcastSnapshot();
    return status;
  });

  handleShell("firewall:resolve", (_ev, { id, decision }: { id: string; decision: ApprovalDecision }) => {
    ctx.firewall.resolveDecision(id, decision);
    return ctx.buildSnapshot();
  });

  handleShell("firewall:revoke", (_ev, { origin }: { origin: string }) => {
    ctx.firewall.revokeOrigin(origin);
    return ctx.buildSnapshot();
  });

  handleShell("firewall:demo", () => ctx.firewall.createDemoCard());

  handleShell("bot:chat", async (_ev, req: ChatRequest) => {
    const bot = ctx.brain.getBot(req.botId);
    const spaceTabs = ctx.getTabManager().listTabs().filter((t) => t.spaceId === req.spaceId);
    const targetTabs = req.activeTabId
      ? [
          ...spaceTabs.filter((t) => t.id === req.activeTabId),
          ...spaceTabs.filter((t) => t.id !== req.activeTabId && !t.hibernated).slice(0, 4)
        ]
      : spaceTabs.filter((t) => !t.hibernated).slice(0, 5);

    if (req.activeTabId) {
      ctx.setCoPresence({
        active: true,
        tabId: req.activeTabId,
        botId: bot.id,
        botName: bot.name,
        botColor: bot.color,
        activity: req.mode === "plan" ? "Drafting a step-by-step plan" : "Reading active tab & sources"
      });
    }

    try {
      const snaps = (
        await Promise.all(targetTabs.map((t) => ctx.getTabManager().readTabSnapshot(t.id)))
      ).filter((s): s is NonNullable<typeof s> => Boolean(s));

      return await ctx.brain.respond({
        req,
        settings: ctx.store.getPublicSettings(),
        apiKey: ctx.store.getDecryptedApiKey(),
        snapshots: snaps,
        totalTrackersBlocked: ctx.shield.getStatus(req.activeTabId, "").totalBlocked
      });
    } finally {
      ctx.setCoPresence(IDLE_COPRESENCE);
    }
  });

  handleShell("bot:abort", (_ev, { requestId }: { requestId: string }) => {
    ctx.brain.abort(requestId);
    ctx.setCoPresence(IDLE_COPRESENCE);
  });

  handleShell(
    "bot:worktree",
    (_ev, { botId, spaceId, urls }: { botId: string; spaceId: string; urls: string[] }) => {
      const bot = ctx.brain.getBot(botId);
      const engine = ctx.store.getPublicSettings().searchEngine;
      const created = urls
        .slice(0, 4)
        .map((u) =>
          ctx.getTabManager().openTab(spaceId || ctx.getState().activeSpaceId, formatSearchUrl(u, engine), bot)
        );
      if (created[0]) {
        ctx.setState({ activeSpaceId: created[0].spaceId, activeTabId: created[0].id });
      }
      // Do not leave Co-Presence stuck active once parallel tabs are spawned
      ctx.setCoPresence(IDLE_COPRESENCE);
      ctx.broadcastSnapshot();
      return created;
    }
  );

  handleShell("bot:take-wheel", () => {
    ctx.getTabManager().setActiveMutationTab(null, null);
    ctx.setCoPresence(IDLE_COPRESENCE);
    return IDLE_COPRESENCE;
  });

  handleShell("lens:build", async (_ev, { spaceId }: { spaceId: string }) => {
    const spaceTabs = ctx.getTabManager().listTabs().filter((t) => t.spaceId === spaceId);
    const snapMap = new Map();
    await Promise.all(
      spaceTabs.map(async (tab) => {
        const snap = await ctx.getTabManager().readTabSnapshot(tab.id);
        if (snap) snapMap.set(tab.id, snap);
      })
    );
    return buildLiveLensTable(spaceId, spaceTabs, snapMap);
  });

  handleShell("skills:toggle-teach", (_ev, { tabId }: { tabId: string }) => {
    const st = ctx.getState();
    if (st.recordingTabId === tabId) {
      ctx.getTabManager().setRecordingTab(null);
      ctx.setState({ recordingTabId: null });
      ctx.broadcastSnapshot();
      return { recording: false, steps: st.recordingSteps };
    }
    ctx.setState({ recordingTabId: tabId, recordingSteps: [] });
    ctx.getTabManager().setRecordingTab(tabId);
    ctx.broadcastSnapshot();
    return { recording: true, steps: [] };
  });

  handleShell("skills:save", (_ev, { name, description }: { name: string; description: string }) => {
    const steps = ctx.getState().recordingSteps;
    if (steps.length === 0) return null;
    let domain = "web";
    try {
      domain = new URL(steps[0].url).hostname.replace(/^www\./, "");
    } catch {
      domain = "web";
    }
    const skill = ctx.store.addSkill({
      id: `skl_${crypto.randomUUID().slice(0, 8)}`,
      name: name.trim() || `Skill on ${domain}`,
      domain,
      description: description.trim() || `${steps.length} recorded browser steps`,
      steps: [...steps],
      createdAt: Date.now(),
      runCount: 0
    });
    ctx.getTabManager().setRecordingTab(null);
    ctx.setState({ recordingTabId: null, recordingSteps: [] });
    ctx.broadcastSnapshot();
    return skill;
  });

  handleShell("skills:replay", async (_ev, { skillId, tabId }: { skillId: string; tabId: string }) => {
    const skill = ctx.store.getSkills().find((s) => s.id === skillId);
    if (!skill) return { ok: false, message: "Skill not found." };
    const bot = ctx.brain.getBot("pi");
    ctx.setState({ activeTabId: tabId });
    ctx.getTabManager().setActiveMutationTab(tabId, bot);
    ctx.setCoPresence({
      active: true,
      tabId,
      botId: bot.id,
      botName: bot.name,
      botColor: bot.color,
      activity: `Replaying skill "${skill.name}"`
    });
    try {
      const res = await ctx.getTabManager().replaySkillOnTab(skill, tabId);
      if (res.ok) {
        ctx.store.incrementSkillRun(skillId);
        ctx.broadcastSnapshot();
      }
      return res;
    } finally {
      ctx.getTabManager().setActiveMutationTab(null, null);
      ctx.setCoPresence(IDLE_COPRESENCE);
    }
  });

  handleShell("skills:delete", (_ev, { skillId }: { skillId: string }) => {
    const skills = ctx.store.deleteSkill(skillId);
    ctx.broadcastSnapshot();
    return skills;
  });

  handleShell(
    "routines:create",
    (_ev, item: Omit<RoutineItem, "id" | "lastRunAt" | "lastSummary">) => {
      const safeUrl = validateHttpUrl(item.url);
      const created = ctx.store.addRoutine({ ...item, url: safeUrl });
      ctx.broadcastSnapshot();
      return created;
    }
  );

  handleShell("routines:toggle", (_ev, { id }: { id: string }) => {
    const routines = ctx.store.toggleRoutine(id);
    ctx.broadcastSnapshot();
    return routines;
  });

  handleShell("routines:run-now", (_ev, { id }: { id: string }) => ctx.runRoutine(id));

  handleShell("routines:delete", (_ev, { id }: { id: string }) => {
    const routines = ctx.store.deleteRoutine(id);
    ctx.broadcastSnapshot();
    return routines;
  });

  handleShell("settings:update", (_ev, patch: SettingsUpdate) => {
    const updated = ctx.store.updateSettings(patch);
    ctx.firewall.setAlwaysGuard(updated.firewallAlwaysOn);
    const win = ctx.getWindow();
    if (win && !win.isDestroyed()) win.setBackgroundColor(ctx.resolveBg(updated.theme));
    ctx.broadcastSnapshot();
    return updated;
  });

  handleShell("settings:detect-ollama", (_ev, { host }: { host?: string }) =>
    detectOllamaModels(host || ctx.store.getPublicSettings().ollamaHost)
  );

  handleShell(
    "window:control",
    (_ev, { action }: { action: "minimize" | "maximize" | "close" }) => {
      const win = ctx.getWindow();
      if (!win || win.isDestroyed()) return;
      if (action === "minimize") win.minimize();
      else if (action === "maximize") {
        if (win.isMaximized()) win.unmaximize();
        else win.maximize();
      } else if (action === "close") win.close();
    }
  );

  ipcMain.on("web:recorded-step", (ev, rawStep: Partial<RecordedStep>) => {
    const st = ctx.getState();
    const senderTabId = ctx.getTabManager().getTabIdForWebContents(ev.sender.id);
    if (!senderTabId || senderTabId !== st.recordingTabId) return;
    const step = sanitizeRecordedStep(rawStep);
    if (!step) return;
    ctx.setState({ recordingSteps: [...st.recordingSteps.slice(-39), step] });
    const shell = ctx.getShellView();
    if (shell && !shell.webContents.isDestroyed()) shell.webContents.send("skills:recorded-step", step);
    ctx.broadcastSnapshot();
  });
}
