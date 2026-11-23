"""App-icon branding of the portable `chrome.exe` (`tests/test_exe_icon.py`)."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

from forge.exe_icon import LUMINARA_ICO, RT_GROUP_ICON, RT_ICON, build_group_icon, embed_app_icon, parse_ico, read_resources


class TestExeIcon(unittest.TestCase):
    def test_bundled_ico_covers_taskbar_and_explorer_sizes(self) -> None:
        sizes = {meta[0] or 256 for meta, _ in parse_ico(LUMINARA_ICO.read_bytes())}
        self.assertTrue({16, 24, 32, 48, 256} <= sizes)

    def test_group_icon_points_at_consecutive_rt_icon_ids(self) -> None:
        entries = parse_ico(LUMINARA_ICO.read_bytes())
        group = build_group_icon(entries, first_id=7)
        self.assertEqual(struct.unpack_from("<HHH", group, 0), (0, 1, len(entries)))
        ids = [struct.unpack_from("<H", group, 6 + 14 * i + 12)[0] for i in range(len(entries))]
        self.assertEqual(ids, list(range(7, 7 + len(entries))))

    def test_parse_ico_rejects_non_ico(self) -> None:
        with self.assertRaises(ValueError):
            parse_ico(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)

    @unittest.skipUnless(os.name == "nt", "UpdateResource is Windows-only")
    def test_embed_rebrands_every_group_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "app.exe"
            shutil.copyfile(getattr(sys, "_base_executable", sys.executable), exe)
            before = read_resources(exe, RT_GROUP_ICON)
            entries = parse_ico(LUMINARA_ICO.read_bytes())
            for _ in range(2):
                self.assertEqual(embed_app_icon(exe), len(before))
            groups = read_resources(exe, RT_GROUP_ICON)
            self.assertEqual(set(groups), set(before))
            self.assertTrue(all(data == build_group_icon(entries, first_id=1) for data in groups.values()))
            icons = read_resources(exe, RT_ICON)
            self.assertEqual(sorted(name for name, _ in icons), list(range(1, len(entries) + 1)))
            self.assertEqual(icons[(1, next(iter(before))[1])], entries[0][1])


if __name__ == "__main__":
    unittest.main()
