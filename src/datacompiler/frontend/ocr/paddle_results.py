"""Normalize PaddleOCR 2.x and 3.x outputs into a common list of text and bounding-box detections without importing Paddle."""

from collections.abc import Mapping
import logging
import math

logger = logging.getLogger(__name__)


def _items(value):
    if value is None:
        return []
    conversion = getattr(value, "tolist", None)
    if callable(conversion):
        value = conversion()
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _bbox(box):
    """Convert a rectangular or polygonal Paddle box to its enclosing rectangle."""
    coords = _items(box)
    if len(coords) == 4 and all(not isinstance(v, (list, tuple)) for v in coords):
        x0, y0, x1, y1 = (float(v) for v in coords)
    else:
        points = [_items(point) for point in coords]
        if len(points) < 2 or any(len(point) < 2 for point in points):
            raise ValueError("Invalid Paddle bounding box")
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)) or x1 <= x0 or y1 <= y0:
        raise ValueError("Paddle bounding box is empty or non-finite")
    return x0, y0, x1, y1


def _confidence(value):
    """Normalize Paddle confidence values from either 0–1 or 0–100 to 0–1."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score) or score < 0:
        return None
    if score <= 1:
        return score
    return score / 100.0 if score <= 100 else None


def _is_v2_line(value):
    line = _items(value)
    if len(line) != 2:
        return False
    text_score = _items(line[1])
    return len(text_score) == 2 and isinstance(text_score[0], str)


def _is_point(value):
    point = _items(value)
    return len(point) >= 2 and all(not isinstance(v, (list, tuple)) for v in point)


def _normalise_v3(page):
    texts = _items(page.get("rec_texts"))
    scores = _items(page.get("rec_scores"))
    boxes = []
    # dt_polys est normalement le choix privilégié. Certaines versions ou
    # sorties Paddle ne le remplissent pas et fournissent seulement rec_boxes.
    for key in ("dt_polys", "rec_polys", "rec_boxes"):
        raw = _items(page.get(key))
        candidates = raw
        # Quelques wrappers retirent aussi la dimension du lot pour une
        # détection unique : polygon [[x,y], ...] ou rectangle [x0,y0,x1,y1].
        if len(texts) == 1 and raw and (
            (len(raw) == 4 and all(not isinstance(v, (list, tuple)) for v in raw))
            or all(_is_point(point) for point in raw)
        ):
            candidates = [raw]
        if candidates:
            boxes = candidates
            break

    if len(texts) != len(boxes):
        logger.warning("PaddleOCR returned %d texts and %d boxes", len(texts), len(boxes))

    detections = []
    for index, (box, text) in enumerate(zip(boxes, texts)):
        if not str(text).strip():
            continue
        try:
            x0, y0, x1, y1 = _bbox(box)
        except (TypeError, ValueError, IndexError) as exc:
            logger.warning("Ignoring PaddleOCR box %d: %s", index, exc)
            continue
        detections.append({
            "text": str(text), "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "confidence": _confidence(scores[index] if index < len(scores) else None),
        })
    return detections


def _normalise_v2(lines):
    detections = []
    for index, raw_line in enumerate(_items(lines)):
        line = _items(raw_line)
        if len(line) != 2:
            continue
        box, text_score = line
        text_score = _items(text_score)
        if len(text_score) != 2 or not str(text_score[0]).strip():
            continue
        try:
            x0, y0, x1, y1 = _bbox(box)
        except (TypeError, ValueError, IndexError) as exc:
            logger.warning("Ignoring PaddleOCR 2.x box %d: %s", index, exc)
            continue
        detections.append({
            "text": str(text_score[0]), "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "confidence": _confidence(text_score[1]),
        })
    return detections


def normaliser_resultat_paddle(result):
    """Normalize PaddleOCR 2.x or 3.x output into text and bounding-box detections."""
    if isinstance(result, Mapping):
        page = result
    else:
        pages = _items(result)
        if not pages:
            return []
        if isinstance(pages[0], Mapping):
            page = pages[0]
        elif _is_v2_line(pages[0]):
            page = pages  # certains wrappers omettent la liste par page
        else:
            page = _items(pages[0])

    if isinstance(page, Mapping):
        return _normalise_v3(page)
    return _normalise_v2(page)
