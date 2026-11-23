import { contextBridge, ipcRenderer } from "electron";
import type {
  ApprovalCard,
  ApprovalDecision,
  ChatRequest,
  CoPresenceState,
  LuminaraShellApi,
  RecordedStep,
  RoutineItem,
  SettingsUpdate,
  ShellSnapshot,
  ShortcutEvent,
  StageLayoutRect
} from "../shared/types";

function subscribe<T>(channel: string, cb: (payload: T) => void): () => void {
  const listener = (_event: Electron.IpcRendererEvent, payload: T) => cb(payload);
  ipcRenderer.on(channel, listener);
  return () => {
    ipcRenderer.removeListener(channel, listener);
  };
}

const api: LuminaraShellApi = {
  getSnapshot: () => ipcRenderer.invoke("shell:get-snapshot"),
  syncLayout: (rect: StageLayoutRect) => ipcRenderer.invoke("shell:layout", rect),
  createSpace: (name: string, accent: string) =>
    ipcRenderer.invoke("spaces:create", { name, accent }),
  switchSpace: (spaceId: string) => ipcRenderer.invoke("spaces:switch", { spaceId }),
  openTab: (spaceId: string, input: string, botId?: string | null, background?: boolean) =>
    ipcRenderer.invoke("tabs:open", {
      spaceId,
      input,
      botId: botId ?? null,
      background: Boolean(background)
    }),
  activateTab: (tabId: string | null) => ipcRenderer.invoke("tabs:activate", { tabId }),
  setSplitTab: (tabId: string | null) => ipcRenderer.invoke("tabs:split", { tabId }),
  closeTab: (tabId: string) => ipcRenderer.invoke("tabs:close", { tabId }),
  hibernateTab: (tabId: string) => ipcRenderer.invoke("tabs:hibernate", { tabId }),
  navigateTab: (tabId: string, input: string) =>
    ipcRenderer.invoke("tabs:navigate", { tabId, input }),
  navAction: (tabId: string, action: "back" | "forward" | "reload" | "stop") =>
    ipcRenderer.invoke("tabs:nav-action", { tabId, action }),
  findInTab: (tabId: string, text: string, forward = true) =>
    ipcRenderer.invoke("tabs:find", { tabId, text, forward }),
  stopFindInTab: (tabId: string) => ipcRenderer.invoke("tabs:stop-find", { tabId }),
  toggleShieldDomain: (domain: string) => ipcRenderer.invoke("shield:toggle", { domain }),
  resolveApproval: (id: string, decision: ApprovalDecision) =>
    ipcRenderer.invoke("firewall:resolve", { id, decision }),
  revokeFirewallOrigin: (origin: string) => ipcRenderer.invoke("firewall:revoke", { origin }),
  triggerDemoApproval: () => ipcRenderer.invoke("firewall:demo"),
  sendBotMessage: (req: ChatRequest) => ipcRenderer.invoke("bot:chat", req),
  abortBotMessage: (requestId: string) => ipcRenderer.invoke("bot:abort", { requestId }),
  openBotWorktree: (botId: string, spaceId: string, urls: string[]) =>
    ipcRenderer.invoke("bot:worktree", { botId, spaceId, urls }),
  takeWheel: () => ipcRenderer.invoke("bot:take-wheel"),
  buildLiveLens: (spaceId: string) => ipcRenderer.invoke("lens:build", { spaceId }),
  toggleTeachMode: (tabId: string) => ipcRenderer.invoke("skills:toggle-teach", { tabId }),
  saveWebSkill: (name: string, description: string) =>
    ipcRenderer.invoke("skills:save", { name, description }),
  replayWebSkill: (skillId: string, tabId: string) =>
    ipcRenderer.invoke("skills:replay", { skillId, tabId }),
  deleteWebSkill: (skillId: string) => ipcRenderer.invoke("skills:delete", { skillId }),
  createRoutine: (item: Omit<RoutineItem, "id" | "lastRunAt" | "lastSummary">) =>
    ipcRenderer.invoke("routines:create", item),
  toggleRoutine: (id: string) => ipcRenderer.invoke("routines:toggle", { id }),
  runRoutineNow: (id: string) => ipcRenderer.invoke("routines:run-now", { id }),
  deleteRoutine: (id: string) => ipcRenderer.invoke("routines:delete", { id }),
  updateSettings: (patch: SettingsUpdate) => ipcRenderer.invoke("settings:update", patch),
  detectOllamaModels: (host?: string) => ipcRenderer.invoke("settings:detect-ollama", { host }),
  windowControl: (action: "minimize" | "maximize" | "close") =>
    ipcRenderer.invoke("window:control", { action }),
  onSnapshot: (cb: (snapshot: ShellSnapshot) => void) =>
    subscribe<ShellSnapshot>("shell:snapshot", cb),
  onApproval: (cb: (card: ApprovalCard) => void) =>
    subscribe<ApprovalCard>("firewall:approval", cb),
  onCoPresence: (cb: (state: CoPresenceState) => void) =>
    subscribe<CoPresenceState>("bot:co-presence", cb),
  onRecordedStep: (cb: (step: RecordedStep) => void) =>
    subscribe<RecordedStep>("skills:recorded-step", cb),
  onShortcut: (cb: (event: ShortcutEvent) => void) =>
    subscribe<ShortcutEvent>("shell:shortcut", cb),
  onToast: (cb: (message: string) => void) => subscribe<string>("shell:toast", cb)
};

contextBridge.exposeInMainWorld("luminaraShell", api);
