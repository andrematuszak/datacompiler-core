"""qwen_vl.py — Backend OCR utilisant Qwen2.5-VL (open source, léger,
donne des coordonnées) en remplacement de Mistral.

⚠️ JAMAIS TESTÉ CONTRE LE VRAI MODÈLE -- aucun GPU ni poids disponibles
dans l'environnement où ce fichier a été écrit. Contrairement à tout le
reste de ce projet, ce backend n'a pas été validé par un test structurel
avant livraison. À vérifier en priorité, avant toute confiance :

  1. UN SEUL mot isolé, bbox connue à l'avance -- comparer la bbox
     retournée au pixel près, exactement comme le premier diagnostic fait
     sur "Pavis" au tout début de ce projet. Ne pas passer à l'échelle
     avant que ce test unitaire ne soit concluant.
  2. Signalement communautaire d'un décalage de coordonnées (surtout en
     Y) sur Qwen2.5-VL, discussion HuggingFace du modèle -- cause
     probable : le modèle voit l'image REDIMENSIONNÉE en interne (par
     blocs de 28px), pas l'image d'origine, et les bbox retournées sont
     relatives à CETTE taille redimensionnée. Ce module force
     explicitement resized_height/resized_width (voir _dimensions_cible)
     plutôt que de laisser qwen-vl-utils redimensionner automatiquement.

Dépendances : transformers (récent), qwen-vl-utils, torch. GPU fortement
recommandé -- "léger" reste relatif, un VLM n'est pas Tesseract.
"""

import json
import re
import torch

from datacompiler.frontend.ocr.base import OcrBackend
from datacompiler.model.document import BBox, Document, Word

MODELE_QWEN = "Qwen/Qwen2.5-VL-3B-Instruct"

# Le modèle attend des dimensions multiples de 28 (taille de patch de l'encodeur visuel)
TAILLE_PATCH = 28
PIXELS_MAX_CIBLE = 1280 * 1280

PROMPT_OCR_BBOX = (
    "Lis tout le texte visible dans cette image, mot par mot. "
    "Pour chaque mot, renvoie sa position. "
    "Réponds UNIQUEMENT avec une liste JSON, un objet par mot, "
    "format exact : "
    '[{"bbox_2d": [x1, y1, x2, y2], "text": "mot"}, ...] '
    "Aucun texte avant ou après le JSON."
)


def _arrondir_a_taille_patch(valeur: float) -> int:
    """Arrondit au multiple de TAILLE_PATCH le plus proche, minimum un patch."""
    arrondi = round(valeur / TAILLE_PATCH) * TAILLE_PATCH
    return max(arrondi, TAILLE_PATCH)


def _dimensions_cible(largeur_orig: int, hauteur_orig: int) -> tuple:
    """Calcule une taille cible multiple de TAILLE_PATCH sous PIXELS_MAX_CIBLE."""
    ratio_max = (PIXELS_MAX_CIBLE / (largeur_orig * hauteur_orig)) ** 0.5
    ratio = min(ratio_max, 1.0)
    largeur_cible = _arrondir_a_taille_patch(largeur_orig * ratio)
    hauteur_cible = _arrondir_a_taille_patch(hauteur_orig * ratio)
    return largeur_cible, hauteur_cible


def _extraire_json_bbox(texte_brut: str) -> list:
    """Extrait la liste JSON de la réponse du modèle."""
    correspondance = re.search(r"\[.*\]", texte_brut, re.DOTALL)
    if not correspondance:
        return []
    try:
        return json.loads(correspondance.group(0))
    except json.JSONDecodeError:
        return []


def _detecter_device(device_souhaite: str = "auto") -> tuple:
    """Détermine le matériel disponible (device) et la précision adaptée (dtype)."""
    if device_souhaite and device_souhaite != "auto":
        dev = device_souhaite
    elif torch.cuda.is_available():
        dev = "cuda"
    elif torch.backends.mps.is_available():
        dev = "mps"
    else:
        dev = "cpu"

    if dev == "cuda":
        dtype = torch.float16
    elif dev == "mps":
        dtype = torch.bfloat16
    else:
        dtype = torch.float32

    return dev, dtype


class QwenVLBackend(OcrBackend):
    name = "qwen_vl"

    def __init__(self, modele: str = MODELE_QWEN, device: str = "auto"):
        self.modele_nom = modele
        self.device, self.dtype = _detecter_device(device)
        self._model = None
        self._processor = None
        self._import_ok = False

        try:
            from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

            print(
                f"[QwenVLBackend] Chargement de {modele} sur device='{self.device}' ({self.dtype})..."
            )

            if self.device in ("mps", "cpu"):
                self._model = (
                    Qwen2_5_VLForConditionalGeneration.from_pretrained(
                        modele, torch_dtype=self.dtype
                    ).to(self.device)
                )
            else:
                self._model = (
                    Qwen2_5_VLForConditionalGeneration.from_pretrained(
                        modele, torch_dtype=self.dtype, device_map=self.device
                    )
                )

            self._processor = AutoProcessor.from_pretrained(modele)
            self._import_ok = True
            print("✅ Qwen2.5-VL chargé avec succès !")

        except ImportError:
            print(
                "❌ transformers/qwen-vl-utils non installés. "
                "Exécutez : pip install git+https://github.com/huggingface/transformers qwen-vl-utils"
            )
        except Exception as e:
            print(
                f"❌ Erreur lors du chargement de Qwen2.5-VL ({modele}) : {e}"
            )

    def _extraire(self, image) -> list:
        if not self._import_ok:
            raise RuntimeError("Qwen2.5-VL n'est pas disponible.")

        largeur_orig, hauteur_orig = image.size
        largeur_cible, hauteur_cible = _dimensions_cible(
            largeur_orig, hauteur_orig
        )
        image_redim = image.resize((largeur_cible, hauteur_cible))

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image_redim},
                    {"type": "text", "text": PROMPT_OCR_BBOX},
                ],
            }
        ]

        texte_prompt = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        entrees = self._processor(
            text=[texte_prompt],
            images=[image_redim],
            padding=True,
            return_tensors="pt",
        ).to(self.device)

        sortie = self._model.generate(**entrees, max_new_tokens=4096)
        sortie_generee = sortie[:, entrees.input_ids.shape[1] :]
        texte_reponse = self._processor.batch_decode(
            sortie_generee,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]

        # --- AJOUTEZ CE PRINT POUR DÉBOGUER ---
        print(f"\n[DEBUG Qwen2.5-VL Reponse Brute] :\n{texte_reponse}\n")
        # -------------------------------------

        detections = _extraire_json_bbox(texte_reponse)

        echelle_x = largeur_orig / largeur_cible
        echelle_y = hauteur_orig / hauteur_cible

        mots = []
        for d in detections:
            bbox_brut = d.get("bbox_2d")
            texte = d.get("text", "")
            if not bbox_brut or len(bbox_brut) != 4 or not texte:
                continue
            x0, y0, x1, y1 = bbox_brut
            mots.append(
                {
                    "text": texte,
                    "x0": x0 * echelle_x,
                    "y0": y0 * echelle_y,
                    "x1": x1 * echelle_x,
                    "y1": y1 * echelle_y,
                    "confidence": None,
                }
            )
        return mots

    def ocraliser_zone(
        self, image, offset: tuple = (0.0, 0.0), dpi: int = None, **kwargs
    ) -> list:
        dpi = dpi or 300
        scale = dpi / 72.0
        dx, dy = offset
        mots = []
        for m in self._extraire(image):
            x = dx + m["x0"] / scale
            y = dy + m["y0"] / scale
            largeur = (m["x1"] - m["x0"]) / scale
            hauteur = (m["y1"] - m["y0"]) / scale
            mots.append(
                Word(
                    id=-1,
                    text=m["text"],
                    resolved_text=m["text"],
                    bbox=BBox(x, y, x + largeur, y + hauteur),
                    confidence=m["confidence"],
                    source="ocr_qwen_vl",
                    is_vectorized=True,
                    reconstructed=True,
                    notes=["texte récupéré par Qwen2.5-VL (zone crop)"],
                )
            )
        return mots

    def ocraliser(
        self, doc: Document, pdf_path: str, pages: list = None, **kwargs
    ) -> Document:
        raise NotImplementedError(
            "QwenVLBackend ne supporte pour l'instant que l'OCR de zone ciblée (ocraliser_zone)."
        )
