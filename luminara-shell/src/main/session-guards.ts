import { session, type Session } from "electron";
import type { PrivacyShieldManager } from "./privacy-shield";
import type { MutationFirewallManager } from "./mutation-firewall";
import type { TabRecord } from "../shared/types";

export const BENIGN_WEB_PERMISSIONS = new Set([
  "fullscreen",
  "clipboard-sanitized-write"
]);

export interface SessionGuardDeps {
  shield: PrivacyShieldManager;
  firewall: MutationFirewallManager;
  resolveTabByWebContents: (wcId: number) => TabRecord | null;
  getActiveMutationState: () => {
    tabId: string | null;
    bot: { id: string; name: string; color: string } | null;
  };
  onBlockedChange: () => void;
  onToast: (message: string) => void;
}

export function isWebPermissionAllowed(permission: string): boolean {
  return BENIGN_WEB_PERMISSIONS.has(permission);
}

export function hardenShellSession(shellSession: Session): void {
  shellSession.setPermissionCheckHandler(() => false);
  shellSession.setPermissionRequestHandler((_wc, _permission, callback) => {
    callback(false);
  });
}

export function attachSessionGuards(partition: string, deps: SessionGuardDeps): void {
  const ses = session.fromPartition(partition);

  ses.setPermissionCheckHandler((_wc, permission) => isWebPermissionAllowed(permission));
  ses.setPermissionRequestHandler((_wc, permission, callback) => {
    callback(isWebPermissionAllowed(permission));
  });

  ses.on("will-download", (_ev, item) => {
    const filename = item.getFilename() || "file";
    deps.onToast(`Downloading ${filename}…`);
    item.once("done", (_doneEv, state) => {
      if (state === "completed") {
        deps.onToast(`Downloaded ${filename}`);
      } else if (state !== "cancelled") {
        deps.onToast(`Download failed: ${filename}`);
      }
    });
  });

  ses.webRequest.onBeforeRequest((details, callback) => {
    const tab = details.webContentsId
      ? deps.resolveTabByWebContents(details.webContentsId)
      : null;
    const tabId = tab?.id ?? null;
    // On mainFrame navigations, compute first-party domain from the destination URL (not stale previous tab URL)
    const pageDomain =
      details.resourceType === "mainFrame"
        ? details.url
        : (tab?.url ?? details.referrer ?? details.url);

    const shieldDecision = deps.shield.evaluateRequest(
      details.url,
      pageDomain,
      details.resourceType,
      tabId,
      details.method
    );
    if (shieldDecision.action === "block") {
      deps.onBlockedChange();
      callback({ cancel: true });
      return;
    }
    if (shieldDecision.action === "redirect") {
      deps.onBlockedChange();
      callback({ redirectURL: shieldDecision.redirectURL });
      return;
    }

    const activeMut = deps.getActiveMutationState();
    const isBotInitiated = Boolean(tabId && activeMut.tabId === tabId);
    const reqCtx = {
      url: details.url,
      method: details.method,
      resourceType: details.resourceType,
      tabId,
      botId: isBotInitiated ? (activeMut.bot?.id ?? null) : null,
      botName: isBotInitiated ? (activeMut.bot?.name ?? "Bot") : "Active Page",
      botColor: isBotInitiated ? (activeMut.bot?.color ?? "#16A095") : "#199473",
      isBotInitiated,
      uploadData: details.uploadData
    };

    if (!deps.firewall.shouldIntercept(reqCtx)) {
      callback({ cancel: false });
      return;
    }
    void deps.firewall
      .requestApproval(reqCtx)
      .then((allowed) => callback({ cancel: !allowed }))
      .catch(() => callback({ cancel: true }));
  });
}
