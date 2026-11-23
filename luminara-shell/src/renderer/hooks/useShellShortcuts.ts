import { useEffect } from "react";
import type { ShortcutEvent, StageMode } from "../../shared/types";

export function useShellShortcuts(opts: {
  activeTabId: string | null;
  coPresenceActive: boolean;
  stageMode: StageMode;
  omniboxRef: React.RefObject<HTMLInputElement | null>;
  onTogglePalette: () => void;
  onNewTab: () => void;
  onToggleDrawer: () => void;
  onToggleFind: () => void;
  onCloseTab: (tabId: string) => void;
  onEscape: () => void;
}): void {
  const {
    activeTabId,
    coPresenceActive,
    stageMode,
    omniboxRef,
    onTogglePalette,
    onNewTab,
    onToggleDrawer,
    onToggleFind,
    onCloseTab,
    onEscape
  } = opts;

  useEffect(() => {
    const dispatch = (shortcut: ShortcutEvent) => {
      switch (shortcut) {
        case "palette":
          onTogglePalette();
          break;
        case "omnibox":
          omniboxRef.current?.focus();
          omniboxRef.current?.select();
          break;
        case "new-tab":
          onNewTab();
          break;
        case "close-tab":
          if (activeTabId && stageMode === "web") onCloseTab(activeTabId);
          break;
        case "toggle-drawer":
          onToggleDrawer();
          break;
        case "find":
          if (activeTabId && stageMode === "web") onToggleFind();
          break;
        case "escape":
          onEscape();
          break;
      }
    };

    const offMain = window.luminaraShell.onShortcut(dispatch);
    return () => {
      offMain();
    };
  }, [
    activeTabId,
    coPresenceActive,
    stageMode,
    omniboxRef,
    onTogglePalette,
    onNewTab,
    onToggleDrawer,
    onToggleFind,
    onCloseTab,
    onEscape
  ]);
}
