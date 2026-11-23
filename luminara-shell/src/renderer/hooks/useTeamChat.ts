import { useRef, useState } from "react";
import type { BotMode, ChatMessage } from "../../shared/types";

function makeId(prefix: string): string {
  const rand =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID().slice(0, 8)
      : Math.random().toString(36).slice(2, 10);
  return `${prefix}_${Date.now()}_${rand}`;
}

export function useTeamChat() {
  const [chatByBot, setChatByBot] = useState<Record<string, ChatMessage[]>>({});
  const [loadingByBot, setLoadingByBot] = useState<Record<string, boolean>>({});
  const [errorByBot, setErrorByBot] = useState<Record<string, string>>({});
  const activeReqByBot = useRef<Record<string, string | null>>({});
  const chatRef = useRef<Record<string, ChatMessage[]>>({});
  chatRef.current = chatByBot;

  const sendMessage = async (opts: {
    botId: string;
    spaceId: string;
    activeTabId: string | null;
    mode: BotMode;
    prompt: string;
  }) => {
    const botId = opts.botId;
    if (loadingByBot[botId]) return;

    const reqId = makeId("req");
    activeReqByBot.current[botId] = reqId;
    setErrorByBot((prev) => ({ ...prev, [botId]: "" }));
    setLoadingByBot((prev) => ({ ...prev, [botId]: true }));

    const historySnapshot = (chatRef.current[botId] ?? []).slice(-6).map((x) => ({
      role: (x.role === "user" ? "user" : "assistant") as "user" | "assistant",
      content: x.content
    }));

    const userMsg: ChatMessage = {
      id: makeId("usr"),
      botId,
      role: "user",
      authorName: "You",
      content: opts.prompt,
      createdAt: Date.now()
    };
    setChatByBot((m) => ({ ...m, [botId]: [...(m[botId] ?? []), userMsg] }));

    try {
      const reply = await window.luminaraShell.sendBotMessage({
        requestId: reqId,
        botId,
        spaceId: opts.spaceId,
        activeTabId: opts.activeTabId,
        mode: opts.mode,
        prompt: opts.prompt,
        history: historySnapshot
      });
      setChatByBot((m) => ({ ...m, [botId]: [...(m[botId] ?? []), reply] }));
    } catch {
      setErrorByBot((prev) => ({
        ...prev,
        [botId]: "Could not complete the request. Check AI Setup or try again."
      }));
    } finally {
      if (activeReqByBot.current[botId] === reqId) {
        activeReqByBot.current[botId] = null;
      }
      setLoadingByBot((prev) => ({ ...prev, [botId]: false }));
    }
  };

  const abort = (botId: string) => {
    const reqId = activeReqByBot.current[botId];
    if (reqId) {
      void window.luminaraShell.abortBotMessage(reqId);
    }
  };

  const isBotLoading = (botId: string): boolean => Boolean(loadingByBot[botId]);
  const getBotError = (botId: string): string => errorByBot[botId] ?? "";

  return { chatByBot, isBotLoading, getBotError, sendMessage, abort };
}
