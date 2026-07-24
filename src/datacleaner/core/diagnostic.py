"""
diagnostic.py — Remplit doc.diagnostic à partir de l'objet Document DÉJÀ
EXTRAIT (doc.pages[].native / .graphics). Ne rouvre JAMAIS le PDF -- c'est le
gain direct de la nouvelle architecture : diagnostic.py devient une fonction
pure de Document, plus rapide et plus simple que la version précédente qui
rouvrait le fichier avec pdfplumber.

Diagnostic est un objet UNIQUE au niveau du document (pas par page, suivant
le schéma JSON fourni) -- diagnostic.py agrège donc les signaux de toutes
les pages. C'est une vraie simplification (perte de nuance par page, ex. un
document de 15 pages où une seule page pose problème déclenchera quand même
recommend_ocr=True pour tout le document) -- les pages concernées restent
listées dans `notes` pour ne pas perdre l'info, à charge pour ocr.py/pipeline
d'affiner plus tard si besoin de cibler certaines pages seulement.

Usage : diagnostiquer(doc) -> Document (même objet, modifié en place et retourné)
"""

import re

from datacleaner.core.document import Document

SUSPECT_PATTERN = re.compile(r"[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]")
TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)

SEUIL_COUVERTURE_PLEINE_PAGE = 0.85
SEUIL_BAS = 0.6
SEUIL_HAUT = 0.9

def _chiffre_dans_mot(tok):
    return any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok)

def _casse_irreguliere(tok):
    return any(tok[i - 1].islower() and tok[i].isupper() for i in range(1, len(tok)))

def _texte_page(page):
    return " ".join(w.text for w in page.native.words)

def _detecter_erreurs_encodage(texte):
    """Détecte les erreurs d'encodage courantes dans les PDFs.

    Returns:
        tuple: (taux_erreurs, details) où details est une liste de tuples
               (type_erreur, count, exemples)
    """
    erreurs = []
    total_chars = len(texte)
    if total_chars == 0:
        return 0.0, []

    # 1. Symbole euro manquant (remplacé par 'e' ou 'E' isolé)
    # Pattern: 'e' ou 'E' précédé/suivi par un espace ou un chiffre
    euro_pattern = re.compile(r'(?<!\w)(\be\b)(?!\w)', re.UNICODE)
    euro_matches = euro_pattern.findall(texte)
    if euro_matches:
        count = len(euro_matches)
        # Filtrer les faux positifs: 'e' dans des mots comme 'le', 'de', etc.
        # On garde seulement les 'e' qui sont probablement des €
        true_euro = [m for m in euro_matches if
                     (m == 'e' and not texte[texte.find(m)-2:texte.find(m)+3].strip().isalpha())]
        if true_euro:
            erreurs.append(('symbole_euro_manquant', len(true_euro), true_euro[:3]))

    # 2. Apostrophes/guillemets mal encodés (droit au lieu de courbé)
    # ' au lieu de ' ou " au lieu de " ou ""
    straight_quote_pattern = re.compile(r"[']")
    straight_quotes = straight_quote_pattern.findall(texte)
    if straight_quotes:
        # Vérifier si ce sont des apostrophes dans des mots (probablement OK)
        # ou des guillemets isolés (probablement mal encodés)
        isolated_quotes = [q for i, q in enumerate(straight_quotes)
                          if i == 0 or not straight_quotes[i-1].isalnum()]
        if len(isolated_quotes) > 0:
            erreurs.append(('apostrophes_droites', len(straight_quotes), straight_quotes[:3]))

    # 3. Accents corrompus (caractères ASCII au lieu de Unicode)
    # Exemples: a au lieu de à, e au lieu de é, c au lieu de ç
    accent_patterns = [
        (r'\ba\b', 'à'),  # 'a' isolé qui devrait être 'à'
        (r'\be\b', 'é'),  # 'e' isolé qui devrait être 'é'
        (r'\bc\b', 'ç'),  # 'c' isolé qui devrait être 'ç'
        (r'\bu\b', 'ù'),  # 'u' isolé qui devrait être 'ù'
    ]
    for pattern, expected in accent_patterns:
        matches = re.findall(pattern, texte, re.UNICODE)
        if matches:
            # Filtrer les faux positifs (mots courts comme 'a', 'e' sont normaux)
            # On vérifie le contexte
            true_matches = []
            for match in matches:
                idx = texte.find(match)
                if idx > 0 and idx < len(texte) - 1:
                    context = texte[max(0, idx-2):min(len(texte), idx+3)]
                    # Si le contexte suggère un mot français, c'est probablement une erreur
                    if any(c.isalpha() for c in context.replace(match, '')):
                        true_matches.append(match)
            if true_matches:
                erreurs.append((f'accent_corrompu_{expected}', len(true_matches), true_matches[:3]))

    # 4. Espaces multiples ou anormaux
    space_pattern = re.compile(r'[ \t]{2,}')
    multi_spaces = space_pattern.findall(texte)
    if multi_spaces:
        erreurs.append(('espaces_multiples', len(multi_spaces), multi_spaces[:3]))

    # 5. Caractères de contrôle ou invisibles
    control_chars = re.compile(r'[\x00-\x1f\x7f-\x9f]')
    control_matches = control_chars.findall(texte)
    if control_matches:
        erreurs.append(('caracteres_controle', len(control_matches), control_matches[:3]))

    # 6. Mots avec des caractères suspects (comme 'pr´elev´ee')
    # Détecter les mots avec des apostrophes ou backticks à l'intérieur
    suspect_word_pattern = re.compile(r'\b\w+[\'`]\w+\b', re.UNICODE)
    suspect_words = suspect_word_pattern.findall(texte)
    if suspect_words:
        erreurs.append(('mots_avec_caracteres_suspects', len(suspect_words), suspect_words[:3]))

    # Calculer le taux d'erreurs
    total_erreurs = sum(count for _, count, _ in erreurs)
    taux = total_erreurs / total_chars if total_chars > 0 else 0.0

    return taux, erreurs

def _qualite_texte(texte):
    """Même heuristique que la version précédente (taux de caractères
    suspects + tokens à structure anormale), mais appliquée au texte
    reconstruit depuis les mots déjà extraits plutôt qu'en rouvrant le pdf.

    Amélioration: détecte aussi les erreurs d'encodage courantes.
    """
    if not texte:
        return None
    tokens = TOKEN_PATTERN.findall(texte)
    taux_suspect = len(SUSPECT_PATTERN.findall(texte)) / len(texte) if texte else 0.0
    taux_tokens = (
        len([t for t in tokens if len(t) >= 2 and (_chiffre_dans_mot(t) or _casse_irreguliere(t))]) / len(tokens)
        if tokens else 0.0
    )

    # Détecter les erreurs d'encodage
    taux_encodage, erreurs_encodage = _detecter_erreurs_encodage(texte)

    # Calculer la qualité en tenant compte des erreurs d'encodage
    # Plus de poids aux erreurs d'encodage car elles sont critiques
    qualite = max(0.0, 1.0 - taux_suspect * 5 - taux_tokens * 3 - taux_encodage * 10)

    return qualite

def _couverture_image_max(page):
    surface_page = page.width * page.height
    if not surface_page:
        return 0.0
    couverture = 0.0
    for img in page.graphics.images:
        if not img.bbox:
            continue
        largeur = img.bbox.x1 - img.bbox.x0
        hauteur = img.bbox.y1 - img.bbox.y0
        couverture = max(couverture, (largeur * hauteur) / surface_page)
    return couverture

def _score_ordre_lecture(page):
    """Proxy sans réouverture du PDF : regroupe les mots en lignes par leur
    position verticale (comme render.py), puis vérifie que l'ordre
    d'apparition dans page.native.words (ordre d'extraction PyMuPDF)
    correspond à l'ordre géométrique gauche->droite au sein de chaque ligne.
    Un score bas signale un flux d'extraction qui ne suit pas la géométrie
    visuelle (colonnes mélangées, mots entrelacés)."""
    mots = [w for w in page.native.words if w.bbox]
    if len(mots) < 2:
        return 1.0

    lignes = {}
    for w in mots:
        y_arrondi = round(w.bbox.y0 / 3) * 3  # tolérance de regroupement
        lignes.setdefault(y_arrondi, []).append(w)

    total_paires = 0
    paires_dans_ordre = 0
    for ligne in lignes.values():
        if len(ligne) < 2:
            continue
        for i in range(len(ligne) - 1):
            total_paires += 1
            if ligne[i].bbox.x0 <= ligne[i + 1].bbox.x0:
                paires_dans_ordre += 1

    return paires_dans_ordre / total_paires if total_paires else 1.0

def diagnostiquer(doc: Document) -> Document:
    notes = []
    scores_qualite = []
    scores_ordre = []
    a_texte_natif = False
    a_images = False
    a_tables = False
    a_images_pleine_page = False
    ocr_integre_detecte = False
    erreurs_encodage_par_page = []

    for page in doc.pages:
        texte = _texte_page(page)
        if page.native.words:
            a_texte_natif = True
        if page.graphics.images:
            a_images = True
        if page.graphics.tables:
            a_tables = True

        couverture = _couverture_image_max(page)
        pleine_page = couverture >= SEUIL_COUVERTURE_PLEINE_PAGE
        if pleine_page:
            a_images_pleine_page = True

        qualite = _qualite_texte(texte)
        if qualite is not None:
            scores_qualite.append(qualite)

        # Détecter les erreurs d'encodage pour cette page
        _, erreurs_page = _detecter_erreurs_encodage(texte)
        if erreurs_page:
            erreurs_encodage_par_page.append((page.number, erreurs_page))

        # OCR tiers déjà appliqué en amont : image pleine page + texte natif
        # présent quand même (cf. test7, session précédente)
        if pleine_page and page.native.words:
            ocr_integre_detecte = True
            notes.append(f"Page {page.number} : OCR tiers probable (image pleine page + texte natif présent)")
            qualite = min(qualite, 0.4) if qualite is not None else 0.4

        ordre = _score_ordre_lecture(page)
        scores_ordre.append(ordre)
        if ordre < 0.85:
            notes.append(f"Page {page.number} : ordre de lecture instable (score {ordre:.2f})")

        if not page.native.words:
            notes.append(f"Page {page.number} : aucun texte natif -- OCR obligatoire")

    native_text_quality = round(sum(scores_qualite) / len(scores_qualite), 3) if scores_qualite else None
    reading_order_score = round(sum(scores_ordre) / len(scores_ordre), 3) if scores_ordre else None

    # Ajouter des notes sur les erreurs d'encodage
    if erreurs_encodage_par_page:
        for page_num, erreurs in erreurs_encodage_par_page:
            for type_erreur, count, exemples in erreurs:
                if type_erreur == 'symbole_euro_manquant':
                    notes.append(f"Page {page_num} : symbole € probablement manquant (trouvé {count}x '{exemples[0] if exemples else 'e'}' à la place)")
                elif type_erreur == 'apostrophes_droites':
                    notes.append(f"Page {page_num} : apostrophes/guillemets probablement mal encodés ({count}x)")
                elif type_erreur.startswith('accent_corrompu_'):
                    char = type_erreur.split('_')[-1]
                    notes.append(f"Page {page_num} : accent '{char}' probablement corrompu ({count}x)")
                elif type_erreur == 'espaces_multiples':
                    notes.append(f"Page {page_num} : espaces multiples détectés ({count}x)")
                elif type_erreur == 'mots_avec_caracteres_suspects':
                    notes.append(f"Page {page_num} : mots avec caractères suspects (ex: {', '.join(exemples[:2])}) ({count}x)")

    recommend_ocr = (
        not a_texte_natif
        or (native_text_quality is not None and native_text_quality < SEUIL_HAUT)
        or ocr_integre_detecte
        or bool(erreurs_encodage_par_page)  # Recommander OCR si erreurs d'encodage
    )

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
    doc.diagnostic.image_quality = None  # pas de métrique fiable sans inspection visuelle -- non fabriqué
    doc.diagnostic.recommend_ocr = recommend_ocr
    doc.diagnostic.notes = notes

    return doc

if __name__ == "__main__":
    import sys
    from document import Document as _Document

    if len(sys.argv) < 2:
        print("Usage : python diagnostic.py document.json")
        sys.exit(1)

    doc = _Document.load(sys.argv[1])
    diagnostiquer(doc)
    print(doc.diagnostic)
