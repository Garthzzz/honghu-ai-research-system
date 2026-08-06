from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release.runtime_environment import (
    canonical_distribution_name,
    lockfile_pins,
    verify_runtime,
)


class _Distribution:
    def __init__(self, name: str, version: str):
        self.metadata = {"Name": name}
        self.version = version


def _pip_check(*_args, **_kwargs):
    return subprocess.CompletedProcess([], 0, stdout="No broken requirements found.\n")


class RuntimeEnvironmentTests(unittest.TestCase):
    def _lockfile(self, root: Path, lines: list[str]) -> Path:
        path = root / "requirements.lock.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_standard_distribution_name_canonicalization(self):
        equivalent = {
            "Backports.TarFile",
            "backports-tarfile",
            "backports_tarfile",
            "BACKPORTS...TARFILE",
        }
        self.assertEqual(
            {canonical_distribution_name(name) for name in equivalent},
            {"backports-tarfile"},
        )

    def test_lockfile_and_installed_metadata_use_same_canonical_names(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = self._lockfile(
                Path(temp),
                [
                    "backports-tarfile==1.2.0 \\",
                    "jaraco-classes==3.4.0 \\",
                    "jaraco_context==6.1.2 \\",
                    "JARACO.FUNCTOOLS==4.6.0 \\",
                ],
            )
            self.assertEqual(
                lockfile_pins(lock),
                {
                    "backports-tarfile": "1.2.0",
                    "jaraco-classes": "3.4.0",
                    "jaraco-context": "6.1.2",
                    "jaraco-functools": "4.6.0",
                },
            )
            installed = [
                _Distribution("backports.tarfile", "1.2.0"),
                _Distribution("jaraco.classes", "3.4.0"),
                _Distribution("JARACO.CONTEXT", "6.1.2"),
                _Distribution("jaraco_funCtools", "4.6.0"),
            ]
            with patch(
                "tools.release.runtime_environment.importlib.metadata.distributions",
                return_value=installed,
            ), patch(
                "tools.release.runtime_environment.subprocess.run",
                side_effect=_pip_check,
            ):
                result = verify_runtime(lock, required_python=sys.version_info[:2])
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["mismatches"], [])
            self.assertTrue(result["pip_check"]["ok"])
            self.assertTrue(Path(result["base_python_executable"]).is_file())
            self.assertTrue(Path(result["site_packages"]).is_dir())

    def test_missing_and_version_mismatch_still_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = self._lockfile(
                Path(temp),
                ["present-package==1.0", "missing.package==2.0"],
            )
            with patch(
                "tools.release.runtime_environment.importlib.metadata.distributions",
                return_value=[_Distribution("present_package", "0.9")],
            ), patch(
                "tools.release.runtime_environment.subprocess.run",
                side_effect=_pip_check,
            ):
                result = verify_runtime(lock, required_python=sys.version_info[:2])
            self.assertFalse(result["ok"])
            self.assertEqual(
                result["mismatches"],
                [
                    {"package": "missing-package", "expected": "2.0", "actual": None},
                    {"package": "present-package", "expected": "1.0", "actual": "0.9"},
                ],
            )

    def test_pip_check_failure_remains_a_runtime_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = self._lockfile(Path(temp), ["example-package==1.0"])
            broken = subprocess.CompletedProcess(
                [], 1, stdout="example-package has requirement dependency>=2, but 1 is installed.\n"
            )
            with patch(
                "tools.release.runtime_environment.importlib.metadata.distributions",
                return_value=[_Distribution("example.package", "1.0")],
            ), patch(
                "tools.release.runtime_environment.subprocess.run",
                return_value=broken,
            ):
                result = verify_runtime(lock, required_python=sys.version_info[:2])
            self.assertFalse(result["ok"])
            self.assertEqual(result["mismatches"], [])
            self.assertFalse(result["pip_check"]["ok"])
            self.assertIn("pip check failed", result["failures"])

    def test_conflicting_equivalent_lockfile_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = self._lockfile(
                Path(temp),
                ["example.package==1.0", "EXAMPLE_package==2.0"],
            )
            with self.assertRaisesRegex(ValueError, "conflicting pins"):
                lockfile_pins(lock)


if __name__ == "__main__":
    unittest.main()
