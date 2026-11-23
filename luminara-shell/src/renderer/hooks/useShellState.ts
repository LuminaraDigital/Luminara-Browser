import { useCallback, useEffect, useRef, useState } from "react";
import type { LiveLensTable, ShellSnapshot, ThemeMode } from "../../shared/types";

function resolveEffectiveTheme(theme: ThemeMode): "light" | "dark" {
  if (theme === "light" || theme === "dark") return theme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function useShellState(onFirstRunOnboarding: () => void) {
  const [snapshot, setSnapshot] = useState<ShellSnapshot | null>(null);
  const [toast, setToast] = useState("");
  const [lensTable, setLensTable] = useState<LiveLensTable | null>(null);
  const [lensLoading, setLensLoading] = useState(false);
  const [lensError, setLensError] = useState("");
  const onboardingCheckedRef = useRef(false);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast((prev) => (prev === msg ? "" : prev)), 3600);
  }, []);

  useEffect(() => {
    let mounted = true;
    void window.luminaraShell.getSnapshot().then((initial) => {
      if (!mounted) return;
      setSnapshot(initial);
      if (!onboardingCheckedRef.current && initial.autoOpenOnboarding) {
        onboardingCheckedRef.current = true;
        onFirstRunOnboarding();
      }
    });
    const offSnap = window.luminaraShell.onSnapshot((next) => setSnapshot(next));
    const offApproval = window.luminaraShell.onApproval((card) => {
      showToast(`Paused ${card.method} on ${card.domain} — review in Inbox or Team Drawer`);
    });
    const offCo = window.luminaraShell.onCoPresence((co) => {
      setSnapshot((prev) => (prev ? { ...prev, coPresence: co } : prev));
    });
    const offToast = window.luminaraShell.onToast((msg) => showToast(msg));
    return () => {
      mounted = false;
      offSnap();
      offApproval();
      offCo();
      offToast();
    };
  }, [showToast, onFirstRunOnboarding]);

  useEffect(() => {
    const mode = snapshot?.settings.theme ?? "system";
    const apply = () =>
      document.documentElement.setAttribute("data-theme", resolveEffectiveTheme(mode));
    apply();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [snapshot?.settings.theme]);

  const refreshLiveLens = useCallback(async () => {
    if (!snapshot) return;
    setLensLoading(true);
    setLensError("");
    try {
      setLensTable(await window.luminaraShell.buildLiveLens(snapshot.activeSpaceId));
    } catch {
      setLensError("Could not extract live comparison data from open tabs.");
    } finally {
      setLensLoading(false);
    }
  }, [snapshot?.activeSpaceId]);

  return { snapshot, toast, showToast, lensTable, lensLoading, lensError, refreshLiveLens };
}
