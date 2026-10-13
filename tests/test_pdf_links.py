import tempfile
import unittest
from pathlib import Path

try:
    import pymupdf
except ImportError:
    pymupdf = None

from datacompiler.model.document import LinkElement, Page
from datacompiler.model.geometry import BBox

if pymupdf is not None:
    from datacompiler.backend.liens_pdf import reinserer_liens
else:
    reinserer_liens = None


@unittest.skipIf(pymupdf is None, "PyMuPDF is required for PDF link integration tests")
class PdfLinkTests(unittest.TestCase):
    def test_uri_and_internal_links_survive_pdf_save_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "links.pdf"
            document = pymupdf.open()
            first_page = document.new_page(width=200, height=200)
            document.new_page(width=200, height=200)
            model_page = Page(number=1, width=200, height=200)
            model_page.links = [
                LinkElement(id=1, bbox=BBox(10, 10, 80, 30), uri="https://example.test"),
                LinkElement(id=2, bbox=BBox(10, 40, 80, 60), kind="goto", target_page=2),
            ]

            self.assertEqual(reinserer_liens(first_page, model_page), 2)
            document.save(output)
            document.close()

            reopened = pymupdf.open(output)
            links = reopened[0].get_links()
            self.assertEqual(len(links), 2)
            self.assertEqual({link["uri"] for link in links if link["uri"]},
                             {"https://example.test"})
            self.assertEqual([link["page"] for link in links if link["kind"] == pymupdf.LINK_GOTO], [1])
            reopened.close()


if __name__ == "__main__":
    unittest.main()
