import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from datacompiler.backend import EXTENSIONS, FORMATS, _strategy_for_cli_format


class BackendRegistryTests(unittest.TestCase):
    def test_cli_format_is_routed_to_the_selected_renderer(self):
        self.assertEqual(_strategy_for_cli_format("faithful-pdf", "clean_overlay"), "clean_overlay")
        for output_format, strategy in (
            ("flow-pdf", "flow"),
            ("rebuilt-pdf", "rebuilt"),
            ("markdown", "markdown"),
            ("html", "html"),
            ("docx", "docx"),
        ):
            with self.subTest(output_format=output_format):
                self.assertEqual(_strategy_for_cli_format(output_format, "overlay"), strategy)

    def test_faithful_formats_pass_the_selected_strategy(self):
        renderer = Mock(return_value="output.pdf")
        module = types.ModuleType("datacompiler.backend.faithful_pdf")
        module.render_faithful_pdf = renderer

        with patch.dict(sys.modules, {module.__name__: module}):
            for key, strategy in (("overlay", "overlay"), ("clean_overlay", "clean_overlay"),
                                  ("rasterized", "rasterized"), ("faithful-pdf", "overlay")):
                with self.subTest(format=key):
                    self.assertEqual(FORMATS[key]("document", "output.pdf"), "output.pdf")
                    self.assertEqual(EXTENSIONS[key], "pdf")

        self.assertEqual(renderer.call_count, 4)
        self.assertEqual([call.kwargs["strategy"] for call in renderer.call_args_list],
                         ["overlay", "clean_overlay", "rasterized", "overlay"])

    def test_markdown_renderer_writes_utf8_text_to_the_requested_path(self):
        renderer = Mock(return_value="Résumé du document")
        module = types.ModuleType("datacompiler.backend.rebuilt_markdown")
        module.render_markdown = renderer

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "document.md"
            with patch.dict(sys.modules, {module.__name__: module}):
                result = FORMATS["markdown"]("document", output)

            self.assertEqual(Path(result).read_text(encoding="utf-8"), "Résumé du document")
        renderer.assert_called_once_with("document")


if __name__ == "__main__":
    unittest.main()
