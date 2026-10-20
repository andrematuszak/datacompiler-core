import unittest

from datacompiler.compile.links import associer_liens
from datacompiler.model.document import LinkElement, Page, ResolvedContainer, Word
from datacompiler.model.geometry import BBox


class LinkAssociationTests(unittest.TestCase):
    def test_words_are_associated_by_center_without_changing_link_bbox(self):
        original_bbox = BBox(10, 10, 40, 30)
        page = Page(number=1, width=100, height=100)
        page.links = [LinkElement(id=1, bbox=original_bbox, uri="https://example.test")]
        page.resolved = ResolvedContainer(words=[
            Word(id=1, text="open", bbox=BBox(12, 12, 20, 20)),
            Word(id=2, text="link", bbox=BBox(21, 12, 30, 20)),
            # This box overlaps the annotation, but its center lies outside it.
            Word(id=3, text="edge", bbox=BBox(35, 12, 50, 20)),
            Word(id=4, text="no bbox"),
        ])

        associer_liens(page)

        self.assertEqual(page.links[0].word_ids, [1, 2])
        self.assertIs(page.links[0].bbox, original_bbox)

    def test_missing_bbox_and_empty_page_clear_stale_word_ids(self):
        page = Page(number=1, width=100, height=100)
        page.links = [
            LinkElement(id=1, bbox=None, word_ids=[7]),
            LinkElement(id=2, bbox=BBox(1, 1, 10, 10), word_ids=[8]),
        ]

        associer_liens(page)

        self.assertEqual([link.word_ids for link in page.links], [[], []])


if __name__ == "__main__":
    unittest.main()
