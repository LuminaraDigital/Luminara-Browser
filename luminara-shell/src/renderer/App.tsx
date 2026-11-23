import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  ApprovalDecision,
  BotMode,
  SettingsUpdate,
  StageMode,
  TabRecord,
  ThemeMode
} from "../shared/types";
import { SpaceRail } from "./components/SpaceRail";
import { TopBar } from "./components/TopBar";
import { StageViews } from "./components/StageViews";
import { TeamDrawer } from "./components/TeamDrawer";
import { CommandPalette } from "./components/CommandPalette";
import { OnboardingModal } from "./components/OnboardingModal";
import { CoPresenceBar, FindStrip, ShieldStrip, TeachStrip } from "./components/ContextStrips";
import { useWebStageLayout } from "./hooks/useWebStageLayout";
import { useShellShortcuts } from "./hooks/useShellShortcuts";
import { useTeamChat } from "./hooks/useTeamChat";
import { useShellState } from "./hooks/useShellState";

function buildWorktreeUrls(activeTab: TabRecord | null, spaceName: string): string[] {
  const topic = activeTab?.title
    ? activeTab.title.replace(/\s[-|–—].*$/, "").trim().slice(0, 60)
    : `${spaceName} overview`;
  return [`${topic} comparison pricing`, `${topic} independent reviews`];
}

export function App(): React.JSX.Element {
  const [stageMode, setStageMode] = useState<StageMode>("home");
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [selectedBotId, setSelectedBotId] = useState("remy");
  const [botMode, setBotMode] = useState<BotMode>("execute");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [shieldStripOpen, setShieldStripOpen] = useState(false);
  const [findOpen, setFindOpen] = useState(false);
  const [findQuery, setFindQuery] = useState("");
  const [skillNameDraft, setSkillNameDraft] = useState("");

  const stageRef = useRef<HTMLDivElement | null>(null);
  const omniboxRef = useRef<HTMLInputElement | null>(null);
  const chat = useTeamChat();
  const openOnboarding = useCallback(() => setSettingsOpen(true), []);
  const { snapshot, toast, showToast, lensTable, lensLoading, lensError, refreshLiveLens } =
    useShellState(openOnboarding);

  useEffect(() => {
    if (stageMode === "web" && snapshot && !snapshot.activeTabId) {
      setStageMode("home");
      setFindOpen(false);
    }
  }, [stageMode, snapshot?.activeTabId]);

  const activeSpace = useMemo(
    () => snapshot?.spaces.find((s) => s.id === snapshot.activeSpaceId) ?? snapshot?.spaces[0] ?? null,
    [snapshot]
  );
  const activeTab = useMemo(
    () => (snapshot?.activeTabId ? snapshot.tabs.find((t) => t.id === snapshot.activeTabId) ?? null : null),
    [snapshot]
  );
  const selectedBot = useMemo(
    () => snapshot?.bots.find((b) => b.id === selectedBotId) ?? snapshot?.bots[0] ?? null,
    [snapshot, selectedBotId]
  );

  useWebStageLayout({
    stageRef,
    activeTabId: snapshot?.activeTabId ?? null,
    splitTabId: snapshot?.splitTabId ?? null,
    stageMode,
    modalBlocking: paletteOpen || settingsOpen,
    layoutEpoch: `${railCollapsed}-${drawerOpen}-${shieldStripOpen}-${findOpen}-${snapshot?.recordingTabId ?? ""}-${snapshot?.coPresence.active ?? false}-${Boolean(toast)}`
  });

  const closeFind = useCallback(() => {
    setFindOpen(false);
    setFindQuery("");
    if (snapshot?.activeTabId) void window.luminaraShell.stopFindInTab(snapshot.activeTabId);
  }, [snapshot?.activeTabId]);

  useShellShortcuts({
    activeTabId: snapshot?.activeTabId ?? null,
    coPresenceActive: snapshot?.coPresence.active ?? false,
    stageMode,
    omniboxRef,
    onTogglePalette: () => setPaletteOpen((v) => !v),
    onNewTab: () => setStageMode("home"),
    onToggleDrawer: () => setDrawerOpen((v) => !v),
    onToggleFind: () => setFindOpen((v) => !v),
    onCloseTab: (id) => void window.luminaraShell.closeTab(id),
    onEscape: () => {
      if (paletteOpen) setPaletteOpen(false);
      else if (settingsOpen) setSettingsOpen(false);
      else if (findOpen) closeFind();
      else if (snapshot?.coPresence.active) {
        void window.luminaraShell.takeWheel();
        showToast("You have the wheel.");
      }
    }
  });

  const openStage = (mode: StageMode) => {
    setStageMode(mode);
    if (mode !== "web" && findOpen) closeFind();
    if (mode === "lens") void refreshLiveLens();
  };

  const openUrlInActiveSpace = async (input: string) => {
    if (!snapshot) return;
    await window.luminaraShell.openTab(snapshot.activeSpaceId, input, null, false);
    setStageMode("web");
  };

  const sendBotChat = (prompt: string) => {
    if (!snapshot) return;
    setDrawerOpen(true);
    void chat.sendMessage({
      botId: selectedBotId,
      spaceId: snapshot.activeSpaceId,
      activeTabId: snapshot.activeTabId,
      mode: botMode,
      prompt
    });
  };

  const handleToggleSplit = async () => {
    if (!snapshot?.activeTabId) return;
    if (snapshot.splitTabId) {
      await window.luminaraShell.setSplitTab(null);
      return;
    }
    const other = snapshot.tabs.find((t) => t.spaceId === snapshot.activeSpaceId && t.id !== snapshot.activeTabId);
    const secondId = other
      ? other.id
      : (await window.luminaraShell.openTab(snapshot.activeSpaceId, "https://duckduckgo.com", null, true)).id;
    await window.luminaraShell.setSplitTab(secondId);
    setStageMode("web");
  };

  const handleCycleTheme = async () => {
    if (!snapshot) return;
    const order: ThemeMode[] = ["light", "dark", "system"];
    await window.luminaraShell.updateSettings({
      theme: order[(order.indexOf(snapshot.settings.theme) + 1) % order.length]
    });
  };

  const replaySkill = (skillId: string) => {
    if (!snapshot?.activeTabId) {
      showToast("Open a web tab first to replay a skill.");
      return;
    }
    setStageMode("web");
    void window.luminaraShell.replayWebSkill(skillId, snapshot.activeTabId).then((r) => showToast(r.message));
  };

  if (!snapshot || !activeSpace || !selectedBot) {
    return (
      <div className="shell-root" style={{ alignItems: "center", justifyContent: "center" }}>
        <span className="kicker">Loading Luminara Browser v4…</span>
      </div>
    );
  }

  const teachingActive = Boolean(snapshot.recordingTabId && snapshot.recordingTabId === snapshot.activeTabId);

  return (
    <div className="shell-root" style={{ "--bot-tint": selectedBot.color } as React.CSSProperties}>
      <SpaceRail
        collapsed={railCollapsed}
        onToggleCollapse={() => setRailCollapsed((v) => !v)}
        stageMode={stageMode}
        onSelectStage={openStage}
        spaces={snapshot.spaces}
        activeSpaceId={snapshot.activeSpaceId}
        onSwitchSpace={(id) =>
          void window.luminaraShell.switchSpace(id).then((next) => setStageMode(next.activeTabId ? "web" : "home"))
        }
        onCreateSpace={(name, accent) =>
          void window.luminaraShell.createSpace(name, accent).then(() => setStageMode("home"))
        }
        tabs={snapshot.tabs}
        activeTabId={snapshot.activeTabId}
        splitTabId={snapshot.splitTabId}
        onActivateTab={(id) => {
          void window.luminaraShell.activateTab(id);
          setStageMode("web");
        }}
        onNewTab={() => setStageMode("home")}
        onHibernateTab={(id) => {
          void window.luminaraShell.hibernateTab(id);
          showToast("Tab hibernated — 0 MB RAM until you click it again.");
        }}
        onSplitTab={(id) => {
          const next = snapshot.splitTabId === id ? null : id;
          void window.luminaraShell.setSplitTab(next);
          if (next) setStageMode("web");
        }}
        onCloseTab={(id) => void window.luminaraShell.closeTab(id)}
        bots={snapshot.bots}
        selectedBotId={selectedBot.id}
        onSelectBot={(id) => {
          setSelectedBotId(id);
          setDrawerOpen(true);
        }}
        pendingApprovalCount={snapshot.pendingApprovals.length}
        theme={snapshot.settings.theme}
        onCycleTheme={() => void handleCycleTheme()}
        onOpenPalette={() => setPaletteOpen(true)}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <main className="center-column">
        <TopBar
          activeTab={activeTab}
          stageMode={stageMode}
          searchEngine={snapshot.settings.searchEngine}
          shield={snapshot.shield}
          shieldStripOpen={shieldStripOpen}
          onToggleShieldStrip={() => setShieldStripOpen((v) => !v)}
          teachingActive={teachingActive}
          onToggleTeach={() => snapshot.activeTabId && void window.luminaraShell.toggleTeachMode(snapshot.activeTabId)}
          onOpenLens={() => openStage(stageMode === "lens" ? (snapshot.activeTabId ? "web" : "home") : "lens")}
          splitActive={Boolean(snapshot.splitTabId)}
          onToggleSplit={() => void handleToggleSplit()}
          drawerOpen={drawerOpen}
          onToggleDrawer={() => setDrawerOpen((v) => !v)}
          windowMaximized={snapshot.windowMaximized}
          onNavigate={(input) =>
            stageMode === "web" && snapshot.activeTabId
              ? void window.luminaraShell.navigateTab(snapshot.activeTabId, input)
              : void openUrlInActiveSpace(input)
          }
          onNavAction={(action) => snapshot.activeTabId && void window.luminaraShell.navAction(snapshot.activeTabId, action)}
          onWindowControl={(action) => void window.luminaraShell.windowControl(action)}
          omniboxRef={omniboxRef}
        />

        {shieldStripOpen && (
          <ShieldStrip
            shield={snapshot.shield}
            pendingCount={snapshot.pendingApprovals.length}
            onToggleDomain={(d) => void window.luminaraShell.toggleShieldDomain(d)}
            onOpenInbox={() => openStage("inbox")}
          />
        )}

        {findOpen && snapshot.activeTabId && stageMode === "web" && (
          <FindStrip
            query={findQuery}
            onQueryChange={(val) => {
              setFindQuery(val);
              if (snapshot.activeTabId) void window.luminaraShell.findInTab(snapshot.activeTabId, val, true);
            }}
            onFind={(forward) => {
              if (snapshot.activeTabId) void window.luminaraShell.findInTab(snapshot.activeTabId, findQuery, forward);
            }}
            onClose={closeFind}
          />
        )}

        {teachingActive && (
          <TeachStrip
            stepCount={snapshot.recordingSteps.length}
            skillName={skillNameDraft}
            onSkillNameChange={setSkillNameDraft}
            onSave={(e) => {
              e.preventDefault();
              void window.luminaraShell
                .saveWebSkill(skillNameDraft || "Recorded Web Skill", `Taught on ${activeTab?.title ?? "active page"}`)
                .then((saved) => {
                  if (saved) {
                    setSkillNameDraft("");
                    showToast(`Saved web skill "${saved.name}" (${saved.steps.length} steps)`);
                  }
                });
            }}
          />
        )}

        <div ref={stageRef} className="stage-host">
          {stageMode !== "web" && (
            <StageViews
              mode={stageMode}
              activeSpace={activeSpace}
              tabs={snapshot.tabs}
              memories={snapshot.memories}
              pendingApprovals={snapshot.pendingApprovals}
              allowlistedOrigins={snapshot.allowlistedOrigins}
              firewallAlwaysOn={snapshot.settings.firewallAlwaysOn}
              lensTable={lensTable}
              lensLoading={lensLoading}
              lensError={lensError}
              routines={snapshot.routines}
              skills={snapshot.skills}
              onUniversalIntent={(input) =>
                /^(ask|compare|research|summarize|summarise|explain|plan)\b/i.test(input)
                  ? sendBotChat(input)
                  : void openUrlInActiveSpace(input)
              }
              onOpenUrl={(url) => void openUrlInActiveSpace(url)}
              onActivateTab={(id) => {
                void window.luminaraShell.activateTab(id);
                setStageMode("web");
              }}
              onOpenStage={openStage}
              onRefreshLens={() => void refreshLiveLens()}
              onResolveApproval={(id: string, d: ApprovalDecision) => void window.luminaraShell.resolveApproval(id, d)}
              onRevokeOrigin={(o) => void window.luminaraShell.revokeFirewallOrigin(o)}
              onToggleFirewallAlways={(enabled) => void window.luminaraShell.updateSettings({ firewallAlwaysOn: enabled })}
              onTriggerDemoApproval={() => void window.luminaraShell.triggerDemoApproval()}
              onCreateRoutine={(item) =>
                void window.luminaraShell.createRoutine(item).catch((err: unknown) => {
                  showToast(err instanceof Error ? err.message : "Could not save routine.");
                })
              }
              onToggleRoutine={(id) => void window.luminaraShell.toggleRoutine(id)}
              onRunRoutine={async (id) => {
                try {
                  await window.luminaraShell.runRoutineNow(id);
                  showToast("Routine finished — summary saved.");
                } catch (err) {
                  showToast(err instanceof Error ? err.message : "Routine failed to run.");
                }
              }}
              onDeleteRoutine={(id) => void window.luminaraShell.deleteRoutine(id)}
              onReplaySkill={replaySkill}
              onDeleteSkill={(id) => void window.luminaraShell.deleteWebSkill(id)}
            />
          )}
        </div>

        <CoPresenceBar
          coPresence={snapshot.coPresence}
          toast={toast}
          onTakeWheel={() => void window.luminaraShell.takeWheel()}
        />
      </main>

      {drawerOpen && (
        <TeamDrawer
          bots={snapshot.bots}
          selectedBot={selectedBot}
          onSelectBot={setSelectedBotId}
          mode={botMode}
          onChangeMode={setBotMode}
          messages={chat.chatByBot[selectedBot.id] ?? []}
          loading={chat.isBotLoading(selectedBot.id)}
          errorText={chat.getBotError(selectedBot.id)}
          activeTab={activeTab}
          pendingApprovals={snapshot.pendingApprovals}
          settings={snapshot.settings}
          onSend={(p) => sendBotChat(p)}
          onAbort={() => chat.abort(selectedBot.id)}
          onQuickCompare={() => openStage("lens")}
          onQuickWorktree={() =>
            void window.luminaraShell
              .openBotWorktree(
                selectedBot.id,
                snapshot.activeSpaceId,
                buildWorktreeUrls(activeTab, activeSpace.name)
              )
              .then(() => {
                setStageMode("web");
                showToast(`${selectedBot.name} opened parallel 60fps worktree tabs.`);
              })
          }
          onQuickTeach={() => {
            if (snapshot.activeTabId) {
              void window.luminaraShell.toggleTeachMode(snapshot.activeTabId);
              setStageMode("web");
            }
          }}
          onQuickWatch={() => {
            if (!activeTab) return;
            void window.luminaraShell
              .createRoutine({
                name: `Watch ${activeTab.title.slice(0, 24)}`,
                spaceId: snapshot.activeSpaceId,
                botId: selectedBot.id,
                hourOfDay: (new Date().getHours() + 1) % 24,
                minuteOfHour: 0,
                url: activeTab.url,
                instruction: "Check for updates or price changes on this page.",
                enabled: true
              })
              .then(() => {
                openStage("routines");
                showToast("Added page watch to your 24-hour Routines.");
              })
              .catch((err: unknown) => {
                showToast(err instanceof Error ? err.message : "Could not schedule page watch.");
              });
          }}
          onResolveApproval={(id, d) => void window.luminaraShell.resolveApproval(id, d)}
          onOpenSettings={() => setSettingsOpen(true)}
          onClose={() => setDrawerOpen(false)}
        />
      )}

      <CommandPalette
        open={paletteOpen}
        tabs={snapshot.tabs}
        memories={snapshot.memories}
        skills={snapshot.skills}
        onClose={() => setPaletteOpen(false)}
        onActivateTab={(id) => {
          void window.luminaraShell.activateTab(id);
          setStageMode("web");
        }}
        onOpenUrl={(input) => void openUrlInActiveSpace(input)}
        onAskTeam={(prompt) => sendBotChat(prompt)}
        onRunAction={(action) => {
          if (action === "lens" || action === "inbox" || action === "routines") openStage(action);
          else if (action === "settings") setSettingsOpen(true);
          else if (action === "theme") void handleCycleTheme();
          else if (action === "split") void handleToggleSplit();
          else setStageMode("home");
        }}
        onReplaySkill={replaySkill}
      />

      <OnboardingModal
        open={settingsOpen}
        settings={snapshot.settings}
        shield={snapshot.shield}
        onSave={async (patch: SettingsUpdate) => {
          await window.luminaraShell.updateSettings(patch);
          showToast("Preferences & AI settings saved.");
        }}
        onDetectOllama={(host) => window.luminaraShell.detectOllamaModels(host)}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  );
}
