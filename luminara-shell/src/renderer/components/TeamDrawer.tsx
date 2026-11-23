import React, { useEffect, useRef, useState } from "react";
import type {
  ApprovalCard,
  ApprovalDecision,
  BotMode,
  BotProfile,
  ChatMessage,
  SettingsPublic,
  TabRecord
} from "../../shared/types";
import { CloseIcon, SendIcon, SettingsIcon, SparklesIcon, StopIcon } from "./Icons";

interface TeamDrawerProps {
  bots: BotProfile[];
  selectedBot: BotProfile;
  onSelectBot: (botId: string) => void;
  mode: BotMode;
  onChangeMode: (mode: BotMode) => void;
  messages: ChatMessage[];
  loading: boolean;
  errorText: string;
  activeTab: TabRecord | null;
  pendingApprovals: ApprovalCard[];
  settings: SettingsPublic;
  onSend: (prompt: string) => void;
  onAbort: () => void;
  onQuickCompare: () => void;
  onQuickWorktree: () => void;
  onQuickTeach: () => void;
  onQuickWatch: () => void;
  onResolveApproval: (id: string, decision: ApprovalDecision) => void;
  onOpenSettings: () => void;
  onClose: () => void;
}

export function TeamDrawer(props: TeamDrawerProps): React.JSX.Element {
  const [draft, setDraft] = useState("");
  const [openReceipts, setOpenReceipts] = useState<Record<string, boolean>>({});
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [props.messages.length, props.loading]);

  const submitDraft = () => {
    const text = draft.trim();
    if (!text || props.loading) return;
    setDraft("");
    props.onSend(text);
  };

  const modelBadge = props.settings.model
    ? `${props.settings.provider} · ${props.settings.model}`
    : props.settings.provider === "ollama"
      ? "Local Ollama (auto)"
      : "Connect AI model";

  return (
    <aside
      className="team-drawer"
      style={{ "--bot-tint": props.selectedBot.color } as React.CSSProperties}
      aria-label="Team assistant drawer"
    >
      <div className="drawer-header">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            <span className="color-dot" style={{ width: 10, height: 10, background: props.selectedBot.color }} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 13.5, lineHeight: 1.2 }}>
                {props.selectedBot.name}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--ink-secondary)" }}>
                {props.selectedBot.roleTitle}
              </div>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div className="segmented" role="group" aria-label="Bot execution mode">
              <button
                type="button"
                className={props.mode === "execute" ? "active" : ""}
                onClick={() => props.onChangeMode("execute")}
              >
                Execute
              </button>
              <button
                type="button"
                className={props.mode === "plan" ? "active" : ""}
                onClick={() => props.onChangeMode("plan")}
              >
                Plan
              </button>
            </div>
            <button
              type="button"
              className="rail-icon-btn"
              aria-label="Close Team Drawer"
              onClick={props.onClose}
            >
              <CloseIcon size={14} />
            </button>
          </div>
        </div>

        <div style={{ display: "flex", gap: 5, overflowX: "auto", paddingBottom: 2 }}>
          {props.bots.slice(0, 6).map((bot) => (
            <button
              key={bot.id}
              type="button"
              className={`space-pill ${bot.id === props.selectedBot.id ? "active" : ""}`}
              onClick={() => props.onSelectBot(bot.id)}
              style={{ flexShrink: 0 }}
            >
              <span className="color-dot" style={{ background: bot.color }} />
              <span>{bot.name}</span>
            </button>
          ))}
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
          <button
            type="button"
            className="pill"
            onClick={() => props.onSend("Summarise the current page with key takeaways and caveats.")}
            disabled={props.loading}
          >
            Summarize
          </button>
          <button type="button" className="pill" onClick={props.onQuickCompare}>
            Compare open tabs
          </button>
          <button type="button" className="pill" onClick={props.onQuickWorktree}>
            Parallel research
          </button>
          <button type="button" className="pill" onClick={props.onQuickTeach} disabled={!props.activeTab}>
            Teach skill
          </button>
          <button type="button" className="pill" onClick={props.onQuickWatch} disabled={!props.activeTab}>
            Watch page
          </button>
        </div>
      </div>

      <div ref={scrollRef} className="drawer-messages">
        {props.pendingApprovals.map((card) => (
          <div key={card.id} className="approval-card" style={{ padding: 12 }}>
            <div style={{ fontWeight: 600, fontSize: 12.5 }}>{card.title}</div>
            <div className="mono" style={{ fontSize: 11, color: "var(--ink-muted)" }}>
              {card.method} · {card.domain}
            </div>
            <div className="diff-box mono" style={{ fontSize: 11 }}>
              {card.diffPreview}
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <button
                type="button"
                className="btn-danger"
                style={{ padding: "5px 9px" }}
                onClick={() => props.onResolveApproval(card.id, "deny")}
              >
                Deny
              </button>
              <button
                type="button"
                className="btn-primary"
                style={{ padding: "5px 9px" }}
                onClick={() => props.onResolveApproval(card.id, "allow-once")}
              >
                Allow once
              </button>
              <button
                type="button"
                className="btn-ghost"
                style={{ padding: "5px 9px" }}
                onClick={() => props.onResolveApproval(card.id, "always-site")}
              >
                Always for site
              </button>
            </div>
          </div>
        ))}

        {props.messages.length === 0 ? (
          <div className="studio-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 600 }}>
              <SparklesIcon size={15} color={props.selectedBot.color} />
              <span>{props.selectedBot.name} is ready</span>
            </div>
            <p style={{ fontSize: 12.5, color: "var(--ink-secondary)" }}>
              {props.selectedBot.description}
            </p>
            {props.selectedBot.quickPrompts.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 5, marginTop: 4 }}>
                {props.selectedBot.quickPrompts.slice(0, 3).map((qp) => (
                  <button
                    key={qp}
                    type="button"
                    className="btn-ghost"
                    style={{ justifyContent: "flex-start", textAlign: "left" }}
                    onClick={() => props.onSend(qp)}
                  >
                    {qp}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          props.messages.map((msg) => (
            <div key={msg.id} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div className={`chat-bubble ${msg.role === "user" ? "user" : ""}`}>
                {msg.role !== "user" && (
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      marginBottom: 4,
                      fontSize: 11.5,
                      fontWeight: 600,
                      color: msg.authorColor ?? "var(--accent-brand)"
                    }}
                  >
                    <span className="color-dot" style={{ background: msg.authorColor ?? "var(--accent-brand)" }} />
                    <span>{msg.authorName}</span>
                  </div>
                )}
                <div>{msg.content}</div>
                {msg.needsModelSetup && (
                  <button
                    type="button"
                    className="btn-ghost"
                    style={{ marginTop: 8 }}
                    onClick={props.onOpenSettings}
                  >
                    <SettingsIcon size={13} />
                    <span>Connect Ollama or API key</span>
                  </button>
                )}
              </div>

              {msg.receipt && (
                <div>
                  <button
                    type="button"
                    className="pill mono"
                    style={{ fontSize: 10.5, color: "var(--ink-muted)" }}
                    onClick={() =>
                      setOpenReceipts((prev) => ({ ...prev, [msg.id]: !prev[msg.id] }))
                    }
                  >
                    <span>
                      Work receipt · {msg.receipt.durationMs}ms · {msg.receipt.tabsRead} tab
                      {msg.receipt.tabsRead === 1 ? "" : "s"} · {msg.receipt.trackersBlocked} shielded
                    </span>
                  </button>
                  {openReceipts[msg.id] && (
                    <div
                      className="mono"
                      style={{
                        marginTop: 5,
                        padding: "7px 10px",
                        borderRadius: 10,
                        background: "var(--bg-surface)",
                        border: "1px solid var(--hairline)",
                        fontSize: 11,
                        color: "var(--ink-secondary)"
                      }}
                    >
                      Engine: {msg.receipt.provider} ({msg.receipt.model}) · Mode: {msg.receipt.mode} · WebMCP tools: {msg.receipt.webMcpToolsFound}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
        )}

        {props.loading && (
          <div className="chat-bubble" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <span style={{ color: "var(--ink-secondary)" }}>
              {props.selectedBot.name} is working…
            </span>
            <button type="button" className="btn-danger" style={{ padding: "4px 9px" }} onClick={props.onAbort}>
              <StopIcon size={11} />
              <span>Stop</span>
            </button>
          </div>
        )}

        {props.errorText && (
          <div className="approval-card" style={{ borderColor: "var(--status-danger)", padding: 11 }}>
            <span style={{ fontSize: 12.5, color: "var(--status-danger)" }}>{props.errorText}</span>
          </div>
        )}
      </div>

      <div className="drawer-composer">
        <div className="composer-box">
          <textarea
            className="composer-input"
            rows={2}
            placeholder={
              props.mode === "plan"
                ? `Ask ${props.selectedBot.name} for a plan…`
                : `Message ${props.selectedBot.name}…`
            }
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submitDraft();
              }
            }}
          />
          {props.loading ? (
            <button type="button" className="btn-danger" onClick={props.onAbort} aria-label="Stop response">
              <StopIcon size={13} />
            </button>
          ) : (
            <button
              type="button"
              className="btn-primary"
              onClick={submitDraft}
              disabled={!draft.trim()}
              aria-label="Send message"
            >
              <SendIcon size={13} />
            </button>
          )}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11, color: "var(--ink-muted)" }}>
          <span>{props.activeTab ? `Reading: ${props.activeTab.title.slice(0, 24)}` : "Space context ready"}</span>
          <button
            type="button"
            className="mono"
            style={{ fontSize: 10.5, color: "var(--accent-brand)" }}
            onClick={props.onOpenSettings}
          >
            {modelBadge}
          </button>
        </div>
      </div>
    </aside>
  );
}
