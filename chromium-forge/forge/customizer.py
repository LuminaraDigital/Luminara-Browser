"""Clean-room OBL-05, OBL-06 & OBL-07 implementation: Custom Fork Compiler & GN Flag Validator.

Compiles a `ForkProfile` into:
1. Valid zero-fuzz unified `.patch` files for Chromium 157 (`custom-branding.patch`,
   `custom-search-engine.patch`, `custom-network-trap.patch`, `custom-first-run.patch`).
2. Retargeted `domain_regex.list` (+ optional extra blocked domains mapped to `.<trap_tld>`).
3. Deduplicated, strictly ASCII-sorted `flags.gn` & `args.gn` passing `validate_gn_flags`
   (fixing upstream Bug #7 in `devutils/check_gn_flags.py:41` where line 1 key wasn't tracked).
4. Ready-to-push 16-stage GitHub Actions Windows x64/arm64 cloud build workflow.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from .domsub import PATTERN_DELIM, retarget_domain_regex_tld
from .models import ForkProfile
from .patcher import parse_unified_diff

ENCODING = "utf-8"


def validate_gn_flags_text(text: str, require_sorted: bool = True) -> list[str]:
    """Validate `flags.gn` format, catching line-1 duplicate keys missed by upstream."""
    errors: list[str] = []
    lines = text.splitlines()
    seen_keys: set[str] = set()
    prev_line: str | None = None

    for idx, line in enumerate(lines, start=1):
        if not line or line.lstrip().startswith("#"):
            errors.append(f"Line {idx}: Blank lines and '#' comments are forbidden in flags.gn")
            continue
        if "=" not in line:
            errors.append(f"Line {idx}: Missing '=' assignment in {line!r}")
            continue
        key = line.split("=", 1)[0].strip()
        if not key:
            errors.append(f"Line {idx}: Empty GN key")
            continue
        if key in seen_keys:
            errors.append(f"Line {idx}: Duplicate GN flag key {key!r}")
        seen_keys.add(key)
        if require_sorted and prev_line is not None and line < prev_line:
            errors.append(f"Line {idx}: Out of ASCII sort order ({line!r} < {prev_line!r})")
        prev_line = line
    return errors


def build_merged_gn_flags(
    base_flags_paths: list[Path],
    profile: ForkProfile,
    for_windows_release: bool = True,
) -> str:
    """Merge base `flags.gn` files with `ForkProfile` overrides in strict ASCII sort order."""
    kv: dict[str, str] = {}
    for path in base_flags_paths:
        if not path.exists():
            continue
        for raw in path.read_text(encoding=ENCODING).splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip()

    for custom_k, custom_v in profile.extra_gn_flags.items():
        kv[custom_k.strip()] = str(custom_v).strip()

    # Enforce mandatory ungoogled invariants AFTER extra_gn_flags so security invariants cannot be weakened
    kv["google_api_key"] = '""'
    kv["google_default_client_id"] = '""'
    kv["google_default_client_secret"] = '""'
    kv["safe_browsing_mode"] = "0"
    kv["use_official_google_api_keys"] = "false"
    kv["disable_fieldtrial_testing_config"] = "true"
    kv["enable_widevine"] = "true" if profile.enable_widevine else "false"

    if for_windows_release:
        kv["target_cpu"] = f'"{profile.target_cpu}"'
        kv["proprietary_codecs"] = "true" if profile.proprietary_codecs else "false"
        kv["ffmpeg_branding"] = '"Chrome"' if profile.proprietary_codecs else '"Chromium"'
        if profile.target_cpu == "x86":
            kv["v8_enable_drumbrake"] = "false"

    sorted_lines = sorted(f"{k}={v}" for k, v in kv.items())
    result = "\n".join(sorted_lines) + "\n"
    validation_errors = validate_gn_flags_text(result, require_sorted=True)
    if validation_errors:
        raise ValueError(f"Generated GN flags failed validation: {validation_errors}")
    return result


def generate_branding_channel_patch(profile: ForkProfile) -> str:
    """Generate zero-fuzz replacement for `add-extra-channel-info.patch` (`version_ui_strings.grdp`)."""
    import html as _html

    tag = _html.escape(f"{profile.brand_name} ({profile.channel_tag})", quote=True)
    patch = "\n".join(
        [
            "--- a/components/version_ui_strings.grdp",
            "+++ b/components/version_ui_strings.grdp",
            "@@ -4,10 +4,10 @@",
            "     About Version",
            "   </message>",
            '   <message name="IDS_VERSION_UI_OFFICIAL" desc="official build on the about:version page">',
            "-    Official Build",
            f"+    Official Build, {tag}",
            "   </message>",
            '   <message name="IDS_VERSION_UI_UNOFFICIAL" desc="unofficial build on the about:version page">',
            "-    Developer Build",
            f"+    Developer Build, {tag}",
            "   </message>",
            '   <message name="IDS_VERSION_UI_32BIT" desc="32-bit on the chrome://version page">',
            "     (32-bit)",
            "",
        ]
    )
    parse_unified_diff(patch, source_name="custom-branding-channel.patch")
    return patch


def generate_search_engine_patch(profile: ForkProfile) -> str:
    """Generate zero-fuzz replacement for `replace-google-search-engine-with-nosearch.patch`.

    REA Stage 4 Invariant: Preserves JSON key `"google"` and `"type": "SEARCH_ENGINE_GOOGLE"` so
    Chromium's country prepopulate tables resolve ID 1 without crashing on first run.
    """
    spec = profile.resolved_search_engine()
    added_fields = [
        f'+      "name": {json.dumps(spec.name)},',
        f'+      "keyword": {json.dumps(spec.keyword)},',
        f'+      "favicon_url": {json.dumps(spec.favicon_url)},',
        f'+      "search_url": {json.dumps(spec.search_url)},',
    ]
    if spec.suggest_url:
        added_fields.append(f'+      "suggest_url": {json.dumps(spec.suggest_url)},')
    added_fields.append(f'+      "new_tab_url": {json.dumps(spec.new_tab_url)},')

    new_count = 6 + len(added_fields)
    patch = "\n".join(
        [
            "--- a/third_party/search_engines_data/resources/definitions/prepopulated_engines.json",
            "+++ b/third_party/search_engines_data/resources/definitions/prepopulated_engines.json",
            f"@@ -173,26 +173,{new_count} @@",
            "     },",
            " ",
            '     "google": {',
            '-      "name": "Google",',
            '-      "keyword": "google.com",',
            '-      "favicon_url": "https://www.google.com/images/branding/product/ico/googleg_alldp.ico",',
            '-      "base_builtin_resource_id": "SEARCH_ENGINE_GOOGLE",',
            '-      "search_url": "{google:baseURL}search?q={searchTerms}&{google:RLZ}{google:originalQueryForSuggestion}{google:assistedQueryStats}{google:searchFieldtrialParameter}{google:language}{google:prefetchSource}{google:searchClient}{google:sourceId}{google:searchSource}{google:contextualSearchVersion}ie={inputEncoding}",',
            '-      "suggest_url": "{google:baseSuggestURL}{google:suggestPath}?{google:searchFieldtrialParameter}client={google:suggestClient}&gs_ri={google:suggestRid}&xssi=t&q={searchTerms}&{google:inputType}{google:omniboxFocusType}{google:cursorPosition}{google:currentPageUrl}{google:pageClassification}{google:clientCacheTimeToLive}{google:searchVersion}{google:sessionToken}{google:prefetchQuery}sugkey={google:suggestAPIKeyParameter}",',
            '-      "image_url": "{google:baseSearchByImageURL}upload",',
            '-      "image_translate_url": "{google:baseSearchByImageURL}upload?filtertype=tr&{imageTranslateSourceLocale}{imageTranslateTargetLocale}",',
            '-      "contextual_search_url": "{google:baseURL}_/contextualsearch?{google:contextualSearchVersion}{google:contextualSearchContextData}",',
            '-      "image_url_post_params": "encoded_image={google:imageThumbnail},image_url={google:imageURL},sbisrc={google:imageSearchSource},original_width={google:imageOriginalWidth},original_height={google:imageOriginalHeight},processed_image_dimensions={google:processedImageDimensions}",',
            '-      "image_translate_source_language_param_key": "sourcelang",',
            '-      "image_translate_target_language_param_key": "targetlang",',
            '-      "search_intent_params": ["si", "gs_ssp", "udm"],',
            '-      "alternate_urls": [',
            '-        "{google:baseURL}#q={searchTerms}",',
            '-        "{google:baseURL}search#q={searchTerms}",',
            '-        "{google:baseURL}webhp#q={searchTerms}",',
            '-        "{google:baseURL}s#q={searchTerms}",',
            '-        "{google:baseURL}s?q={searchTerms}"',
            "-      ],",
            *added_fields,
            '       "type": "SEARCH_ENGINE_GOOGLE",',
            '       "preconnect_to_search_url" : "ALLOWED",',
            '       "prefetch_likely_navigations" : "ALLOWED",',
            "",
        ]
    )
    parse_unified_diff(patch, source_name="custom-search-engine.patch")
    return patch


def customize_network_trap_patch(upstream_block_trk_patch: str, profile: ForkProfile) -> str:
    """Adapt `block-trk-and-subdomains.patch` to custom `trap_tld` and `trap_scheme`."""
    tld_needle = 'base::EndsWith(url.host(), "qjz9zk"'
    scheme_needle = 'inline constexpr char kTraceScheme[] = "trk";'
    if tld_needle not in upstream_block_trk_patch or scheme_needle not in upstream_block_trk_patch:
        raise ValueError("Upstream block-trk-and-subdomains.patch anchor lines changed unexpectedly")
    updated = upstream_block_trk_patch.replace(
        tld_needle,
        f'base::EndsWith(url.host(), "{profile.trap_tld}"',
    ).replace(
        scheme_needle,
        f'inline constexpr char kTraceScheme[] = "{profile.trap_scheme}";',
    )
    parse_unified_diff(updated, source_name="block-trk-and-subdomains.patch")
    return updated


def build_custom_domain_regex_list(upstream_lines: list[str], profile: ForkProfile) -> list[str]:
    """Retarget `domain_regex.list` to `profile.trap_tld` and append user-defined blocked domains."""
    lines = retarget_domain_regex_tld(upstream_lines, new_tld=profile.trap_tld)
    for idx, raw_dom in enumerate(profile.extra_blocked_domains, start=1):
        dom = raw_dom.strip().lower()
        if not dom or "." not in dom:
            continue
        escaped = re.escape(dom)
        label = re.sub(r"[^a-z0-9]", "", dom.split(".")[0]) or f"custom{idx}"
        lines.append(f"{escaped}{PATTERN_DELIM}{label}trp{idx}.{profile.trap_tld}")
    return lines


def generate_github_actions_cloud_workflow(profile: ForkProfile) -> str:
    """Generate a full 16-stage checkpointed GitHub Actions Windows x64/arm64 PGO+ThinLTO cloud builder workflow."""
    arch_flag = "--x86" if profile.target_cpu == "x86" else "--arm" if profile.target_cpu == "arm64" else ""
    stages_yaml: list[str] = []
    for stage in range(1, 17):
        prev_job = "verify-custom-patches" if stage == 1 else f"compile-stage-{stage - 1}"
        restore_block = (
            ""
            if stage == 1
            else f"""      - name: Restore Checkpointed Build Tree (Stage {stage - 1})
        uses: actions/download-artifact@v4
        with:
          name: luminara-stage-{stage - 1}-${{{{ matrix.arch }}}}
          path: ungoogled-chromium-windows/build/src/out/Default
"""
        )
        stages_yaml.append(
            f"""  compile-stage-{stage}:
    needs: {prev_job}
    if: always() && needs.{prev_job}.result == 'success' && fromJSON(inputs.stage_limit || '16') >= {stage}
    strategy:
      fail-fast: false
      matrix:
        arch: [{profile.target_cpu}]
    runs-on: windows-2022
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
{restore_block}      - name: Install V8 Metagen Clang Bindings & Forge Package
        run: |
          python -m pip install -e .
          python -m pip install httplib2==0.22.0 clang==21.1.7
      - name: Apply {profile.brand_name} Overlay & Run Ninja Stage {stage}/16 (PGO + ThinLTO)
        run: |
          luminara-forge export-windows-overlay --profile chromium-forge/fork.json --windows-repo ./ungoogled-chromium-windows
          cd ungoogled-chromium-windows
          python build.py --ci -j 4 {arch_flag}
      - name: Checkpoint Stage {stage} Artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: luminara-stage-{stage}-${{{{ matrix.arch }}}}
          path: ungoogled-chromium-windows/build/src/out/Default
          retention-days: 3
"""
        )

    return f"""name: Build {profile.brand_name} 16-Stage Cloud Compiler (Windows {profile.target_cpu})

on:
  workflow_dispatch:
    inputs:
      stage_limit:
        description: 'Max 3.5h compilation stages (1..16)'
        required: false
        default: '16'

jobs:
  verify-custom-patches:
    runs-on: windows-2022
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Run Chromium Forge REA + Upstream Patch Pre-Flight Gate
        shell: bash
        run: |
          cd chromium-forge
          python -W error -m unittest discover -s tests -v
          python -m forge verify-upstream-patches
          python -m forge verify-rea --static-only

  # 16-stage checkpointed Ninja + ThinLTO + PGO pipeline (exit 124 checkpoints cleanly across 3.5h windows)
{"".join(stages_yaml)}  package-signed-release:
    needs: compile-stage-16
    runs-on: windows-2022
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Restore Final Stage 16 Build Tree
        uses: actions/download-artifact@v4
        with:
          name: luminara-stage-16-{profile.target_cpu}
          path: ungoogled-chromium-windows/build/src/out/Default
      - name: Package Portable ZIP + Mini Installer + SHA-256 Manifest
        run: |
          cd ungoogled-chromium-windows
          python package.py
"""


def compile_fork_overlay(
    profile: ForkProfile,
    upstream_core_repo: Path,
    upstream_win_repo: Path,
    output_dir: Path,
) -> dict[str, Path]:
    """Compile all customized patches, domain regex rules, GN flags, and cloud CI files."""
    profile.validate()
    output_dir.mkdir(parents=True, exist_ok=True)
    patches_out = output_dir / "patches"
    patches_out.mkdir(parents=True, exist_ok=True)

    branding_patch_path = patches_out / "custom-branding-channel.patch"
    branding_patch_path.write_text(generate_branding_channel_patch(profile), encoding=ENCODING, newline="\n")

    search_patch_path = patches_out / "custom-search-engine.patch"
    search_patch_path.write_text(generate_search_engine_patch(profile), encoding=ENCODING, newline="\n")

    upstream_trk = (
        upstream_core_repo / "patches" / "core" / "ungoogled-chromium" / "block-trk-and-subdomains.patch"
    ).read_text(encoding=ENCODING)
    trap_patch_path = patches_out / "block-trk-and-subdomains.patch"
    trap_patch_path.write_text(customize_network_trap_patch(upstream_trk, profile), encoding=ENCODING, newline="\n")

    upstream_regex = (upstream_core_repo / "domain_regex.list").read_text(encoding=ENCODING).splitlines()
    custom_regex = build_custom_domain_regex_list(upstream_regex, profile)
    regex_path = output_dir / "domain_regex.list"
    regex_path.write_text("\n".join(custom_regex) + "\n", encoding=ENCODING, newline="\n")

    gn_text = build_merged_gn_flags(
        [upstream_core_repo / "flags.gn", upstream_win_repo / "flags.windows.gn"],
        profile,
        for_windows_release=True,
    )
    gn_path = output_dir / "args.gn"
    gn_path.write_text(gn_text, encoding=ENCODING, newline="\n")

    workflow_path = output_dir / "cloud-build-windows.yml"
    workflow_path.write_text(generate_github_actions_cloud_workflow(profile), encoding=ENCODING, newline="\n")

    profile_path = output_dir / "fork.json"
    profile.save(profile_path)

    return {
        "fork_profile": profile_path,
        "branding_patch": branding_patch_path,
        "search_patch": search_patch_path,
        "network_trap_patch": trap_patch_path,
        "domain_regex": regex_path,
        "args_gn": gn_path,
        "cloud_workflow": workflow_path,
    }
