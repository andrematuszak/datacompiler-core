"""Regression tests for the PaddleOCR 2.x/3.x response adapter."""

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "src/datacompiler/frontend/ocr/paddle_results.py"
)
SPEC = importlib.util.spec_from_file_location("paddle_results", MODULE_PATH)
PARSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PARSER)


class ArrayLike:
    """Small stand-in for NumPy arrays returned by PaddleOCR."""

    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


class PaddleResultTests(unittest.TestCase):
    def test_paddle_2_polygon_lines_keep_each_word(self):
        lines = [
            [[[10, 20], [40, 20], [40, 35], [10, 35]], ("Alpha", 0.91)],
            [[[50, 20], [80, 20], [80, 35], [50, 35]], ("Beta", 0.87)],
        ]

        words = PARSER.normaliser_resultat_paddle([lines])

        self.assertEqual([word["text"] for word in words], ["Alpha", "Beta"])
        self.assertEqual(
            [(word["x0"], word["y0"], word["x1"], word["y1"]) for word in words],
            [(10, 20, 40, 35), (50, 20, 80, 35)],
        )
        self.assertEqual([word["confidence"] for word in words], [0.91, 0.87])

    def test_paddle_3_polygons_and_rectangles_have_same_bbox_contract(self):
        polygon_result = [{
            "rec_texts": ["Alpha", "Beta"],
            "rec_scores": ArrayLike([0.91, 0.87]),
            "dt_polys": ArrayLike([
                [[10, 20], [40, 20], [40, 35], [10, 35]],
                [[50, 20], [80, 20], [80, 35], [50, 35]],
            ]),
        }]
        rectangle_result = [{
            "rec_texts": ["Alpha", "Beta"],
            "rec_scores": [91, 87],
            "dt_polys": [],
            "rec_boxes": ArrayLike([[10, 20, 40, 35], [50, 20, 80, 35]]),
        }]

        polygons = PARSER.normaliser_resultat_paddle(polygon_result)
        rectangles = PARSER.normaliser_resultat_paddle(rectangle_result)

        self.assertEqual(len(polygons), 2)
        self.assertEqual(len(rectangles), 2)
        self.assertEqual(
            [(word["text"], word["x0"], word["y0"], word["x1"], word["y1"]) for word in polygons],
            [(word["text"], word["x0"], word["y0"], word["x1"], word["y1"]) for word in rectangles],
        )
        self.assertEqual([word["confidence"] for word in rectangles], [0.91, 0.87])

    def test_missing_scores_do_not_drop_detected_words(self):
        result = {
            "rec_texts": ["Alpha", "Beta"],
            "rec_scores": [0.9],
            "rec_boxes": [[1, 2, 11, 12], [20, 2, 30, 12]],
        }

        words = PARSER.normaliser_resultat_paddle(result)

        self.assertEqual(len(words), 2)
        self.assertEqual([word["confidence"] for word in words], [0.9, None])

    def test_single_unbatched_polygon_is_still_one_word(self):
        result = {
            "rec_texts": ["Alpha"],
            "rec_scores": [0.9],
            "dt_polys": [[10, 20], [40, 20], [40, 35], [10, 35]],
        }

        words = PARSER.normaliser_resultat_paddle(result)

        self.assertEqual(len(words), 1)
        self.assertEqual((words[0]["x0"], words[0]["y0"], words[0]["x1"], words[0]["y1"]), (10, 20, 40, 35))

    def test_empty_results_and_malformed_boxes_are_safe(self):
        self.assertEqual(PARSER.normaliser_resultat_paddle([]), [])
        words = PARSER.normaliser_resultat_paddle({
            "rec_texts": ["bad", "good"],
            "rec_boxes": [[], [1, 2, 11, 12]],
            "rec_scores": [0.8, 0.9],
        })
        self.assertEqual([word["text"] for word in words], ["good"])


if __name__ == "__main__":
    unittest.main()
