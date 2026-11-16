# Chromium Forge (`ungoogled-chromium` Clean-Room Engine & Customizer)

Clean-room Python 3.12 reconstruction and fork customizer for `ungoogled-software/ungoogled-chromium` (Chromium `157.0.8103.78`) and `ungoogled-software/ungoogled-chromium-windows`, built and verified using **REA (Reverse Engineer Anything)** 7-Stage Epistemic Discipline.

## Quick Start

```powershell
cd C:\Users\lumin\.gemini\antigravity\scratch\ungoogled-chromium-studio\chromium-forge

# 1. Create/update your custom fork profile & compile C++/GN overlay
python -m forge init --brand "Apex Chromium" --slug "apex-chromium" --trap-tld "void0" --search "duckduckgo"

# 2. Build an immediately runnable customized Windows x64 portable browser (<30s)
python -m forge build-portable

# 3. Launch your customized browser directly
.\dist\apex-chromium-win64\Launch-apex-chromium.cmd

# 4. Run the REA 7-Obligation Verification Gate + Unit Tests
python -m unittest discover -s tests -v
python -m forge verify-rea

# 5. Open the interactive Chromium Forge Studio Cockpit (http://127.0.0.1:8795)
python -m forge studio
```

## Two Ways to Build & Customize

| Mode | Speed & Disk | What Gets Customized | Command |
| :--- | :--- | :--- | :--- |
| **Mode A: Instant Portable Distribution** | ~15s · ~500 MB | Branded offline New Tab UI, default privacy search engine, Manifest V3 `.trap` TLD firewall extension, `initial_preferences`, portable DPAPI/Machine-ID vault (`--disable-encryption`, `--disable-machine-id`), canvas/client-rects anti-fingerprinting switches | `python -m forge build-portable` |
| **Mode B: Full C++ Source Compilation** | ~16–30h · ~150 GB (or Free on GitHub Actions) | Compile-time `14,266` binary pruning, `108` core + `26` Windows Quilt `-p1` patches, C++ `URLRequest` `.<trap_tld>` -> `trk:` blackhole, `prepopulated_engines.json` ID-1 replacement, `version_ui_strings.grdp` branding, sorted `args.gn`, `mini_installer.exe` + `.zip` | `python -m forge export-windows-overlay` then run `build.py` or `.github/workflows/cloud-build-windows.yml` |

## Architecture (`forge/`)

- `forge/models.py` — Typed `ForkProfile` & search presets (`duckduckgo`, `brave`, `startpage`, `searxng`, `kagi`, `nosearch`, or `custom`).
- `forge/downloads.py` — `downloads.ini` schema validator, `.hashes` double-space digest checker, `.partial` resumable fetcher, and Windows-safe streaming tar/zip unpacker.
- `forge/pruner.py` — `pruning.list` + `CONTINGENT_PATHS` stripper (preserving `KEEP_FILES` with `.as_posix()` on Windows) + binary/domain tree scanner.
- `forge/patcher.py` — Quilt `series` auditor, Git `patch.exe` + pure-Python zero-fuzz unified diff applier, reverser, and platform merger.
- `forge/domsub.py` — `#`-delimited regex substitutor (`UTF-8` / `ISO-8859-1` byte-exact roundtrip), `+1s`/`-1s` nanosecond `utime` preservation, and CRC32 tamper-checked `domsubcache` revert engine.
- `forge/customizer.py` — Compiles `fork.json` into zero-fuzz C++/JSON/GRDP patches, custom `domain_regex.list`, sorted `args.gn`, and 16-stage GitHub Actions cloud builder YAML.
- `forge/packager.py` — Safe AST `FILES.cfg` parser & deterministic `.zip`/`.tar.xz` packager.
- `forge/portable.py` — Assembles runnable portable Windows x64 distributions + PE header & headless DOM verification.
- `forge/studio.py` & `forge/ui/index.html` — Local HTTP control plane (`127.0.0.1:8787`).
