import io
import logging

import pymupdf
import numpy as np
from PIL import Image

from datacompiler.model.document import BBox, Word
from datacompiler.frontend.ocr.base import OcrBackend

logger = logging.getLogger(__name__)


class PaddleOcrBackend(OcrBackend):
    name = "paddleocr"
    _engine_instance = None  # Singleton pour le moteur PaddleOCR

    def __init__(self, lang: str = "fr", dpi: int = 300, **kwargs):
        self.lang = lang
        self.dpi = dpi

        # Nettoyage des arguments obsolètes
        kwargs.pop("use_gpu", None)
        kwargs.pop("show_log", None)
        self.extra_kwargs = kwargs

        # Initialisation lazy du Singleton
        self._get_engine(self.lang, **self.extra_kwargs)

    @classmethod
    def _get_engine(cls, lang: str = "fr", **kwargs):
        """Initialise le moteur PaddleOCR une seule fois."""
        if cls._engine_instance is None:
            try:
                from paddleocr import PaddleOCR
                logger.info("Initialisation unique du moteur PaddleOCR (langue: %s)...", lang)
                cls._engine_instance = PaddleOCR(
                    lang=lang,
                    use_textline_orientation=False,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    **kwargs
                )
            except ImportError:
                logger.error("❌ PaddleOCR non installé. Exécutez : pip install paddlepaddle paddleocr")
                cls._engine_instance = None
            except Exception as e:
                logger.error("❌ Erreur lors de l'initialisation de PaddleOCR : %s", e)
                cls._engine_instance = None

        return cls._engine_instance

    def _extraire(self, image: Image.Image) -> list:
        """Exécute l'OCR sur une image et extrait les boîtes et scores."""
        engine = self._get_engine(self.lang, **self.extra_kwargs)
        if engine is None:
            raise RuntimeError("PaddleOCR n'est pas disponible.")

        img_np = np.array(image)
        result = engine.ocr(img_np)

        mots = []
        if not result or not result[0]:
            return mots

        res = result[0]

        # Format PaddleOCR 3.x (Dictionnaire)
        if isinstance(res, dict):
            texts = res.get("rec_texts", [])
            scores = res.get("rec_scores", [])
            boxes = res.get("dt_polys", res.get("rec_boxes", []))

            for box, text, score in zip(boxes, texts, scores):
                x0 = min(p[0] for p in box)
                y0 = min(p[1] for p in box)
                x1 = max(p[0] for p in box)
                y1 = max(p[1] for p in box)
                mots.append({
                    "text": text,
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "confidence": float(score),
                })

        # Format PaddleOCR 2.x (Liste)
        elif isinstance(res, list):
            for line in res:
                if not line:
                    continue
                bbox_points, (text, confidence) = line
                x0 = min(p[0] for p in bbox_points)
                y0 = min(p[1] for p in bbox_points)
                x1 = max(p[0] for p in bbox_points)
                y1 = max(p[1] for p in bbox_points)
                mots.append({
                    "text": text,
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "confidence": float(confidence),
                })

        return mots

    def ocraliser_zone(self, image: Image.Image, offset: tuple = (0.0, 0.0), dpi: int = None, **kwargs) -> list:
        """OCR ciblé sur une zone vectorielle croppée."""
        dpi = dpi or self.dpi
        scale = dpi / 72.0
        dx, dy = offset
        mots = []
        for m in self._extraire(image):
            x = dx + m["x0"] / scale
            y = dy + m["y0"] / scale
            largeur = (m["x1"] - m["x0"]) / scale
            hauteur = (m["y1"] - m["y0"]) / scale
            mots.append(Word(
                id=-1,
                text=m["text"],
                resolved_text=m["text"],
                bbox=BBox(x, y, x + largeur, y + hauteur),
                confidence=m["confidence"],
                source="ocr_vectoriel_paddle",
                is_vectorized=True,
                reconstructed=True,
                notes=["texte vectorisé récupéré par OCR ciblé (PaddleOCR, zone crop)"],
            ))
        return mots

    def ocraliser(self, doc, pdf_path: str, pages: list = None, **kwargs):
        """OCR pleine page (requis par la classe abstraite OcrBackend)."""
        source = pymupdf.open(pdf_path)
        scale = self.dpi / 72.0
        matrix = pymupdf.Matrix(scale, scale)

        try:
            for i, page_obj in enumerate(doc.pages):
                if pages is not None and page_obj.number not in pages:
                    continue

                pix = source[i].get_pixmap(matrix=matrix, alpha=False)
                image = Image.open(io.BytesIO(pix.tobytes("png")))

                mots = []
                for m in self._extraire(image):
                    x = m["x0"] / scale
                    y = m["y0"] / scale
                    largeur = (m["x1"] - m["x0"]) / scale
                    hauteur = (m["y1"] - m["y0"]) / scale
                    mots.append(Word(
                        id=len(mots) + 1,
                        text=m["text"],
                        bbox=BBox(x, y, x + largeur, y + hauteur),
                        confidence=m["confidence"],
                        source="paddleocr",
                    ))

                page_obj.ocr.engine = f"paddleocr-{self.lang}"
                page_obj.ocr.words = mots
        finally:
            source.close()

        return doc


# Alias pour supporter la variante de nommage PaddleOCRBackend
PaddleOCRBackend = PaddleOcrBackend
