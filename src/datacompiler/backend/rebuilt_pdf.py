"""rebuilt_pdf.py — Reconstruction fidèle d'un PDF neuf, texte VISIBLE et
sélectionnable, à la même position que le source.

Reprend et corrige _copier_images_et_dessins / _inserer_texte de
faithful_pdf.py (clean_overlay), adaptées pour tourner directement sur le
modèle Document (pas de JSON brut). Correctifs appliqués par rapport au
faithful_pdf.py :

  1. bug 'qu'/fitz.Quad : pts = item[1:] -> pts = list(item[1])
  2. fill_opacity=0.015 codé en dur dans _inserer_texte : ici le texte
     reconstruit est le SEUL contenu textuel de la page (rien dessous à
     dupliquer visuellement, contrairement au mode overlay) -> opacité
     pleine (1.0)
  3. police de repli sans fichier réel (_FALLBACK_FONTFILE = None dans le
     fichier uploadé) -> LiberationSans (Regular/Bold), qui contient bien
     le glyphe '€' contrairement au Helvetica de base intégré à PyMuPDF
  4. fitz.TextWriter au lieu d'insert_text() mot par mot (un nouveau
     content stream par mot sinon) -- un writer par segment de couleur
     contiguë, pas un writer par couleur globale (cf. docstring de
     `inserer_mot`, ça détruirait l'ordre de lecture)
  5. output.subset_fonts() juste avant la sauvegarde -- police embarquée
     réduite aux seuls glyphes utilisés

ORDRE DE LECTURE : reading_order.ordonner() directement sur native.words,
pour TOUTES les pages, sans exception ni cas particulier par page.

Remplace deux choses de la version précédente, qui reproduisaient encore
le bug qu'on venait de corriger :
  - pages 1 et 3 utilisaient `resolved.words` tel quel -- c'est-à-dire
    l'ordre produit par l'ANCIEN moteur colonnes (celui qu'on a démonté),
    pas le nouveau moteur boîtes/rangées. Confirmé : c'est exactement ce
    qui faisait ressortir "Vos" avant "Direction" sur la page 1.
  - la page 2 passait par `simulate_reading_order.ordonner_instrumente`,
    un module distinct de `reading_order.py`, potentiellement une version
    antérieure lui aussi -- plus un réappariement par position arrondie
    (round(x0,1), round(y0,1), text) vers resolved.words pour récupérer
    font_size/font/bold, qui échouait silencieusement sur certains mots
    (log "ATTENTION: N mots non réappariés") et les faisait retomber sur
    font_size=0.0 -- une des deux causes du désalignement de la session
    précédente.

`reading_order.ordonner()` prend `page.native.words` (qui porte déjà
font_size/font/bold/color/resolved_text) et rend une copie triée dans le
bon ordre -- plus besoin de réappariement du tout, plus besoin de
`simulate_reading_order.py`. Une seule source de vérité pour toutes les
pages.
"""

import logging
from pathlib import Path

import fitz

from datacompiler.compile.reading_order import ordonner
from datacompiler.model.document import Document

logger = logging.getLogger(__name__)

# --- Polices embarquées dans le package (backend/fonts/) ---
# LiberationSans contient le glyphe '€', contrairement au Helvetica de base
# intégré à PyMuPDF (bug déjà rencontré sur la couche invisible -- ici le
# texte est VISIBLE, donc l'erreur serait visible aussi).
_FONTS_DIR = Path(__file__).parent / "fonts"
_FONT_REGULAR = _FONTS_DIR / "LiberationSans-Regular.ttf"
_FONT_BOLD = _FONTS_DIR / "LiberationSans-Bold.ttf"
# Repli si LiberationSans absent (ex. installation minimale) : DejaVuSans
# contient aussi '€'.
_FONT_FALLBACK = _FONTS_DIR / "DejaVuSans.ttf"

_polices = {}  # cache global (chemin -> (fitz.Font, nom))


def _font_objet(gras):
    """Retourne (fitz.Font, nom) pour le style demandé, avec cache."""
    fichier = _FONT_BOLD if gras else _FONT_REGULAR
    nom = "LiberationSans-Bold" if gras else "LiberationSans"
    if not fichier.exists():
        fichier = _FONT_FALLBACK
        nom = "DejaVuSans"
    if fichier not in _polices:
        _polices[fichier] = (fitz.Font(fontfile=str(fichier)), nom)
    return _polices[fichier]


def _hex_to_rgb(hex_color):
    """Convertit '#RRGGBB' ou '#RRGGBBAA' en tuple RGB(A) normalisé 0..1."""
    if not hex_color or not isinstance(hex_color, str):
        return (0, 0, 0)
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return (r / 255.0, g / 255.0, b / 255.0)
    elif len(hex_color) == 8:
        r, g, b, a = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16), int(hex_color[6:8], 16)
        return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)
    return (0, 0, 0)


def _copier_images_et_dessins(src_page, dst_page, report, exclure=None):
    """Copie les images et dessins vectoriels du source vers la page de
    destination.

    `exclure` : liste de bbox (objets BBox) des mots reconstruits/
    vectorisés (is_vectorized/reconstructed). Un groupe de dessin dont le
    rectangle englobant tombe majoritairement dans une de ces bbox est un
    tracé de GLYPHE (le mot a été vectorisé puis OCRisé, donc ce n'est pas
    du texte sélectionnable dans la source -- exactement la même chose
    qu'un mot ocr_vectoriel) -- pas une bordure/logo/décoration. On ne le
    copie pas, sinon on obtient une double impression : le tracé original
    + le texte OCR réinséré par-dessus au même endroit (bug reproduit et
    confirmé empiriquement sur "Avis d'impôt établi en 2021", page 1).
    """
    exclure = exclure or []

    def _dans_une_exclusion(rect):
        if rect is None:
            return False
        for b in exclure:
            zone = fitz.Rect(b.x0, b.y0, b.x1, b.y1)
            inter = rect & zone
            if not inter.is_empty and inter.get_area() >= 0.6 * rect.get_area():
                return True
        return False

    # --- Images ---
    for img in src_page.get_images():
        xref = img[0]
        rects = src_page.get_image_rects(xref)
        if not rects:
            report["images_ignorees"] += 1
            continue
        try:
            img_dict = src_page.parent.extract_image(xref)
            if img_dict and "image" in img_dict:
                stream = img_dict["image"]
                for rect in rects:
                    dst_page.insert_image(rect, stream=stream)
                report["images_copiees"] += len(rects)
            else:
                report["images_ignorees"] += 1
        except Exception as e:
            logger.warning("Échec copie image xref %s : %s", xref, e)
            report["images_ignorees"] += 1

    # --- Dessins vectoriels ---
    shape = dst_page.new_shape()
    dessins_ignores = 0
    dessins_exclus_glyphes = 0
    for draw in src_page.get_drawings():
        if _dans_une_exclusion(draw.get("rect")):
            dessins_exclus_glyphes += 1
            continue
        items = draw.get("items", [])
        color = draw.get("color", None)
        fill = draw.get("fill", None)
        width = draw.get("width", 1.0)
        dashes = draw.get("dashes", None)
        for item in items:
            typ = item[0]
            try:
                if typ == "l":
                    shape.draw_line(item[1], item[2])
                elif typ == "re":
                    shape.draw_rect(item[1])
                elif typ == "c":
                    pts = item[1:]
                    if len(pts) == 4:
                        shape.draw_bezier(pts[0], pts[1], pts[2], pts[3])
                elif typ == "qu":
                    q = item[1]  # fitz.Quad : list(q) donne (ul, ur, ll, lr) --
                                 # ordre "Z", pas un ordre de périmètre. Reste
                                 # tel quel = quadrilatère croisé (vérifié).
                    shape.draw_polyline([q.ul, q.ur, q.lr, q.ll])
                else:
                    dessins_ignores += 1
                    continue
            except Exception:
                dessins_ignores += 1
                continue
        if shape:
            shape.finish(color=color, fill=fill, width=width, dashes=dashes)
    shape.commit()
    report["dessins_ignores"] += dessins_ignores
    report["dessins_exclus_glyphes"] = report.get("dessins_exclus_glyphes", 0) + dessins_exclus_glyphes


def _inserer_mot(etat, page_rect, mot, report):
    """Ajoute le mot à un fitz.TextWriter. insert_text() crée un NOUVEAU
    content stream à chaque appel (confirmé : 322 objets stream rien que
    pour les ~317 mots de la page 1) -- TextWriter accumule en mémoire et
    n'écrit qu'UN SEUL stream par write_text().

    ATTENTION ordre : un TextWriter fixe SA couleur au moment de
    write_text(), pas mot par mot. Grouper tous les mots par couleur AVANT
    d'écrire (un writer noir, un writer blanc) déplace tous les mots blancs
    à la fin du flux -- confirmé empiriquement, ça détruit l'ordre de
    lecture qu'on vient de corriger (le bloc "Somme qui vous est
    remboursée" en blanc se retrouvait en position 312/317 au lieu de sa
    place naturelle). Correctif : un nouveau writer est ouvert seulement
    quand la couleur CHANGE dans la séquence -- l'ordre est préservé, et
    comme la couleur change rarement (2 couleurs sur tout le document,
    quelques transitions par page), le nombre de streams reste bas.
    """
    texte = mot.resolved_text or mot.text or ""
    if not texte.strip():
        return
    bbox = mot.bbox
    if bbox is None:
        return
    gras = bool(mot.bold) or "bold" in (mot.font or "").lower()
    police, nom_police = _font_objet(gras)

    taille_nominale = mot.font_size or 0.0
    if not taille_nominale:
        taille_nominale = max(4.0, bbox.y1 - bbox.y0)
        report["taille_heuristique"] += 1

    largeur_cible = max(bbox.x1 - bbox.x0, 0.1)
    largeur_rendue = police.text_length(texte, fontsize=taille_nominale)
    taille = (taille_nominale * (largeur_cible / largeur_rendue)
              if largeur_rendue else taille_nominale)

    couleur_cle = mot.color or "#000000"
    if couleur_cle != etat["couleur_cle"]:
        etat["segments"].append((etat["couleur_cle"], etat["tw"]))
        etat["tw"] = fitz.TextWriter(page_rect)
        etat["couleur_cle"] = couleur_cle

    point = fitz.Point(bbox.x0, bbox.y1)
    etat["tw"].append(point, texte, font=police, fontsize=taille)
    report["mots_inseres"] += 1


def render_rebuilt_pdf(doc: Document, output_path: str, source_pdf: str = None, dpi: int = 300) -> str:
    """Reconstruit un PDF neuf, texte visible et sélectionnable, à la même
    position que le source.

    - Copie les images et dessins du PDF source (en excluant les tracés de
      glyphes des mots vectorisés/OCRisés, pour éviter la double impression).
    - Réinjecte le texte résolu dans l'ordre de lecture réel
      (reading_order.ordonner sur native.words), à la même position.
    - Utilise LiberationSans (embarquée dans le package) pour couvrir '€'.

    Retourne le chemin du fichier écrit.
    """
    source_path = source_pdf or doc.metadata.source_pdf
    if not source_path:
        raise ValueError("Le chemin du PDF source est requis (doc.metadata.source_pdf).")

    source = fitz.open(source_path)
    if len(source) != len(doc.pages):
        source.close()
        raise ValueError("Le PDF source et Document n'ont pas le même nombre de pages.")

    output = fitz.open()
    try:
        for src_page, model_page in zip(source, doc.pages):
            dst_page = output.new_page(width=src_page.rect.width, height=src_page.rect.height)

            report = {"images_copiees": 0, "images_ignorees": 0, "dessins_ignores": 0,
                      "mots_inseres": 0, "taille_heuristique": 0}

            # Bbox des mots reconstruits/vectorisés : leurs tracés de glyphes
            # dans le source ne doivent pas être recopiés (double impression).
            bbox_vectorisees = [w.bbox for w in model_page.resolved.words
                                if w.bbox and (w.reconstructed or w.is_vectorized
                                               or w.source == "ocr_vectoriel")]
            _copier_images_et_dessins(src_page, dst_page, report, exclure=bbox_vectorisees)

            # Ordre de lecture réel, directement depuis native.words.
            ordre = ordonner(model_page)

            writers = {"tw": fitz.TextWriter(dst_page.rect), "couleur_cle": "#000000",
                       "segments": []}
            for mot in ordre:
                _inserer_mot(writers, dst_page.rect, mot, report)
            writers["segments"].append((writers["couleur_cle"], writers["tw"]))
            for couleur_cle, tw in writers["segments"]:
                tw.write_text(dst_page, color=_hex_to_rgb(couleur_cle), render_mode=0, opacity=1.0)

            logger.info("page %s : %s", model_page.number, report)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        output.set_metadata({"producer": "DataCompiler rebuilt_pdf",
                             "title": doc.metadata.filename})
        output.subset_fonts()  # police embarquée réduite aux seuls glyphes utilisés
        output.save(output_path, garbage=4, deflate=True)
    finally:
        output.close()
        source.close()

    return output_path
