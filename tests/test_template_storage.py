import os
import shutil
import unittest
from pathlib import Path

from app.services.template_storage import ensure_template_storage_dir, resolve_storage_path, to_storage_path


class TemplateStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_cwd = Path.cwd()
        self.temp_root = self.original_cwd / "tests_tmp"
        self.temp_root.mkdir(exist_ok=True)
        self.temp_dir = self.temp_root / self._testMethodName
        self.temp_dir.mkdir(exist_ok=True)
        os.chdir(self.temp_dir)

    def tearDown(self) -> None:
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ensure_template_storage_dir_creates_report_templates_folder(self) -> None:
        ensure_template_storage_dir()

        self.assertTrue((Path.cwd() / "report_templates").exists())

    def test_to_storage_path_returns_relative_posix_path(self) -> None:
        file_path = Path.cwd() / "report_templates" / "target_test_report.html"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()

        result = to_storage_path(file_path)

        self.assertEqual("report_templates/target_test_report.html", result)

    def test_resolve_storage_path_returns_absolute_path_for_relative_value(self) -> None:
        relative_path = "report_templates/comparative_report.html"

        result = resolve_storage_path(relative_path)

        self.assertEqual(Path.cwd() / relative_path, result)


if __name__ == "__main__":
    unittest.main()
