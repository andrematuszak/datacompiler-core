# diagnostic/report.py
"""report.py — Interface humaine pour diagnostic/. Affiche un résumé lisible
dans le terminal après diagnostiquer(doc) : pensé pour l'inspection manuelle
lors des tests sur des fichiers réels, sans avoir à lire le JSON brut.

Volontairement séparé de __init__.py : diagnostiquer() reste une fonction
pure (aucun effet de bord), l'affichage est un consommateur externe du
résultat, pas une étape du calcul."""

from datacompiler.model.document import Document

_LARGEUR_LABEL = 35


def _ligne(label, valeur):
    return f"  {label:<{_LARGEUR_LABEL}} {valeur}"


def _oui_non(valeur: bool) -> str:
    return "oui" if valeur else "non"


def _oui_non_inconnu(valeur) -> str:
    if valeur is None:
        return "inconnu"
    return "oui" if valeur else "non"


def afficher(doc: Document) -> None:
    d = doc.diagnostic
    print("\n" + "=" * 64)
    print(f"DIAGNOSTIC — {doc.metadata.filename}")
    print("=" * 64)

    print(_ligne("Pages", doc.metadata.page_count))
    print(_ligne("Texte natif présent", _oui_non(d.has_native_text)))
    print(_ligne("Qualité texte natif", d.native_text_quality if d.native_text_quality is not None else "n/a"))
    couverture = f"{d.native_text_coverage:.1%}" if d.native_text_coverage is not None else "n/a"
    print(_ligne("Couverture texte natif", couverture))
    print(_ligne("Score ordre de lecture", d.reading_order_score if d.reading_order_score is not None else "n/a"))
    print(_ligne("Images", _oui_non(d.has_images)))
    print(_ligne("Tableaux", _oui_non(d.has_tables)))
    print(_ligne("Texte vectorisé (glyphes)", _oui_non(d.vectorized_text_detected)))
    print(_ligne("Images avec texte", _oui_non_inconnu(d.has_images_with_text)))
    print(_ligne("Images pleine page", _oui_non(d.has_full_page_images)))
    print(_ligne("OCR embarqué détecté", _oui_non(d.embedded_ocr_detected)))
    print(_ligne("Images basse résolution", _oui_non(d.low_dpi_images_detected)))
    print(_ligne("Chevauchement de texte", _oui_non(d.overlapping_text_detected)))
    print(_ligne("Coordonnées hors-limites", _oui_non(d.out_of_bounds_detected)))
    print(_ligne("Chiffré", _oui_non(d.encrypted)))
    if d.suspect_producer:
        print(_ligne("Producteur suspect", d.suspect_producer))
    if d.empty_pages:
        print(_ligne("Pages vides", ", ".join(str(p) for p in d.empty_pages)))
    if d.categorie:
        print(_ligne("Catégorie", d.categorie))

    print("-" * 64)
    print(_ligne("RECOMMANDATION SEGMENTATION", "OUI" if getattr(d, "recommend_segmentation", False) else "NON"))
    if getattr(d, "segmentation_reasons", []):
        print(_ligne("Raisons segmentation", ", ".join(d.segmentation_reasons)))

    print("-" * 64)
    print(_ligne("RECOMMANDATION OCR", "OUI" if d.recommend_ocr else "NON"))
    print(_ligne("OCR pleine page", "OUI" if d.recommend_full_ocr else "NON"))
    if d.ocr_reasons:
        print(_ligne("Raisons", ", ".join(d.ocr_reasons)))

    if d.notes:
        print("-" * 64)
        print("Notes détaillées :")
        for note in d.notes:
            print(f"  • {note}")
    print("=" * 64 + "\n")

