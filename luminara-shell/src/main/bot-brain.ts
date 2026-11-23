import crypto from "node:crypto";
import type {
  BotMode,
  BotProfile,
  ChatMessage,
  ChatRequest,
  LiveLensRow,
  LiveLensTable,
  RecordedStep,
  SearchEngine,
  SettingsPublic,
  TabRecord,
  WorkReceipt
} from "../shared/types";
import { loadBotProfiles } from "./pibot-roles";
import { callLlmProvider, detectOllamaModels, validateEndpointUrl } from "./llm-client";

export { loadBotProfiles, detectOllamaModels, validateEndpointUrl };

export interface PageSnapshot {
  tabId: string;
  url: string;
  title: string;
  domain: string;
  textExcerpt: string;
  wordCount: number;
  prices: string[];
  ratings: string[];
  headings: string[];
  webMcpTools: string[];
  botName: string | null;
  hibernated: boolean;
}

const STEP_SECRET_RE =
  /(Bearer\s+[A-Za-z0-9._-]+|sk-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{20,}|\b(?:\d[ -]*?){13,16}\b)/g;

export function validateHttpUrl(raw: string): string {
  const trimmed = raw.trim();
  const normalized = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error("Please enter a valid website URL (for example, https://example.org).");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Only http:// and https:// URLs are supported.");
  }
  const host = parsed.hostname.toLowerCase();
  if (!host || (host !== "localhost" && !host.includes("."))) {
    throw new Error("Please include a valid domain name (for example, news.ycombinator.com).");
  }
  return parsed.toString();
}

export function formatSearchUrl(rawInput: string, engine: SearchEngine): string {
  const trimmed = rawInput.trim();
  if (!trimmed) return "https://duckduckgo.com";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (/^localhost(:\d+)?(\/.*)?$/i.test(trimmed) || /^127\.0\.0\.1(:\d+)?(\/.*)?$/.test(trimmed)) {
    return `http://${trimmed}`;
  }
  if (!trimmed.includes(" ") && /^[a-z0-9-]+(\.[a-z0-9-]+)+([/:?#].*)?$/i.test(trimmed)) {
    return `https://${trimmed}`;
  }
  const encoded = encodeURIComponent(trimmed);
  switch (engine) {
    case "kagi":
      return `https://kagi.com/search?q=${encoded}`;
    case "brave":
      return `https://search.brave.com/search?q=${encoded}`;
    case "google":
      return `https://www.google.com/search?q=${encoded}`;
    default:
      return `https://duckduckgo.com/?q=${encoded}`;
  }
}

export function buildLiveLensTable(
  spaceId: string,
  tabs: TabRecord[],
  snapshots: Map<string, PageSnapshot>
): LiveLensTable {
  const rows: LiveLensRow[] = tabs.map((tab) => {
    const snap = snapshots.get(tab.id);
    let domain = tab.url;
    try {
      domain = new URL(tab.url).hostname.replace(/^www\./, "");
    } catch {
      // keep raw
    }
    const priceOrMetric =
      snap && snap.prices.length > 0
        ? snap.prices.slice(0, 3).join(" · ")
        : snap && snap.wordCount > 0
          ? `${snap.wordCount.toLocaleString()} words`
          : tab.hibernated
            ? "Hibernated (0 MB)"
            : "—";
    const ratingOrSignal =
      snap && snap.ratings.length > 0
        ? snap.ratings[0]
        : snap && snap.webMcpTools.length > 0
          ? `${snap.webMcpTools.length} WebMCP tools`
          : tab.blockedCount > 0
            ? `${tab.blockedCount} trackers blocked`
            : "Clean page";
    const summary =
      snap && snap.headings.length > 0
        ? snap.headings.slice(0, 2).join(" — ")
        : snap && snap.textExcerpt
          ? snap.textExcerpt.slice(0, 140)
          : tab.hibernated
            ? "Click tab to wake and extract live details."
            : tab.title;

    return {
      tabId: tab.id,
      title: tab.title || domain,
      domain,
      url: tab.url,
      priceOrMetric,
      ratingOrSignal,
      summary,
      wordCount: snap?.wordCount ?? 0,
      webMcpTools: snap?.webMcpTools ?? tab.webMcpTools,
      botName: tab.botName,
      hibernated: tab.hibernated
    };
  });

  return { spaceId, generatedAt: Date.now(), rows };
}

export function sanitizeRecordedStep(raw: Partial<RecordedStep>): RecordedStep | null {
  const label = String(raw.label ?? "").trim().slice(0, 80);
  const selector = String(raw.selector ?? "").trim().slice(0, 120);
  if (!selector || /password|passwd|secret|cvv|token|otp/i.test(`${label} ${selector}`)) {
    return null;
  }
  const action =
    raw.action === "input" || raw.action === "submit" || raw.action === "navigate"
      ? raw.action
      : "click";
  const safeValue = String(raw.valuePreview ?? "")
    .replace(STEP_SECRET_RE, "[redacted]")
    .slice(0, 64);

  return {
    id: `stp_${crypto.randomUUID().slice(0, 8)}`,
    action,
    label: label || selector,
    selector,
    valuePreview: safeValue,
    url: String(raw.url ?? ""),
    timestamp: raw.timestamp ?? Date.now()
  };
}

export class BotBrain {
  private readonly bots: BotProfile[];
  private readonly controllers = new Map<string, AbortController>();

  constructor(pibotBuiltinDir: string) {
    this.bots = loadBotProfiles(pibotBuiltinDir);
  }

  public getBots(): BotProfile[] {
    return this.bots;
  }

  public getBot(botId: string): BotProfile {
    return this.bots.find((b) => b.id === botId) ?? this.bots[0];
  }

  public abort(requestId: string): void {
    const ctrl = this.controllers.get(requestId);
    if (ctrl) {
      ctrl.abort();
      this.controllers.delete(requestId);
    }
  }

  public async respond(params: {
    req: ChatRequest;
    settings: SettingsPublic;
    apiKey: string;
    snapshots: PageSnapshot[];
    totalTrackersBlocked: number;
    worktreeTabIds?: string[];
  }): Promise<ChatMessage> {
    const started = Date.now();
    const bot = this.getBot(params.req.botId);
    const ctrl = new AbortController();
    this.controllers.set(params.req.requestId, ctrl);

    const webMcpToolsFound = params.snapshots.reduce((sum, s) => sum + s.webMcpTools.length, 0);
    const contextBlock = this.buildContextBlock(params.snapshots, params.req.mode);
    const systemPrompt = `${bot.systemPrompt}\n\nMode: ${
      params.req.mode === "plan"
        ? "PLAN ONLY — propose a concise numbered plan without claiming actions were executed."
        : "EXECUTE — answer directly using the live browser tab context below."
    }`;

    let content = "";
    let usedProvider: string = params.settings.provider;
    let usedModel = params.settings.model || "local-extractor";
    let needsModelSetup = false;

    try {
      const llmReply = await callLlmProvider({
        provider: params.settings.provider,
        model: params.settings.model,
        baseUrl: params.settings.baseUrl,
        ollamaHost: params.settings.ollamaHost,
        apiKey: params.apiKey,
        systemPrompt,
        history: params.req.history,
        userMessage: `${params.req.prompt}\n\n[Open Browser Context]\n${contextBlock}`,
        signal: ctrl.signal
      });

      if (llmReply) {
        content = llmReply.text;
        usedProvider = llmReply.provider;
        usedModel = llmReply.model;
      } else {
        needsModelSetup = true;
        usedProvider = "local-on-device";
        usedModel = "DOM + WebMCP Reader";
        content = this.buildLocalFallbackResponse(bot, params.req.mode, params.req.prompt, params.snapshots);
      }
    } catch (err) {
      if (ctrl.signal.aborted) {
        content = "Stopped at your request. Ready whenever you want to continue.";
        usedProvider = "cancelled";
        usedModel = "stopped";
      } else {
        needsModelSetup = true;
        usedProvider = "local-fallback";
        usedModel = "DOM Reader";
        const msg = err instanceof Error ? err.message : "Model connection failed";
        content = `${this.buildLocalFallbackResponse(bot, params.req.mode, params.req.prompt, params.snapshots)}\n\nNote: Could not reach ${params.settings.provider} (${msg}). Click "AI Setup" to pick a local Ollama model or API key.`;
      }
    } finally {
      this.controllers.delete(params.req.requestId);
    }

    const receipt: WorkReceipt = {
      durationMs: Math.max(1, Date.now() - started),
      tabsRead: params.snapshots.length,
      provider: usedProvider,
      model: usedModel,
      trackersBlocked: params.totalTrackersBlocked,
      mode: params.req.mode,
      webMcpToolsFound
    };

    return {
      id: `msg_${crypto.randomUUID().slice(0, 8)}`,
      botId: bot.id,
      role: "assistant",
      authorName: bot.name,
      authorColor: bot.color,
      content,
      createdAt: Date.now(),
      receipt,
      worktreeTabIds: params.worktreeTabIds,
      needsModelSetup
    };
  }

  private buildContextBlock(snapshots: PageSnapshot[], mode: BotMode): string {
    if (snapshots.length === 0) return `No live web tabs are open in this Space yet. Mode: ${mode}.`;
    return snapshots
      .slice(0, 6)
      .map((s, idx) =>
        [
          `[${idx + 1}] ${s.title} (${s.url})`,
          s.prices.length > 0 ? `Prices/Metrics: ${s.prices.slice(0, 5).join(", ")}` : "",
          s.webMcpTools.length > 0 ? `WebMCP Tools: ${s.webMcpTools.slice(0, 6).join(", ")}` : "",
          s.headings.length > 0 ? `Headings: ${s.headings.slice(0, 4).join(" | ")}` : "",
          s.textExcerpt ? `Excerpt: ${s.textExcerpt.slice(0, 700)}` : ""
        ]
          .filter(Boolean)
          .join("\n")
      )
      .join("\n\n");
  }

  private buildLocalFallbackResponse(
    bot: BotProfile,
    mode: BotMode,
    prompt: string,
    snapshots: PageSnapshot[]
  ): string {
    if (mode === "plan") {
      const tabList = snapshots.map((s) => `• ${s.title} (${s.domain})`).join("\n");
      return [
        `${bot.name} Plan for: "${prompt}"`,
        "",
        "1. Remy (Research): Cross-check claims & headings across open Space tabs.",
        "2. Dana (Data): Align prices, metrics, and WebMCP forms in Live Lens.",
        "3. Pi (Action): Prepare a concise verdict and pause any external write on an Approval Card.",
        snapshots.length > 0
          ? `\nTabs ready in this Space:\n${tabList}`
          : "\nOpen one or more web tabs or launch a Bot Worktree to pull live sources."
      ].join("\n");
    }

    if (snapshots.length === 0) {
      return `${bot.name} is ready. Open a webpage in this Space (or paste a URL above) to read its text, tables, and WebMCP tools directly at 60fps. Connect local Ollama or an API key in AI Setup for full synthesis.`;
    }

    if (bot.isGroup) {
      const remySources = snapshots
        .slice(0, 4)
        .map((s, i) => `[${i + 1}] ${s.title} (${s.domain}) — ${s.headings[0] || s.textExcerpt.slice(0, 120)}`)
        .join("\n");
      const allPrices = snapshots.flatMap((s) => s.prices.map((p) => `${s.domain}: ${p}`)).slice(0, 6);
      const totalTools = snapshots.reduce((sum, s) => sum + s.webMcpTools.length, 0);
      const totalWords = snapshots.reduce((sum, s) => sum + s.wordCount, 0);
      return [
        `Research Team Synthesis across ${snapshots.length} live tab${snapshots.length === 1 ? "" : "s"}:`,
        "",
        `Remy (Sources):\n${remySources}`,
        "",
        `Dana (Data): ${totalWords.toLocaleString()} words scanned · ${
          allPrices.length > 0 ? `Prices detected: ${allPrices.join(", ")}` : "No pricing figures detected"
        } · ${totalTools} WebMCP/form tools found.`,
        "",
        "Pi (Next step): Open Live Lens to sort and export these tabs to CSV/Markdown, or connect a local Ollama / cloud model for deeper synthesis."
      ].join("\n");
    }

    const lines = snapshots.slice(0, 4).map((s, idx) => {
      const priceNote = s.prices.length > 0 ? ` · Metrics: ${s.prices.slice(0, 3).join(", ")}` : "";
      const toolNote = s.webMcpTools.length > 0 ? ` · Tools: ${s.webMcpTools.slice(0, 3).join(", ")}` : "";
      return `[${idx + 1}] ${s.title} (${s.domain}${priceNote}${toolNote})\n${s.textExcerpt.slice(0, 240)}`;
    });
    return `Live on-device read by ${bot.name} across ${snapshots.length} tab${snapshots.length === 1 ? "" : "s"}:\n\n${lines.join("\n\n")}`;
  }
}
