import { clipboard, Menu, type MenuItemConstructorOptions, type WebContents } from "electron";

export function attachTabContextMenu(
  wc: WebContents,
  opts: {
    spaceId: string;
    onOpenLinkNewTab: (spaceId: string, url: string, background: boolean) => void;
  }
): void {
  wc.on("context-menu", (_ev, params) => {
    const items: MenuItemConstructorOptions[] = [];

    if (params.linkURL && /^https?:\/\//i.test(params.linkURL)) {
      items.push(
        {
          label: "Open Link in New Tab",
          click: () => opts.onOpenLinkNewTab(opts.spaceId, params.linkURL, false)
        },
        {
          label: "Open Link in Background Tab",
          click: () => opts.onOpenLinkNewTab(opts.spaceId, params.linkURL, true)
        },
        {
          label: "Copy Link Address",
          click: () => clipboard.writeText(params.linkURL)
        },
        { type: "separator" }
      );
    }

    if (params.selectionText) {
      items.push({ label: "Copy", role: "copy" });
    }
    if (params.isEditable) {
      items.push(
        { label: "Cut", role: "cut" },
        { label: "Paste", role: "paste" },
        { label: "Select All", role: "selectAll" }
      );
    }
    if (params.selectionText || params.isEditable) {
      items.push({ type: "separator" });
    }

    items.push(
      {
        label: "Back",
        enabled: wc.navigationHistory.canGoBack(),
        click: () => wc.navigationHistory.goBack()
      },
      {
        label: "Forward",
        enabled: wc.navigationHistory.canGoForward(),
        click: () => wc.navigationHistory.goForward()
      },
      {
        label: "Reload",
        click: () => wc.reload()
      },
      { type: "separator" },
      {
        label: "Inspect Element",
        click: () => {
          if (!wc.isDestroyed()) wc.inspectElement(params.x, params.y);
        }
      }
    );

    Menu.buildFromTemplate(items).popup();
  });
}
