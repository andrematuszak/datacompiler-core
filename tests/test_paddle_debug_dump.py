import importlib.util
import tempfile
import unittest

_HAS_PADDLE_MODULE_DEPS = all(
    importlib.util.find_spec(name) is not None for name in ("pymupdf", "numpy", "PIL")
)
if _HAS_PADDLE_MODULE_DEPS:
    from datacompiler.frontend.ocr import paddle as paddle_module
else:
    paddle_module = None


@unittest.skipUnless(_HAS_PADDLE_MODULE_DEPS, "Paddle OCR module dependencies are required")
class PaddleDebugDumpTests(unittest.TestCase):
    def test_filesystem_error_is_logged_and_does_not_interrupt_extraction(self):
        class FailingCrop:
            def save(self, _path):
                raise OSError("disk unavailable")

        with tempfile.TemporaryDirectory() as directory:
            original_debug_dir = paddle_module._DEBUG_DIR
            paddle_module._DEBUG_DIR = directory
            try:
                with self.assertLogs(paddle_module.logger, level="DEBUG") as captured:
                    paddle_module._sauver_debug(FailingCrop(), 0.5, "mot")
                self.assertTrue(any("Could not save OCR diagnostic crop" in line for line in captured.output))
            finally:
                paddle_module._DEBUG_DIR = original_debug_dir


if __name__ == "__main__":
    unittest.main()
