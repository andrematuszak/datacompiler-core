import unittest

from datacompiler.frontend.ocr.fusion_ocr import fusionner_candidats_ocr
from datacompiler.model.document import Word
from datacompiler.model.geometry import BBox


def mot(word_id, text, bbox, confidence):
    return Word(id=word_id, text=text, bbox=BBox(*bbox), confidence=confidence)


class OcrFusionTests(unittest.TestCase):
    def test_higher_confidence_wins_overlapping_candidates(self):
        paddle = mot(1, "correct", (0, 0, 20, 10), 0.9)
        other = mot(2, "incorect", (1, 0, 19, 10), 0.7)

        result = fusionner_candidats_ocr({"paddle": [paddle], "other": [other]})

        self.assertEqual(result, [paddle])
        self.assertTrue(any("texte écarté" in note for note in paddle.notes))

    def test_non_overlapping_words_and_same_backend_overlaps_are_kept(self):
        first = mot(1, "one", (0, 0, 10, 10), 0.8)
        adjacent_same_backend = mot(2, "two", (5, 0, 15, 10), 0.6)
        separate_engine = mot(3, "three", (30, 0, 40, 10), 0.7)

        result = fusionner_candidats_ocr({
            "paddle": [first, adjacent_same_backend],
            "other": [separate_engine],
        })

        self.assertEqual(result, [first, adjacent_same_backend, separate_engine])

    def test_unknown_confidence_is_safe_and_ties_keep_first_backend(self):
        first = mot(1, "first", (0, 0, 10, 10), None)
        tied = mot(2, "tied", (0, 0, 10, 10), None)

        result = fusionner_candidats_ocr({"first": [first], "second": [tied]})

        self.assertEqual(result, [first])
        self.assertTrue(any("conservé face à second" in note for note in first.notes))


if __name__ == "__main__":
    unittest.main()
