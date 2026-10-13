"""Combine OCR detections for the same region. Geometric conflicts are resolved using confidence, then nearby detections can be merged."""

from datacompiler.model.document import Word


def _chevauche(a: Word, b: Word) -> bool:
    """Return whether two word bounding boxes overlap."""
    return not (
        a.bbox.x1 <= b.bbox.x0 or b.bbox.x1 <= a.bbox.x0
        or a.bbox.y1 <= b.bbox.y0 or b.bbox.y1 <= a.bbox.y0
    )


def _confiance(mot: Word) -> float:
    """Normalize a confidence score for comparison, treating unknown confidence as the lowest score."""
    return mot.confidence if mot.confidence is not None else -1.0


def fusionner_candidats_ocr(candidats: dict) -> list:
    """Resolve overlapping candidates from OCR backends that processed the same page region."""
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
   


def fusionner_zone_multi_backend(image, offset: tuple, backends: dict, dpi: int = None, lang: str = None,
                                  **kwargs) -> list:
    """Run configured OCR backends on the same cropped image, then resolve their candidate detections."""
    candidats = {
        nom: backend.ocraliser_zone(image, offset=offset, dpi=dpi, lang=lang, **kwargs)
        for nom, backend in backends.items()
    }
    return fusionner_candidats_ocr(candidats)
