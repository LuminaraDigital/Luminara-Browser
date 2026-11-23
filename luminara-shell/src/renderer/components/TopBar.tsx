import React, { useEffect, useRef, useState } from "react";
import type { SearchEngine, ShieldStatus, StageMode, TabRecord } from "../../shared/types";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  CloseIcon,
  MaximizeIcon,
  MinimizeIcon,
  PanelRightIcon,
  RecordIcon,
  ReloadIcon,
  RestoreIcon,
  SearchIcon,
  ShieldIcon,
  SplitIcon,
  TableIcon
} from "./Icons";

interface TopBarProps {
  activeTab: TabRecord | null;
  stageMode: StageMode;
  searchEngine: SearchEngine;
  shield: ShieldStatus;
  shieldStripOpen: boolean;
  onToggleShieldStrip: () => void;
  teachingActive: boolean;
  onToggleTeach: () => void;
  onOpenLens: () => void;
  splitActive: boolean;
  onToggleSplit: () => void;
  drawerOpen: boolean;
  onToggleDrawer: () => void;
  windowMaximized: boolean;
  onNavigate: (input: string) => void;
  onNavAction: (action: "back" | "forward" | "reload" | "stop") => void;
  onWindowControl: (action: "minimize" | "maximize" | "close") => void;
  omniboxRef: React.RefObject<HTMLInputElement | null>;
}

const ENGINE_LABELS: Record<SearchEngine, string> = {
  duckduckgo: "DDG",
  kagi: "Kagi",
  brave: "Brave",
  google: "Google"
};

export function TopBar(props: TopBarProps): React.JSX.Element {
  const [addressValue, setAddressValue] = useState("");
  const [focused, setFocused] = useState(false);
  const justSubmittedRef = useRef(false);

  useEffect(() => {
    if (!focused && !justSubmittedRef.current) {
      setAddressValue(props.stageMode === "web" && props.activeTab ? props.activeTab.url : "");
    }
    justSubmittedRef.current = false;
  }, [props.activeTab?.url, props.activeTab?.id, props.stageMode, focused]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = addressValue.trim();
    if (!trimmed) return;
    justSubmittedRef.current = true;
    props.onNavigate(trimmed);
    props.omniboxRef.current?.blur();
  };

  return (
    <header className="topbar">
      <div className="topbar-group">
        <button
          type="button"
          className="rail-icon-btn"
          title="Back (Alt+Left)"
          aria-label="Back"
          disabled={!props.activeTab?.canGoBack || props.stageMode !== "web"}
          onClick={() => props.onNavAction("back")}
        >
          <ChevronLeftIcon size={16} />
        </button>
        <button
          type="button"
          className="rail-icon-btn"
          title="Forward (Alt+Right)"
          aria-label="Forward"
          disabled={!props.activeTab?.canGoForward || props.stageMode !== "web"}
          onClick={() => props.onNavAction("forward")}
        >
          <ChevronRightIcon size={16} />
        </button>
        <button
          type="button"
          className="rail-icon-btn"
          title={props.activeTab?.loading ? "Stop loading" : "Reload (Ctrl+R)"}
          aria-label={props.activeTab?.loading ? "Stop" : "Reload"}
          disabled={!props.activeTab || props.stageMode !== "web"}
          onClick={() => props.onNavAction(props.activeTab?.loading ? "stop" : "reload")}
        >
          {props.activeTab?.loading ? <CloseIcon size={14} /> : <ReloadIcon size={15} />}
        </button>
      </div>

      <form className="omnibox-form" onSubmit={handleSubmit}>
        <SearchIcon size={14} color="var(--ink-muted)" />
        <input
          ref={props.omniboxRef}
          className={`omnibox-input ${addressValue.startsWith("http") ? "mono" : ""}`}
          placeholder={`Search ${ENGINE_LABELS[props.searchEngine]} or enter a website…`}
          value={addressValue}
          onFocus={(e) => {
            setFocused(true);
            e.currentTarget.select();
          }}
          onBlur={() => setFocused(false)}
          onChange={(e) => setAddressValue(e.target.value)}
          aria-label="Search or enter website address"
        />
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-muted)" }}>
          {ENGINE_LABELS[props.searchEngine]}
        </span>
      </form>

      <div className="topbar-group">
        <button
          type="button"
          className={`topbar-pill ${props.shield.activeDomainPaused ? "warn" : props.shieldStripOpen ? "active" : ""}`}
          onClick={props.onToggleShieldStrip}
          title="Privacy Shield v3 — click to inspect or pause for this site"
        >
          <ShieldIcon size={14} />
          <span className="mono">{props.shield.activeTabBlocked}</span>
        </button>

        <button
          type="button"
          className={`topbar-pill ${props.teachingActive ? "warn" : ""}`}
          onClick={props.onToggleTeach}
          disabled={!props.activeTab || props.stageMode !== "web"}
          title="Teach-It-Once Skill Recorder (never records passwords)"
        >
          <RecordIcon size={13} color={props.teachingActive ? "var(--status-danger)" : undefined} />
          <span>{props.teachingActive ? "Recording" : "Teach"}</span>
        </button>

        <button
          type="button"
          className={`topbar-pill ${props.stageMode === "lens" ? "active" : ""}`}
          onClick={props.onOpenLens}
          title="Live Lens — compare all open tabs in this Space"
        >
          <TableIcon size={14} />
          <span>Lens</span>
        </button>

        <button
          type="button"
          className={`topbar-pill ${props.splitActive ? "active" : ""}`}
          onClick={props.onToggleSplit}
          disabled={!props.activeTab}
          title="Toggle native side-by-side Split View"
        >
          <SplitIcon size={14} />
          <span>Split</span>
        </button>

        <button
          type="button"
          className={`topbar-pill ${props.drawerOpen ? "active" : ""}`}
          onClick={props.onToggleDrawer}
          title="Toggle Team Drawer (Ctrl+Shift+B)"
        >
          <PanelRightIcon size={14} />
          <span>Team</span>
        </button>
      </div>

      <div className="win-controls">
        <button
          type="button"
          className="win-btn"
          aria-label="Minimize window"
          onClick={() => props.onWindowControl("minimize")}
        >
          <MinimizeIcon size={14} />
        </button>
        <button
          type="button"
          className="win-btn"
          aria-label={props.windowMaximized ? "Restore window" : "Maximize window"}
          title={props.windowMaximized ? "Restore" : "Maximize"}
          onClick={() => props.onWindowControl("maximize")}
        >
          {props.windowMaximized ? <RestoreIcon size={13} /> : <MaximizeIcon size={13} />}
        </button>
        <button
          type="button"
          className="win-btn close"
          aria-label="Close window"
          onClick={() => props.onWindowControl("close")}
        >
          <CloseIcon size={14} />
        </button>
      </div>
    </header>
  );
}
