import React, { useMemo, useState } from "react";
import type {
  ApprovalCard,
  ApprovalDecision,
  LiveLensTable,
  MemoryEntry,
  RoutineItem,
  Space,
  StageMode,
  TabRecord,
  WebSkill
} from "../../shared/types";
import { DownloadIcon, ReloadIcon, SearchIcon, SparklesIcon } from "./Icons";
import { InboxView, RoutinesView } from "./InboxRoutinesViews";

interface StageViewsProps {
  mode: Exclude<StageMode, "web">;
  activeSpace: Space;
  tabs: TabRecord[];
  memories: MemoryEntry[];
  pendingApprovals: ApprovalCard[];
  allowlistedOrigins: string[];
  firewallAlwaysOn: boolean;
  lensTable: LiveLensTable | null;
  lensLoading: boolean;
  lensError: string;
  routines: RoutineItem[];
  skills: WebSkill[];
  onUniversalIntent: (input: string) => void;
  onOpenUrl: (url: string) => void;
  onActivateTab: (tabId: string) => void;
  onOpenStage: (mode: StageMode) => void;
  onRefreshLens: () => void;
  onResolveApproval: (id: string, decision: ApprovalDecision) => void;
  onRevokeOrigin: (origin: string) => void;
  onToggleFirewallAlways: (enabled: boolean) => void;
  onTriggerDemoApproval: () => void;
  onCreateRoutine: (item: Omit<RoutineItem, "id" | "lastRunAt" | "lastSummary">) => void;
  onToggleRoutine: (id: string) => void;
  onRunRoutine: (id: string) => Promise<void>;
  onDeleteRoutine: (id: string) => void;
  onReplaySkill: (skillId: string) => void;
  onDeleteSkill: (skillId: string) => void;
}

const SPEED_DIALS = [
  { title: "DuckDuckGo", url: "https://duckduckgo.com", note: "Private search" },
  { title: "Hacker News", url: "https://news.ycombinator.com", note: "Engineering feed" },
  { title: "Wikipedia", url: "https://en.wikipedia.org", note: "Open reference" },
  { title: "GitHub", url: "https://github.com", note: "Repositories" }
];

function triggerDownload(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function StageViews(props: StageViewsProps): React.JSX.Element {
  if (props.mode === "home") return <CalmHomeView {...props} />;
  if (props.mode === "lens") return <LiveLensView {...props} />;
  if (props.mode === "inbox") {
    return (
      <InboxView
        pendingApprovals={props.pendingApprovals}
        allowlistedOrigins={props.allowlistedOrigins}
        firewallAlwaysOn={props.firewallAlwaysOn}
        onResolveApproval={props.onResolveApproval}
        onRevokeOrigin={props.onRevokeOrigin}
        onToggleFirewallAlways={props.onToggleFirewallAlways}
        onTriggerDemoApproval={props.onTriggerDemoApproval}
      />
    );
  }
  return (
    <RoutinesView
      activeSpace={props.activeSpace}
      routines={props.routines}
      skills={props.skills}
      onCreateRoutine={props.onCreateRoutine}
      onToggleRoutine={props.onToggleRoutine}
      onRunRoutine={props.onRunRoutine}
      onDeleteRoutine={props.onDeleteRoutine}
      onReplaySkill={props.onReplaySkill}
      onDeleteSkill={props.onDeleteSkill}
    />
  );
}

function CalmHomeView(props: StageViewsProps): React.JSX.Element {
  const [intent, setIntent] = useState("");
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const spaceTabs = props.tabs.filter((t) => t.spaceId === props.activeSpace.id);
  const spaceMemories = props.memories.filter((m) => m.spaceId === props.activeSpace.id).slice(0, 6);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!intent.trim()) return;
    props.onUniversalIntent(intent.trim());
    setIntent("");
  };

  return (
    <div className="stage-scroll">
      <div className="home-container">
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 12 }}>
          <span className="kicker">{props.activeSpace.name} Space · Isolated Session</span>
          <h1 className="display-title">{greeting}. Where shall we explore?</h1>
          <p style={{ color: "var(--ink-secondary)", maxWidth: "60ch" }}>
            Type a website, search query, or start with &ldquo;Ask Remy&rdquo; or &ldquo;Compare&rdquo; to work alongside your local team.
          </p>
        </div>

        <form className="intent-shell" onSubmit={handleSubmit}>
          <SearchIcon size={18} color="var(--accent-brand)" />
          <input
            className="intent-input"
            placeholder="Search the web, paste a URL, or ask Remy, Dana, or Pi…"
            value={intent}
            onChange={(e) => setIntent(e.target.value)}
            autoFocus
          />
          <button type="submit" className="btn-primary">
            Go
          </button>
        </form>

        {props.pendingApprovals.length > 0 && (
          <div className="approval-card" style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <div>
              <div style={{ fontWeight: 600 }}>
                {props.pendingApprovals.length} action waiting for your approval
              </div>
              <div style={{ fontSize: 12.5, color: "var(--ink-secondary)" }}>
                {props.pendingApprovals[0].title}
              </div>
            </div>
            <button type="button" className="btn-primary" onClick={() => props.onOpenStage("inbox")}>
              Review in Inbox
            </button>
          </div>
        )}

        <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <span className="kicker">Quick Launch</span>
          <div className="card-grid">
            {SPEED_DIALS.map((tile) => (
              <button key={tile.url} type="button" className="speed-tile" onClick={() => props.onOpenUrl(tile.url)}>
                <span style={{ fontWeight: 600, fontSize: 14 }}>{tile.title}</span>
                <span style={{ fontSize: 12, color: "var(--ink-secondary)" }}>{tile.note}</span>
              </button>
            ))}
          </div>
        </section>

        <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span className="kicker">Continue Where You Left Off</span>
            {spaceTabs.length >= 2 && (
              <button type="button" className="btn-ghost" onClick={() => props.onOpenStage("lens")}>
                <SparklesIcon size={13} />
                <span>Compare in Live Lens</span>
              </button>
            )}
          </div>
          {spaceTabs.length === 0 && spaceMemories.length === 0 ? (
            <div className="studio-card" style={{ color: "var(--ink-secondary)" }}>
              Pages you browse in {props.activeSpace.name} stay isolated in this Space and appear here for instant recall.
            </div>
          ) : (
            <div className="card-grid">
              {spaceTabs.slice(0, 4).map((tab) => (
                <button key={tab.id} type="button" className="speed-tile" onClick={() => props.onActivateTab(tab.id)}>
                  <span style={{ fontWeight: 600, fontSize: 13 }}>{tab.title}</span>
                  <span className="mono" style={{ color: "var(--ink-muted)", fontSize: 11 }}>
                    {tab.hibernated ? "Hibernated · 0 MB" : "Live 60fps tab"}
                  </span>
                </button>
              ))}
              {spaceMemories.slice(0, Math.max(0, 4 - spaceTabs.length)).map((mem) => (
                <button key={mem.id} type="button" className="speed-tile" onClick={() => props.onOpenUrl(mem.url)}>
                  <span style={{ fontWeight: 600, fontSize: 13 }}>{mem.title}</span>
                  <span className="mono" style={{ color: "var(--ink-muted)", fontSize: 11 }}>
                    {mem.domain}
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function LiveLensView(props: StageViewsProps): React.JSX.Element {
  const [filter, setFilter] = useState("");
  const [sortBy, setSortBy] = useState<"title" | "domain" | "wordCount">("wordCount");
  const [asc, setAsc] = useState(false);

  const rows = useMemo(() => {
    const base = props.lensTable?.rows ?? [];
    const q = filter.trim().toLowerCase();
    const filtered = q
      ? base.filter((r) => `${r.title} ${r.domain} ${r.priceOrMetric} ${r.summary}`.toLowerCase().includes(q))
      : base;
    return [...filtered].sort((a, b) => {
      const cmp = sortBy === "wordCount" ? a.wordCount - b.wordCount : a[sortBy].localeCompare(b[sortBy]);
      return asc ? cmp : -cmp;
    });
  }, [props.lensTable, filter, sortBy, asc]);

  const toggleSort = (col: "title" | "domain" | "wordCount") => {
    if (sortBy === col) setAsc((v) => !v);
    else {
      setSortBy(col);
      setAsc(col !== "wordCount");
    }
  };

  const exportCsv = () => {
    const header = ["Title", "Domain", "URL", "Price/Metric", "Signal", "Words", "WebMCP Tools"];
    const lines = [
      header.join(","),
      ...rows.map((r) =>
        [r.title, r.domain, r.url, r.priceOrMetric, r.ratingOrSignal, String(r.wordCount), r.webMcpTools.join(";")]
          .map((cell) => `"${cell.replace(/"/g, '""')}"`)
          .join(",")
      )
    ];
    triggerDownload(`luminara-lens-${props.activeSpace.id}.csv`, lines.join("\n"), "text/csv");
  };

  const exportMarkdown = () => {
    const lines = [
      `# Live Lens — ${props.activeSpace.name}`,
      "",
      "| Page | Domain | Prices & Metrics | Signals | Summary |",
      "| --- | --- | --- | --- | --- |",
      ...rows.map(
        (r) =>
          `| [${r.title.replace(/\|/g, "/")}](${r.url}) | ${r.domain} | ${r.priceOrMetric} | ${r.ratingOrSignal} | ${r.summary.slice(0, 90).replace(/\|/g, "/")} |`
      )
    ];
    triggerDownload(`luminara-lens-${props.activeSpace.id}.md`, lines.join("\n"), "text/markdown");
  };

  return (
    <div className="stage-scroll">
      <div className="stage-wide">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
          <div>
            <span className="kicker">Cross-Tab Synthesis · {props.activeSpace.name}</span>
            <h2 className="section-heading">Live Lens Comparison Table</h2>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input className="field-input" placeholder="Filter rows…" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 180 }} />
            <button type="button" className="btn-ghost" onClick={props.onRefreshLens} disabled={props.lensLoading}>
              <ReloadIcon size={14} />
              <span>{props.lensLoading ? "Extracting…" : "Refresh"}</span>
            </button>
            <button type="button" className="btn-ghost" onClick={exportCsv} disabled={rows.length === 0}>
              <DownloadIcon size={14} />
              <span>CSV</span>
            </button>
            <button type="button" className="btn-primary" onClick={exportMarkdown} disabled={rows.length === 0}>
              <DownloadIcon size={14} />
              <span>Markdown</span>
            </button>
          </div>
        </div>

        {props.lensError && (
          <div className="approval-card" style={{ borderColor: "var(--status-danger)" }}>
            <span style={{ color: "var(--status-danger)", fontWeight: 600 }}>{props.lensError}</span>
            <button type="button" className="btn-ghost" style={{ alignSelf: "flex-start" }} onClick={props.onRefreshLens}>
              Try again
            </button>
          </div>
        )}

        {props.lensLoading ? (
          <div className="studio-card" style={{ color: "var(--ink-secondary)" }}>
            Reading live text, prices, and WebMCP tools across open tabs in {props.activeSpace.name}…
          </div>
        ) : rows.length === 0 ? (
          <div className="studio-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ fontWeight: 600 }}>No tabs to compare in {props.activeSpace.name} yet</div>
            <p style={{ color: "var(--ink-secondary)" }}>
              Open two or more pages (or ask Remy to launch a parallel research worktree) to build a live sortable table.
            </p>
          </div>
        ) : (
          <div className="lens-table-wrap">
            <table className="lens-table">
              <thead>
                <tr>
                  <th onClick={() => toggleSort("title")}>Page</th>
                  <th onClick={() => toggleSort("domain")}>Domain</th>
                  <th>Prices / Metrics</th>
                  <th>Signals & Tools</th>
                  <th onClick={() => toggleSort("wordCount")}>Words</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.tabId}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{row.title}</div>
                      <div style={{ fontSize: 12, color: "var(--ink-secondary)", marginTop: 2 }}>{row.summary}</div>
                    </td>
                    <td className="mono">{row.domain}</td>
                    <td className="mono">{row.priceOrMetric}</td>
                    <td>
                      <span className="pill">{row.ratingOrSignal}</span>
                    </td>
                    <td className="mono">{row.wordCount.toLocaleString()}</td>
                    <td>
                      <button type="button" className="btn-ghost" onClick={() => props.onActivateTab(row.tabId)}>
                        Focus tab
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
