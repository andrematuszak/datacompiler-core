import os
import re
import io
import logging

import pymupdf
import numpy as np
from PIL import Image

from datacompiler.model.document import BBox, Word
from datacompiler.frontend.ocr.base import OcrBackend

logger = logging.getLogger(__name__)
_DEBUG_DIR = os.environ.get("DATACOMPILER_DEBUG_INK_RATIO")
_debug_compteur = 0

# Seuil de distance couleur (espace RGB, 0-441) pour distinguer "encre" de
# "fond" -- EMPIRIQUE, teste sur test-impots-revenu.pdf uniquement.
_SEUIL_DISTANCE_ENCRE = 60


def _sauver_debug(crop_img, ratio, texte_debug, extra=""):
    """Sauvegarde le crop passe a une methode ink_ratio, si
    DATACOMPILER_DEBUG_INK_RATIO est defini -- diagnostic pur, aucun effet
    sur le comportement normal. Factorise entre _ratio_encre_connue et
    _ratio_encre_relatif (session du 26/09/2026 : le dump n'etait cable
    que dans le repli, jamais declenche puisque _ratio_encre_connue est la
    methode reellement utilisee sur ce document)."""
    if not _DEBUG_DIR:
        return
    global _debug_compteur
    _debug_compteur += 1
    try:
        os.makedirs(_DEBUG_DIR, exist_ok=True)
        nom = re.sub(r"[^A-Za-z0-9]+", "_", texte_debug or "mot").strip("_")[:40]
        suffixe = f"_{extra}" if extra else ""
        crop_img.save(os.path.join(_DEBUG_DIR, f"{_debug_compteur:04d}_{nom}_ratio{ratio:.4f}{suffixe}.png"))
    except Exception:
        pass  # jamais casser l'extraction pour un souci d'ecriture du debug


def _ratio_encre_connue(image: Image.Image, x0: float, y0: float, x1: float, y1: float,
                         couleur_encre_rgb: tuple, marge_px: float = 8.0, texte_debug: str = ""):
    """Densite d'encre d'UN mot, par comparaison a une couleur d'encre
    CONNUE (lue dans le tracé vectoriel, cf. vector_zones._couleur_encre_zone)
    plutot qu'a un fond ESTIME depuis la bordure du crop (cf. version
    precedente _ratio_encre_relatif, conservee ci-dessous en repli).

    CORRECTIF (session du 26/09/2026, test-impots-revenu.pdf) : l'ancienne
    version supposait toujours un peu de fond blanc disponible en bordure
    du crop pour estimer `fond`. Faux sur "DIRECTION" (et les 4 autres mots
    du meme titre) : la zone y est rognee a zero marge par
    _clipper_marge_sur_natifs (collee a "Impôt sur les revenus de 2020" en
    dessous), les lettres touchent les bords du crop, et la bordure
    echantillonnee contient alors une partie des lettres elles-memes --
    fond estime anormalement sombre, ink_ratio gonfle pour toute la ligne.
    Connaitre la couleur d'encre a priori evite le probleme par
    construction (plus besoin de marge blanche du tout).

    Validee empiriquement (meme session) : ecart net (~0,05) entre
    libelles gras confirmes (~0,19) et le titre non-gras (~0,13), contre
    un chevauchement quasi total (0,001 d'ecart, "DIRECTION" a 0,2507
    coince entre "service" a 0,2472 et "rôle" a 0,2517) avec l'ancienne
    methode -- toujours un proxy geometrique, pas une detection de police,
    et toujours valide sur ce seul document.

    Retourne None si le crop est trop petit pour etre fiable (mot tronque,
    artefact de zone) -- meme garde que l'ancienne version.
    """
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
    """REPLI seulement -- utilisee quand aucune couleur d'encre connue n'a
    pu etre resolue pour la zone (cf. vector_zones._couleur_encre_zone
    retournant None : aucun element graphique trouve en recouvrement).
    Historiquement la seule version ; remplacee en usage normal par
    _ratio_encre_connue (cf. docstring ci-dessus pour le defaut identifie
    sur "DIRECTION"). Fond estime par la couleur mediane des pixels de
    bordure du crop -- suppose que le mot n'occupe pas toute la bordure,
    hypothese qui peut echouer dans les memes conditions que "DIRECTION"
    (crop sans marge). A surveiller si ce repli se declenche souvent en
    pratique (cf. notes du mot, "couleur_encre=None -- repli bordure").
    """
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

    def ocraliser_zone(self, image: Image.Image, offset: tuple = (0.0, 0.0), dpi: int = None,
                        couleur_encre: tuple = None, **kwargs) -> list:
        """OCR ciblé sur une zone vectorielle croppée.

        couleur_encre : RGB (0-255) déjà résolu par
        vector_zones._couleur_encre_zone à partir du tracé vectoriel réel de
        la zone. None si aucun élément graphique n'a été trouvé en
        recouvrement (repli sur l'estimation par bordure de crop, moins
        fiable -- cf. _ratio_encre_relatif) : cas non rencontré sur
        test-impots-revenu.pdf mais pas exclu sur un autre document, d'où le
        repli plutôt qu'un crash ou un ink_ratio=None systématique.
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
