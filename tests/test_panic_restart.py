"""ری‌استارت اضطراری باید از ریشهٔ مخزن اجرا شود، نه از پوشهٔ بستهٔ bot."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from bot.handlers.hub import panic_restart_directory


class PanicRestartDirectoryTests(unittest.TestCase):
    def test_directory_is_repository_root(self) -> None:
        root = panic_restart_directory()
        self.assertTrue((root / "bot" / "main.py").is_file())
        self.assertTrue((root / "bot" / "handlers" / "hub.py").is_file())
        self.assertNotEqual(root, root / "bot")

    def test_exec_uses_repository_root_and_pythonpath(self) -> None:
        source = Path(panic_restart_directory() / "bot" / "handlers" / "hub.py").read_text()
        self.assertIn("panic_restart_directory()", source)
        self.assertIn("os.execve", source)
        self.assertNotIn("parent.parent)", source)

    def test_bot_main_resolves_from_repo_and_pythonpath_not_package_dir(self) -> None:
        root = panic_restart_directory()
        code = (
            "import importlib.util, sys; "
            "sys.exit(0 if importlib.util.find_spec('bot.main') else 1)"
        )
        clean = os.environ.copy()
        clean.pop("PYTHONPATH", None)
        from_repo = subprocess.run(
            [sys.executable, "-c", code],
            cwd=root,
            env=clean,
            capture_output=True,
            text=True,
        )
        from_package = subprocess.run(
            [sys.executable, "-c", code],
            cwd=root / "bot",
            env=clean,
            capture_output=True,
            text=True,
        )
        rescued_env = clean.copy()
        rescued_env["PYTHONPATH"] = str(root)
        rescued = subprocess.run(
            [sys.executable, "-c", code],
            cwd=root / "bot",
            env=rescued_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(from_repo.returncode, 0, from_repo.stderr[-300:])
        self.assertNotEqual(from_package.returncode, 0)
        self.assertIn("No module named 'bot'", from_package.stderr)
        self.assertEqual(rescued.returncode, 0, rescued.stderr[-300:])


if __name__ == "__main__":
    unittest.main()
