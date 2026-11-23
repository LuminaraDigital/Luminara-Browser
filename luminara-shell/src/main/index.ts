import path from "node:path";
import crypto from "node:crypto";
import { pathToFileURL } from "node:url";
import { app, BaseWindow, Menu, nativeTheme, safeStorage, WebContentsView } from "electron";
import type {
  CoPresenceState,
  RecordedStep,
  RoutineItem,
  ShellSnapshot,
  ThemeMode
} from "../shared/types";
import { PrivacyShieldManager } from "./privacy-shield";
import { MutationFirewallManager } from "./mutation-firewall";
import { LocalStore } from "./store";
import { BotBrain, sanitizeRecordedStep } from "./bot-brain";
import { TabManager } from "./tab-manager";
import { IDLE_COPRESENCE, registerShellIpc } from "./ipc-handlers";
import { hardenShellSession } from "./session-guards";
import { attachWindowShortcuts, type ShortcutHost } from "./window-shortcuts";

const IS_SMOKE = process.env.LUMINARA_SMOKE_TEST === "1";

function resolveBackgroundColor(theme: ThemeMode): string {
  const dark = theme === "dark" || (theme === "system" && nativeTheme.shouldUseDarkColors);
  return dark ? "#141519" : "#FAF9F6";
}

function resolvePiBotBuiltinDir(): string {
  return path.resolve(__dirname, "../../../vendor/PiBot/packages/teams/builtin");
}

let mainWindow: BaseWindow | null = null;
let shellView: WebContentsView | null = null;
let store: LocalStore;
let shield: PrivacyShieldManager;
let firewall: MutationFirewallManager;
let brain: BotBrain;
let tabManager: TabManager;

let activeSpaceId = "research";
let activeTabId: string | null = null;
let splitTabId: string | null = null;
let recordingTabId: string | null = null;
let recordingSteps: RecordedStep[] = [];
let coPresence: CoPresenceState = { ...IDLE_COPRESENCE };
let routineTimer: ReturnType<typeof setInterval> | null = null;
let lastRoutineMinuteKey = "";

function sendToast(message: string): void {
  if (shellView && !shellView.webContents.isDestroyed()) {
    shellView.webContents.send("shell:toast", message);
  }
}

function syncWindowTitle(): void {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const tab = tabManager?.getTab(activeTabId);
  mainWindow.setTitle(tab?.title ? `${tab.title} — Luminara Browser` : "Luminara Browser");
}

function buildSnapshot(): ShellSnapshot {
  const activeTab = tabManager.getTab(activeTabId);
  const settings = store.getPublicSettings();
  return {
    spaces: store.getSpaces(),
    activeSpaceId,
    tabs: tabManager.listTabs(),
    activeTabId,
    splitTabId,
    bots: brain.getBots(),
    pendingApprovals: firewall.getPending(),
    allowlistedOrigins: firewall.listAllowlisted(),
    skills: store.getSkills(),
    routines: store.getRoutines(),
    memories: store.getMemories(),
    settings,
    shield: shield.getStatus(activeTabId, activeTab?.url ?? ""),
    coPresence,
    recordingTabId,
    recordingSteps,
    windowMaximized: mainWindow?.isMaximized() ?? false,
    autoOpenOnboarding: !IS_SMOKE && !settings.onboardingComplete
  };
}

let broadcastPending = false;
function broadcastSnapshot(): void {
  syncWindowTitle();
  if (broadcastPending || !shellView || shellView.webContents.isDestroyed()) return;
  broadcastPending = true;
  setTimeout(() => {
    broadcastPending = false;
    if (shellView && !shellView.webContents.isDestroyed()) {
      shellView.webContents.send("shell:snapshot", buildSnapshot());
    }
  }, 16);
}

function setCoPresence(next: CoPresenceState): void {
  coPresence = next;
  if (shellView && !shellView.webContents.isDestroyed()) {
    shellView.webContents.send("bot:co-presence", next);
  }
  broadcastSnapshot();
}

async function runRoutine(id: string): Promise<{ routine: RoutineItem; summary: string }> {
  const target = store.getRoutines().find((r) => r.id === id);
  if (!target) throw new Error("Routine not found");
  const bot = brain.getBot(target.botId);
  const tab = tabManager.openTab(target.spaceId, target.url, bot);
  setCoPresence({
    active: true,
    tabId: tab.id,
    botId: bot.id,
    botName: bot.name,
    botColor: bot.color,
    activity: `Running routine "${target.name}"`
  });

  try {
    await tabManager.waitForTabLoad(tab.id, 8000);
    const snap = await tabManager.readTabSnapshot(tab.id);
    const msg = await brain.respond({
      req: {
        requestId: `rtn_${crypto.randomUUID().slice(0, 6)}`,
        botId: bot.id,
        spaceId: target.spaceId,
        activeTabId: tab.id,
        mode: "execute",
        prompt: target.instruction,
        history: []
      },
      settings: store.getPublicSettings(),
      apiKey: store.getDecryptedApiKey(),
      snapshots: snap ? [snap] : [],
      totalTrackersBlocked: shield.getStatus(tab.id, tab.url).totalBlocked
    });

    const updated = store.updateRoutineRun(id, msg.content) ?? target;
    return { routine: updated, summary: msg.content };
  } finally {
    tabManager.closeTab(tab.id);
    setCoPresence(IDLE_COPRESENCE);
    broadcastSnapshot();
  }
}

function startRoutineScheduler(): void {
  routineTimer = setInterval(() => {
    const now = new Date();
    const key = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}-${now.getHours()}-${now.getMinutes()}`;
    if (key === lastRoutineMinuteKey) return;
    lastRoutineMinuteKey = key;
    for (const r of store.getRoutines()) {
      if (r.enabled && r.hourOfDay === now.getHours() && r.minuteOfHour === now.getMinutes()) {
        void runRoutine(r.id).catch(() => undefined);
      }
    }
  }, 30_000);
}

function createWindow(): void {
  const settings = store.getPublicSettings();
  const rendererHtml = path.resolve(__dirname, "../renderer/index.html");
  const allowedShellUrl = pathToFileURL(rendererHtml).href.toLowerCase();

  mainWindow = new BaseWindow({
    title: "Luminara Browser",
    width: 1420,
    height: 900,
    minWidth: 960,
    minHeight: 620,
    frame: false,
    show: !IS_SMOKE,
    backgroundColor: resolveBackgroundColor(settings.theme)
  });

  shellView = new WebContentsView({
    webPreferences: {
      partition: "luminara-chrome-shell",
      preload: path.join(__dirname, "shell-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true
    }
  });

  hardenShellSession(shellView.webContents.session);
  shellView.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  shellView.webContents.on("will-navigate", (ev, url) => {
    const lower = url.toLowerCase();
    const devOrigin = process.env.LUMINARA_DEV_URL?.toLowerCase();
    const allowed = lower === allowedShellUrl || (devOrigin ? lower.startsWith(devOrigin) : false);
    if (!allowed) ev.preventDefault();
  });

  const shortcutHost: ShortcutHost = {
    getShellWebContents: () =>
      shellView && !shellView.webContents.isDestroyed() ? shellView.webContents : null,
    getActiveTabWebContents: () => tabManager?.getTabWebContents(activeTabId) ?? null,
    onNavAction: (action) => {
      if (activeTabId) tabManager.navAction(activeTabId, action);
    },
    isEscapeBlocking: () => coPresence.active
  };
  attachWindowShortcuts(shellView.webContents, shortcutHost, true);

  mainWindow.contentView.addChildView(shellView);
  const syncShellBounds = () => {
    if (!mainWindow || mainWindow.isDestroyed() || !shellView) return;
    const [w, h] = mainWindow.getContentSize();
    shellView.setBounds({ x: 0, y: 0, width: w, height: h });
  };
  syncShellBounds();

  mainWindow.on("resize", syncShellBounds);
  mainWindow.on("maximize", () => {
    syncShellBounds();
    broadcastSnapshot();
  });
  mainWindow.on("unmaximize", () => {
    syncShellBounds();
    broadcastSnapshot();
  });
  mainWindow.on("enter-full-screen", syncShellBounds);
  mainWindow.on("leave-full-screen", syncShellBounds);
  mainWindow.on("closed", () => {
    shellView = null;
    mainWindow = null;
    tabManager.disposeAll();
    firewall.disposeAll();
  });

  tabManager = new TabManager({
    win: mainWindow,
    webPreloadPath: path.join(__dirname, "web-preload.js"),
    shield,
    firewall,
    shortcutHost,
    allowDataHtml: IS_SMOKE,
    onChanged: broadcastSnapshot,
    onPageLoaded: (spaceId, url, title, excerpt) => {
      store.recordMemory(spaceId, url, title, excerpt);
      broadcastSnapshot();
    },
    onOpenNewTab: (spaceId, url, background) => {
      const tab = tabManager.openTab(spaceId, url, null);
      if (!background) {
        activeSpaceId = tab.spaceId;
        activeTabId = tab.id;
      }
      broadcastSnapshot();
    },
    onRecordedNavStep: (tabId, url) => {
      if (tabId !== recordingTabId) return;
      const step = sanitizeRecordedStep({
        action: "navigate",
        label: `Navigate to ${url.slice(0, 48)}`,
        selector: "window",
        valuePreview: "",
        url
      });
      if (!step) return;
      recordingSteps = [...recordingSteps.slice(-39), step];
      if (shellView && !shellView.webContents.isDestroyed()) {
        shellView.webContents.send("skills:recorded-step", step);
      }
      broadcastSnapshot();
    },
    onRecordingCleared: (tabId) => {
      if (recordingTabId === tabId) recordingTabId = null;
    },
    onToast: sendToast
  });

  void shellView.webContents.loadFile(rendererHtml);
  if (IS_SMOKE) void runElectronSmokeVerification();
}

async function runElectronSmokeVerification(): Promise<void> {
  if (!shellView) return;
  const consoleErrors: string[] = [];
  shellView.webContents.on("console-message", (_ev, level, message) => {
    if (level >= 3) consoleErrors.push(message);
  });

  await new Promise<void>((resolve) => {
    shellView?.webContents.once("did-finish-load", () => resolve());
  });
  await new Promise((r) => setTimeout(r, 700));

  const domCheck = (await shellView.webContents.executeJavaScript(
    `(() => ({
      rootChildren: document.getElementById('root')?.children.length ?? 0,
      title: document.title,
      hasApi: typeof window.luminaraShell?.getSnapshot === 'function',
      bodyTextLen: (document.body.innerText || '').trim().length
    }))()`
  )) as { rootChildren: number; title: string; hasApi: boolean; bodyTextLen: number };

  const testTab = tabManager.openTab(
    "research",
    "data:text/html,<h1>Luminara%20Tab%20OK</h1><p>$49/mo</p>"
  );
  tabManager.syncLayout({
    x: 248,
    y: 48,
    width: 820,
    height: 760,
    visible: true,
    activeTabId: testTab.id,
    splitTabId: null
  });
  await tabManager.waitForTabLoad(testTab.id, 4000);
  const snap = await tabManager.readTabSnapshot(testTab.id);
  const hibernated = tabManager.hibernateTab(testTab.id);
  const woke = tabManager.ensureAwake(testTab.id);
  tabManager.closeTab(testTab.id);

  const ok =
    domCheck.rootChildren > 0 &&
    domCheck.hasApi &&
    domCheck.bodyTextLen > 40 &&
    consoleErrors.length === 0 &&
    hibernated &&
    woke &&
    Boolean(snap?.prices.includes("$49/mo"));

  console.log(
    JSON.stringify({
      event: ok ? "SMOKE_OK" : "SMOKE_FAIL",
      domCheck,
      consoleErrors,
      tabExtractedPrices: snap?.prices ?? [],
      hibernated,
      woke,
      botsLoaded: brain.getBots().length
    })
  );
  app.exit(ok ? 0 : 1);
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  store = new LocalStore(app.getPath("userData"), {
    isAvailable: () => safeStorage.isEncryptionAvailable(),
    encrypt: (plain) => safeStorage.encryptString(plain),
    decrypt: (buf) => safeStorage.decryptString(buf)
  });
  shield = new PrivacyShieldManager();
  firewall = new MutationFirewallManager({
    alwaysGuard: store.getPublicSettings().firewallAlwaysOn
  });
  firewall.setCallbacks(
    (card) => {
      if (shellView && !shellView.webContents.isDestroyed()) {
        shellView.webContents.send("firewall:approval", card);
      }
    },
    broadcastSnapshot
  );
  brain = new BotBrain(resolvePiBotBuiltinDir());

  registerShellIpc({
    getWindow: () => mainWindow,
    getShellView: () => shellView,
    store,
    shield,
    firewall,
    brain,
    getTabManager: () => tabManager,
    getState: () => ({
      activeSpaceId,
      activeTabId,
      splitTabId,
      recordingTabId,
      recordingSteps,
      coPresence
    }),
    setState: (patch) => {
      if (patch.activeSpaceId !== undefined) activeSpaceId = patch.activeSpaceId;
      if (patch.activeTabId !== undefined) activeTabId = patch.activeTabId;
      if (patch.splitTabId !== undefined) splitTabId = patch.splitTabId;
      if (patch.recordingTabId !== undefined) recordingTabId = patch.recordingTabId;
      if (patch.recordingSteps !== undefined) recordingSteps = patch.recordingSteps;
    },
    setCoPresence,
    buildSnapshot,
    broadcastSnapshot,
    runRoutine,
    resolveBg: resolveBackgroundColor
  });

  createWindow();
  if (!IS_SMOKE) startRoutineScheduler();
});

app.on("window-all-closed", () => {
  if (routineTimer) clearInterval(routineTimer);
  app.quit();
});
