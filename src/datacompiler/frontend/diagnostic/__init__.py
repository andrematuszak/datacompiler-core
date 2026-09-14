"""diagnostic/ — Remplit page.diagnostic (et agrège doc.diagnostic) à partir
de l'objet Document DÉJÀ EXTRAIT. Ne rouvre jamais le PDF."""

from datacompiler.model.document import Document
from datacompiler.model.metadata import Diagnostic

from .categorize import SEUIL_QUALITE_CORROMPU, categoriser
from . import blind_spots, container, spatial_integrity, text_integrity, vector_text, visual_integrity

def _diagnostiquer_page(page) -> Diagnostic:
    notes = []
    ocr_reasons = []
    diag = page.diagnostic

    texte = text_integrity.texte_page(page)
    has_native = bool(page.native.words)
    qualite = text_integrity.qualite_texte(texte)
    confiance = blind_spots.qualite_avec_confiance(texte, qualite)
    symboles = blind_spots.symboles_corrompus(texte)
    mots_suspects = blind_spots.mots_suspects_ngrammes(texte)

    couverture = visual_integrity.couverture_image_max(page)
    couverture_native = vector_text.couverture_texte_natif(page)
    texte_vectorise = vector_text.texte_vectorise_detecte(page)
    images_avec_texte = visual_integrity.images_avec_texte(page)
    pleine_page = couverture >= visual_integrity.SEUIL_COUVERTURE_PLEINE_PAGE
    ocr_integre = pleine_page and has_native

    if ocr_integre:
        notes.append("OCR tiers probable (image pleine page + texte natif présent)")
        qualite = min(qualite, 0.4) if qualite is not None else 0.4

    if text_integrity.page_a_faible_densite(page) and not page.graphics.images and has_native:
        notes.append("Densité textuelle anormalement basse pour une page non vide")

    images_basse_res = visual_integrity.images_basse_resolution(page)
    for img, dpi in images_basse_res:
        notes.append(f"Image basse résolution ({dpi:.0f} DPI effectif)")

    chevauchements = spatial_integrity.detecter_chevauchements(page)
    if chevauchements:
        notes.append(f"{len(chevauchements)} paire(s) de mots avec bbox chevauchantes")

    hors_limites = spatial_integrity.detecter_hors_limites(page)
    if hors_limites:
        notes.append(f"{len(hors_limites)} mot(s) hors des limites de la page")

    ordre = spatial_integrity.score_ordre_lecture(page)
    if ordre < 0.85:
        notes.append(f"Ordre de lecture instable (score {ordre:.2f})")

    if not has_native:
        notes.append("Aucun texte natif -- OCR obligatoire")

    if couverture_native is not None and couverture_native < 0.9:
        notes.append(f"Couverture texte natif insuffisante ({couverture_native:.1%}) -- texte vectoriel à extraire")

    if symboles:
        notes.append(f"Symboles corrompus suspects : {symboles}")

    if not confiance["confiance_suffisante"]:
        notes.append(
            f"Échantillon court ({confiance['nb_mots_analyses']} mots) -- "
            "score de qualité peu fiable"
        )

    recommend_ocr = (
        not has_native
        or (qualite is not None and qualite < SEUIL_QUALITE_CORROMPU)
        or (couverture_native is not None and couverture_native < 0.9)
        or images_avec_texte is True
        or ocr_integre
        or confiance["recommend_ocr_par_precaution"]
        or bool(symboles)
    )
    # Une recommandation d'enrichissement n'implique pas une OCRisation
    # coûteuse de la page entière. Les pages mixtes sont traitées par les
    # OCR ciblés (vecteurs / images) ; seul un scan complet y a droit.
    recommend_full_ocr = not has_native or ocr_integre

    if not has_native:
        ocr_reasons.append("aucun_texte_natif")
    if qualite is not None and qualite < SEUIL_QUALITE_CORROMPU:
        ocr_reasons.append("qualite_texte_basse")
    if couverture_native is not None and couverture_native < 0.9:
        ocr_reasons.append("couverture_native_basse")
    if images_avec_texte is True:
        ocr_reasons.append("texte_dans_image")
    if ocr_integre:
        ocr_reasons.append("ocr_tiers_detecte")
    if confiance["recommend_ocr_par_precaution"]:
        ocr_reasons.append("echantillon_court")
    if symboles:
        ocr_reasons.append("symboles_corrompus")

    diag.has_native_text = has_native
    diag.has_images = bool(page.graphics.images)
    diag.has_tables = bool(page.graphics.tables)
    diag.has_full_page_images = pleine_page
    diag.embedded_ocr_detected = ocr_integre
    diag.reading_order_score = round(ordre, 3)
    diag.native_text_quality = round(qualite, 3) if qualite is not None else None
    diag.native_text_coverage = round(couverture_native, 3) if couverture_native is not None else None
    diag.image_quality = None
    diag.recommend_ocr = recommend_ocr
    diag.recommend_full_ocr = recommend_full_ocr
    diag.ocr_reasons = ocr_reasons
    diag.low_dpi_images_detected = bool(images_basse_res)
    diag.overlapping_text_detected = bool(chevauchements)
    diag.out_of_bounds_detected = bool(hors_limites)
    diag.confiance_suffisante = confiance["confiance_suffisante"]
    diag.symboles_suspects = symboles
    diag.mots_suspects_ngrammes = mots_suspects
    diag.notes = notes
    diag.vectorized_text_detected = texte_vectorise
    diag.has_images_with_text = images_avec_texte
    diag.categorie = categoriser(diag.has_native_text, diag.embedded_ocr_detected, diag.native_text_quality, diag.native_text_coverage)
    return diag


def pages_a_ocriser(doc: Document) -> list[int]:
    return [page.number for page in doc.pages if page.diagnostic.recommend_ocr]


def diagnostiquer(doc: Document) -> Document:
    notes = []
    ocr_reasons = []
    scores_qualite = []
    scores_ordre = []
    couvertures_natives = []
    a_texte_natif = False
    a_images = False
    a_tables = False
    a_images_pleine_page = False
    ocr_integre_detecte = False
    ocr_pleine_page_recommande = False
    dpi_bas_detecte = False
    chevauchement_detecte = False
    hors_limites_detecte = False
    pages_vides = []
    confiance_globale = True
    symboles_globaux = {}
    mots_suspects_globaux = []

    for page in doc.pages:
        _diagnostiquer_page(page)
        pd = page.diagnostic

        if pd.has_native_text:
            a_texte_natif = True
        if pd.has_images:
            a_images = True
        if pd.has_tables:
            a_tables = True
        if pd.has_full_page_images:
            a_images_pleine_page = True
        if pd.embedded_ocr_detected:
            ocr_integre_detecte = True
        if pd.recommend_full_ocr:
            ocr_pleine_page_recommande = True
        if pd.low_dpi_images_detected:
            dpi_bas_detecte = True
        if pd.overlapping_text_detected:
            chevauchement_detecte = True
        if pd.out_of_bounds_detected:
            hors_limites_detecte = True
        if pd.confiance_suffisante is False:
            confiance_globale = False
        symboles_globaux.update(pd.symboles_suspects)
        if pd.mots_suspects_ngrammes:
            mots_suspects_globaux.extend(pd.mots_suspects_ngrammes)

        if not page.native.words and not page.graphics.images:
            pages_vides.append(page.number)

        if pd.native_text_quality is not None:
            scores_qualite.append(pd.native_text_quality)
        if pd.reading_order_score is not None:
            scores_ordre.append(pd.reading_order_score)
        if pd.native_text_coverage is not None:
            couvertures_natives.append(pd.native_text_coverage)

        for note in pd.notes:
            notes.append(f"Page {page.number} : {note}")
        for reason in pd.ocr_reasons:
            if reason not in ocr_reasons:
                ocr_reasons.append(reason)

    native_text_quality = round(sum(scores_qualite) / len(scores_qualite), 3) if scores_qualite else None
    reading_order_score = round(sum(scores_ordre) / len(scores_ordre), 3) if scores_ordre else None
    native_text_coverage = min(couvertures_natives) if couvertures_natives else None

    encrypted = doc.metadata.encrypted
    if encrypted:
        notes.append("Document chiffré -- l'extraction peut être incomplète ou échouer selon les restrictions")

    suspect = container.producteur_suspect(doc)
    if suspect:
        notes.append(f"Producteur '{suspect}' déjà observé comme peu fiable sur vos tests précédents")

    recommend_ocr = any(page.diagnostic.recommend_ocr for page in doc.pages)

    if recommend_ocr and not notes:
        notes.append("Enrichissement recommandé (raison non détaillée par page)")
    if not recommend_ocr:
        notes.append("Texte natif jugé suffisamment fiable sur toutes les pages -- OCR non recommandé (économie)")

    doc.diagnostic.has_native_text = a_texte_natif
    doc.diagnostic.has_images = a_images
    doc.diagnostic.has_tables = a_tables
    doc.diagnostic.has_full_page_images = a_images_pleine_page
    doc.diagnostic.embedded_ocr_detected = ocr_integre_detecte
    doc.diagnostic.reading_order_score = reading_order_score
    doc.diagnostic.native_text_quality = native_text_quality
    doc.diagnostic.native_text_coverage = native_text_coverage
    doc.diagnostic.image_quality = None
    doc.diagnostic.recommend_ocr = recommend_ocr
    doc.diagnostic.recommend_full_ocr = ocr_pleine_page_recommande
    doc.diagnostic.ocr_reasons = ocr_reasons
    doc.diagnostic.encrypted = encrypted
    doc.diagnostic.suspect_producer = suspect
    doc.diagnostic.low_dpi_images_detected = dpi_bas_detecte
    doc.diagnostic.overlapping_text_detected = chevauchement_detecte
    doc.diagnostic.out_of_bounds_detected = hors_limites_detecte
    doc.diagnostic.empty_pages = pages_vides
    doc.diagnostic.confiance_suffisante = confiance_globale
    doc.diagnostic.symboles_suspects = symboles_globaux
    doc.diagnostic.mots_suspects_ngrammes = mots_suspects_globaux
    doc.diagnostic.notes = notes
    doc.diagnostic.vectorized_text_detected = any(page.diagnostic.vectorized_text_detected for page in doc.pages)
    statuts_images_texte = [page.diagnostic.has_images_with_text for page in doc.pages if page.diagnostic.has_images_with_text is not None]
    doc.diagnostic.has_images_with_text = any(statuts_images_texte) if statuts_images_texte else None
    doc.diagnostic.categorie = categoriser(doc.diagnostic.has_native_text, doc.diagnostic.embedded_ocr_detected, doc.diagnostic.native_text_quality, doc.diagnostic.native_text_coverage)
    return doc
