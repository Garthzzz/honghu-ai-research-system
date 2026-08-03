from __future__ import annotations

import ctypes
import os
import tempfile
import unittest
from pathlib import Path

from tools.portable_paths import canonical_path, relative_path


@unittest.skipUnless(os.name == "nt", "Windows alias contract")
class WindowsPortablePathTests(unittest.TestCase):
    @staticmethod
    def _short_path(path: Path) -> Path:
        size = ctypes.windll.kernel32.GetShortPathNameW(str(path), None, 0)
        if not size:
            raise unittest.SkipTest("8.3 aliases are unavailable on this volume")
        buffer = ctypes.create_unicode_buffer(size)
        written = ctypes.windll.kernel32.GetShortPathNameW(
            str(path), buffer, size
        )
        if not written or "~" not in buffer.value:
            raise unittest.SkipTest("8.3 aliases are unavailable on this path")
        return Path(buffer.value)

    def test_relative_path_accepts_long_and_short_aliases_for_same_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            long_root = canonical_path(Path(temp))
            child = long_root / "papers" / "fixture.pdf"
            child.parent.mkdir(parents=True)
            child.write_bytes(b"fixture")
            short_root = self._short_path(long_root)

            self.assertEqual(
                relative_path(child, short_root).as_posix(),
                "papers/fixture.pdf",
            )

    def test_relative_path_still_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            outside = Path(temp) / "outside.txt"
            root.mkdir()
            outside.write_text("outside", encoding="utf-8")

            with self.assertRaises(ValueError):
                relative_path(outside, root)


if __name__ == "__main__":
    unittest.main()
