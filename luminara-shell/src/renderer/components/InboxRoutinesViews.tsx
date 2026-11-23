import React, { useState } from "react";
import type {
  ApprovalCard,
  ApprovalDecision,
  RoutineItem,
  Space,
  WebSkill
} from "../../shared/types";
import { ClockIcon, PlayIcon, ShieldIcon } from "./Icons";

export interface InboxViewProps {
  pendingApprovals: ApprovalCard[];
  allowlistedOrigins: string[];
  firewallAlwaysOn: boolean;
  onResolveApproval: (id: string, decision: ApprovalDecision) => void;
  onRevokeOrigin: (origin: string) => void;
  onToggleFirewallAlways: (enabled: boolean) => void;
  onTriggerDemoApproval: () => void;
}

export function InboxView(props: InboxViewProps): React.JSX.Element {
  const [expandedWhy, setExpandedWhy] = useState<Record<string, boolean>>({});

  return (
    <div className="stage-scroll">
      <div className="stage-wide">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
          <div>
            <span className="kicker">Network Mutation Firewall</span>
            <h2 className="section-heading">Approval Inbox</h2>
            <p style={{ color: "var(--ink-secondary)", marginTop: 4 }}>
              External writes (POST, PUT, PATCH, DELETE) pause here until you approve them. Passwords and auth tokens are always redacted.
            </p>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <label className="pill" style={{ cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={props.firewallAlwaysOn}
                onChange={(e) => props.onToggleFirewallAlways(e.target.checked)}
              />
              <span>Guard all external writes</span>
            </label>
            <button type="button" className="btn-ghost" onClick={props.onTriggerDemoApproval}>
              Test Approval Card
            </button>
          </div>
        </div>

        {props.pendingApprovals.length === 0 ? (
          <div className="studio-card" style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <ShieldIcon size={20} color="var(--accent-brand)" />
            <div>
              <div style={{ fontWeight: 600 }}>All clear — nothing waiting for approval</div>
              <div style={{ fontSize: 12.5, color: "var(--ink-secondary)" }}>
                When a Bot (or any page while Guard All is enabled) attempts to submit or delete data on an outside site, its Approval Card appears right here.
              </div>
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {props.pendingApprovals.map((card) => (
              <article key={card.id} className="approval-card">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className="color-dot" style={{ background: card.botColor }} />
                    <span style={{ fontWeight: 600 }}>{card.title}</span>
                  </div>
                  <span className="pill mono">
                    {card.method} · {card.domain}
                  </span>
                </div>

                <div className="diff-box mono">{card.diffPreview}</div>

                <div>
                  <button
                    type="button"
                    className="btn-ghost"
                    style={{ fontSize: 11.5, padding: "4px 9px" }}
                    onClick={() =>
                      setExpandedWhy((prev) => ({ ...prev, [card.id]: !prev[card.id] }))
                    }
                  >
                    {expandedWhy[card.id] ? "Hide policy explanation" : "Why am I asked?"}
                  </button>
                  {expandedWhy[card.id] && (
                    <p style={{ marginTop: 8, fontSize: 12.5, color: "var(--ink-secondary)" }}>
                      {card.why}
                    </p>
                  )}
                </div>

                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button type="button" className="btn-danger" onClick={() => props.onResolveApproval(card.id, "deny")}>
                    Deny
                  </button>
                  <button type="button" className="btn-primary" onClick={() => props.onResolveApproval(card.id, "allow-once")}>
                    Allow once
                  </button>
                  <button type="button" className="btn-ghost" onClick={() => props.onResolveApproval(card.id, "always-site")}>
                    Always allow for {card.domain}
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}

        {props.allowlistedOrigins.length > 0 && (
          <section className="studio-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <span className="kicker">Trusted Sites (Always Allowed)</span>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {props.allowlistedOrigins.map((origin) => (
                <span key={origin} className="pill mono">
                  <span>{origin}</span>
                  <button
                    type="button"
                    style={{ color: "var(--status-danger)", fontWeight: 700, padding: "0 3px" }}
                    onClick={() => props.onRevokeOrigin(origin)}
                    title="Revoke trust"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

export interface RoutinesViewProps {
  activeSpace: Space;
  routines: RoutineItem[];
  skills: WebSkill[];
  onCreateRoutine: (item: Omit<RoutineItem, "id" | "lastRunAt" | "lastSummary">) => void;
  onToggleRoutine: (id: string) => void;
  onRunRoutine: (id: string) => Promise<void>;
  onDeleteRoutine: (id: string) => void;
  onReplaySkill: (skillId: string) => void;
  onDeleteSkill: (skillId: string) => void;
}

export function RoutinesView(props: RoutinesViewProps): React.JSX.Element {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("https://");
  const [hour, setHour] = useState(9);
  const [instruction, setInstruction] = useState("");
  const [formError, setFormError] = useState("");
  const [runningId, setRunningId] = useState<string | null>(null);

  const scheduledHours = new Set(props.routines.filter((r) => r.enabled).map((r) => r.hourOfDay));

  const handleAddRoutine = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    const trimmedName = name.trim();
    const rawUrl = url.trim();
    if (!trimmedName) {
      setFormError("Please enter a routine name.");
      return;
    }
    const normalized = /^https?:\/\//i.test(rawUrl) ? rawUrl : `https://${rawUrl}`;
    let parsed: URL;
    try {
      parsed = new URL(normalized);
    } catch {
      setFormError("Please enter a valid http:// or https:// website URL.");
      return;
    }
    if (
      (parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
      !parsed.hostname ||
      (parsed.hostname !== "localhost" && !parsed.hostname.includes("."))
    ) {
      setFormError("Please include a valid domain (for example, https://news.ycombinator.com).");
      return;
    }
    props.onCreateRoutine({
      name: trimmedName,
      spaceId: props.activeSpace.id,
      botId: "remy",
      hourOfDay: hour,
      minuteOfHour: 0,
      url: parsed.toString(),
      instruction: instruction.trim() || "Summarise the top updates on this page.",
      enabled: true
    });
    setName("");
    setUrl("https://");
    setInstruction("");
  };

  return (
    <div className="stage-scroll">
      <div className="stage-wide">
        <div>
          <span className="kicker">24-Hour Spatial Scheduler</span>
          <h2 className="section-heading">Routines & Taught Web Skills</h2>
        </div>

        <div className="timeline-bar" aria-label="24-hour routine timeline">
          {Array.from({ length: 24 }, (_, h) => (
            <div
              key={h}
              className={`timeline-slot ${scheduledHours.has(h) ? "scheduled" : ""}`}
              title={`${String(h).padStart(2, "0")}:00`}
            >
              {String(h).padStart(2, "0")}
            </div>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(290px, 1fr))", gap: 14 }}>
          {props.routines.map((routine) => (
            <article key={routine.id} className="studio-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontWeight: 600 }}>{routine.name}</span>
                <span className="pill mono">
                  <ClockIcon size={12} />
                  {String(routine.hourOfDay).padStart(2, "0")}:{String(routine.minuteOfHour).padStart(2, "0")}
                </span>
              </div>
              <div className="mono" style={{ fontSize: 11.5, color: "var(--ink-muted)" }}>
                {routine.url}
              </div>
              <p style={{ fontSize: 12.5, color: "var(--ink-secondary)" }}>{routine.lastSummary}</p>
              <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                <button
                  type="button"
                  className="btn-primary"
                  disabled={runningId === routine.id}
                  onClick={async () => {
                    setRunningId(routine.id);
                    try {
                      await props.onRunRoutine(routine.id);
                    } finally {
                      setRunningId(null);
                    }
                  }}
                >
                  <PlayIcon size={11} />
                  <span>{runningId === routine.id ? "Running…" : "Run now"}</span>
                </button>
                <button type="button" className="btn-ghost" onClick={() => props.onToggleRoutine(routine.id)}>
                  {routine.enabled ? "Pause" : "Enable"}
                </button>
                <button type="button" className="btn-ghost" onClick={() => props.onDeleteRoutine(routine.id)}>
                  Remove
                </button>
              </div>
            </article>
          ))}
        </div>

        <form className="studio-card" onSubmit={handleAddRoutine} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, alignItems: "end" }}>
          <div className="field-group">
            <label className="field-label">Routine name</label>
            <input className="field-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Daily briefing…" />
          </div>
          <div className="field-group">
            <label className="field-label">Target URL</label>
            <input className="field-input mono" value={url} onChange={(e) => setUrl(e.target.value)} />
          </div>
          <div className="field-group">
            <label className="field-label">Hour (0–23)</label>
            <input className="field-input mono" type="number" min={0} max={23} value={hour} onChange={(e) => setHour(Number(e.target.value))} />
          </div>
          <div className="field-group">
            <label className="field-label">Instruction</label>
            <input className="field-input" value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder="What should Remy check?" />
          </div>
          <button type="submit" className="btn-primary" style={{ height: 36 }}>
            Add Routine
          </button>
          {formError && (
            <div style={{ gridColumn: "1 / -1", fontSize: 12, color: "var(--status-danger)" }}>
              {formError}
            </div>
          )}
        </form>

        <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <span className="kicker">Teach-It-Once Saved Web Skills ({props.skills.length})</span>
          {props.skills.length === 0 ? (
            <div className="studio-card" style={{ color: "var(--ink-secondary)" }}>
              Click <strong>Teach</strong> in the top bar while browsing any website to record repeatable clicks and form steps (password fields are never recorded).
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12 }}>
              {props.skills.map((skill) => (
                <article key={skill.id} className="studio-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontWeight: 600 }}>{skill.name}</span>
                    <span className="pill mono">{skill.steps.length} steps</span>
                  </div>
                  <div className="mono" style={{ fontSize: 11.5, color: "var(--ink-muted)" }}>
                    {skill.domain} · ran {skill.runCount}×
                  </div>
                  <p style={{ fontSize: 12.5, color: "var(--ink-secondary)" }}>{skill.description}</p>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button type="button" className="btn-primary" onClick={() => props.onReplaySkill(skill.id)}>
                      Replay on active tab
                    </button>
                    <button type="button" className="btn-ghost" onClick={() => props.onDeleteSkill(skill.id)}>
                      Delete
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
