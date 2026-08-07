# frontend/ocr/paddleocr.py

import os
from pathlib import Path
import numpy as np
from PIL import Image

from datacompiler.model.document import BBox, Word
from datacompiler.frontend.ocr.base import OcrBackend


class PaddleOCRBackend(OcrBackend):
    name = "paddleocr"

    def __init__(self, lang: str = "fr", use_gpu: bool = False, **kwargs):
        self.lang = lang
        self.use_gpu = use_gpu
        self._ocr = None
        self._import_ok = False

        try:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(
                lang=lang,          # 'fr', 'en', 'ch', etc.
                use_gpu=use_gpu,
                show_log=False,
                **kwargs
            )
            self._import_ok = True
        except ImportError:
            print("❌ PaddleOCR non installé. Exécutez : pip install paddlepaddle paddleocr")
        except Exception as e:
            print(f"❌ Erreur lors de l'initialisation de PaddleOCR : {e}")

    def ocraliser_zone(self, image: Image.Image, offset: tuple = (0.0, 0.0), **kwargs) -> list:
        """
        OCR d'une zone (image crop) retournant une liste de Word avec bbox.
        `offset` est le décalage (x0, y0) de la zone dans le repère de la page.
        """
        if not self._import_ok or self._ocr is None:
            raise RuntimeError("PaddleOCR n'est pas disponible.")

        # Convertir l'image PIL en tableau numpy
        img_np = np.array(image)

        # Appel OCR
        result = self._ocr.ocr(img_np, cls=True)

        mots = []
        if not result or not result[0]:
            return mots

        # result[0] est une liste de lignes, chaque ligne = [ [[x1,y1], [x2,y2], [x3,y3], [x4,y4]], (texte, confiance) ]
        for line in result[0]:
            bbox_points, (text, confidence) = line
            # Les points sont dans l'ordre : haut-gauche, haut-droit, bas-droit, bas-gauche
            x0 = min(p[0] for p in bbox_points) + offset[0]
            y0 = min(p[1] for p in bbox_points) + offset[1]
            x1 = max(p[0] for p in bbox_points) + offset[0]
            y1 = max(p[1] for p in bbox_points) + offset[1]

            word = Word(
                id=len(mots) + 1,
                text=text,
                bbox=BBox(x0, y0, x1, y1),
                confidence=confidence,
                source="paddleocr",
                is_vectorized=True,
                reconstructed=True,
            )
            mots.append(word)

        return mots

    def ocraliser(self, doc, pdf_path, pages=None, **kwargs):
        """
        OCR page entière (optionnel) – on peut l'implémenter si besoin,
        mais on se concentre sur l'OCR ciblé.
        """
        raise NotImplementedError("PaddleOCRBackend ne supporte pas encore l'OCR page entière.")
