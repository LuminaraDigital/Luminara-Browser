import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import type {
  LlmProvider,
  MemoryEntry,
  RoutineItem,
  SearchEngine,
  SettingsPublic,
  SettingsUpdate,
  Space,
  ThemeMode,
  WebSkill
} from "../shared/types";

export interface SecretCipher {
  isAvailable: () => boolean;
  encrypt: (plain: string) => Buffer;
  decrypt: (buf: Buffer) => string;
}

interface StoredConfig {
  theme: ThemeMode;
  searchEngine: SearchEngine;
  provider: LlmProvider;
  model: string;
  baseUrl: string;
  ollamaHost: string;
  encryptedApiKeyBase64: string;
  apiKeyHint: string;
  onboardingComplete: boolean;
  firewallAlwaysOn: boolean;
  developerMode: boolean;
}

interface StoredState {
  spaces: Space[];
  skills: WebSkill[];
  routines: RoutineItem[];
  memories: MemoryEntry[];
}

export const DEFAULT_SPACES: Space[] = [
  {
    id: "research",
    name: "Research",
    accent: "#16A095",
    partition: "persist:luminara-space-research",
    description: "Deep reading, comparisons, and Remy's sourced notes"
  },
  {
    id: "work",
    name: "Work",
    accent: "#2E7CF6",
    partition: "persist:luminara-space-work",
    description: "Isolated work logins, docs, and Dana's live tables"
  },
  {
    id: "personal",
    name: "Personal",
    accent: "#7C4DFF",
    partition: "persist:luminara-space-personal",
    description: "Everyday browsing with isolated cookies and routines"
  }
];

const DEFAULT_ROUTINES: RoutineItem[] = [
  {
    id: "rtn_morning_brief",
    name: "Morning Tech & AI Digest",
    spaceId: "research",
    botId: "remy",
    hourOfDay: 8,
    minuteOfHour: 30,
    url: "https://news.ycombinator.com",
    instruction: "Summarise the top 5 engineering stories and flag anything relevant to browsers or local AI.",
    enabled: true,
    lastRunAt: null,
    lastSummary: "Ready to run on schedule or on demand."
  },
  {
    id: "rtn_pricing_watch",
    name: "Midday Market Watch",
    spaceId: "work",
    botId: "dana",
    hourOfDay: 13,
    minuteOfHour: 0,
    url: "https://example.org",
    instruction: "Extract headline numbers and compare against the previous run.",
    enabled: false,
    lastRunAt: null,
    lastSummary: "Paused — toggle on to run automatically."
  }
];

const DEFAULT_CONFIG: StoredConfig = {
  theme: "system",
  searchEngine: "duckduckgo",
  provider: "ollama",
  model: "",
  baseUrl: "",
  ollamaHost: "http://127.0.0.1:11434",
  encryptedApiKeyBase64: "",
  apiKeyHint: "",
  onboardingComplete: false,
  firewallAlwaysOn: false,
  developerMode: false
};

const ENC_V1_PREFIX = "enc:v1:";
const REDACT_SECRET_RE =
  /(sk-[A-Za-z0-9_-]{12,}|AIza[0-9A-Za-z_-]{20,}|ghp_[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9._-]{10,})/g;

export class LocalStore {
  private readonly configPath: string;
  private readonly statePath: string;
  private readonly cipher: SecretCipher;
  private config: StoredConfig;
  private state: StoredState;
  private memoryOnlyApiKey = "";

  constructor(userDataDir: string, cipher: SecretCipher) {
    fs.mkdirSync(userDataDir, { recursive: true });
    this.configPath = path.join(userDataDir, "luminara-v4-config.json");
    this.statePath = path.join(userDataDir, "luminara-v4-state.json");
    this.cipher = cipher;
    this.config = this.loadJson<StoredConfig>(this.configPath, { ...DEFAULT_CONFIG });
    this.state = this.loadJson<StoredState>(this.statePath, {
      spaces: [...DEFAULT_SPACES],
      skills: [],
      routines: [...DEFAULT_ROUTINES],
      memories: []
    });
    if (!Array.isArray(this.state.spaces) || this.state.spaces.length === 0) {
      this.state.spaces = [...DEFAULT_SPACES];
    }
  }

  public getPublicSettings(): SettingsPublic {
    const hasEncrypted = this.config.encryptedApiKeyBase64.startsWith(ENC_V1_PREFIX);
    return {
      theme: this.config.theme,
      searchEngine: this.config.searchEngine,
      provider: this.config.provider,
      model: this.config.model,
      baseUrl: this.config.baseUrl,
      ollamaHost: this.config.ollamaHost || "http://127.0.0.1:11434",
      hasApiKey: hasEncrypted || this.memoryOnlyApiKey.length > 0,
      apiKeyHint: this.config.apiKeyHint,
      encryptionAvailable: this.cipher.isAvailable(),
      onboardingComplete: this.config.onboardingComplete,
      firewallAlwaysOn: this.config.firewallAlwaysOn,
      developerMode: this.config.developerMode
    };
  }

  public getDecryptedApiKey(): string {
    if (this.memoryOnlyApiKey) return this.memoryOnlyApiKey;
    const raw = this.config.encryptedApiKeyBase64;
    if (!raw || !raw.startsWith(ENC_V1_PREFIX) || !this.cipher.isAvailable()) return "";
    try {
      const buf = Buffer.from(raw.slice(ENC_V1_PREFIX.length), "base64");
      return this.cipher.decrypt(buf);
    } catch {
      return "";
    }
  }

  public updateSettings(patch: SettingsUpdate): SettingsPublic {
    if (patch.theme !== undefined) this.config.theme = patch.theme;
    if (patch.searchEngine !== undefined) this.config.searchEngine = patch.searchEngine;
    if (patch.provider !== undefined) this.config.provider = patch.provider;
    if (patch.model !== undefined) this.config.model = patch.model.trim();
    if (patch.baseUrl !== undefined) this.config.baseUrl = patch.baseUrl.trim();
    if (patch.ollamaHost !== undefined) {
      this.config.ollamaHost = patch.ollamaHost.trim() || "http://127.0.0.1:11434";
    }
    if (patch.onboardingComplete !== undefined) this.config.onboardingComplete = patch.onboardingComplete;
    if (patch.firewallAlwaysOn !== undefined) this.config.firewallAlwaysOn = patch.firewallAlwaysOn;
    if (patch.developerMode !== undefined) this.config.developerMode = patch.developerMode;

    if (patch.clearApiKey) {
      this.memoryOnlyApiKey = "";
      this.config.encryptedApiKeyBase64 = "";
      this.config.apiKeyHint = "";
    } else if (patch.apiKey && patch.apiKey.trim().length > 0) {
      const raw = patch.apiKey.trim();
      const tail = raw.length >= 4 ? raw.slice(-4) : "****";
      this.config.apiKeyHint = `${raw.slice(0, 3)}…${tail}`;
      if (this.cipher.isAvailable()) {
        this.memoryOnlyApiKey = "";
        this.config.encryptedApiKeyBase64 = `${ENC_V1_PREFIX}${this.cipher.encrypt(raw).toString("base64")}`;
      } else {
        // Never write plaintext API keys to disk; keep in process memory for this session only
        this.memoryOnlyApiKey = raw;
        this.config.encryptedApiKeyBase64 = "";
      }
    }
    this.saveJsonAtomic(this.configPath, this.config);
    return this.getPublicSettings();
  }

  public getSpaces(): Space[] {
    return this.state.spaces;
  }

  public createSpace(name: string, accent: string): Space {
    const slug =
      name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") ||
      `space-${crypto.randomUUID().slice(0, 4)}`;
    const id = this.state.spaces.some((s) => s.id === slug)
      ? `${slug}-${crypto.randomUUID().slice(0, 4)}`
      : slug;
    const space: Space = {
      id,
      name: name.trim().slice(0, 28) || "New Space",
      accent: accent || "#199473",
      partition: `persist:luminara-space-${id}`,
      description: "Isolated cookies, local memory, and tabs"
    };
    this.state.spaces.push(space);
    this.saveJsonAtomic(this.statePath, this.state);
    return space;
  }

  public getSkills(): WebSkill[] {
    return this.state.skills;
  }

  public addSkill(skill: WebSkill): WebSkill {
    this.state.skills.unshift(skill);
    this.saveJsonAtomic(this.statePath, this.state);
    return skill;
  }

  public incrementSkillRun(skillId: string): void {
    const found = this.state.skills.find((s) => s.id === skillId);
    if (found) {
      found.runCount += 1;
      this.saveJsonAtomic(this.statePath, this.state);
    }
  }

  public deleteSkill(skillId: string): WebSkill[] {
    this.state.skills = this.state.skills.filter((s) => s.id !== skillId);
    this.saveJsonAtomic(this.statePath, this.state);
    return this.state.skills;
  }

  public getRoutines(): RoutineItem[] {
    return this.state.routines;
  }

  public addRoutine(item: Omit<RoutineItem, "id" | "lastRunAt" | "lastSummary">): RoutineItem {
    const routine: RoutineItem = {
      ...item,
      id: `rtn_${crypto.randomUUID().slice(0, 8)}`,
      lastRunAt: null,
      lastSummary: "Scheduled — awaiting first run."
    };
    this.state.routines.push(routine);
    this.saveJsonAtomic(this.statePath, this.state);
    return routine;
  }

  public toggleRoutine(id: string): RoutineItem[] {
    const item = this.state.routines.find((r) => r.id === id);
    if (item) {
      item.enabled = !item.enabled;
      this.saveJsonAtomic(this.statePath, this.state);
    }
    return this.state.routines;
  }

  public updateRoutineRun(id: string, summary: string): RoutineItem | null {
    const item = this.state.routines.find((r) => r.id === id);
    if (!item) return null;
    item.lastRunAt = Date.now();
    item.lastSummary = summary.slice(0, 320);
    this.saveJsonAtomic(this.statePath, this.state);
    return item;
  }

  public deleteRoutine(id: string): RoutineItem[] {
    this.state.routines = this.state.routines.filter((r) => r.id !== id);
    this.saveJsonAtomic(this.statePath, this.state);
    return this.state.routines;
  }

  public getMemories(): MemoryEntry[] {
    return this.state.memories;
  }

  public recordMemory(spaceId: string, url: string, title: string, snippet: string): void {
    if (!url.startsWith("http://") && !url.startsWith("https://")) return;
    let domain = "";
    try {
      domain = new URL(url).hostname.replace(/^www\./, "");
    } catch {
      return;
    }
    const safeSnippet = snippet.replace(REDACT_SECRET_RE, "[redacted]").trim().slice(0, 220);
    const existingIdx = this.state.memories.findIndex((m) => m.spaceId === spaceId && m.url === url);
    const entry: MemoryEntry = {
      id: existingIdx >= 0 ? this.state.memories[existingIdx].id : `mem_${crypto.randomUUID().slice(0, 8)}`,
      spaceId,
      url,
      domain,
      title: (title || domain).slice(0, 120),
      snippet: safeSnippet || `Visited ${domain}`,
      savedAt: Date.now()
    };
    if (existingIdx >= 0) this.state.memories.splice(existingIdx, 1);
    this.state.memories.unshift(entry);
    if (this.state.memories.length > 80) this.state.memories = this.state.memories.slice(0, 80);
    this.saveJsonAtomic(this.statePath, this.state);
  }

  private loadJson<T>(filePath: string, fallback: T): T {
    try {
      if (!fs.existsSync(filePath)) return fallback;
      return { ...fallback, ...(JSON.parse(fs.readFileSync(filePath, "utf8")) as Partial<T>) };
    } catch {
      return fallback;
    }
  }

  private saveJsonAtomic(filePath: string, data: unknown): void {
    const tmpPath = `${filePath}.tmp`;
    try {
      fs.writeFileSync(tmpPath, JSON.stringify(data, null, 2), { encoding: "utf8", mode: 0o600 });
      fs.renameSync(tmpPath, filePath);
    } catch {
      try {
        if (fs.existsSync(tmpPath)) fs.unlinkSync(tmpPath);
      } catch {
        // ignore cleanup failure
      }
    }
  }
}
