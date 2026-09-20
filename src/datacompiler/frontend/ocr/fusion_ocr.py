"""fusion_ocr.py — Arbitrage entre PLUSIEURS backends OCR sur une même
zone (ex. Tesseract vs PaddleOCR sur le même crop vectorisé).

À placer dans compile/ (ou compile/resolve/ si c'est là que vit déjà
alignment.py -- je n'ai pas ce fichier sous les yeux, à toi de voir où ça
s'aligne le mieux avec l'existant).

NE PAS CONFONDRE avec :
- frontend/extract/merge.py::fusionner_page -- fusionne DEUX MOTEURS
  D'EXTRACTION NATIVE (PyMuPDF + pdfplumber), pas de l'OCR.
- resolve/alignment.py (mentionné dans tesseract.py) -- aligne natif <->
  UN SEUL flux OCR par texte/séquence (pas de bbox fiable côté Mistral).

Ce module couvre un troisième cas, pas encore implémenté avant
aujourd'hui : arbitrer entre PLUSIEURS flux OCR concurrents sur la MÊME
zone, où chaque backend fournit une bbox ET une confiance PAR MOT
(Tesseract et PaddleOCR le font tous les deux, contrairement à Mistral) --
ce qui permet un arbitrage géométrique mot-à-mot plutôt que par séquence.

⚠️ HEURISTIQUE V0, PAS ENCORE VALIDÉE EMPIRIQUEMENT : "confiance la plus
haute gagne" en cas de chevauchement est un point de départ raisonnable
mais arbitraire tant qu'on n'a pas de données comparatives réelles
Tesseract vs PaddleOCR sur ce document (cf. piste tesseract.py en cours).
Chaque arbitrage est tracé dans `notes` pour pouvoir auditer/revenir en
arrière si l'heuristique s'avère mauvaise sur des cas réels.
"""

from datacompiler.model.document import Word


def _chevauche(a: Word, b: Word) -> bool:
    """Même logique que _chevauche dans tesseract.py, généralisée à des
    objets Word (bbox typée) plutôt qu'à des dicts bruts."""
    return not (
        a.bbox.x1 <= b.bbox.x0 or b.bbox.x1 <= a.bbox.x0
        or a.bbox.y1 <= b.bbox.y0 or b.bbox.y1 <= a.bbox.y0
    )


def _confiance(mot: Word) -> float:
    """Confiance normalisée pour comparaison -- traite None (confiance
    inconnue) comme la plus basse possible plutôt que de planter la
    comparaison, mais c'est un choix conservateur à revoir si un backend
    renvoie fréquemment None en pratique (actuellement aucun des deux ne
    devrait, mais Tesseract le fait pour conf_brute < 0 -- cf. tesseract.py)."""
    return mot.confidence if mot.confidence is not None else -1.0


def fusionner_candidats_ocr(candidats: dict) -> list:
    """Arbitre entre plusieurs backends OCR ayant tourné sur LA MÊME zone
    (même repère page, même crop source).

    candidats : dict {nom_backend: list[Word]}, ex.
        {"tesseract": [...], "paddleocr": [...]}

    Stratégie (v0, cf. avertissement en tête de fichier) :
    - deux mots de backends différents dont les bbox se CHEVAUCHENT
      -> on garde celui de plus haute confiance, on note le nom du
         backend écarté et son texte dans `notes` (traçabilité/audit)
    - un mot détecté par un seul backend, sans chevauchement chez les
      autres -> conservé tel quel (même logique que la fusion PSM3/PSM6
      dans tesseract.py::_extraire_deux_passes, généralisée à N backends
      au lieu de 2 passes d'un même moteur)

    Ordre de traitement : les backends sont parcourus dans l'ordre du
    dict (Python 3.7+ préserve l'ordre d'insertion) -- en cas d'égalité
    stricte de confiance entre deux mots qui se chevauchent, c'est donc
    le premier backend listé par l'appelant qui gagne. Pas de biais
    implicite favorisant un moteur : c'est à l'appelant de trancher
    l'ordre s'il a une préférence (aucune justifiée pour l'instant, faute
    de données comparatives).
    """
    fusion: list = []

    for nom_backend, mots in candidats.items():
        for mot in mots:
            conflit_idx = None
            for i, (backend_existant, existant) in enumerate(fusion):
                # Un même moteur peut légitimement produire deux lignes dont
                # les bbox se touchent : ce n'est jamais un arbitrage OCR.
                if backend_existant != nom_backend and _chevauche(existant, mot):
                    conflit_idx = i
                    break

            if conflit_idx is None:
                mot.notes = list(mot.notes or []) + [
                    f"candidat unique ({nom_backend}), aucun chevauchement inter-backend"
                ]
                fusion.append((nom_backend, mot))
                continue

            backend_existant, existant = fusion[conflit_idx]
            if _confiance(mot) > _confiance(existant):
                mot.notes = list(mot.notes or []) + [
                    f"retenu ({nom_backend}, conf={mot.confidence}) au détriment de "
                    f"{backend_existant} (texte écarté : {existant.text!r}, "
                    f"conf={existant.confidence})"
                ]
                fusion[conflit_idx] = (nom_backend, mot)
            else:
                existant.notes = list(existant.notes or []) + [
                    f"conservé face à {nom_backend} "
                    f"(texte écarté : {mot.text!r}, conf={mot.confidence})"
                ]

    return [mot for _, mot in fusion]
   


def fusionner_zone_multi_backend(image, offset: tuple, backends: dict, dpi: int = None, lang: str = None) -> list:
    """Point d'entrée pratique : fait tourner plusieurs backends sur LA
    MÊME image de zone déjà croppée, puis arbitre. Pas encore câblé dans
    vector_zones.py (je n'ai pas ce fichier) -- à intégrer là où
    recuperer_texte_vectorise() appelle actuellement un seul backend.

    backends : dict {nom: instance_de_backend}, ex.
        {"tesseract": TesseractBackend(...), "paddleocr": PaddleOCRBackend(...)}
    """
    candidats = {
        nom: backend.ocraliser_zone(image, offset=offset, dpi=dpi, lang=lang)
        for nom, backend in backends.items()
    }
    return fusionner_candidats_ocr(candidats)
