import type { ShieldStatus } from "../shared/types";

export const TRACKER_DOMAINS: readonly string[] = [
  "doubleclick.net",
  "googlesyndication.com",
  "googleadservices.com",
  "google-analytics.com",
  "googletagmanager.com",
  "googletagservices.com",
  "pagead2.googlesyndication.com",
  "adservice.google.com",
  "analytics.google.com",
  "connect.facebook.net",
  "pixel.facebook.com",
  "an.facebook.com",
  "ads-twitter.com",
  "static.ads-twitter.com",
  "analytics.twitter.com",
  "ads.linkedin.com",
  "px.ads.linkedin.com",
  "snap.licdn.com",
  "analytics.tiktok.com",
  "ads.tiktok.com",
  "tr.snapchat.com",
  "sc-static.net",
  "bat.bing.com",
  "clarity.ms",
  "c.bing.com",
  "ads.yahoo.com",
  "analytics.yahoo.com",
  "amazon-adsystem.com",
  "fls-na.amazon.com",
  "adnxs.com",
  "rubiconproject.com",
  "pubmatic.com",
  "openx.net",
  "criteo.com",
  "criteo.net",
  "taboola.com",
  "outbrain.com",
  "mgid.com",
  "revcontent.com",
  "sharethrough.com",
  "casalemedia.com",
  "indexww.com",
  "lijit.com",
  "bidswitch.net",
  "smartadserver.com",
  "serving-sys.com",
  "adsrvr.org",
  "demdex.net",
  "omtrdc.net",
  "everesttech.net",
  "krxd.net",
  "bluekai.com",
  "exelator.com",
  "rlcdn.com",
  "tapad.com",
  "agkn.com",
  "scorecardresearch.com",
  "quantserve.com",
  "quantcount.com",
  "comscore.com",
  "imrworldwide.com",
  "chartbeat.com",
  "chartbeat.net",
  "newrelic.com",
  "nr-data.net",
  "hotjar.com",
  "hotjar.io",
  "fullstory.com",
  "mouseflow.com",
  "crazyegg.com",
  "luckyorange.com",
  "mixpanel.com",
  "amplitude.com",
  "segment.io",
  "segment.com",
  "heapanalytics.com",
  "kissmetrics.com",
  "intercom.io",
  "hubspot.com",
  "hs-analytics.net",
  "hs-scripts.com",
  "hsadspixel.net",
  "marketo.net",
  "mktoresp.com",
  "pardot.com",
  "branch.io",
  "app.link",
  "adjust.com",
  "appsflyer.com",
  "kochava.com",
  "sentry.io",
  "bugsnag.com",
  "datadoghq.com",
  "browser-intake-datadoghq.com",
  "optimizely.com",
  "vwo.com",
  "bounceexchange.com",
  "klaviyo.com",
  "doubleverify.com",
  "moatads.com",
  "iasds01.com"
];

const TRACKING_QUERY_EXACT = new Set([
  "fbclid",
  "gclid",
  "gbraid",
  "wbraid",
  "dclid",
  "mc_cid",
  "mc_eid",
  "yclid",
  "igshid",
  "msclkid",
  "_hsenc",
  "_hsmi",
  "mkt_tok",
  "vero_id",
  "ref_src",
  "oly_anon_id",
  "oly_enc_id"
]);

const MULTI_PART_TLDS = new Set([
  "co.uk",
  "org.uk",
  "gov.uk",
  "ac.uk",
  "com.au",
  "net.au",
  "org.au",
  "co.nz",
  "co.jp",
  "ne.jp",
  "or.jp",
  "com.br",
  "com.cn",
  "com.sg",
  "com.mx",
  "co.in",
  "co.kr",
  "co.za"
]);

export type ShieldDecision =
  | { action: "allow" }
  | { action: "block"; reason: string }
  | { action: "redirect"; redirectURL: string; strippedCount: number };

export function normalizeDomain(input: string): string {
  try {
    const parsed = input.includes("://") ? new URL(input) : new URL(`https://${input}`);
    return parsed.hostname.toLowerCase().replace(/^www\./, "");
  } catch {
    return input.trim().toLowerCase().replace(/^www\./, "");
  }
}

export function getRegistrableDomain(hostname: string): string {
  const clean = normalizeDomain(hostname);
  if (!clean || clean === "localhost" || /^[\d.]+$/.test(clean) || clean.includes(":")) {
    return clean;
  }
  const parts = clean.split(".").filter(Boolean);
  if (parts.length <= 2) return clean;
  const lastTwo = `${parts[parts.length - 2]}.${parts[parts.length - 1]}`;
  if (MULTI_PART_TLDS.has(lastTwo) && parts.length >= 3) {
    return `${parts[parts.length - 3]}.${lastTwo}`;
  }
  return lastTwo;
}

export function isTrackerHost(hostname: string): boolean {
  const host = hostname.toLowerCase();
  for (const tracker of TRACKER_DOMAINS) {
    if (host === tracker || host.endsWith(`.${tracker}`)) {
      return true;
    }
  }
  return false;
}

export function stripTrackingParams(rawUrl: string): { cleanedUrl: string; strippedCount: number } {
  try {
    const parsed = new URL(rawUrl);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return { cleanedUrl: rawUrl, strippedCount: 0 };
    }
    const keysToDelete: string[] = [];
    for (const key of parsed.searchParams.keys()) {
      const lower = key.toLowerCase();
      if (lower.startsWith("utm_") || TRACKING_QUERY_EXACT.has(lower)) {
        keysToDelete.push(key);
      }
    }
    if (keysToDelete.length === 0) return { cleanedUrl: rawUrl, strippedCount: 0 };
    for (const key of keysToDelete) parsed.searchParams.delete(key);
    return { cleanedUrl: parsed.toString(), strippedCount: keysToDelete.length };
  } catch {
    return { cleanedUrl: rawUrl, strippedCount: 0 };
  }
}

const REDIRECT_LOOP_WINDOW_MS = 5_000;

export class PrivacyShieldManager {
  private readonly pausedDomains = new Set<string>();
  private readonly tabBlockedCounts = new Map<string, number>();
  private readonly recentRedirects = new Map<string, number>();
  private totalBlocked = 0;

  public isDomainPaused(domain: string): boolean {
    const norm = normalizeDomain(domain);
    return norm.length > 0 && this.pausedDomains.has(norm);
  }

  public toggleDomain(domain: string): boolean {
    const norm = normalizeDomain(domain);
    if (!norm) return false;
    if (this.pausedDomains.has(norm)) {
      this.pausedDomains.delete(norm);
      return false;
    }
    this.pausedDomains.add(norm);
    return true;
  }

  public resetTabCount(tabId: string): void {
    this.tabBlockedCounts.set(tabId, 0);
  }

  public removeTab(tabId: string): void {
    this.tabBlockedCounts.delete(tabId);
  }

  public getTabBlockedCount(tabId: string): number {
    return this.tabBlockedCounts.get(tabId) ?? 0;
  }

  public evaluateRequest(
    url: string,
    pageDomain: string,
    resourceType: string,
    tabId: string | null,
    method = "GET"
  ): ShieldDecision {
    if (!url.startsWith("http://") && !url.startsWith("https://")) {
      return { action: "allow" };
    }

    const effectivePage = resourceType === "mainFrame" ? url : pageDomain;
    const normalizedPage = normalizeDomain(effectivePage);
    if (normalizedPage && this.pausedDomains.has(normalizedPage)) {
      return { action: "allow" };
    }

    let reqHost = "";
    try {
      reqHost = new URL(url).hostname.toLowerCase();
    } catch {
      return { action: "allow" };
    }

    if (reqHost === "localhost" || reqHost === "127.0.0.1" || reqHost === "[::1]") {
      return { action: "allow" };
    }

    const reqBase = getRegistrableDomain(reqHost);
    const pageBase = normalizedPage ? getRegistrableDomain(normalizedPage) : "";
    const isThirdParty = !pageBase || reqBase !== pageBase;

    if (resourceType !== "mainFrame" && isThirdParty && isTrackerHost(reqHost)) {
      this.recordBlocked(tabId, 1);
      return { action: "block", reason: `Blocked third-party tracker ${reqHost}` };
    }

    if (method.toUpperCase() === "GET" && resourceType === "mainFrame") {
      const { cleanedUrl, strippedCount } = stripTrackingParams(url);
      if (strippedCount > 0 && cleanedUrl !== url) {
        const now = Date.now();
        const loopKey = `${tabId ?? "global"}|${cleanedUrl}`;
        const prevTs = this.recentRedirects.get(loopKey);
        if (prevTs !== undefined && now - prevTs < REDIRECT_LOOP_WINDOW_MS) {
          return { action: "allow" };
        }
        this.recentRedirects.set(loopKey, now);
        this.pruneRecentRedirects(now);
        this.recordBlocked(tabId, strippedCount);
        return { action: "redirect", redirectURL: cleanedUrl, strippedCount };
      }
    }

    return { action: "allow" };
  }

  public getStatus(activeTabId: string | null, activeUrl: string): ShieldStatus {
    const activeDomain = activeUrl.startsWith("http") ? normalizeDomain(activeUrl) : "";
    return {
      totalBlocked: this.totalBlocked,
      pausedDomains: Array.from(this.pausedDomains).sort(),
      activeTabBlocked: activeTabId ? this.getTabBlockedCount(activeTabId) : 0,
      activeDomain,
      activeDomainPaused: activeDomain ? this.pausedDomains.has(activeDomain) : false
    };
  }

  private recordBlocked(tabId: string | null, delta: number): void {
    this.totalBlocked += delta;
    if (tabId) {
      this.tabBlockedCounts.set(tabId, (this.tabBlockedCounts.get(tabId) ?? 0) + delta);
    }
  }

  private pruneRecentRedirects(now: number): void {
    if (this.recentRedirects.size < 120) return;
    for (const [key, ts] of this.recentRedirects.entries()) {
      if (now - ts >= REDIRECT_LOOP_WINDOW_MS) this.recentRedirects.delete(key);
    }
  }
}
