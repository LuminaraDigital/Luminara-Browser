"""Automated REA Obligation & Regression Test Suite (`tests/test_rea_obligations.py`)."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from forge.customizer import (
    build_merged_gn_flags,
    compile_fork_overlay,
    validate_gn_flags_text,
)
from forge.domsub import (
    DomainRegexSet,
    apply_domain_substitution,
    generate_standalone_domsub_script,
    revert_domain_substitution,
)
from forge.downloads import (
    HashMismatchError,
    SchemaValidationError,
    extract_archive,
    parse_downloads_ini,
    verify_cached_downloads,
)
from forge.models import ForkProfile
from forge.packager import collect_official_outputs, create_portable_archive
from forge.patcher import (
    apply_patch_series,
    audit_patch_directory,
    merge_patch_directories,
)
from forge.pruner import KEEP_FILES, prune_source_tree, scan_source_lists

STUDIO_ROOT = Path(__file__).resolve().parent.parent.parent
CORE_REPO = STUDIO_ROOT / "ungoogled-chromium"
WIN_REPO = STUDIO_ROOT / "ungoogled-chromium-windows"


class TestREAReconstructionObligations(unittest.TestCase):
    def test_obl01_downloads_schema_and_bug5_traversal_guard(self) -> None:
        ver = (CORE_REPO / "chromium_version.txt").read_text(encoding="utf-8").strip()
        core_entries = parse_downloads_ini([CORE_REPO / "downloads.ini"], ver)
        self.assertEqual(len(core_entries), 1)
        self.assertIn(ver, core_entries[0].download_filename)

        win_entries = parse_downloads_ini([WIN_REPO / "downloads.ini"], ver)
        self.assertGreaterEqual(len(win_entries), 15)

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.ini"
            bad.write_text(
                "[x]\nurl=https://a.example/x.tgz\ndownload_filename=x.tgz\noutput_path=../../etc\n",
                encoding="utf-8",
            )
            with self.assertRaises(SchemaValidationError):
                parse_downloads_ini([bad], ver)

            good = Path(tmp) / "good.ini"
            good.write_text(
                "[x]\nurl=https://a.example/x.tgz\ndownload_filename=x.tgz\noutput_path=sub\nsha256=0000\n",
                encoding="utf-8",
            )
            (Path(tmp) / "x.tgz").write_bytes(b"payload")
            entries = parse_downloads_ini([good], ver)
            with self.assertRaises(HashMismatchError):
                verify_cached_downloads(entries, Path(tmp))

    def test_obl01_tar_xz_and_plain_tar_bug4_fix(self) -> None:
        import io
        import tarfile

        with tempfile.TemporaryDirectory() as tmp:
            tpath = Path(tmp)
            for ext, mode in ((".tar", "w"), (".tar.xz", "w:xz")):
                arc = tpath / f"sample{ext}"
                with tarfile.open(str(arc), mode) as tf:
                    data = b"hello world\n"
                    info = tarfile.TarInfo(name="lead/inner/file.txt")
                    info.size = len(data)
                    tf.addfile(info, io.BytesIO(data))
                out = tpath / f"out_{ext.replace('.', '_')}"
                extract_archive(arc, out, strip_leading_dirs="lead")
                self.assertEqual((out / "inner" / "file.txt").read_bytes(), b"hello world\n")

    def test_obl02_pruner_windows_keep_files_bug1_fix_and_scanner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            for keep in KEEP_FILES:
                f = src / Path(keep)
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("keep me", encoding="utf-8")
            (src / "v8" / "test" / "drop.bin").write_bytes(b"\x00\x01\x02\xff")
            (src / "net" / "client.cc").parent.mkdir(parents=True, exist_ok=True)
            (src / "net" / "client.cc").write_text('const char* u = "https://www.google.com";\n', encoding="utf-8")
            (src / "third_party" / "tool.exe").parent.mkdir(parents=True, exist_ok=True)
            (src / "third_party" / "tool.exe").write_bytes(b"MZ\x00\x90\xff")

            regex_set = DomainRegexSet.from_file(CORE_REPO / "domain_regex.list")
            prune_list, domsub_list = scan_source_lists(src, regex_set.combined_search)
            self.assertIn("third_party/tool.exe", prune_list)
            self.assertIn("net/client.cc", domsub_list)

            rep = prune_source_tree(src, prune_list, keep_contingent_paths=False)
            self.assertEqual(rep.missing_files, [])
            for keep in KEEP_FILES:
                self.assertTrue((src / Path(keep)).exists(), f"KEEP_FILE deleted on Windows: {keep}")
            self.assertFalse((src / "v8" / "test" / "drop.bin").exists())
            self.assertFalse((src / "third_party" / "tool.exe").exists())

    def test_obl03_patch_audit_python_and_git_apply_revert_and_merge(self) -> None:
        core_audit = audit_patch_directory(CORE_REPO / "patches")
        win_audit = audit_patch_directory(WIN_REPO / "patches")
        self.assertTrue(core_audit.ok, f"Core patch audit failed: {core_audit}")
        self.assertTrue(win_audit.ok, f"Windows patch audit failed: {win_audit}")
        self.assertEqual(core_audit.total_series_entries, 108)

        with tempfile.TemporaryDirectory() as tmp:
            w = Path(tmp)
            p1 = w / "p1"
            p2 = w / "p2"
            p1.mkdir()
            p2.mkdir()
            patch_body = (
                "--- a/hello.cc\n"
                "+++ b/hello.cc\n"
                "@@ -1,3 +1,3 @@\n"
                " int a = 1;\n"
                "-int b = 2;\n"
                "+int b = 42;\n"
                " int c = 3;\n"
            )
            (p1 / "step1.patch").write_text(patch_body, encoding="utf-8", newline="\n")
            (p1 / "series").write_text("step1.patch\n", encoding="utf-8", newline="\n")
            (p2 / "step2.patch").write_text(
                "--- /dev/null\n+++ b/added.h\n@@ -0,0 +1,2 @@\n+#pragma once\n+#define OK 1\n",
                encoding="utf-8",
                newline="\n",
            )
            (p2 / "series").write_text("step2.patch # inline comment\n", encoding="utf-8", newline="\n")

            merged = w / "merged"
            count = merge_patch_directories(merged, [p1, p2])
            self.assertEqual(count, 2)

            src = w / "src"
            src.mkdir()
            (src / "hello.cc").write_text("int a = 1;\nint b = 2;\nint c = 3;\n", encoding="utf-8", newline="\n")
            apply_patch_series(src, [merged], prefer_python_engine=True)
            self.assertIn("int b = 42;", (src / "hello.cc").read_text(encoding="utf-8"))
            self.assertTrue((src / "added.h").exists())

            apply_patch_series(src, [merged], reverse=True, prefer_python_engine=True)
            self.assertIn("int b = 2;", (src / "hello.cc").read_text(encoding="utf-8"))
            self.assertFalse((src / "added.h").exists())

    def test_obl04_domsub_crlf_latin1_crc32_tamper_and_perl_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            w = Path(tmp)
            src = w / "src"
            src.mkdir()
            # Include ISO-8859-1 byte 0xE9 ('é') + CRLF endings
            orig_bytes = b"// Caf\xe9 author\r\nconst char* g = \"https://fonts.googleapis.com/css\";\r\n"
            f = src / "ui.cc"
            f.write_bytes(orig_bytes)
            orig_mtime = f.stat().st_mtime_ns

            rset = DomainRegexSet(["fonts(\\*?)\\.googleapis(\\*?)\\.com#f0ntz\\g<1>.9oo91e8p1\\g<2>.void0"])
            cache = w / "cache.tar.xz"  # Tests Bug #4 .tar.xz fix!
            rep = apply_domain_substitution(rset, ["ui.cc"], src, cache)
            self.assertEqual(rep.modified_files, 1)
            subbed = f.read_bytes()
            self.assertIn(b"f0ntz.9oo91e8p1.void0", subbed)
            self.assertIn(b"\xe9", subbed)
            self.assertIn(b"\r\n", subbed)
            self.assertEqual(f.stat().st_mtime_ns, orig_mtime + 1_000_000_000)

            # Tamper check
            f.write_bytes(subbed + b"// tampered")
            with self.assertRaises(KeyError):
                revert_domain_substitution(cache, src)

            f.write_bytes(subbed)
            os.utime(f, ns=(orig_mtime + 1_000_000_000, orig_mtime + 1_000_000_000))
            revert_domain_substitution(cache, src)
            self.assertEqual(f.read_bytes(), orig_bytes)

            sh_out = w / "domsub.sh"
            generate_standalone_domsub_script(
                ["fonts(\\*?)\\.googleapis(\\*?)\\.com#f0ntz\\g<1>.9oo91e8p1\\g<2>.void0"],
                ["ui.cc"],
                sh_out,
                backup_mode="quilt",
            )
            self.assertNotIn(b"\r\n", sh_out.read_bytes())

    def test_obl05_06_07_customizer_gn_bug7_and_packager(self) -> None:
        # Bug #7: duplicate key on line 1 & line 2 must be caught!
        errs = validate_gn_flags_text("alpha=1\nalpha=2\n", require_sorted=True)
        self.assertTrue(any("Duplicate GN flag key" in e for e in errs))

        prof = ForkProfile(
            brand_name="Nebula Browser",
            slug="nebula-browser",
            channel_tag="nebula-sec",
            trap_tld="void0",
            default_search="brave",
            extra_blocked_domains=["telemetry.badcorp.com"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            w = Path(tmp)
            compiled = compile_fork_overlay(prof, CORE_REPO, WIN_REPO, w / "overlay")
            self.assertTrue(compiled["args_gn"].exists())
            gn_errs = validate_gn_flags_text(compiled["args_gn"].read_text(encoding="utf-8"))
            self.assertEqual(gn_errs, [])
            self.assertIn("brave.com", compiled["search_patch"].read_text(encoding="utf-8"))
            self.assertIn(".void0", compiled["domain_regex"].read_text(encoding="utf-8"))

            cfg = w / "FILES.cfg"
            cfg.write_text(
                "FILES = [{'filename': 'chrome.exe', 'buildtype': ['official']}, "
                "{'filename': 'chrome.pdb', 'buildtype': ['official']}]\n",
                encoding="utf-8",
            )
            out = w / "out"
            out.mkdir()
            (out / "chrome.exe").write_bytes(b"MZ")
            (out / "chrome.pdb").write_bytes(b"PDB")
            rels = collect_official_outputs(cfg, out)
            self.assertEqual([r.as_posix() for r in rels], ["chrome.exe"])
            arc = create_portable_archive(rels, out, w / "pkg.zip", deterministic_timestamp=1700000000)
            self.assertTrue(arc.exists())


if __name__ == "__main__":
    unittest.main()
