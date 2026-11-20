"""Upstream `chromium/chromium` Blobless Sparse Checkout & Patch Verifier (`forge/chromium_src.py`).

Solves the 60 GB / 150 GB local disk barrier safely on constrained drives (`< 90 MB` footprint):
- Uses `git clone --filter=blob:none --no-checkout --depth=1 --sparse` to mirror only the exact
  upstream C++/Mojom/Blink directories targeted by Luminara & ungoogled-chromium patches.
- Verifies custom `.patch` hunks and version provenance directly against real upstream files.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .models import ForkProfile
from .patcher import apply_patch_in_memory, parse_unified_diff

ENCODING = "utf-8"
UPSTREAM_CHROMIUM_URL = "https://github.com/chromium/chromium.git"

# Tight sparse-checkout cone covering Luminara C++ patch targets (< 80 MB total on NTFS)
DEFAULT_SPARSE_PATHS: tuple[str, ...] = (
    "chrome/browser/ui/views/side_panel",
    "chrome/browser/ui/webui",
    "components/os_crypt",
    "components/version_ui",
    "content/public/common",
    "services/network/public/cpp",
    "third_party/search_engines_data/resources/definitions",
)


def free_disk_gb(path: Path) -> float:
    probe = path if path.exists() else path.parent
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return round(usage.free / (1024**3), 2)


def directory_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return round(total / (1024**2), 2)


def _run_git(args: list[str], cwd: Path | None = None, timeout: float = 180.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding=ENCODING,
        errors="replace",
        timeout=timeout,
        check=False,
    )


def ensure_sparse_chromium_checkout(
    target_dir: Path,
    *,
    tag: str | None = None,
    sparse_paths: tuple[str, ...] = DEFAULT_SPARSE_PATHS,
    min_free_gb: float = 2.0,
) -> dict[str, Any]:
    """Create or update a `< 90 MB` blobless sparse checkout of `chromium/chromium`."""
    target_dir = target_dir.resolve()
    avail_gb = free_disk_gb(target_dir)
    if avail_gb < min_free_gb:
        raise RuntimeError(
            f"Refusing sparse checkout: only {avail_gb:.2f} GB free (need >= {min_free_gb:.2f} GB)"
        )

    git_dir = target_dir / ".git"
    created = False
    if not git_dir.exists():
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        clone_args = [
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            "--depth=1",
            "--sparse",
        ]
        if tag:
            clone_args.extend(["--branch", tag])
        clone_args.extend([UPSTREAM_CHROMIUM_URL, str(target_dir)])
        res = _run_git(clone_args, timeout=240.0)
        if res.returncode != 0 and tag:
            # Fallback to default branch if exact tag isn't mirrored yet on GitHub
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            fallback_args = [
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                "--depth=1",
                "--sparse",
                UPSTREAM_CHROMIUM_URL,
                str(target_dir),
            ]
            res = _run_git(fallback_args, timeout=240.0)
        if res.returncode != 0:
            raise RuntimeError(f"git sparse clone failed: {(res.stderr or res.stdout).strip()[:400]}")
        created = True

    sp_init = _run_git(["sparse-checkout", "init", "--cone"], cwd=target_dir)
    if sp_init.returncode != 0:
        raise RuntimeError(f"sparse-checkout init failed: {sp_init.stderr.strip()}")

    sp_set = _run_git(["sparse-checkout", "set", *sparse_paths], cwd=target_dir)
    if sp_set.returncode != 0:
        raise RuntimeError(f"sparse-checkout set failed: {sp_set.stderr.strip()}")

    co = _run_git(["checkout"], cwd=target_dir, timeout=240.0)
    if co.returncode != 0:
        raise RuntimeError(f"sparse checkout materialization failed: {(co.stderr or co.stdout).strip()[:400]}")

    head = _run_git(["rev-parse", "--short", "HEAD"], cwd=target_dir)
    version_file = target_dir / "chrome" / "VERSION"
    upstream_version = version_file.read_text(encoding=ENCODING).strip() if version_file.exists() else ""

    present_paths = [p for p in sparse_paths if (target_dir / p).exists()]
    return {
        "ok": True,
        "created": created,
        "target_dir": str(target_dir),
        "head_commit": head.stdout.strip(),
        "upstream_version": upstream_version,
        "sparse_paths_present": present_paths,
        "disk_used_mb": directory_size_mb(target_dir),
        "disk_free_gb_after": free_disk_gb(target_dir),
    }


def verify_patches_against_upstream(
    patches_dir: Path,
    chromium_src_dir: Path,
) -> dict[str, Any]:
    """Validate Luminara patch syntax and anchor target presence against `vendor/chromium-src`."""
    patches_dir = patches_dir.resolve()
    chromium_src_dir = chromium_src_dir.resolve()
    series_path = patches_dir / "series"
    patch_files: list[Path] = []
    if series_path.exists():
        for raw in series_path.read_text(encoding=ENCODING).splitlines():
            clean = raw.strip()
            if clean and not clean.startswith("#"):
                patch_files.append(patches_dir / clean)
    else:
        patch_files = sorted(patches_dir.glob("*.patch"))

    src_ready = (chromium_src_dir / ".git").exists()
    results: list[dict[str, Any]] = []
    all_ok = True
    for pf in patch_files:
        if not pf.exists():
            results.append({"patch": pf.name, "valid_diff": False, "error": "missing_file"})
            all_ok = False
            continue
        text = pf.read_text(encoding=ENCODING)
        try:
            parsed = parse_unified_diff(text, source_name=pf.name)
            targets = [fp.new_path if fp.new_path != "/dev/null" else fp.old_path for fp in parsed]
            upstream_hits = [t for t in targets if (chromium_src_dir / t).exists()]
            hunks_verified = src_ready
            hunk_errors: list[str] = []
            if src_ready:
                if len(upstream_hits) != len(targets):
                    hunks_verified = False
                    all_ok = False
                    hunk_errors.append("missing_target_in_sparse_checkout")
                else:
                    files_map = {
                        t: (chromium_src_dir / t).read_text(encoding=ENCODING).splitlines()
                        for t in targets
                    }
                    try:
                        apply_patch_in_memory(files_map, text, source_name=pf.name)
                    except Exception as hunk_exc:  # noqa: BLE001
                        hunks_verified = False
                        all_ok = False
                        hunk_errors.append(str(hunk_exc))
            results.append(
                {
                    "patch": pf.name,
                    "valid_diff": True,
                    "hunks_verified": hunks_verified,
                    "files_touched": targets,
                    "upstream_files_found": upstream_hits,
                    "upstream_checked": src_ready,
                    **({"errors": hunk_errors} if hunk_errors else {}),
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append({"patch": pf.name, "valid_diff": False, "error": str(exc)})
            all_ok = False

    return {
        "ok": all_ok,
        "patch_count": len(patch_files),
        "chromium_src_available": src_ready,
        "results": results,
    }


def audit_version_provenance(
    profile: ForkProfile,
    core_repo: Path,
    cache_dir: Path,
    chromium_src_dir: Path | None = None,
) -> dict[str, Any]:
    """Cross-check declared Chromium version across `fork.json`, `ungoogled-chromium`, and `cache/`."""
    ug_ver_file = core_repo / "chromium_version.txt"
    ug_version = ug_ver_file.read_text(encoding=ENCODING).strip() if ug_ver_file.exists() else ""
    cached_zips = sorted(p.name for p in cache_dir.glob("*.zip")) if cache_dir.exists() else []
    exact_cache_match = any(profile.chromium_version in name for name in cached_zips)
    major = profile.chromium_version.split(".", 1)[0]
    major_cache_match = any(f"_{major}." in name for name in cached_zips)
    sparse_info: dict[str, Any] = {"present": False}
    if chromium_src_dir and (chromium_src_dir / ".git").exists():
        head = _run_git(["rev-parse", "--short", "HEAD"], cwd=chromium_src_dir)
        sparse_info = {
            "present": True,
            "path": str(chromium_src_dir),
            "head_commit": head.stdout.strip(),
            "disk_used_mb": directory_size_mb(chromium_src_dir),
        }

    warnings: list[str] = []
    if ug_version and ug_version != profile.chromium_version:
        warnings.append(f"fork.json ({profile.chromium_version}) differs from ungoogled-chromium ({ug_version})")
    if cached_zips and not exact_cache_match:
        warnings.append(
            f"Portable binary cache ({cached_zips[0]}) minor-patch differs from source target ({profile.chromium_version}); major M{major} aligned."
        )

    return {
        "fork_chromium_version": profile.chromium_version,
        "ungoogled_chromium_version": ug_version,
        "cached_portable_archives": cached_zips,
        "exact_cache_match": exact_cache_match,
        "major_aligned": major_cache_match or not cached_zips,
        "sparse_checkout": sparse_info,
        "warnings": warnings,
    }


def save_provenance_manifest(report: dict[str, Any], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding=ENCODING, newline="\n")
    return out_path
