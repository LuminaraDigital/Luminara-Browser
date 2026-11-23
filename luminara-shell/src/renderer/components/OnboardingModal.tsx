import React, { useEffect, useState } from "react";
import type {
  LlmProvider,
  SearchEngine,
  SettingsPublic,
  SettingsUpdate,
  ShieldStatus,
  ThemeMode
} from "../../shared/types";
import { CloseIcon, LuminaraMark, ReloadIcon } from "./Icons";

interface OnboardingModalProps {
  open: boolean;
  settings: SettingsPublic;
  shield: ShieldStatus;
  onSave: (patch: SettingsUpdate) => Promise<void>;
  onDetectOllama: (host?: string) => Promise<{ available: boolean; models: string[] }>;
  onClose: () => void;
}

const PROVIDERS: Array<{ id: LlmProvider; label: string; defaultModel: string }> = [
  { id: "ollama", label: "Local Ollama", defaultModel: "" },
  { id: "openrouter", label: "OpenRouter", defaultModel: "anthropic/claude-3.5-sonnet" },
  { id: "gemini", label: "Google Gemini", defaultModel: "gemini-2.0-flash" },
  { id: "anthropic", label: "Anthropic Claude", defaultModel: "claude-sonnet-4-5" },
  { id: "openai", label: "OpenAI", defaultModel: "gpt-4o-mini" },
  { id: "custom", label: "Custom OpenAI-Compatible", defaultModel: "" }
];

export function OnboardingModal(props: OnboardingModalProps): React.JSX.Element | null {
  const [theme, setTheme] = useState<ThemeMode>(props.settings.theme);
  const [searchEngine, setSearchEngine] = useState<SearchEngine>(props.settings.searchEngine);
  const [provider, setProvider] = useState<LlmProvider>(props.settings.provider);
  const [model, setModel] = useState(props.settings.model);
  const [baseUrl, setBaseUrl] = useState(props.settings.baseUrl);
  const [ollamaHost, setOllamaHost] = useState(props.settings.ollamaHost);
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [firewallAlwaysOn, setFirewallAlwaysOn] = useState(props.settings.firewallAlwaysOn);
  const [ollamaStatus, setOllamaStatus] = useState<{
    checked: boolean;
    available: boolean;
    models: string[];
  }>({ checked: false, available: false, models: [] });
  const [saving, setSaving] = useState(false);

  const refreshOllama = async (hostToProbe?: string) => {
    const res = await props.onDetectOllama(hostToProbe ?? ollamaHost);
    setOllamaStatus({ checked: true, available: res.available, models: res.models });
    if (res.available && res.models.length > 0 && !model && provider === "ollama") {
      setModel(res.models[0]);
    }
  };

  useEffect(() => {
    if (!props.open) return;
    setTheme(props.settings.theme);
    setSearchEngine(props.settings.searchEngine);
    setProvider(props.settings.provider);
    setModel(props.settings.model);
    setBaseUrl(props.settings.baseUrl);
    setOllamaHost(props.settings.ollamaHost);
    setFirewallAlwaysOn(props.settings.firewallAlwaysOn);
    setApiKey("");
    setClearApiKey(false);
    void refreshOllama(props.settings.ollamaHost);
  }, [props.open]);

  useEffect(() => {
    if (!props.open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") props.onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [props.open, props.onClose]);

  if (!props.open) return null;

  const handleProviderChange = (next: LlmProvider) => {
    setProvider(next);
    if (next === "ollama") {
      setModel(ollamaStatus.models[0] ?? "");
    } else if (next === "custom") {
      setModel("");
    } else {
      setModel(PROVIDERS.find((p) => p.id === next)?.defaultModel ?? "");
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await props.onSave({
        theme,
        searchEngine,
        provider,
        model,
        baseUrl,
        ollamaHost,
        apiKey: !clearApiKey && apiKey.trim() ? apiKey.trim() : undefined,
        clearApiKey,
        firewallAlwaysOn,
        onboardingComplete: true
      });
      props.onClose();
    } finally {
      setSaving(false);
    }
  };

  const showKeySaved = props.settings.hasApiKey && !clearApiKey;

  return (
    <div className="modal-backdrop" onClick={props.onClose} role="dialog" aria-modal="true" aria-label="Setup and preferences">
      <form
        className="modal-card"
        style={{ padding: 22, display: "flex", flexDirection: "column", gap: 16 }}
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <LuminaraMark size={26} />
            <div>
              <h2 className="section-heading">Luminara v4 Studio Setup</h2>
              <p style={{ fontSize: 12.5, color: "var(--ink-secondary)" }}>
                Personalise theme, search, local Ollama or encrypted cloud AI keys.
              </p>
            </div>
          </div>
          <button type="button" className="rail-icon-btn" aria-label="Close setup" onClick={props.onClose}>
            <CloseIcon size={16} />
          </button>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div className="field-group">
            <label className="field-label">Appearance</label>
            <select className="field-input" value={theme} onChange={(e) => setTheme(e.target.value as ThemeMode)}>
              <option value="system">System adaptive</option>
              <option value="light">Warm Alabaster (Light)</option>
              <option value="dark">Deep Obsidian (Dark)</option>
            </select>
          </div>
          <div className="field-group">
            <label className="field-label">Default Search Engine</label>
            <select className="field-input" value={searchEngine} onChange={(e) => setSearchEngine(e.target.value as SearchEngine)}>
              <option value="duckduckgo">DuckDuckGo</option>
              <option value="kagi">Kagi</option>
              <option value="brave">Brave Search</option>
              <option value="google">Google</option>
            </select>
          </div>
        </div>

        <div className="studio-card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span className="kicker">AI Model Provider (Encrypted via OS Vault)</span>
            <button type="button" className="btn-ghost" style={{ padding: "4px 8px" }} onClick={() => void refreshOllama()}>
              <ReloadIcon size={12} />
              <span>Scan Ollama</span>
            </button>
          </div>

          <div className="field-group">
            <label className="field-label">Provider</label>
            <select
              className="field-input"
              value={provider}
              onChange={(e) => handleProviderChange(e.target.value as LlmProvider)}
            >
              {PROVIDERS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>

          {provider === "ollama" ? (
            <>
              <div className="field-group">
                <label className="field-label">Local Ollama Host</label>
                <input className="field-input mono" value={ollamaHost} onChange={(e) => setOllamaHost(e.target.value)} />
              </div>
              {ollamaStatus.available && ollamaStatus.models.length > 0 ? (
                <div className="field-group">
                  <label className="field-label">Detected Local Models</label>
                  <select className="field-input mono" value={model} onChange={(e) => setModel(e.target.value)}>
                    {ollamaStatus.models.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </div>
              ) : (
                <p style={{ fontSize: 12, color: "var(--ink-secondary)" }}>
                  {ollamaStatus.checked
                    ? "No running Ollama server detected yet. You can still browse & extract pages locally, or pick a cloud provider above."
                    : "Checking local Ollama…"}
                </p>
              )}
            </>
          ) : (
            <>
              <div className="field-group">
                <label className="field-label">Model ID</label>
                <input
                  className="field-input mono"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="e.g. claude-sonnet-4-5 or gemini-2.0-flash"
                />
              </div>
              {provider === "custom" && (
                <div className="field-group">
                  <label className="field-label">Base URL (OpenAI-compatible HTTPS or localhost)</label>
                  <input
                    className="field-input mono"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder="https://api.example.com/v1"
                  />
                </div>
              )}
              <div className="field-group">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <label className="field-label">
                    API Key{" "}
                    {showKeySaved && (
                      <span className="mono" style={{ color: "var(--accent-brand)" }}>
                        ({props.settings.encryptionAvailable ? "Encrypted" : "Session-only"}: {props.settings.apiKeyHint})
                      </span>
                    )}
                  </label>
                  {showKeySaved && (
                    <button
                      type="button"
                      className="btn-ghost"
                      style={{ padding: "2px 8px", fontSize: 11, color: "var(--status-danger)" }}
                      onClick={() => {
                        setClearApiKey(true);
                        setApiKey("");
                      }}
                    >
                      Clear key
                    </button>
                  )}
                </div>
                <input
                  type="password"
                  className="field-input mono"
                  value={apiKey}
                  onChange={(e) => {
                    setApiKey(e.target.value);
                    if (e.target.value) setClearApiKey(false);
                  }}
                  placeholder={
                    showKeySaved
                      ? "Leave blank to keep existing key"
                      : props.settings.encryptionAvailable
                        ? "Paste key (encrypted via OS Vault)"
                        : "Paste key (kept in RAM for this session only)"
                  }
                />
              </div>
            </>
          )}
        </div>

        <label className="studio-card" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, cursor: "pointer" }}>
          <div>
            <div style={{ fontWeight: 600, fontSize: 13 }}>Guard all external web mutations</div>
            <div style={{ fontSize: 12, color: "var(--ink-secondary)" }}>
              Privacy Shield has blocked {props.shield.totalBlocked} trackers this session. Enable this to pause every external POST/PUT/DELETE, not just Bot actions.
            </div>
          </div>
          <input type="checkbox" checked={firewallAlwaysOn} onChange={(e) => setFirewallAlwaysOn(e.target.checked)} />
        </label>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button
            type="button"
            className="btn-ghost"
            onClick={async () => {
              if (!props.settings.onboardingComplete) {
                await props.onSave({ onboardingComplete: true });
              }
              props.onClose();
            }}
          >
            Skip for now
          </button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? "Saving…" : "Save & Start Browsing"}
          </button>
        </div>
      </form>
    </div>
  );
}
