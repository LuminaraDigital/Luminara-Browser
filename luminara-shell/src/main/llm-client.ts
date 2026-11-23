import type { LlmProvider } from "../shared/types";

export interface LlmCallOptions {
  provider: LlmProvider;
  model: string;
  baseUrl: string;
  ollamaHost: string;
  apiKey: string;
  systemPrompt: string;
  history: Array<{ role: "user" | "assistant"; content: string }>;
  userMessage: string;
  signal: AbortSignal;
}

const METADATA_HOSTS = new Set([
  "169.254.169.254",
  "metadata.google.internal",
  "metadata.goog",
  "100.100.100.200"
]);

export function isLoopbackHost(hostname: string): boolean {
  const h = hostname.toLowerCase();
  return h === "localhost" || h === "127.0.0.1" || h === "::1" || h === "[::1]";
}

function isPrivateLanHost(hostname: string): boolean {
  if (isLoopbackHost(hostname)) return true;
  if (/^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(hostname)) return true;
  if (/^192\.168\.\d{1,3}\.\d{1,3}$/.test(hostname)) return true;
  const m172 = /^172\.(\d{1,3})\.\d{1,3}\.\d{1,3}$/.exec(hostname);
  if (m172) {
    const second = Number(m172[1]);
    return second >= 16 && second <= 31;
  }
  return false;
}

export function validateEndpointUrl(raw: string): URL {
  const parsed = new URL(raw.trim());
  const host = parsed.hostname.toLowerCase();
  const bare = host.replace(/^\[|\]$/g, "");
  if (
    METADATA_HOSTS.has(bare) ||
    bare.startsWith("169.254.") ||
    bare.startsWith("fe80:") ||
    bare === "fd00:ec2::254"
  ) {
    throw new Error("Blocked metadata or link-local endpoint address.");
  }
  if (parsed.protocol === "https:") return parsed;
  if (parsed.protocol === "http:" && isPrivateLanHost(bare)) return parsed;
  throw new Error("Remote AI endpoints must use HTTPS (HTTP is allowed only for localhost/LAN).");
}

async function readErrorSnippet(res: Response): Promise<string> {
  try {
    const txt = (await res.text()).replace(/\s+/g, " ").trim();
    return txt ? ` — ${txt.slice(0, 180)}` : "";
  } catch {
    return "";
  }
}

function normalizeAnthropicMessages(
  history: Array<{ role: "user" | "assistant"; content: string }>,
  userMessage: string
): Array<{ role: "user" | "assistant"; content: string }> {
  const combined = [...history.slice(-6), { role: "user" as const, content: userMessage }];
  const out: Array<{ role: "user" | "assistant"; content: string }> = [];
  for (const item of combined) {
    const text = item.content.trim();
    if (!text) continue;
    if (out.length === 0 && item.role !== "user") continue;
    const prev = out[out.length - 1];
    if (prev && prev.role === item.role) {
      prev.content = `${prev.content}\n\n${text}`;
    } else {
      out.push({ role: item.role, content: text });
    }
  }
  return out.length > 0 ? out : [{ role: "user", content: userMessage }];
}

export async function detectOllamaModels(
  host = "http://127.0.0.1:11434"
): Promise<{ available: boolean; models: string[] }> {
  try {
    const base = validateEndpointUrl(host).toString().replace(/\/+$/, "");
    const res = await fetch(`${base}/api/tags`, { redirect: "error", signal: AbortSignal.timeout(1800) });
    if (!res.ok) return { available: false, models: [] };
    const data = (await res.json()) as { models?: Array<{ name?: string }> };
    return {
      available: true,
      models: (data.models ?? []).map((m) => m.name ?? "").filter(Boolean)
    };
  } catch {
    return { available: false, models: [] };
  }
}

export async function callLlmProvider(
  opts: LlmCallOptions
): Promise<{ text: string; provider: string; model: string } | null> {
  if (opts.provider === "ollama") {
    const base = validateEndpointUrl(opts.ollamaHost || "http://127.0.0.1:11434")
      .toString()
      .replace(/\/+$/, "");
    let model = opts.model.trim();
    if (!model) {
      const detected = await detectOllamaModels(base);
      model = detected.models[0] || "";
      if (!detected.available || !model) return null;
    }
    const res = await fetch(`${base}/api/chat`, {
      method: "POST",
      redirect: "error",
      headers: { "Content-Type": "application/json" },
      signal: opts.signal,
      body: JSON.stringify({
        model,
        stream: false,
        messages: [
          { role: "system", content: opts.systemPrompt },
          ...opts.history.slice(-6),
          { role: "user", content: opts.userMessage }
        ]
      })
    });
    if (!res.ok) throw new Error(`Ollama HTTP ${res.status}${await readErrorSnippet(res)}`);
    const json = (await res.json()) as { message?: { content?: string } };
    return { text: json.message?.content?.trim() || "(Empty reply)", provider: "Ollama (local)", model };
  }

  if (opts.provider === "anthropic") {
    if (!opts.apiKey) return null;
    const model = opts.model || "claude-sonnet-4-5";
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      redirect: "error",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": opts.apiKey,
        "anthropic-version": "2023-06-01"
      },
      signal: opts.signal,
      body: JSON.stringify({
        model,
        max_tokens: 900,
        system: opts.systemPrompt,
        messages: normalizeAnthropicMessages(opts.history, opts.userMessage)
      })
    });
    if (!res.ok) throw new Error(`Anthropic HTTP ${res.status}${await readErrorSnippet(res)}`);
    const json = (await res.json()) as { content?: Array<{ type?: string; text?: string }> };
    const text = (json.content ?? [])
      .filter((b) => !b.type || b.type === "text")
      .map((b) => b.text ?? "")
      .join("")
      .trim();
    return { text: text || "(Empty reply)", provider: "Anthropic", model };
  }

  if (opts.provider === "gemini") {
    if (!opts.apiKey) return null;
    const model = opts.model || "gemini-2.0-flash";
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`;
    const contents = [
      ...opts.history.slice(-6).map((m) => ({
        role: m.role === "assistant" ? "model" : "user",
        parts: [{ text: m.content }]
      })),
      { role: "user", parts: [{ text: opts.userMessage }] }
    ];
    const res = await fetch(url, {
      method: "POST",
      redirect: "error",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": opts.apiKey
      },
      signal: opts.signal,
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: opts.systemPrompt }] },
        contents
      })
    });
    if (!res.ok) throw new Error(`Gemini HTTP ${res.status}${await readErrorSnippet(res)}`);
    const json = (await res.json()) as {
      candidates?: Array<{ content?: { parts?: Array<{ text?: string; thought?: boolean }> } }>;
    };
    const parts = json.candidates?.[0]?.content?.parts ?? [];
    const text = parts
      .filter((p) => !p.thought && typeof p.text === "string")
      .map((p) => p.text ?? "")
      .join("")
      .trim();
    return { text: text || "(Empty reply)", provider: "Gemini", model };
  }

  let endpoint = "https://api.openai.com/v1/chat/completions";
  if (opts.provider === "openrouter") {
    endpoint = "https://openrouter.ai/api/v1/chat/completions";
  } else if (opts.provider === "custom") {
    if (!opts.baseUrl.trim()) return null;
    const parsedBase = validateEndpointUrl(opts.baseUrl);
    endpoint = `${parsedBase.toString().replace(/\/+$/, "")}/chat/completions`;
    if (!opts.apiKey && !isLoopbackHost(parsedBase.hostname)) return null;
  }

  if (opts.provider !== "custom" && !opts.apiKey) return null;
  const model =
    opts.model || (opts.provider === "openrouter" ? "anthropic/claude-3.5-sonnet" : "gpt-4o-mini");

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.apiKey) headers.Authorization = `Bearer ${opts.apiKey}`;

  const res = await fetch(endpoint, {
    method: "POST",
    redirect: "error",
    headers,
    signal: opts.signal,
    body: JSON.stringify({
      model,
      messages: [
        { role: "system", content: opts.systemPrompt },
        ...opts.history.slice(-6),
        { role: "user", content: opts.userMessage }
      ]
    })
  });
  if (!res.ok) throw new Error(`${opts.provider} HTTP ${res.status}${await readErrorSnippet(res)}`);
  const json = (await res.json()) as { choices?: Array<{ message?: { content?: string } }> };
  return {
    text: json.choices?.[0]?.message?.content?.trim() || "(Empty reply)",
    provider: opts.provider,
    model
  };
}
