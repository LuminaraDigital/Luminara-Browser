import type { WebContents } from "electron";
import type { ShortcutEvent } from "../shared/types";

export interface ShortcutHost {
  getShellWebContents: () => WebContents | null;
  getActiveTabWebContents: () => WebContents | null;
  onNavAction: (action: "back" | "forward" | "reload") => void;
  isEscapeBlocking: () => boolean;
}

function emitToShell(host: ShortcutHost, shortcut: ShortcutEvent, focusShell: boolean): void {
  const shell = host.getShellWebContents();
  if (!shell || shell.isDestroyed()) return;
  if (focusShell) shell.focus();
  shell.send("shell:shortcut", shortcut);
}

function adjustZoom(wc: WebContents | null, mode: "in" | "out" | "reset"): void {
  if (!wc || wc.isDestroyed()) return;
  if (mode === "reset") {
    wc.setZoomLevel(0);
    return;
  }
  const current = wc.getZoomLevel();
  const next = mode === "in" ? Math.min(3, current + 0.5) : Math.max(-3, current - 0.5);
  wc.setZoomLevel(next);
}

function toggleDevTools(host: ShortcutHost): void {
  const target = host.getActiveTabWebContents() ?? host.getShellWebContents();
  if (!target || target.isDestroyed()) return;
  if (target.isDevToolsOpened()) target.closeDevTools();
  else target.openDevTools({ mode: "detach" });
}

export function attachWindowShortcuts(
  wc: WebContents,
  host: ShortcutHost,
  isShellView: boolean
): void {
  wc.on("before-input-event", (event, input) => {
    if (input.type !== "keyDown") return;
    const mod = input.control || input.meta;
    const key = input.key.toLowerCase();

    if (mod && !input.alt && !input.shift) {
      if (key === "k") {
        event.preventDefault();
        emitToShell(host, "palette", true);
        return;
      }
      if (key === "l") {
        event.preventDefault();
        emitToShell(host, "omnibox", true);
        return;
      }
      if (key === "t") {
        event.preventDefault();
        emitToShell(host, "new-tab", true);
        return;
      }
      if (key === "w") {
        event.preventDefault();
        emitToShell(host, "close-tab", false);
        return;
      }
      if (key === "r") {
        event.preventDefault();
        host.onNavAction("reload");
        return;
      }
      if (key === "f") {
        event.preventDefault();
        emitToShell(host, "find", true);
        return;
      }
      if (key === "+" || key === "=") {
        event.preventDefault();
        adjustZoom(host.getActiveTabWebContents(), "in");
        return;
      }
      if (key === "-") {
        event.preventDefault();
        adjustZoom(host.getActiveTabWebContents(), "out");
        return;
      }
      if (key === "0") {
        event.preventDefault();
        adjustZoom(host.getActiveTabWebContents(), "reset");
        return;
      }
    }

    if (mod && input.shift && !input.alt) {
      if (key === "b") {
        event.preventDefault();
        emitToShell(host, "toggle-drawer", false);
        return;
      }
      if (key === "i") {
        event.preventDefault();
        toggleDevTools(host);
        return;
      }
    }

    if (input.key === "F5") {
      event.preventDefault();
      host.onNavAction("reload");
      return;
    }

    if (input.key === "F12") {
      event.preventDefault();
      toggleDevTools(host);
      return;
    }

    if (input.alt && !mod && !input.shift) {
      if (input.key === "ArrowLeft") {
        event.preventDefault();
        host.onNavAction("back");
        return;
      }
      if (input.key === "ArrowRight") {
        event.preventDefault();
        host.onNavAction("forward");
        return;
      }
    }

    if (input.key === "Escape") {
      if (isShellView || host.isEscapeBlocking()) {
        event.preventDefault();
      }
      emitToShell(host, "escape", false);
    }
  });
}
