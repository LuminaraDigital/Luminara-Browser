import { useCallback, useEffect, useRef } from "react";
import type { StageMode } from "../../shared/types";

export function useWebStageLayout(opts: {
  stageRef: React.RefObject<HTMLDivElement | null>;
  activeTabId: string | null;
  splitTabId: string | null;
  stageMode: StageMode;
  modalBlocking: boolean;
  layoutEpoch: string;
}): void {
  const { stageRef, activeTabId, splitTabId, stageMode, modalBlocking, layoutEpoch } = opts;
  const rafRef = useRef<number | null>(null);

  const flushBounds = useCallback(() => {
    const el = stageRef.current;
    const shouldShowWeb = Boolean(activeTabId) && stageMode === "web" && !modalBlocking;

    if (!el || !shouldShowWeb) {
      void window.luminaraShell.syncLayout({
        x: 0,
        y: 0,
        width: 0,
        height: 0,
        visible: false,
        activeTabId,
        splitTabId
      });
      return;
    }

    const r = el.getBoundingClientRect();
    void window.luminaraShell.syncLayout({
      x: Math.round(r.left),
      y: Math.round(r.top),
      width: Math.round(r.width),
      height: Math.round(r.height),
      visible: true,
      activeTabId,
      splitTabId
    });
  }, [stageRef, activeTabId, splitTabId, stageMode, modalBlocking]);

  const scheduleBounds = useCallback(() => {
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      flushBounds();
    });
  }, [flushBounds]);

  useEffect(() => {
    // Immediate hide when switching away or opening a modal so Chromium never flashes over overlays
    if (modalBlocking || stageMode !== "web" || !activeTabId) {
      flushBounds();
    } else {
      scheduleBounds();
    }

    const el = stageRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => scheduleBounds());
    ro.observe(el);
    window.addEventListener("resize", scheduleBounds);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", scheduleBounds);
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [flushBounds, scheduleBounds, stageRef, modalBlocking, stageMode, activeTabId, layoutEpoch]);
}
