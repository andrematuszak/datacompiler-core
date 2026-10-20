import os
import subprocess
import sys
import unittest
from pathlib import Path


class PackageImportTests(unittest.TestCase):
    def test_root_import_does_not_initialize_paddle(self):
        project_root = Path(__file__).parents[1]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(project_root / "src")
        result = subprocess.run(
            [sys.executable, "-c", "import sys, datacompiler; "
             "from datacompiler.frontend.ocr import BACKENDS; "
             "assert {'extract_document', 'diagnose_document', 'run_ocr', "
             "'resolve_document', 'run_pipeline', 'display_report'} <= set(datacompiler.__all__); "
             "from datacompiler import display_report; "
             "from datacompiler.frontend import report; "
             "assert display_report is report.display_report; "
             "assert report.afficher is report.display_report; "
             "import datacompiler.backend; "
             "assert 'paddle' in BACKENDS; "
             "assert 'tesseract' not in BACKENDS; "
             "assert 'pymupdf' not in sys.modules; "
             "assert not any(m == 'paddle' or m.startswith('paddle.') for m in sys.modules)"],
            cwd=project_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
