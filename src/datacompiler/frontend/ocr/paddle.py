import os
import re
import io
import logging
import threading

import pymupdf
import numpy as np
from PIL import Image

from datacompiler.model.document import BBox, Word
from datacompiler.frontend.ocr.base import OcrBackend
from datacompiler.frontend.ocr.paddle_results import normaliser_resultat_paddle

logger = logging.getLogger(__name__)
_DEBUG_DIR = os.environ.get("DATACOMPILER_DEBUG_INK_RATIO")
_debug_compteur = 0

# Seuil de distance couleur (espace RGB, 0-441) pour distinguer "encre" de
# "fond" -- EMPIRIQUE, teste sur test-impots-revenu.pdf uniquement.
_SEUIL_DISTANCE_ENCRE = 60


def _sauver_debug(crop_img, ratio, texte_debug, extra=""):
    """Save an optional diagnostic crop when DATACOMPILER_DEBUG_INK_RATIO is set; failures do not affect normal OCR."""
    if not _DEBUG_DIR:
        return
    global _debug_compteur
    _debug_compteur += 1
    try:
        os.makedirs(_DEBUG_DIR, exist_ok=True)
        nom = re.sub(r"[^A-Za-z0-9]+", "_", texte_debug or "mot").strip("_")[:40]
        suffixe = f"_{extra}" if extra else ""
        crop_img.save(os.path.join(_DEBUG_DIR, f"{_debug_compteur:04d}_{nom}_ratio{ratio:.4f}{suffixe}.png"))
    except OSError:
        # Un dump de diagnostic ne doit pas interrompre l'extraction, mais
        # l'échec reste visible pour faciliter le diagnostic.
        logger.debug("Could not save OCR diagnostic crop", exc_info=True)


def _ratio_encre_connue(image: Image.Image, x0: float, y0: float, x1: float, y1: float,
                         couleur_encre_rgb: tuple, marge_px: float = 8.0, texte_debug: str = ""):
    """Estimate one word’s ink density by comparing crop pixels with the known vector-ink color."""
    gx0, gy0 = max(0, int(x0 - marge_px)), max(0, int(y0 - marge_px))
    gx1, gy1 = min(image.width, int(x1 + marge_px)), min(image.height, int(y1 + marge_px))
    if gx1 - gx0 < 3 or gy1 - gy0 < 3:
        return None
    crop_img = image.crop((gx0, gy0, gx1, gy1)).convert("RGB")
    crop = np.array(crop_img).astype(int)
    ref = np.array(couleur_encre_rgb, dtype=int)  # BUG corrigé : `ref` n'était jamais défini (NameError garanti à l'appel)
    distance = np.sqrt(((crop - ref) ** 2).sum(axis=2))
    encre = distance < _SEUIL_DISTANCE_ENCRE  # PRES de l'encre connue (inverse de la version bordure : LOIN du fond)
    ratio = float(encre.sum() / encre.size)
    _sauver_debug(crop_img, ratio, texte_debug, extra=f"refcouleur{tuple(int(v) for v in ref)}")
    return ratio


def _ratio_encre_relatif(image: Image.Image, x0: float, y0: float, x1: float, y1: float, marge_px: float = 8.0, texte_debug: str = ""):
    """Fallback ink-density estimate using the crop border as an estimate of background color."""
    gx0, gy0 = max(0, int(x0 - marge_px)), max(0, int(y0 - marge_px))
    gx1, gy1 = min(image.width, int(x1 + marge_px)), min(image.height, int(y1 + marge_px))
    if gx1 - gx0 < 3 or gy1 - gy0 < 3:
        return None
    crop_img = image.crop((gx0, gy0, gx1, gy1)).convert("RGB")
    crop = np.array(crop_img).astype(int)
    bordure = np.concatenate([crop[0, :], crop[-1, :], crop[:, 0], crop[:, -1]])
    fond = np.median(bordure, axis=0)
    distance = np.sqrt(((crop - fond) ** 2).sum(axis=2))
    encre = distance > _SEUIL_DISTANCE_ENCRE
    ratio = float(encre.sum() / encre.size)
    _sauver_debug(crop_img, ratio, texte_debug, extra=f"fondestime{tuple(int(v) for v in fond)}")
    return ratio


class PaddleOcrBackend(OcrBackend):
    name = "paddleocr"
    _engine_instances = {}
    _engine_lock = threading.Lock()

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
        """Reuse PaddleOCR engines only when language and options match."""
        cache_key = (lang, tuple(sorted((key, repr(value)) for key, value in kwargs.items())))
        with cls._engine_lock:
            if cache_key in cls._engine_instances:
                return cls._engine_instances[cache_key]
            try:
                from paddleocr import PaddleOCR
                logger.info("Initializing the PaddleOCR engine (language: %s)...", lang)
                engine = PaddleOCR(
                    lang=lang,
                    use_textline_orientation=False,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    **kwargs
                )
            except ImportError:
                logger.error("PaddleOCR is not installed. Install paddlepaddle and paddleocr.")
                return None
            except Exception:
                # Paddle initialization spans optional native/runtime dependencies;
                # keep the backend unavailable and retain the complete traceback.
                logger.exception("Could not initialize PaddleOCR")
                return None
            cls._engine_instances[cache_key] = engine
            return engine

    def _extraire(self, image: Image.Image) -> list:
        """Run OCR on an image and normalize Paddle text boxes and confidence scores."""
        engine = self._get_engine(self.lang, **self.extra_kwargs)
        if engine is None:
            raise RuntimeError("PaddleOCR is unavailable.")

        img_np = np.array(image)
        result = engine.ocr(img_np)
        return normaliser_resultat_paddle(result)

    def ocraliser_zone(self, image: Image.Image, offset: tuple = (0.0, 0.0), dpi: int = None,
                        couleur_encre: tuple = None, **kwargs) -> list:
        """Run targeted OCR on a vector region and convert detections to page coordinates."""
        dpi = dpi or self.dpi
        scale = dpi / 72.0
        dx, dy = offset
        mots = []
        for m in self._extraire(image):
            x = dx + m["x0"] / scale
            y = dy + m["y0"] / scale
            largeur = (m["x1"] - m["x0"]) / scale
            hauteur = (m["y1"] - m["y0"]) / scale
            if couleur_encre is not None:
                ratio = _ratio_encre_connue(image, m["x0"], m["y0"], m["x1"], m["y1"], couleur_encre, texte_debug=m["text"])
                note_methode = f"ink_ratio={ratio:.4f} (méthode couleur connue {couleur_encre})" \
                    if ratio is not None else "ink_ratio=None"
            else:
                ratio = _ratio_encre_relatif(image, m["x0"], m["y0"], m["x1"], m["y1"], texte_debug=m["text"])
                note_methode = f"ink_ratio={ratio:.4f} (repli bordure -- couleur_encre=None)" \
                    if ratio is not None else "ink_ratio=None"
            mots.append(Word(
                id=-1,
                text=m["text"],
                resolved_text=m["text"],
                bbox=BBox(x, y, x + largeur, y + hauteur),
                confidence=m["confidence"],
                language=self.lang,
                source="ocr_vectoriel_paddle",
                is_vectorized=True,
                reconstructed=True,
                ink_ratio=ratio,
                notes=["texte vectorisé récupéré par OCR ciblé (PaddleOCR, zone crop)",
                       note_methode,
                       "bold decide au niveau page, cf. vector_zones._assigner_gras_relatif"],
            ))
        return mots

    def ocraliser(self, doc, pdf_path: str, pages: list = None, **kwargs):
        """Run full-page OCR for the requested pages."""
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
                        language=self.lang,
                        source="paddleocr",
                    ))

                page_obj.ocr.engine = f"paddleocr-{self.lang}"
                page_obj.ocr.words = mots
        finally:
            source.close()

        return doc


# Alias pour supporter la variante de nommage PaddleOCRBackend
PaddleOCRBackend = PaddleOcrBackend
