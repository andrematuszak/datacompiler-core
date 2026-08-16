# frontend/ocr/paddleocr.py

import io

import fitz
import numpy as np
from PIL import Image

from datacompiler.model.document import BBox, Word
from datacompiler.frontend.ocr.base import OcrBackend


class PaddleOCRBackend(OcrBackend):
    name = "paddleocr"

    def __init__(self, lang: str = "fr", dpi: int = 300, use_gpu: bool = False, **kwargs):
        self.lang = lang
        self.dpi = dpi  # AJOUTÉ : absent avant, incohérent avec TesseractBackend
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

    def _extraire(self, image: Image.Image) -> list:
        """Fait tourner PaddleOCR sur une image déjà rendue et retourne les
        détections brutes en coordonnées PIXEL de cette image -- la
        conversion en points PDF (dépendante du DPI de rendu, pas de
        PaddleOCR lui-même) se fait dans ocraliser_zone/ocraliser, pas ici.
        Séparé du reste pour rester testable directement avec une image
        (PNG/PIL), même logique que _parser_image dans tesseract.py."""
        if not self._import_ok or self._ocr is None:
            raise RuntimeError("PaddleOCR n'est pas disponible.")

        img_np = np.array(image)
        result = self._ocr.ocr(img_np, cls=True)

        mots = []
        if not result or not result[0]:
            return mots

        # result[0] est une liste de lignes, chaque ligne =
        # [ [[x1,y1],[x2,y2],[x3,y3],[x4,y4]], (texte, confiance) ]
        # Les points sont dans l'ordre : haut-gauche, haut-droit, bas-droit, bas-gauche
        for line in result[0]:
            bbox_points, (text, confidence) = line
            x0 = min(p[0] for p in bbox_points)
            y0 = min(p[1] for p in bbox_points)
            x1 = max(p[0] for p in bbox_points)
            y1 = max(p[1] for p in bbox_points)
            mots.append({"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "confidence": confidence})
        return mots

    def ocraliser_zone(self, image: Image.Image, offset: tuple = (0.0, 0.0), dpi: int = None, **kwargs) -> list:
        """OCRise UNE image déjà croppée (zone précise, pas la page) et
        translate les bbox résultantes dans le repère de la PAGE COMPLÈTE,
        pas celui du crop -- `offset` = (x0, y0) de la zone dans la page,
        en points PDF, tel que fourni par vector_text.py.

        `dpi` correspond au DPI de RENDU du crop passé en entrée (pas
        nécessairement self.dpi : ce backend est appelé sur des crops
        produits en amont par vector_zones.py, qui peut utiliser un DPI
        différent du DPI par défaut du backend).

        BUG CORRIGÉ ici (présent dans la version précédente) : l'ancien
        code ajoutait `offset` (points PDF) directement aux coordonnées
        PIXEL de PaddleOCR, sans les diviser par l'échelle DPI -> points.
        Les bbox n'étaient donc justes qu'à 72 DPI -- jamais le cas en
        pratique puisqu'un DPI plus élevé est nécessaire pour une bonne
        précision OCR. Corrigé par symétrie avec
        TesseractBackend._ocraliser_zone_image, qui fait déjà cette
        conversion correctement.
        """
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
                id=-1,  # renumérotation finale par compile/compiler.py (même convention que tesseract.py)
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
        """OCR page entière -- AJOUTÉ (l'ancienne version levait
        NotImplementedError). Symétrique à TesseractBackend.ocraliser,
        nécessaire pour permettre une comparaison directe backend à
        backend sur le document entier, pas seulement zone par zone."""
        source = fitz.open(pdf_path)
        scale = self.dpi / 72.0
        matrix = fitz.Matrix(scale, scale)

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
                page_obj.ocr.words = mots  # ré-appel idempotent : remplace, n'accumule pas
        finally:
            source.close()

        return doc
