import crypto from "node:crypto";
import type { ApprovalCard, ApprovalDecision } from "../shared/types";

const MUTATION_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const IGNORED_RESOURCE_TYPES = new Set(["ping", "cspReport"]);

const SENSITIVE_KEY_RE =
  /(pass(word|wd)?|secret|token|auth(orization)?|api[_-]?key|session|cookie|jwt|bearer|credit|card|cvv|ssn|pin|otp)/i;

const SENSITIVE_VALUE_RE =
  /(Bearer\s+[A-Za-z0-9._-]+|sk-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{20,}|\b(?:\d[ -]*?){13,16}\b)/g;

export interface UploadChunk {
  bytes?: Uint8Array;
  file?: string;
}

export interface MutationRequestContext {
  url: string;
  method: string;
  resourceType?: string;
  tabId: string | null;
  botId: string | null;
  botName: string;
  botColor: string;
  isBotInitiated: boolean;
  uploadData?: UploadChunk[];
}

interface PendingEntry {
  card: ApprovalCard;
  resolve: (allowed: boolean) => void;
  timer: ReturnType<typeof setTimeout>;
}

function scrubMultipart(raw: string): string | null {
  if (!/Content-Disposition:\s*form-data/i.test(raw)) return null;
  const parts = raw.split(/\r?\n--[^\r\n]+/);
  const lines: string[] = [];
  for (const part of parts) {
    const match = /name="([^"]+)"/i.exec(part);
    if (!match) continue;
    const fieldName = match[1];
    const headerSep = part.search(/\r?\n\r?\n/);
    const rawVal = headerSep >= 0 ? part.slice(headerSep).trim() : "";
    const safeVal = SENSITIVE_KEY_RE.test(fieldName)
      ? "[redacted]"
      : rawVal.replace(SENSITIVE_VALUE_RE, "[redacted]").replace(/\s+/g, " ").slice(0, 80);
    lines.push(`${fieldName}: ${safeVal || "(empty)"}`);
    if (lines.length >= 12) break;
  }
  return lines.length > 0 ? lines.join("\n") : null;
}

export function scrubPayloadPreview(rawText: string): string {
  const trimmed = rawText.trim();
  if (!trimmed) return "No request body fields sent.";

  const multipart = scrubMultipart(trimmed);
  if (multipart) return multipart.slice(0, 650);

  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const parsed: unknown = JSON.parse(trimmed);
      return JSON.stringify(redactJsonNode(parsed), null, 2).slice(0, 650);
    } catch {
      // Fallback to form/text scrubber
    }
  }

  if (trimmed.includes("=") && !trimmed.includes("\n")) {
    try {
      const params = new URLSearchParams(trimmed);
      const lines: string[] = [];
      for (const [k, v] of params.entries()) {
        const safeVal = SENSITIVE_KEY_RE.test(k)
          ? "[redacted]"
          : v.replace(SENSITIVE_VALUE_RE, "[redacted]").slice(0, 80);
        lines.push(`${k}: ${safeVal}`);
        if (lines.length >= 12) break;
      }
      if (lines.length > 0) return lines.join("\n");
    } catch {
      // Fallback below
    }
  }

  const lines = trimmed
    .split(/\r?\n/)
    .slice(0, 12)
    .map((line) => {
      const colonIdx = line.indexOf(":");
      if (colonIdx > 0 && SENSITIVE_KEY_RE.test(line.slice(0, colonIdx))) {
        return `${line.slice(0, colonIdx)}: [redacted]`;
      }
      return line.replace(SENSITIVE_VALUE_RE, "[redacted]");
    });
  return lines.join("\n").slice(0, 650);
}

function redactJsonNode(node: unknown, depth = 0): unknown {
  if (depth > 4) return "[truncated]";
  if (Array.isArray(node)) {
    return node.slice(0, 8).map((item) => redactJsonNode(item, depth + 1));
  }
  if (node && typeof node === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(node as Record<string, unknown>).slice(0, 16)) {
      out[k] = SENSITIVE_KEY_RE.test(k) ? "[redacted]" : redactJsonNode(v, depth + 1);
    }
    return out;
  }
  if (typeof node === "string") {
    return node.replace(SENSITIVE_VALUE_RE, "[redacted]").slice(0, 120);
  }
  return node;
}

function extractRawUpload(uploadData?: UploadChunk[]): string {
  if (!uploadData || uploadData.length === 0) return "";
  const parts: string[] = [];
  for (const chunk of uploadData) {
    if (chunk.bytes && chunk.bytes.byteLength > 0) {
      parts.push(Buffer.from(chunk.bytes).toString("utf8"));
    } else if (chunk.file) {
      parts.push(`[file upload: ${chunk.file.split(/[\\/]/).pop() ?? "attachment"}]`);
    }
  }
  return parts.join("\n");
}

function describeAction(method: string, domain: string, path: string): string {
  const cleanPath = path.length > 36 ? `${path.slice(0, 36)}…` : path;
  switch (method.toUpperCase()) {
    case "DELETE":
      return `Delete data on ${domain} (${cleanPath})`;
    case "PUT":
      return `Replace data on ${domain} (${cleanPath})`;
    case "PATCH":
      return `Update record on ${domain} (${cleanPath})`;
    default:
      return `Submit form or change on ${domain} (${cleanPath})`;
  }
}

export class MutationFirewallManager {
  private readonly pending = new Map<string, PendingEntry>();
  private readonly allowlistedOrigins = new Set<string>();
  private alwaysGuard = false;
  private readonly timeoutMs: number;
  private onCardCreated?: (card: ApprovalCard) => void;
  private onStateChanged?: () => void;

  constructor(options?: {
    timeoutMs?: number;
    alwaysGuard?: boolean;
    onCardCreated?: (card: ApprovalCard) => void;
    onStateChanged?: () => void;
  }) {
    this.timeoutMs = options?.timeoutMs ?? 90_000;
    this.alwaysGuard = options?.alwaysGuard ?? false;
    this.onCardCreated = options?.onCardCreated;
    this.onStateChanged = options?.onStateChanged;
  }

  public setCallbacks(onCardCreated: (card: ApprovalCard) => void, onStateChanged: () => void): void {
    this.onCardCreated = onCardCreated;
    this.onStateChanged = onStateChanged;
  }

  public setAlwaysGuard(enabled: boolean): void {
    this.alwaysGuard = enabled;
  }

  public isAlwaysGuard(): boolean {
    return this.alwaysGuard;
  }

  public getPending(): ApprovalCard[] {
    return Array.from(this.pending.values()).map((entry) => entry.card);
  }

  public listAllowlisted(): string[] {
    return Array.from(this.allowlistedOrigins).sort();
  }

  public revokeOrigin(origin: string): void {
    this.allowlistedOrigins.delete(origin);
    this.onStateChanged?.();
  }

  public shouldIntercept(ctx: MutationRequestContext): boolean {
    if (ctx.resourceType && IGNORED_RESOURCE_TYPES.has(ctx.resourceType)) return false;
    if (!MUTATION_METHODS.has(ctx.method.toUpperCase())) return false;
    if (!this.alwaysGuard && !ctx.isBotInitiated) return false;

    let parsed: URL;
    try {
      parsed = new URL(ctx.url);
    } catch {
      return false;
    }

    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
    if (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1" || parsed.hostname === "[::1]") {
      return false;
    }
    return !this.allowlistedOrigins.has(parsed.origin);
  }

  public requestApproval(ctx: MutationRequestContext): Promise<boolean> {
    if (!this.shouldIntercept(ctx)) return Promise.resolve(true);

    const parsed = new URL(ctx.url);
    const id = `apr_${crypto.randomUUID().slice(0, 8)}`;
    const method = ctx.method.toUpperCase();
    const rawUpload = extractRawUpload(ctx.uploadData);
    const queryPreview = parsed.search ? scrubPayloadPreview(parsed.search.slice(1)) : "";
    const bodyPreview = scrubPayloadPreview(rawUpload);
    const diffPreview = queryPreview ? `Query:\n${queryPreview}\n\nBody:\n${bodyPreview}` : bodyPreview;

    const actorText = ctx.isBotInitiated
      ? `${ctx.botName} tried to send an external ${method} request`
      : `This page tried to send an external ${method} request while Mutation Firewall is enabled`;

    const card: ApprovalCard = {
      id,
      botId: ctx.botId,
      botName: ctx.botName,
      botColor: ctx.botColor,
      tabId: ctx.tabId,
      title: describeAction(method, parsed.hostname, parsed.pathname || "/"),
      domain: parsed.hostname,
      origin: parsed.origin,
      method,
      path: parsed.pathname || "/",
      why: `${actorText}. Luminara pauses changes to outside sites (${parsed.hostname}) until you approve them. Passwords, cookies, and tokens are hidden below.`,
      diffPreview,
      createdAt: Date.now()
    };

    return new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          resolve(false);
          this.onStateChanged?.();
        }
      }, this.timeoutMs);

      this.pending.set(id, { card, resolve, timer });
      this.onCardCreated?.(card);
      this.onStateChanged?.();
    });
  }

  public createDemoCard(): ApprovalCard {
    const id = `apr_${crypto.randomUUID().slice(0, 8)}`;
    const card: ApprovalCard = {
      id,
      botId: "remy",
      botName: "Remy",
      botColor: "#16A095",
      tabId: null,
      title: "Submit vendor inquiry on example.org (/api/contact)",
      domain: "example.org",
      origin: "https://example.org",
      method: "POST",
      path: "/api/contact",
      why: "Remy prepared an external POST request while assisting you. Luminara pauses irreversible web mutations until you approve them. Secrets and auth tokens are automatically redacted.",
      diffPreview: scrubPayloadPreview(
        JSON.stringify({
          recipient: "sales@example.org",
          subject: "Pricing comparison request",
          authorization: "Bearer sk-live-secret-hidden",
          password: "never-shown-value",
          includeQuote: true
        })
      ),
      createdAt: Date.now()
    };

    const timer = setTimeout(() => {
      if (this.pending.has(id)) {
        this.pending.delete(id);
        this.onStateChanged?.();
      }
    }, this.timeoutMs);

    this.pending.set(id, { card, resolve: () => undefined, timer });
    this.onCardCreated?.(card);
    this.onStateChanged?.();
    return card;
  }

  public resolveDecision(id: string, decision: ApprovalDecision): boolean {
    const entry = this.pending.get(id);
    if (!entry) return false;
    clearTimeout(entry.timer);
    this.pending.delete(id);

    if (decision === "always-site") {
      this.allowlistedOrigins.add(entry.card.origin);
      entry.resolve(true);
    } else if (decision === "allow-once") {
      entry.resolve(true);
    } else {
      entry.resolve(false);
    }
    this.onStateChanged?.();
    return true;
  }

  public cancelTab(tabId: string): number {
    let cancelled = 0;
    for (const [id, entry] of Array.from(this.pending.entries())) {
      if (entry.card.tabId === tabId) {
        clearTimeout(entry.timer);
        this.pending.delete(id);
        entry.resolve(false);
        cancelled += 1;
      }
    }
    if (cancelled > 0) this.onStateChanged?.();
    return cancelled;
  }

  public disposeAll(): void {
    for (const entry of this.pending.values()) {
      clearTimeout(entry.timer);
      entry.resolve(false);
    }
    this.pending.clear();
  }
}
