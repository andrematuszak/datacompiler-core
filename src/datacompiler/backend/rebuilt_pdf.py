"""
rebuilt_pdf.py — Reconstruction fidèle d'un PDF neuf, texte visuellement
fidèle et sélectionnable, à la même position que le source.

Architecture optimisée :
  1. Regroupement des mots consécutifs en Spans/Lignes continus (métrique de ligne stable).
  2. Calcul précis de la Baseline typographique basé sur l'ascender réel de la police.
  3. Compression horizontale ciblée via matrice (morphing PyMuPDF) sans altérer la hauteur.
  4. Préservation de la sélection du texte sans injection de hacks d'espaces fictifs.
  5. Conservation des tracés des mots vectorisés inchangés ; les corrections
     restent visibles dans la couche reconstruite.
  6. Copie fidèle des images et éléments graphiques du document source.
"""

import logging
from functools import lru_cache
from pathlib import Path
import pymupdf

from datacompiler.model.document import Document
from datacompiler.utils.font_metrics import ratio_encre_em

logger = logging.getLogger(__name__)

# --- Polices embarquées dans le package (backend/fonts/) ---
_FONTS_DIR = Path(__file__).parent / "fonts"
_FONT_REGULAR = _FONTS_DIR / "LiberationSans-Regular.ttf"
_FONT_BOLD = _FONTS_DIR / "LiberationSans-Bold.ttf"
_FONT_ITALIC = _FONTS_DIR / "LiberationSans-Italic.ttf"
_FONT_BOLD_ITALIC = _FONTS_DIR / "LiberationSans-BoldItalic.ttf"
_FONT_FALLBACK = _FONTS_DIR / "DejaVuSans.ttf"

_polices = {}  # cache global (chemin -> (pymupdf.Font, nom))


def _font_objet(gras, italic=False):
    """Retourne (pymupdf.Font, nom) pour le style demandé, avec cache."""
    if gras and italic:
        fichier, nom = _FONT_BOLD_ITALIC, "LiberationSans-BoldItalic"
    elif gras:
        fichier, nom = _FONT_BOLD, "LiberationSans-Bold"
    elif italic:
        fichier, nom = _FONT_ITALIC, "LiberationSans-Italic"
    else:
        fichier, nom = _FONT_REGULAR, "LiberationSans"

    if not fichier.exists():
        fichier = _FONT_FALLBACK
        nom = "DejaVuSans"

    if fichier not in _polices:
        _polices[fichier] = (pymupdf.Font(fontfile=str(fichier)), nom)
    return _polices[fichier]


def _hex_to_rgb(hex_color):
    """Convertit '#RRGGBB' ou '#RRGGBBAA' en tuple RGB(A) normalisé 0..1."""
    if not hex_color or not isinstance(hex_color, str):
        return (0.0, 0.0, 0.0)
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return (r / 255.0, g / 255.0, b / 255.0)
    elif len(hex_color) == 8:
        r, g, b, a = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16), int(hex_color[6:8], 16)
        return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)
    return (0.0, 0.0, 0.0)


def _copier_images_et_dessins(src_page, dst_page, report, exclure=None):
    """
    Copie les images et dessins vectoriels du source vers la page de destination.
    Les tracés de glyphes ne sont exclus que lorsque leur texte est reconstruit
    visiblement ; les mots vectorisés inchangés gardent leur forme source.
    """
    exclure = exclure or []

    def _match_exclusion(rect):
        if rect is None:
            return None
        for w in exclure:
            if not w.bbox:
                continue
            zone = pymupdf.Rect(w.bbox.x0, w.bbox.y0, w.bbox.x1, w.bbox.y1)
            inter = rect & zone
            if not inter.is_empty and inter.get_area() >= 0.6 * rect.get_area():
                return w
        return None

    # --- Images ---
    for img in src_page.get_images():
        xref = img[0]
        rects = src_page.get_image_rects(xref)
        if not rects:
            report["images_ignorees"] = report.get("images_ignorees", 0) + 1
            continue
        try:
            img_dict = src_page.parent.extract_image(xref)
            if img_dict and "image" in img_dict:
                stream = img_dict["image"]
                for rect in rects:
                    dst_page.insert_image(rect, stream=stream)
                report["images_copiees"] = report.get("images_copiees", 0) + len(rects)
            else:
                report["images_ignorees"] = report.get("images_ignorees", 0) + 1
        except Exception as e:
            logger.warning("Échec copie image xref %s : %s", xref, e)
            report["images_ignorees"] = report.get("images_ignorees", 0) + 1

    # --- Dessins vectoriels ---
    couleurs_echantillonnees = {}
    shape = dst_page.new_shape()
    dessins_ignores = 0
    dessins_exclus_glyphes = 0

    for draw in src_page.get_drawings():
        mot_touche = _match_exclusion(draw.get("rect"))
        if mot_touche is not None:
            dessins_exclus_glyphes += 1
            couleur = draw.get("fill") or draw.get("color")
            if couleur is not None:
                couleurs_echantillonnees[id(mot_touche)] = couleur
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
                    q = item[1]
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
    report["dessins_ignores"] = report.get("dessins_ignores", 0) + dessins_ignores
    report["dessins_exclus_glyphes"] = report.get("dessins_exclus_glyphes", 0) + dessins_exclus_glyphes

    return couleurs_echantillonnees


def _grouper_en_spans(mots, couleurs_echantillonnees=None, tolerance_y=3.0, ecart_max_mot=8.0):
    """
    Regroupe les mots consécutifs partageant ligne, style, couleur et mode
    de conservation des tracés source en spans continus.
    """
    if not mots:
        return []

    couleurs_echantillonnees = couleurs_echantillonnees or {}
    spans = []
    span_courant = None

    for w in mots:
        if not w.bbox:
            continue
        texte = w.resolved_text or w.text or ""
        if not texte.strip():
            continue

        b = pymupdf.Rect(w.bbox.x0, w.bbox.y0, w.bbox.x1, w.bbox.y1)
        gras = bool(w.bold) or "bold" in (w.font or "").lower()
        italic = bool(w.italic) or "italic" in (w.font or "").lower()
        taille = w.font_size or max(4.0, b.height)
        source_graphic = bool(w.is_vectorized and w.resolved_text == w.text)

        mot_id = id(w)
        if mot_id in couleurs_echantillonnees:
            couleur = tuple(couleurs_echantillonnees[mot_id])
        else:
            couleur = _hex_to_rgb(getattr(w, "color", "#000000"))
        couleur_key = tuple(round(c, 3) for c in couleur)

        if span_courant is None:
            span_courant = {
                "mots": [w],
                "textes": [texte],
                "bbox": b,
                "size": taille,
                "bold": gras,
                "italic": italic,
                "color": couleur_key,
                "source_graphic": source_graphic,
            }
            continue

        # Vérification d'appartenance au Span courant
        meme_ligne = abs(b.y0 - span_courant["bbox"].y0) <= tolerance_y
        meme_style = (
            span_courant["bold"] == gras
            and span_courant["italic"] == italic
            and span_courant["color"] == couleur_key
            and span_courant["source_graphic"] == source_graphic
            and abs(span_courant["size"] - taille) <= 1.5
        )
        proche = (b.x0 - span_courant["bbox"].x1) <= ecart_max_mot

        if meme_ligne and meme_style and proche:
            span_courant["mots"].append(w)
            span_courant["textes"].append(texte)
            span_courant["bbox"] |= b  # Étendre la bounding box du span
        else:
            # Même ligne, écart faible, mais nouveau span (taille/style/couleur
            # différents) : le flux PDF ne contiendrait AUCUN caractère espace
            # entre les deux, et Chrome/pdfium décide alors seul d'après l'écart
            # géométrique rendu -- faux si l'écart est sous son seuil (cas
            # "DES"/"FINANCES" : ~1,6 pt à 10 pt de corps). On matérialise
            # l'espace dans le texte du span précédent. Au-delà d'1 corps de
            # police d'écart, pdfium infère déjà l'espace : on n'ajoute rien
            # (évite un double espace, ex. "(C) :" / "13 86 ...").
            if meme_ligne and (b.x0 - span_courant["bbox"].x1) <= span_courant["size"]:
                span_courant["espace_apres"] = True
            spans.append(span_courant)
            span_courant = {
                "mots": [w],
                "textes": [texte],
                "bbox": b,
                "size": taille,
                "bold": gras,
                "italic": italic,
                "color": couleur_key,
                "source_graphic": source_graphic,
            }

    if span_courant:
        spans.append(span_courant)

    return spans


@lru_cache(maxsize=None)
def _ascender_police_source(fontname, gras, italic):
    ascender = None
    if fontname:
        try:
            ascender = getattr(pymupdf.Font(fontname), "ascender", None)
        except Exception as exc:
            logger.warning(
                "Métrique de police source '%s' indisponible (%s) -- "
                "repli sur la police de substitution",
                fontname, exc,
            )
    if ascender is None:
        ascender = getattr(_font_objet(gras, italic)[0], "ascender", 0.8)
    return ascender / 1000.0 if ascender > 10.0 else ascender


def _calibrer_lignes(ordre, tolerance=3.0):
    """
    Calcule une ligne de base COMMUNE par ligne visuelle.

    L'ancienne méthode utilisait `bbox.y1`, ce qui provoquait un
    flottement vertical car `y1` inclut les descendantes (p, q, j).
    Les mots natifs réutilisent l'ascendante de la police source ; les
    mots vectorisés utilisent leur hauteur d'encre propre. La médiane des
    baselines obtenues aligne les spans d'une même ligne.
    """
    candidats = [w for w in ordre if w.bbox]

    lignes = []
    ligne_courante = None
    for w in candidats:
        b = w.bbox
        meme_ligne = (
            ligne_courante is not None
            and abs(b.y0 - ligne_courante["y0_ref"]) <= tolerance
            and b.x0 >= ligne_courante["x1_max"] - 5.0
        )
        if meme_ligne:
            ligne_courante["mots"].append(w)
            ligne_courante["x1_max"] = max(ligne_courante["x1_max"], b.x1)
        else:
            ligne_courante = {"y0_ref": b.y0, "x1_max": b.x1, "mots": [w]}
            lignes.append(ligne_courante)

    baseline_par_id = {}
    for ligne in lignes:
        mots_ligne = ligne["mots"]

        def _calc_baseline_mot(w):
            gras = bool(w.bold) or "bold" in (getattr(w, "font", "") or "").lower()
            italic = bool(w.italic) or "italic" in (getattr(w, "font", "") or "").lower()
            hauteur = w.bbox.y1 - w.bbox.y0
            taille = w.font_size or max(4.0, hauteur)
            if w.is_vectorized:
                texte = w.resolved_text or w.text or ""
                ratio = ratio_encre_em(texte, gras, italic)
                if ratio is not None and ratio > 0:
                    return w.bbox.y0 + (taille * ratio)
            asc = _ascender_police_source(w.font, gras, italic)
            if asc <= 0:
                asc = 0.8
            return w.bbox.y0 + (taille * asc)

        # Mots natifs comme référence (métrique de ligne fiable)
        natifs = [w for w in mots_ligne if not w.is_vectorized]
        if natifs:
            baselines = sorted(_calc_baseline_mot(w) for w in natifs)
            baseline = baselines[len(baselines) // 2]  # médiane des baselines typographiques
        else:
            baselines = sorted(_calc_baseline_mot(w) for w in mots_ligne)
            baseline = baselines[len(baselines) // 2]

        for w in mots_ligne:
            baseline_par_id[id(w)] = baseline
            
    return baseline_par_id


def _recalage_necessaire(mot) -> bool:
    """Un mot natif intact porte déjà sa taille de police exacte -- le
    recalage horizontal le déforme inutilement (cf. cas , police
    monospace mesurée avec une police de substitution : le recalage
    inconditionnel la déformait sans raison). Nécessaire seulement pour
    les mots dont le texte ou la provenance impose une reconstruction."""
    texte_modifie = mot.resolved_text is not None and mot.resolved_text != mot.text
    return bool(
        mot.reconstructed
        or getattr(mot, "is_corrected", False)
        or mot.is_vectorized
        or mot.source == "ocr_vectoriel"
        or texte_modifie
    )


def _inserer_span(writers, page_rect, span, report, baseline_par_id=None):
    """
    Insère un Span complet de texte dans le TextWriter correspondant à sa couleur.
    Repositionne verticalement par baseline et comprime horizontalement
    les spans reconstruits sans réduire leur corps vertical.
    """
    texte_complet = " ".join(span["textes"])
    espace_apres = bool(span.get("espace_apres"))
    rect = span["bbox"]
    fontsize = span["size"]
    couleur_key = span["color"]

    police, _ = _font_objet(span["bold"], span["italic"])

    est_vectorise = any(w.is_vectorized for w in span["mots"])
    render_mode = 3 if span["source_graphic"] else 0

    # 1. Baseline : priorité au calibrage par ligne (médiane des mots
    # natifs de cette ligne visuelle, cf. _calibrer_lignes) -- plus
    # stable qu'un calcul par ascender seul, surtout quand plusieurs
    # spans coexistent sur la même ligne (coupure de couleur en plein
    # milieu d'une ligne, par exemple). Repli sur l'ascender si ce span
    # n'a pas de baseline calibrée (ne devrait pas arriver en pratique,
    # défensif).
    baseline_par_id = baseline_par_id or {}
    baseline_calibree = baseline_par_id.get(id(span["mots"][0])) if span["mots"] else None

    if baseline_calibree is not None:
        baseline_y = baseline_calibree
    else:
        ratio = ratio_encre_em(texte_complet, span["bold"], span["italic"]) if est_vectorise else None
        if ratio is not None and ratio > 0:
            baseline_y = rect.y0 + (fontsize * ratio)
        else:
            asc = getattr(police, "ascender", 0.8)
            if asc > 10.0:
                asc /= 1000.0  # Normalisation si l'ascender est sur l'échelle 1000 em
            if asc <= 0:
                asc = 0.8
            baseline_y = rect.y0 + (fontsize * asc)

    # 2. Les reconstructions vectorisées gardent leur corps mesuré sur les
    # tracés source ; seule leur largeur est ajustée. Les autres corrections
    # conservent le recalage existant.
    morph = None
    if any(_recalage_necessaire(m) for m in span["mots"]):
        largeur_mesuree = police.text_length(texte_complet, fontsize=fontsize)
        largeur_cible = max(rect.width, 0.1)
        if largeur_mesuree > 0 and largeur_cible < largeur_mesuree:
            ratio = min(largeur_cible / largeur_mesuree, 1.0)
            if est_vectorise:
                morph = (
                    pymupdf.Point(rect.x0, baseline_y),
                    pymupdf.Matrix(ratio, 0, 0, 1, 0, 0),
                )
            else:
                fontsize = fontsize * ratio

    # 3. Séparation des TextWriter par couleur, visibilité et morphologie
    if (
        couleur_key != writers["couleur_cle"]
        or render_mode != writers["render_mode"]
    ):
        if writers["pending"]:
            writers["segments"].append((
                writers["couleur_cle"], writers["tw"], None, writers["render_mode"]
            ))
        writers["tw"] = pymupdf.TextWriter(page_rect)
        writers["couleur_cle"] = couleur_key
        writers["render_mode"] = render_mode

    point = pymupdf.Point(rect.x0, baseline_y)
    if espace_apres:
        texte_complet += " "
    if morph is not None:
        if writers["pending"]:
            writers["segments"].append((
                writers["couleur_cle"], writers["tw"], None, writers["render_mode"]
            ))
            writers["tw"] = pymupdf.TextWriter(page_rect)
            writers["pending"] = False
        tw_span = pymupdf.TextWriter(page_rect)
        tw_span.append(point, texte_complet, font=police, fontsize=fontsize)
        writers["segments"].append((couleur_key, tw_span, morph, render_mode))
    else:
        writers["tw"].append(point, texte_complet, font=police, fontsize=fontsize)
        writers["pending"] = True
    report["mots_inseres"] = report.get("mots_inseres", 0) + len(span["mots"])
    

def render_rebuilt_pdf(doc: Document, output_path: str, source_pdf: str = None,
                       dpi: int = 300, simple_sort=False) -> str:
    """
    Reconstruit un PDF neuf, texte VISIBLE et sélectionnable, à la même position
    que le source en utilisant l'approche par Spans / Lignes.
    """
    source_path = source_pdf or doc.metadata.source_pdf
    if not source_path:
        raise ValueError("Le chemin du PDF source est requis (doc.metadata.source_pdf).")

    source = pymupdf.open(source_path)
    if len(source) != len(doc.pages):
        source.close()
        raise ValueError("Le PDF source et Document n'ont pas le même nombre de pages.")

    output = pymupdf.open()
    try:
        for src_page, model_page in zip(source, doc.pages):
            dst_page = output.new_page(width=src_page.rect.width, height=src_page.rect.height)

            report = {
                "images_copiees": 0,
                "images_ignorees": 0,
                "dessins_ignores": 0,
                "dessins_exclus_glyphes": 0,
                "mots_inseres": 0,
                "spans_traites": 0,
            }

            ordre = model_page.resolved.words

            # Exclusion des tracés vectoriels de glyphes
            mots_exclus = [
                w for w in ordre
                if w.bbox
                and (w.reconstructed or w.is_vectorized or w.source == "ocr_vectoriel")
                and not (w.is_vectorized and w.resolved_text == w.text)
            ]

            # Copier les images et tracés graphiques
            couleurs_echantillonnees = _copier_images_et_dessins(
                src_page, dst_page, report, exclure=mots_exclus
            )

            # Calibrage des baselines par ligne visuelle (niveau mot, sur
            # ordre AVANT le groupement en spans -- cf. docstring de
            # _calibrer_lignes pour pourquoi).
            baseline_par_id = _calibrer_lignes(ordre)

            # Regrouper le texte par spans homogènes
            spans = _grouper_en_spans(ordre, couleurs_echantillonnees=couleurs_echantillonnees)
            report["spans_traites"] = len(spans)

            # Injection du texte avec TextWriter
            writers = {
                "tw": pymupdf.TextWriter(dst_page.rect),
                "couleur_cle": (0.0, 0.0, 0.0),
                "render_mode": 0,
                "segments": [],
                "pending": False,
            }

            for span in spans:
                _inserer_span(writers, dst_page.rect, span, report, baseline_par_id=baseline_par_id)

            if writers["pending"]:
                writers["segments"].append((
                    writers["couleur_cle"], writers["tw"], None, writers["render_mode"]
                ))
            for couleur_rgb, tw, morph, render_mode in writers["segments"]:
                tw.write_text(
                    dst_page, color=couleur_rgb, render_mode=render_mode,
                    opacity=1.0, morph=morph
                )

            logger.info("page %s : %s", model_page.number, report)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        output.set_metadata({
            "producer": "DataCompiler rebuilt_pdf",
            "title": doc.metadata.filename
        })
        output.subset_fonts()
        output.save(output_path, garbage=4, deflate=True)

    finally:
        output.close()
        source.close()

    return output_path
