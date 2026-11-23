import React, { useState } from "react";
import type { BotProfile, Space, StageMode, TabRecord, ThemeMode } from "../../shared/types";
import {
  ClockIcon,
  CloseIcon,
  HomeIcon,
  InboxIcon,
  LuminaraMark,
  PanelLeftIcon,
  PlusIcon,
  SearchIcon,
  SettingsIcon,
  SnowflakeIcon,
  SplitIcon,
  TableIcon
} from "./Icons";

interface SpaceRailProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
  stageMode: StageMode;
  onSelectStage: (mode: StageMode) => void;
  spaces: Space[];
  activeSpaceId: string;
  onSwitchSpace: (spaceId: string) => void;
  onCreateSpace: (name: string, accent: string) => void;
  tabs: TabRecord[];
  activeTabId: string | null;
  splitTabId: string | null;
  onActivateTab: (tabId: string) => void;
  onNewTab: () => void;
  onHibernateTab: (tabId: string) => void;
  onSplitTab: (tabId: string) => void;
  onCloseTab: (tabId: string) => void;
  bots: BotProfile[];
  selectedBotId: string;
  onSelectBot: (botId: string) => void;
  pendingApprovalCount: number;
  theme: ThemeMode;
  onCycleTheme: () => void;
  onOpenPalette: () => void;
  onOpenSettings: () => void;
}

const SPACE_ACCENTS = ["#16A095", "#2E7CF6", "#7C4DFF", "#C47F17", "#199473"];

export function SpaceRail(props: SpaceRailProps): React.JSX.Element {
  const [creatingSpace, setCreatingSpace] = useState(false);
  const [newSpaceName, setNewSpaceName] = useState("");
  const [accentIdx, setAccentIdx] = useState(0);
  const [brokenFavicons, setBrokenFavicons] = useState<Record<string, boolean>>({});

  const spaceTabs = props.tabs.filter((t) => t.spaceId === props.activeSpaceId);

  const handleCreateSpace = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newSpaceName.trim();
    if (!trimmed) return;
    props.onCreateSpace(trimmed, SPACE_ACCENTS[accentIdx % SPACE_ACCENTS.length]);
    setNewSpaceName("");
    setCreatingSpace(false);
    setAccentIdx((i) => i + 1);
  };

  if (props.collapsed) {
    return (
      <aside className="space-rail collapsed" aria-label="Spaces and navigation">
        <button
          type="button"
          className="rail-icon-btn"
          title="Expand sidebar"
          aria-label="Expand sidebar"
          onClick={props.onToggleCollapse}
        >
          <LuminaraMark size={22} />
        </button>
        <button
          type="button"
          className="rail-icon-btn"
          title="Search & commands (Ctrl+K)"
          aria-label="Command palette"
          onClick={props.onOpenPalette}
        >
          <SearchIcon size={16} />
        </button>
        <button
          type="button"
          className="rail-icon-btn"
          title="Home"
          aria-label="Home"
          onClick={() => props.onSelectStage("home")}
        >
          <HomeIcon size={16} />
        </button>
        <button
          type="button"
          className="rail-icon-btn"
          title={`Inbox (${props.pendingApprovalCount})`}
          aria-label="Inbox"
          onClick={() => props.onSelectStage("inbox")}
        >
          <InboxIcon size={16} color={props.pendingApprovalCount > 0 ? "var(--status-warn)" : undefined} />
        </button>
        <button
          type="button"
          className="rail-icon-btn"
          title="Routines"
          aria-label="Routines"
          onClick={() => props.onSelectStage("routines")}
        >
          <ClockIcon size={16} />
        </button>
        <button
          type="button"
          className="rail-icon-btn"
          title="Live Lens"
          aria-label="Live Lens"
          onClick={() => props.onSelectStage("lens")}
        >
          <TableIcon size={16} />
        </button>
        <div style={{ flex: 1 }} />
        <button
          type="button"
          className="rail-icon-btn"
          title="Settings & AI Setup"
          aria-label="Settings"
          onClick={props.onOpenSettings}
        >
          <SettingsIcon size={16} />
        </button>
      </aside>
    );
  }

  return (
    <aside className="space-rail" aria-label="Spaces, tabs, and team">
      <div className="rail-brand">
        <div className="rail-brand-left">
          <LuminaraMark size={22} />
          <span className="rail-brand-title">Luminara</span>
        </div>
        <button
          type="button"
          className="rail-icon-btn"
          title="Collapse rail"
          aria-label="Collapse rail"
          onClick={props.onToggleCollapse}
        >
          <PanelLeftIcon size={15} />
        </button>
      </div>

      <button type="button" className="rail-search-btn" onClick={props.onOpenPalette}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
          <SearchIcon size={14} />
          <span>Jump or search…</span>
        </span>
        <span className="mono" style={{ opacity: 0.7 }}>
          Ctrl+K
        </span>
      </button>

      <nav className="rail-nav-group" aria-label="Primary views">
        <button
          type="button"
          className={`rail-item ${props.stageMode === "home" ? "active" : ""}`}
          onClick={() => props.onSelectStage("home")}
        >
          <span className="rail-item-main">
            <HomeIcon size={15} />
            <span className="rail-item-label">Home</span>
          </span>
        </button>
        <button
          type="button"
          className={`rail-item ${props.stageMode === "inbox" ? "active" : ""}`}
          onClick={() => props.onSelectStage("inbox")}
        >
          <span className="rail-item-main">
            <InboxIcon size={15} />
            <span className="rail-item-label">Inbox</span>
          </span>
          {props.pendingApprovalCount > 0 && (
            <span className="rail-badge">{props.pendingApprovalCount}</span>
          )}
        </button>
        <button
          type="button"
          className={`rail-item ${props.stageMode === "routines" ? "active" : ""}`}
          onClick={() => props.onSelectStage("routines")}
        >
          <span className="rail-item-main">
            <ClockIcon size={15} />
            <span className="rail-item-label">Routines & Skills</span>
          </span>
        </button>
        <button
          type="button"
          className={`rail-item ${props.stageMode === "lens" ? "active" : ""}`}
          onClick={() => props.onSelectStage("lens")}
        >
          <span className="rail-item-main">
            <TableIcon size={15} />
            <span className="rail-item-label">Live Lens</span>
          </span>
        </button>
      </nav>

      <div className="rail-scroll">
        <section>
          <div className="rail-section-head">
            <span className="kicker">Spaces</span>
            <button
              type="button"
              className="tab-mini-btn"
              title="New isolated Space"
              aria-label="New Space"
              onClick={() => setCreatingSpace((v) => !v)}
            >
              <PlusIcon size={14} />
            </button>
          </div>
          <div className="space-pills">
            {props.spaces.map((space) => (
              <button
                key={space.id}
                type="button"
                className={`space-pill ${space.id === props.activeSpaceId ? "active" : ""}`}
                onClick={() => props.onSwitchSpace(space.id)}
                title={space.description}
              >
                <span className="color-dot" style={{ background: space.accent }} />
                <span>{space.name}</span>
              </button>
            ))}
          </div>
          {creatingSpace && (
            <form onSubmit={handleCreateSpace} style={{ marginTop: 8, display: "flex", gap: 4 }}>
              <input
                className="field-input"
                style={{ flex: 1, minWidth: 0, padding: "5px 8px", fontSize: 12 }}
                placeholder="Space name…"
                value={newSpaceName}
                onChange={(e) => setNewSpaceName(e.target.value)}
                autoFocus
              />
              <button type="submit" className="btn-primary" style={{ padding: "5px 9px" }}>
                Add
              </button>
            </form>
          )}
        </section>

        <section>
          <div className="rail-section-head">
            <span className="kicker">Tabs ({spaceTabs.length})</span>
            <button
              type="button"
              className="tab-mini-btn"
              title="Open new tab (Ctrl+T)"
              aria-label="New tab"
              onClick={props.onNewTab}
            >
              <PlusIcon size={14} />
            </button>
          </div>
          {spaceTabs.length === 0 ? (
            <div style={{ padding: "6px 6px", fontSize: 12, color: "var(--ink-muted)" }}>
              No tabs in this Space yet.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {spaceTabs.map((tab) => {
                const isActive = props.stageMode === "web" && tab.id === props.activeTabId;
                const isSplit = tab.id === props.splitTabId;
                return (
                  <div
                    key={tab.id}
                    role="button"
                    tabIndex={0}
                    className={`tab-row ${isActive ? "active" : ""} ${tab.hibernated ? "hibernated" : ""}`}
                    onClick={() => props.onActivateTab(tab.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        props.onActivateTab(tab.id);
                      }
                    }}
                  >
                    {tab.faviconUrl && !brokenFavicons[tab.id] && !tab.hibernated ? (
                      <img
                        src={tab.faviconUrl}
                        alt=""
                        width={14}
                        height={14}
                        style={{ borderRadius: 3, flexShrink: 0, objectFit: "contain" }}
                        onError={() =>
                          setBrokenFavicons((prev) => ({ ...prev, [tab.id]: true }))
                        }
                      />
                    ) : (
                      <span
                        className="color-dot"
                        style={{
                          background: tab.botColor ?? (tab.hibernated ? "var(--ink-muted)" : "var(--accent-brand)")
                        }}
                        title={tab.botName ? `${tab.botName} worktree tab` : tab.hibernated ? "Hibernated (0 MB)" : "Live tab"}
                      />
                    )}
                    <span className="rail-item-label" style={{ flex: 1, fontSize: 12.5 }}>
                      {tab.title || tab.url}
                    </span>
                    {tab.botName && (
                      <span
                        className="mono"
                        style={{
                          fontSize: 10,
                          padding: "1px 5px",
                          borderRadius: 999,
                          background: `color-mix(in srgb, ${tab.botColor ?? "#16A095"} 16%, transparent)`,
                          color: tab.botColor ?? "var(--accent-brand)"
                        }}
                      >
                        {tab.botName}
                      </span>
                    )}
                    {tab.hibernated && (
                      <span className="mono" style={{ fontSize: 10, color: "var(--ink-muted)" }}>
                        0MB
                      </span>
                    )}
                    <div className="tab-actions" onClick={(e) => e.stopPropagation()}>
                      {!tab.hibernated && (
                        <button
                          type="button"
                          className="tab-mini-btn"
                          title="Hibernate tab (free memory)"
                          aria-label="Hibernate tab"
                          onClick={() => props.onHibernateTab(tab.id)}
                        >
                          <SnowflakeIcon size={12} />
                        </button>
                      )}
                      {tab.id !== props.activeTabId && props.activeTabId && (
                        <button
                          type="button"
                          className="tab-mini-btn"
                          title={isSplit ? "Remove from Split View" : "Open side-by-side"}
                          aria-label="Split view"
                          onClick={() => props.onSplitTab(tab.id)}
                        >
                          <SplitIcon size={12} color={isSplit ? "var(--accent-brand)" : undefined} />
                        </button>
                      )}
                      <button
                        type="button"
                        className="tab-mini-btn"
                        title="Close tab"
                        aria-label="Close tab"
                        onClick={() => props.onCloseTab(tab.id)}
                      >
                        <CloseIcon size={12} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section>
          <div className="rail-section-head">
            <span className="kicker">Team</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {props.bots.map((bot) => (
              <button
                key={bot.id}
                type="button"
                className={`rail-item ${bot.id === props.selectedBotId ? "active" : ""}`}
                onClick={() => props.onSelectBot(bot.id)}
                title={bot.description}
              >
                <span className="rail-item-main">
                  <span className="color-dot" style={{ background: bot.color }} />
                  <span className="rail-item-label">{bot.name}</span>
                </span>
                <span style={{ fontSize: 11, color: "var(--ink-muted)" }}>{bot.roleTitle}</span>
              </button>
            ))}
          </div>
        </section>
      </div>

      <div className="rail-footer">
        <button type="button" className="btn-ghost" style={{ flex: 1 }} onClick={props.onOpenSettings}>
          <SettingsIcon size={14} />
          <span>AI & Settings</span>
        </button>
        <button
          type="button"
          className="btn-ghost"
          title={`Theme: ${props.theme} (click to switch)`}
          onClick={props.onCycleTheme}
          style={{ padding: "7px 9px", textTransform: "capitalize" }}
        >
          {props.theme}
        </button>
      </div>
    </aside>
  );
}
