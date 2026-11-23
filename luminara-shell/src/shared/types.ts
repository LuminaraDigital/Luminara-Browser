export type ThemeMode = "light" | "dark" | "system";
export type SearchEngine = "duckduckgo" | "kagi" | "brave" | "google";
export type LlmProvider =
  | "ollama"
  | "openrouter"
  | "gemini"
  | "anthropic"
  | "openai"
  | "custom";

export type StageMode = "home" | "web" | "lens" | "inbox" | "routines";
export type BotMode = "execute" | "plan";
export type ApprovalDecision = "deny" | "allow-once" | "always-site";
export type ShortcutEvent =
  | "palette"
  | "omnibox"
  | "new-tab"
  | "close-tab"
  | "toggle-drawer"
  | "find"
  | "escape";

export interface Space {
  id: string;
  name: string;
  accent: string;
  partition: string;
  description: string;
}

export interface TabRecord {
  id: string;
  spaceId: string;
  url: string;
  title: string;
  faviconUrl: string;
  loading: boolean;
  canGoBack: boolean;
  canGoForward: boolean;
  hibernated: boolean;
  botId: string | null;
  botName: string | null;
  botColor: string | null;
  blockedCount: number;
  webMcpTools: string[];
  lastActiveAt: number;
}

export interface BotProfile {
  id: string;
  name: string;
  roleTitle: string;
  description: string;
  color: string;
  isGroup: boolean;
  members?: string[];
  systemPrompt: string;
  quickPrompts: string[];
  source: "builtin" | "pibot";
}

export interface WorkReceipt {
  durationMs: number;
  tabsRead: number;
  provider: string;
  model: string;
  trackersBlocked: number;
  mode: BotMode;
  webMcpToolsFound: number;
}

export interface ChatMessage {
  id: string;
  botId: string;
  role: "user" | "assistant" | "system";
  authorName: string;
  authorColor?: string;
  content: string;
  createdAt: number;
  receipt?: WorkReceipt;
  worktreeTabIds?: string[];
  needsModelSetup?: boolean;
}

export interface ApprovalCard {
  id: string;
  botId: string | null;
  botName: string;
  botColor: string;
  tabId: string | null;
  title: string;
  domain: string;
  origin: string;
  method: string;
  path: string;
  why: string;
  diffPreview: string;
  createdAt: number;
}

export interface LiveLensRow {
  tabId: string;
  title: string;
  domain: string;
  url: string;
  priceOrMetric: string;
  ratingOrSignal: string;
  summary: string;
  wordCount: number;
  webMcpTools: string[];
  botName: string | null;
  hibernated: boolean;
}

export interface LiveLensTable {
  spaceId: string;
  generatedAt: number;
  rows: LiveLensRow[];
}

export interface RecordedStep {
  id: string;
  action: "click" | "input" | "submit" | "navigate";
  label: string;
  selector: string;
  valuePreview: string;
  url: string;
  timestamp: number;
}

export interface WebSkill {
  id: string;
  name: string;
  domain: string;
  description: string;
  steps: RecordedStep[];
  createdAt: number;
  runCount: number;
}

export interface RoutineItem {
  id: string;
  name: string;
  spaceId: string;
  botId: string;
  hourOfDay: number;
  minuteOfHour: number;
  url: string;
  instruction: string;
  enabled: boolean;
  lastRunAt: number | null;
  lastSummary: string;
}

export interface MemoryEntry {
  id: string;
  spaceId: string;
  url: string;
  domain: string;
  title: string;
  snippet: string;
  savedAt: number;
}

export interface SettingsPublic {
  theme: ThemeMode;
  searchEngine: SearchEngine;
  provider: LlmProvider;
  model: string;
  baseUrl: string;
  ollamaHost: string;
  hasApiKey: boolean;
  apiKeyHint: string;
  encryptionAvailable: boolean;
  onboardingComplete: boolean;
  firewallAlwaysOn: boolean;
  developerMode: boolean;
}

export interface SettingsUpdate {
  theme?: ThemeMode;
  searchEngine?: SearchEngine;
  provider?: LlmProvider;
  model?: string;
  baseUrl?: string;
  ollamaHost?: string;
  apiKey?: string;
  clearApiKey?: boolean;
  onboardingComplete?: boolean;
  firewallAlwaysOn?: boolean;
  developerMode?: boolean;
}

export interface StageLayoutRect {
  x: number;
  y: number;
  width: number;
  height: number;
  visible: boolean;
  activeTabId: string | null;
  splitTabId: string | null;
}

export interface ShieldStatus {
  totalBlocked: number;
  pausedDomains: string[];
  activeTabBlocked: number;
  activeDomain: string;
  activeDomainPaused: boolean;
}

export interface CoPresenceState {
  active: boolean;
  tabId: string | null;
  botId: string | null;
  botName: string;
  botColor: string;
  activity: string;
}

export interface ShellSnapshot {
  spaces: Space[];
  activeSpaceId: string;
  tabs: TabRecord[];
  activeTabId: string | null;
  splitTabId: string | null;
  bots: BotProfile[];
  pendingApprovals: ApprovalCard[];
  allowlistedOrigins: string[];
  skills: WebSkill[];
  routines: RoutineItem[];
  memories: MemoryEntry[];
  settings: SettingsPublic;
  shield: ShieldStatus;
  coPresence: CoPresenceState;
  recordingTabId: string | null;
  recordingSteps: RecordedStep[];
  windowMaximized: boolean;
  autoOpenOnboarding: boolean;
}

export interface ChatRequest {
  requestId: string;
  botId: string;
  spaceId: string;
  activeTabId: string | null;
  mode: BotMode;
  prompt: string;
  history: Array<{ role: "user" | "assistant"; content: string }>;
}

export interface LuminaraShellApi {
  getSnapshot: () => Promise<ShellSnapshot>;
  syncLayout: (rect: StageLayoutRect) => Promise<void>;
  createSpace: (name: string, accent: string) => Promise<Space>;
  switchSpace: (spaceId: string) => Promise<ShellSnapshot>;
  openTab: (
    spaceId: string,
    input: string,
    botId?: string | null,
    background?: boolean
  ) => Promise<TabRecord>;
  activateTab: (tabId: string | null) => Promise<ShellSnapshot>;
  setSplitTab: (tabId: string | null) => Promise<ShellSnapshot>;
  closeTab: (tabId: string) => Promise<ShellSnapshot>;
  hibernateTab: (tabId: string) => Promise<ShellSnapshot>;
  navigateTab: (tabId: string, input: string) => Promise<TabRecord | null>;
  navAction: (tabId: string, action: "back" | "forward" | "reload" | "stop") => Promise<void>;
  findInTab: (tabId: string, text: string, forward?: boolean) => Promise<void>;
  stopFindInTab: (tabId: string) => Promise<void>;
  toggleShieldDomain: (domain: string) => Promise<ShieldStatus>;
  resolveApproval: (id: string, decision: ApprovalDecision) => Promise<ShellSnapshot>;
  revokeFirewallOrigin: (origin: string) => Promise<ShellSnapshot>;
  triggerDemoApproval: () => Promise<ApprovalCard>;
  sendBotMessage: (req: ChatRequest) => Promise<ChatMessage>;
  abortBotMessage: (requestId: string) => Promise<void>;
  openBotWorktree: (botId: string, spaceId: string, urls: string[]) => Promise<TabRecord[]>;
  takeWheel: () => Promise<CoPresenceState>;
  buildLiveLens: (spaceId: string) => Promise<LiveLensTable>;
  toggleTeachMode: (tabId: string) => Promise<{ recording: boolean; steps: RecordedStep[] }>;
  saveWebSkill: (name: string, description: string) => Promise<WebSkill | null>;
  replayWebSkill: (skillId: string, tabId: string) => Promise<{ ok: boolean; message: string }>;
  deleteWebSkill: (skillId: string) => Promise<WebSkill[]>;
  createRoutine: (item: Omit<RoutineItem, "id" | "lastRunAt" | "lastSummary">) => Promise<RoutineItem>;
  toggleRoutine: (id: string) => Promise<RoutineItem[]>;
  runRoutineNow: (id: string) => Promise<{ routine: RoutineItem; summary: string }>;
  deleteRoutine: (id: string) => Promise<RoutineItem[]>;
  updateSettings: (patch: SettingsUpdate) => Promise<SettingsPublic>;
  detectOllamaModels: (host?: string) => Promise<{ available: boolean; models: string[] }>;
  windowControl: (action: "minimize" | "maximize" | "close") => Promise<void>;
  onSnapshot: (cb: (snapshot: ShellSnapshot) => void) => () => void;
  onApproval: (cb: (card: ApprovalCard) => void) => () => void;
  onCoPresence: (cb: (state: CoPresenceState) => void) => () => void;
  onRecordedStep: (cb: (step: RecordedStep) => void) => () => void;
  onShortcut: (cb: (event: ShortcutEvent) => void) => () => void;
  onToast: (cb: (message: string) => void) => () => void;
}
