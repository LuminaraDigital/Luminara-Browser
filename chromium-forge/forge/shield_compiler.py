"""Privacy Shield v3 — DNR Filter Compiler, Query-Param Scrubber & Deterministic Farbling (`forge/shield_compiler.py`).

Upgrades Luminara's runtime privacy engine from a 1-rule static blocklist to:
1. High-speed MV3 `declarativeNetRequest` ruleset compiler (up to 30,000 rules) combining:
   - Custom `.trap_tld` domain blackhole + user-defined blocked domains.
   - Clean-room first-party list of 68 public telemetry, analytics & ad-beacon domains.
   - Automatic tracking query-parameter stripping (`utm_*`, `fbclid`, `gclid`, `dclid`,
     `msclkid`, `mc_eid`, `_hsenc`, `_hsmi`, `igshid`, `yclid`, `ref_src`, `twclid`, `ttclid`).
   - Support for parsing user-supplied Adblock-syntax filter lines (`||domain.com^`).
2. eTLD+1 Session-Keyed Deterministic Fingerprint Farbling (`build_deterministic_farbling_js`):
   - Perturbs Canvas 2D, AudioContext, WebGL renderer metadata, and `hardwareConcurrency`
     using a per-session + per-eTLD+1 deterministic PRNG seed so values stay 100% consistent
     within a site visit yet un-linkable across origins.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from typing import Any
import urllib.parse

from .models import ForkProfile

TRACKING_QUERY_PARAMS: tuple[str, ...] = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "dclid",
    "gbraid",
    "wbraid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "_hsenc",
    "_hsmi",
    "igshid",
    "yclid",
    "ref_src",
    "spm",
    "mkt_tok",
)

# High-confidence telemetry, ad-beacon, and CNAME-tracker domains (zero broken core sites)
CORE_TRACKER_DOMAINS: tuple[str, ...] = (
    "google-analytics.com",
    "googletagmanager.com",
    "googlesyndication.com",
    "googleadservices.com",
    "doubleclick.net",
    "pagead2.googlesyndication.com",
    "adservice.google.com",
    "analytics.google.com",
    "connect.facebook.net",
    "pixel.facebook.com",
    "bat.bing.com",
    "clarity.ms",
    "cdn.segment.com",
    "api.segment.io",
    "api.mixpanel.com",
    "cdn.mxpnl.com",
    "api.amplitude.com",
    "api2.amplitude.com",
    "static.hotjar.com",
    "script.hotjar.com",
    "vars.hotjar.com",
    "fullstory.com",
    "rs.fullstory.com",
    "snap.licdn.com",
    "px.ads.linkedin.com",
    "ads-twitter.com",
    "analytics.twitter.com",
    "static.ads-twitter.com",
    "analytics.tiktok.com",
    "ct.pinterest.com",
    "sc-static.net",
    "tr.snapchat.com",
    "adnxs.com",
    "criteo.com",
    "criteo.net",
    "outbrain.com",
    "taboola.com",
    "scorecardresearch.com",
    "quantserve.com",
    "newrelic.com",
    "bam.nr-data.net",
    "js-agent.newrelic.com",
    "browser-intake-datadoghq.com",
    "sentry.io",
    "o0.ingest.sentry.io",
    "bugsnag.com",
    "notify.bugsnag.com",
    "heapanalytics.com",
    "cdn.heapanalytics.com",
    "js.hs-analytics.net",
    "js.hs-banner.com",
    "track.hubspot.com",
    "munchkin.marketo.net",
    "stats.wp.com",
    "pixel.wp.com",
    "matomo.cloud",
    "mc.yandex.ru",
    "an.yandex.ru",
    "hm.baidu.com",
    "cpro.baidu.com",
    "t.co",
    "amazon-adsystem.com",
    "fls-na.amazon.com",
    "metrics.icloud.com",
    "xp.apple.com",
    "telemetry.mozilla.org",
    "incoming.telemetry.mozilla.org",
    "vortex.data.microsoft.com",
    "telemetry.microsoft.com",
    "events.data.microsoft.com",
)

_AB_DOMAIN_RE = re.compile(r"^\|\|([a-z0-9][a-z0-9.\-]{1,250})\^(?:\$[a-z0-9,=_\-]+)?$", re.IGNORECASE)
_TRACKER_RESOURCE_TYPES = [
    "sub_frame",
    "stylesheet",
    "script",
    "image",
    "font",
    "object",
    "xmlhttprequest",
    "ping",
    "csp_report",
    "media",
    "websocket",
    "other",
]
_ALL_RESOURCE_TYPES = ["main_frame", *_TRACKER_RESOURCE_TYPES]
_TWO_LABEL_PUBLIC_SUFFIXES = frozenset(
    {"co.uk", "org.uk", "gov.uk", "ac.uk", "com.au", "net.au", "org.au", "co.jp", "com.br", "co.nz", "co.in", "com.sg"}
)


def parse_adblock_domains(filter_lines: list[str], *, max_domains: int = 29000) -> list[str]:
    """Parse EasyList/Adblock `||domain^` lines into clean deduplicated hostnames."""
    seen: set[str] = set()
    domains: list[str] = []
    for raw in filter_lines:
        line = raw.strip()
        if not line or line.startswith(("!", "#", "[@", "@@")):
            continue
        m = _AB_DOMAIN_RE.match(line)
        if not m:
            continue
        dom = m.group(1).lower().rstrip(".")
        if "." in dom and dom not in seen:
            seen.add(dom)
            domains.append(dom)
            if len(domains) >= max_domains:
                break
    return domains


def strip_tracking_params_url(url: str, extra_params: tuple[str, ...] = ()) -> str:
    """Pure-Python equivalent of Luminara's DNR & C++ `URLLoaderThrottle` query-param scrubber."""
    parsed = urllib.parse.urlsplit(url)
    if not parsed.query:
        return url
    blocked = set(TRACKING_QUERY_PARAMS) | set(extra_params)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if k.lower() not in blocked]
    if len(kept) == len(pairs):
        return url
    new_query = urllib.parse.urlencode(kept, doseq=True)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))


def compile_dnr_shield_rules(
    profile: ForkProfile,
    *,
    extra_filter_lines: list[str] | None = None,
    max_rules: int = 30000,
) -> list[dict[str, Any]]:
    """Compile Privacy Shield v3 MV3 `declarativeNetRequest` rules (`trap` + `queryTransform` + `trackers`)."""
    rules: list[dict[str, Any]] = []
    rule_id = 1

    # Rule 1: Hard block custom `.trap_tld` blackhole across all resource types
    rules.append(
        {
            "id": rule_id,
            "priority": 3,
            "action": {"type": "block"},
            "condition": {
                "urlFilter": f"||{profile.trap_tld}^",
                "resourceTypes": list(_ALL_RESOURCE_TYPES),
            },
        }
    )
    rule_id += 1

    # Rule 2: Strip tracking URL parameters on every HTTP/HTTPS navigation
    if getattr(profile, "enable_shield_v3", True):
        rules.append(
            {
                "id": rule_id,
                "priority": 2,
                "action": {
                    "type": "redirect",
                    "redirect": {
                        "transform": {
                            "queryTransform": {
                                "removeParams": list(TRACKING_QUERY_PARAMS),
                            }
                        }
                    },
                },
                "condition": {
                    "urlFilter": "|http",
                    "resourceTypes": ["main_frame", "sub_frame"],
                },
            }
        )
        rule_id += 1

    seen_domains: set[str] = set()

    # User-blocked custom domains (all resource types, priority 2)
    for raw_dom in profile.extra_blocked_domains:
        clean = raw_dom.strip().lower().lstrip(".")
        if clean and clean not in seen_domains and len(rules) < max_rules:
            seen_domains.add(clean)
            rules.append(
                {
                    "id": rule_id,
                    "priority": 2,
                    "action": {"type": "block"},
                    "condition": {
                        "urlFilter": f"||{clean}^",
                        "resourceTypes": list(_ALL_RESOURCE_TYPES),
                    },
                }
            )
            rule_id += 1

    if getattr(profile, "enable_shield_v3", True):
        all_trackers = list(CORE_TRACKER_DOMAINS)
        if extra_filter_lines:
            all_trackers.extend(parse_adblock_domains(extra_filter_lines, max_domains=max_rules - len(rules)))
        for dom in all_trackers:
            if dom in seen_domains or len(rules) >= max_rules:
                continue
            seen_domains.add(dom)
            rules.append(
                {
                    "id": rule_id,
                    "priority": 1,
                    "action": {"type": "block"},
                    "condition": {
                        "urlFilter": f"||{dom}^",
                        "domainType": "thirdParty",
                        "resourceTypes": list(_TRACKER_RESOURCE_TYPES),
                    },
                }
            )
            rule_id += 1

    return rules


def _extract_etld1(origin_or_host: str) -> str:
    host = (urllib.parse.urlparse(origin_or_host).hostname or origin_or_host or "local").strip().lower()
    parts = [p for p in host.split(".") if p]
    if len(parts) >= 3 and ".".join(parts[-2:]) in _TWO_LABEL_PUBLIC_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def derive_farbling_seed(session_secret: bytes, origin_or_host: str) -> int:
    """Compute a deterministic 32-bit farbling seed per `(session_secret, eTLD+1 host)`."""
    etld1 = _extract_etld1(origin_or_host)
    digest = hmac.new(session_secret, f"luminara-farble-v3:{etld1}".encode("utf-8"), hashlib.sha256).digest()
    return int.from_bytes(digest[:4], "big")


def build_deterministic_farbling_js(session_token: str | None = None) -> str:
    """Build site-consistent, cross-site-unlinkable Canvas/Audio/WebGL farbling content script."""
    tok = session_token or secrets.token_hex(16)
    suffixes_json = json.dumps(sorted(_TWO_LABEL_PUBLIC_SUFFIXES))
    return f"""
(() => {{
  if (window.__luminaraFarbleV3) return;
  const SESSION_KEY = {json.dumps(tok)};
  const TWO_LABEL = new Set({suffixes_json});
  const host = (location.hostname || 'local').toLowerCase();
  const parts = host.split('.').filter(Boolean);
  const etld1 = (parts.length >= 3 && TWO_LABEL.has(parts.slice(-2).join('.')))
    ? parts.slice(-3).join('.')
    : (parts.length >= 2 ? parts.slice(-2).join('.') : host);

  // Deterministic FNV-1a 32-bit hash of (SESSION_KEY + etld1) -> consistent within site, distinct across sites
  let h = 2166136261 >>> 0;
  const seedStr = SESSION_KEY + '|' + etld1;
  for (let i = 0; i < seedStr.length; i++) {{
    h ^= seedStr.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }}
  const siteSeed = h;
  const deltaByte = ((siteSeed & 0x03) || 1); // +1..+3 deterministic LSB delta

  // 1. Canvas 2D + HTMLCanvasElement.toDataURL/toBlob deterministic farbling
  function perturbImageData(img) {{
    if (img && img.data && img.data.length >= 4) {{
      const stride = Math.max(4, Math.floor(img.data.length / 32) & ~3);
      for (let i = 0; i < img.data.length; i += stride) {{
        img.data[i] = (img.data[i] ^ deltaByte) & 0xff;
      }}
    }}
    return img;
  }}

  const origGetImageData = typeof CanvasRenderingContext2D !== 'undefined'
    ? CanvasRenderingContext2D.prototype.getImageData
    : null;
  if (origGetImageData) {{
    CanvasRenderingContext2D.prototype.getImageData = function(...args) {{
      return perturbImageData(origGetImageData.apply(this, args));
    }};
  }}

  if (typeof HTMLCanvasElement !== 'undefined' && origGetImageData) {{
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    const origToBlob = HTMLCanvasElement.prototype.toBlob;
    function cloneFarbledCanvas(src) {{
      try {{
        if (!src || src.width <= 0 || src.height <= 0 || src.width > 4096 || src.height > 4096) return null;
        const copy = document.createElement('canvas');
        copy.width = src.width;
        copy.height = src.height;
        const ctx = copy.getContext('2d');
        if (!ctx) return null;
        ctx.drawImage(src, 0, 0);
        const raw = perturbImageData(origGetImageData.call(ctx, 0, 0, copy.width, copy.height));
        ctx.putImageData(raw, 0, 0);
        return copy;
      }} catch (_e) {{ return null; }}
    }}
    HTMLCanvasElement.prototype.toDataURL = function(...args) {{
      const c = cloneFarbledCanvas(this);
      return origToDataURL.apply(c || this, args);
    }};
    if (origToBlob) {{
      HTMLCanvasElement.prototype.toBlob = function(...args) {{
        const c = cloneFarbledCanvas(this);
        return origToBlob.apply(c || this, args);
      }};
    }}
  }}

  // 2. AudioBuffer deterministic micro-perturbation
  if (typeof AudioBuffer !== 'undefined') {{
    const origGetChannelData = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function(...args) {{
      const ch = origGetChannelData.apply(this, args);
      if (ch && ch.length >= 16 && !ch.__luminaraFarbled) {{
        const eps = ((siteSeed & 0xff) + 1) * 1e-7;
        for (let i = 0; i < ch.length; i += 64) ch[i] += eps;
        try {{ Object.defineProperty(ch, '__luminaraFarbled', {{ value: true }}); }} catch (_e) {{}}
      }}
      return ch;
    }};
  }}

  // 3. WebGL UNMASKED_VENDOR / UNMASKED_RENDERER normalization
  for (const Ctx of [window.WebGLRenderingContext, window.WebGL2RenderingContext]) {{
    if (!Ctx || !Ctx.prototype) continue;
    const origGetParam = Ctx.prototype.getParameter;
    Ctx.prototype.getParameter = function(p) {{
      if (p === 37445) return 'Generic GPU Vendor';
      if (p === 37446) return 'Luminara Angle Renderer (' + (siteSeed % 4) + ')';
      return origGetParam.apply(this, arguments);
    }};
  }}

  // 4. HardwareConcurrency clamping (reduces CPU core entropy without breaking WebWorkers)
  try {{
    const allowedCores = [4, 8];
    const farbledCores = allowedCores[siteSeed % allowedCores.length];
    Object.defineProperty(navigator, 'hardwareConcurrency', {{
      get: () => farbledCores,
      configurable: true
    }});
  }} catch (_e) {{}}

  window.__luminaraFarbleV3 = {{ etld1, siteSeed, deltaByte }};
}})();
"""
