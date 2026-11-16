"""Typed domain models and preset configurations for Chromium Forge."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class SearchEngineSpec:
    key: str
    name: str
    keyword: str
    search_url: str
    suggest_url: str = ""
    favicon_url: str = "about:blank"
    new_tab_url: str = "about:blank"


SEARCH_ENGINE_PRESETS: dict[str, SearchEngineSpec] = {
    "duckduckgo": SearchEngineSpec(
        key="duckduckgo",
        name="DuckDuckGo",
        keyword="ddg",
        search_url="https://duckduckgo.com/?q={searchTerms}&kp=-2",
        suggest_url="https://ac.duckduckgo.com/ac/?q={searchTerms}&type=list",
    ),
    "brave": SearchEngineSpec(
        key="brave",
        name="Brave Search",
        keyword="brave",
        search_url="https://search.brave.com/search?q={searchTerms}",
        suggest_url="https://search.brave.com/api/suggest?q={searchTerms}",
    ),
    "startpage": SearchEngineSpec(
        key="startpage",
        name="Startpage",
        keyword="sp",
        search_url="https://www.startpage.com/do/dsearch?query={searchTerms}",
        suggest_url="https://www.startpage.com/osuggestions?q={searchTerms}",
    ),
    "searxng": SearchEngineSpec(
        key="searxng",
        name="SearXNG",
        keyword="searx",
        search_url="https://searx.be/search?q={searchTerms}",
    ),
    "kagi": SearchEngineSpec(
        key="kagi",
        name="Kagi",
        keyword="kagi",
        search_url="https://kagi.com/search?q={searchTerms}",
        suggest_url="https://kagi.com/api/autosuggest?q={searchTerms}",
    ),
    "nosearch": SearchEngineSpec(
        key="nosearch",
        name="No Search",
        keyword="nosearch",
        search_url="http://{searchTerms}",
    ),
}


_TLD_RE = re.compile(r"^[a-z0-9]{3,16}$")
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+\-.]{1,15}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")
_BAD_SWITCH_CHARS = re.compile(r"""["'`$&|;<>()\r\n]""")


@dataclass
class ForkProfile:
    """Declarative specification of a customized ungoogled-chromium / Luminara Browser fork."""

    brand_name: str = "Luminara Browser"
    slug: str = "luminara-browser"
    channel_tag: str = "luminara-agentic"
    chromium_version: str = "157.0.8103.78"
    fork_revision: str = "2"
    trap_tld: str = "void0"
    trap_scheme: str = "trk"
    default_search: str = "duckduckgo"
    custom_search_name: str = ""
    custom_search_keyword: str = ""
    custom_search_url: str = ""
    custom_suggest_url: str = ""
    portable_mode: bool = True
    canvas_noise: bool = True
    client_rects_noise: bool = True
    webgl_spoof: bool = False
    popups_to_tabs: bool = True
    force_punycode: bool = True
    allow_crx_install: bool = True
    keep_manifest_v2: bool = True
    block_third_party_cookies: bool = True
    disable_webrtc_leak: bool = True
    clear_data_on_exit: bool = False
    enable_widevine: bool = True
    proprietary_codecs: bool = True
    enable_agent_cobrowsing: bool = True
    cdp_port: int = 9229
    agent_port: int = 8796
    target_cpu: str = "x64"
    extra_gn_flags: dict[str, str] = field(default_factory=dict)
    extra_cli_switches: list[str] = field(default_factory=list)
    extra_blocked_domains: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.brand_name.strip():
            raise ValueError("brand_name must be non-empty")
        if not _SLUG_RE.match(self.slug):
            raise ValueError(f"Invalid slug {self.slug!r}: must be 2-49 lowercase alphanumeric/hyphen chars")
        if not str(self.fork_revision).isdigit() or not (0 <= int(self.fork_revision) <= 65535):
            raise ValueError(f"Invalid fork_revision {self.fork_revision!r}: must be 0..65535")
        if not _TLD_RE.match(self.trap_tld):
            raise ValueError(f"Invalid trap_tld {self.trap_tld!r}: must be 3-16 lowercase alphanumeric chars")
        if not _SCHEME_RE.match(self.trap_scheme):
            raise ValueError(f"Invalid trap_scheme {self.trap_scheme!r}")
        if self.target_cpu not in ("x64", "x86", "arm64"):
            raise ValueError(f"Unsupported target_cpu: {self.target_cpu!r}")
        if not (1024 <= int(self.cdp_port) <= 65535) or not (1024 <= int(self.agent_port) <= 65535):
            raise ValueError("cdp_port and agent_port must be between 1024 and 65535")
        if int(self.cdp_port) == int(self.agent_port):
            raise ValueError("cdp_port and agent_port must be distinct ports")
        for sw in self.extra_cli_switches:
            if _BAD_SWITCH_CHARS.search(sw):
                raise ValueError(f"Unsafe shell metacharacter in extra_cli_switches: {sw!r}")
        if self.default_search != "custom" and self.default_search not in SEARCH_ENGINE_PRESETS:
            raise ValueError(f"Unknown default_search preset: {self.default_search!r}")
        if self.default_search == "custom" and "{searchTerms}" not in self.custom_search_url:
            raise ValueError("custom_search_url must contain '{searchTerms}'")

    def resolved_search_engine(self) -> SearchEngineSpec:
        if self.default_search == "custom":
            return SearchEngineSpec(
                key="custom",
                name=self.custom_search_name or f"{self.brand_name} Search",
                keyword=self.custom_search_keyword or self.slug,
                search_url=self.custom_search_url,
                suggest_url=self.custom_suggest_url,
            )
        return SEARCH_ENGINE_PRESETS[self.default_search]

    def runtime_switches(self) -> list[str]:
        switches: list[str] = [
            "--no-default-browser-check",
            "--no-pings",
            "--disable-background-networking",
            "--disable-Breakpad",
            "--disable-component-update",
            "--disable-domain-reliability",
        ]
        if self.portable_mode:
            switches.extend(["--disable-encryption", "--disable-machine-id"])
        if self.canvas_noise:
            switches.append("--fingerprinting-canvas-image-data-noise")
        if self.client_rects_noise:
            switches.append("--fingerprinting-client-rects-noise")
        if self.webgl_spoof:
            switches.append("--ungoogled-webgl-renderer=Generic GPU")
        if self.popups_to_tabs:
            switches.append("--popups-to-tabs")
        if self.force_punycode:
            switches.append("--force-punycode-hostnames")
        if self.allow_crx_install:
            switches.append("--extension-mime-request-handling=always-prompt-for-install")
        for extra in self.extra_cli_switches:
            clean = extra.strip()
            if clean:
                switches.append(clean if clean.startswith("--") else f"--{clean}")
        return switches

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: Path) -> None:
        self.validate()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8", newline="\n")

    @classmethod
    def load(cls, path: Path) -> "ForkProfile":
        raw = json.loads(path.read_text(encoding="utf-8"))
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in raw.items() if k in allowed}
        profile = cls(**filtered)
        profile.validate()
        return profile


@dataclass
class ObligationResult:
    obligation_id: str
    title: str
    confidence: str
    upstream_evidence: str
    passed: bool
    details: str
    metrics: dict[str, Any] = field(default_factory=dict)
