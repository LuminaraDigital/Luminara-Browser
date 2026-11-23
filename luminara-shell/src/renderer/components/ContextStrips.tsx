import React from "react";
import type { CoPresenceState, ShieldStatus } from "../../shared/types";
import { CloseIcon, SearchIcon, ShieldIcon } from "./Icons";

export function ShieldStrip(props: {
  shield: ShieldStatus;
  pendingCount: number;
  onToggleDomain: (domain: string) => void;
  onOpenInbox: () => void;
}): React.JSX.Element {
  return (
    <div className="context-strip">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <ShieldIcon size={14} color="var(--accent-brand)" />
        <span>
          Privacy Shield v3 blocked{" "}
          <strong className="mono">{props.shield.activeTabBlocked}</strong> on this tab (
          <strong className="mono">{props.shield.totalBlocked}</strong> total)
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {props.shield.activeDomain && (
          <button
            type="button"
            className="btn-ghost"
            style={{ padding: "3px 10px" }}
            onClick={() => props.onToggleDomain(props.shield.activeDomain)}
          >
            {props.shield.activeDomainPaused
              ? `Resume shield on ${props.shield.activeDomain}`
              : `Pause shield on ${props.shield.activeDomain}`}
          </button>
        )}
        <button type="button" className="btn-ghost" style={{ padding: "3px 10px" }} onClick={props.onOpenInbox}>
          Firewall Inbox ({props.pendingCount})
        </button>
      </div>
    </div>
  );
}

export function FindStrip(props: {
  query: string;
  onQueryChange: (val: string) => void;
  onFind: (forward: boolean) => void;
  onClose: () => void;
}): React.JSX.Element {
  return (
    <form
      className="context-strip"
      onSubmit={(e) => {
        e.preventDefault();
        props.onFind(true);
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1 }}>
        <SearchIcon size={14} color="var(--accent-brand)" />
        <input
          className="field-input"
          style={{ padding: "3px 8px", fontSize: 12, width: 220 }}
          placeholder="Find in page…"
          value={props.query}
          onChange={(e) => props.onQueryChange(e.target.value)}
          autoFocus
        />
        <button type="button" className="btn-ghost" style={{ padding: "3px 9px" }} onClick={() => props.onFind(false)}>
          Prev
        </button>
        <button type="submit" className="btn-ghost" style={{ padding: "3px 9px" }}>
          Next
        </button>
      </div>
      <button type="button" className="rail-icon-btn" aria-label="Close find bar" onClick={props.onClose}>
        <CloseIcon size={14} />
      </button>
    </form>
  );
}

export function TeachStrip(props: {
  stepCount: number;
  skillName: string;
  onSkillNameChange: (val: string) => void;
  onSave: (e: React.FormEvent) => void;
}): React.JSX.Element {
  return (
    <form className="context-strip" onSubmit={props.onSave}>
      <span style={{ color: "var(--status-warn)", fontWeight: 600 }}>
        Teaching mode active · {props.stepCount} steps captured (passwords ignored)
      </span>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <input
          className="field-input"
          style={{ padding: "3px 8px", fontSize: 12, width: 170 }}
          placeholder="Name this skill…"
          value={props.skillName}
          onChange={(e) => props.onSkillNameChange(e.target.value)}
        />
        <button
          type="submit"
          className="btn-primary"
          style={{ padding: "4px 10px" }}
          disabled={props.stepCount === 0}
        >
          Save skill
        </button>
      </div>
    </form>
  );
}

export function CoPresenceBar(props: {
  coPresence: CoPresenceState;
  toast: string;
  onTakeWheel: () => void;
}): React.JSX.Element | null {
  if (!props.coPresence.active && !props.toast) return null;
  return (
    <div className="copresence-bar">
      {props.coPresence.active ? (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="color-dot" style={{ background: props.coPresence.botColor }} />
            <span>
              <strong>{props.coPresence.botName}</strong> · {props.coPresence.activity}
            </span>
          </div>
          <button type="button" className="btn-ghost" style={{ padding: "3px 10px" }} onClick={props.onTakeWheel}>
            Take wheel [Esc]
          </button>
        </>
      ) : (
        <span style={{ color: "var(--ink-secondary)" }}>{props.toast}</span>
      )}
    </div>
  );
}
