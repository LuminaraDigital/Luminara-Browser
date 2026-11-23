import React, { useEffect, useMemo, useState } from "react";
import type { MemoryEntry, TabRecord, WebSkill } from "../../shared/types";
import { SearchIcon } from "./Icons";

interface CommandItem {
  id: string;
  group: string;
  title: string;
  subtitle: string;
  run: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  tabs: TabRecord[];
  memories: MemoryEntry[];
  skills: WebSkill[];
  onClose: () => void;
  onActivateTab: (tabId: string) => void;
  onOpenUrl: (input: string) => void;
  onAskTeam: (prompt: string) => void;
  onRunAction: (action: "new-tab" | "lens" | "inbox" | "routines" | "settings" | "theme" | "split") => void;
  onReplaySkill: (skillId: string) => void;
}

export function CommandPalette(props: CommandPaletteProps): React.JSX.Element | null {
  const [query, setQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);

  useEffect(() => {
    if (props.open) {
      setQuery("");
      setSelectedIdx(0);
    }
  }, [props.open]);

  const items = useMemo<CommandItem[]>(() => {
    const q = query.trim();
    const ql = q.toLowerCase();
    const list: CommandItem[] = [];

    if (q) {
      list.push({
        id: "direct-open",
        group: "Web",
        title: `Open or search "${q}"`,
        subtitle: "Opens in a 60fps tab inside the current Space",
        run: () => props.onOpenUrl(q)
      });
      list.push({
        id: "direct-ask",
        group: "Team",
        title: `Ask Remy & Team: "${q}"`,
        subtitle: "Sends directly to the contextual Team Drawer",
        run: () => props.onAskTeam(q)
      });
    }

    for (const tab of props.tabs) {
      if (!ql || `${tab.title} ${tab.url}`.toLowerCase().includes(ql)) {
        list.push({
          id: `tab-${tab.id}`,
          group: "Open Tabs",
          title: tab.title || tab.url,
          subtitle: `${tab.spaceId} Space${tab.hibernated ? " · Hibernated" : ""}`,
          run: () => props.onActivateTab(tab.id)
        });
      }
    }

    const actions: Array<{
      id: string;
      title: string;
      subtitle: string;
      action: "new-tab" | "lens" | "inbox" | "routines" | "settings" | "theme" | "split";
    }> = [
      { id: "act-lens", title: "Open Live Lens comparison table", subtitle: "Compare all tabs in this Space", action: "lens" },
      { id: "act-inbox", title: "Open Approval Inbox", subtitle: "Review Network Mutation Firewall cards", action: "inbox" },
      { id: "act-routines", title: "Open Routines & Taught Skills", subtitle: "24-hour web scheduler and replays", action: "routines" },
      { id: "act-split", title: "Toggle Split View", subtitle: "Mount two native Chromium views side-by-side", action: "split" },
      { id: "act-theme", title: "Switch Light / Dark / System theme", subtitle: "Warm Atelier Precision palette", action: "theme" },
      { id: "act-settings", title: "AI Setup & Preferences", subtitle: "Local Ollama or encrypted API keys", action: "settings" }
    ];

    for (const act of actions) {
      if (!ql || `${act.title} ${act.subtitle}`.toLowerCase().includes(ql)) {
        list.push({
          id: act.id,
          group: "Quick Actions",
          title: act.title,
          subtitle: act.subtitle,
          run: () => props.onRunAction(act.action)
        });
      }
    }

    for (const skill of props.skills) {
      if (!ql || `${skill.name} ${skill.domain}`.toLowerCase().includes(ql)) {
        list.push({
          id: `skill-${skill.id}`,
          group: "Web Skills",
          title: `Replay skill: ${skill.name}`,
          subtitle: `${skill.domain} · ${skill.steps.length} steps`,
          run: () => props.onReplaySkill(skill.id)
        });
      }
    }

    for (const mem of props.memories.slice(0, 12)) {
      if (!ql || `${mem.title} ${mem.domain} ${mem.snippet}`.toLowerCase().includes(ql)) {
        list.push({
          id: `mem-${mem.id}`,
          group: "Space Memory",
          title: mem.title,
          subtitle: `${mem.domain} · ${mem.snippet.slice(0, 64)}`,
          run: () => props.onOpenUrl(mem.url)
        });
      }
    }

    return list.slice(0, 14);
  }, [query, props]);

  useEffect(() => {
    setSelectedIdx(0);
  }, [query]);

  if (!props.open) return null;

  const executeSelected = (idx: number) => {
    const item = items[idx];
    if (!item) return;
    props.onClose();
    item.run();
  };

  return (
    <div className="modal-backdrop" onClick={props.onClose} role="dialog" aria-modal="true" aria-label="Command palette">
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 16px", borderBottom: "1px solid var(--hairline)" }}>
          <SearchIcon size={17} color="var(--accent-brand)" />
          <input
            className="intent-input"
            style={{ fontSize: 14 }}
            placeholder="Jump to a tab, Space memory, quick action, URL, or ask Remy…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                props.onClose();
              } else if (e.key === "ArrowDown") {
                e.preventDefault();
                setSelectedIdx((i) => Math.min(items.length - 1, i + 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setSelectedIdx((i) => Math.max(0, i - 1));
              } else if (e.key === "Enter") {
                e.preventDefault();
                executeSelected(selectedIdx);
              }
            }}
            autoFocus
          />
          <span className="pill mono" style={{ fontSize: 10.5 }}>
            Esc
          </span>
        </div>

        <div style={{ padding: 8, display: "flex", flexDirection: "column", gap: 3 }}>
          {items.length === 0 ? (
            <div style={{ padding: 16, textAlign: "center", color: "var(--ink-muted)" }}>
              No matching tabs, memories, or actions.
            </div>
          ) : (
            items.map((item, idx) => (
              <button
                key={item.id}
                type="button"
                onClick={() => executeSelected(idx)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 10,
                  padding: "9px 12px",
                  borderRadius: 10,
                  textAlign: "left",
                  background: idx === selectedIdx ? "var(--bg-elevated)" : "transparent"
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>{item.title}</div>
                  <div style={{ fontSize: 11.5, color: "var(--ink-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {item.subtitle}
                  </div>
                </div>
                <span className="pill mono" style={{ fontSize: 10, flexShrink: 0 }}>
                  {item.group}
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
