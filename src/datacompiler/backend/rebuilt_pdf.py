"""Rebuild a selectable PDF from resolved text and retained page graphics."""

import logging
from collections import Counter
from functools import lru_cache
from pathlib import Path
import pymupdf

from datacompiler.backend.liens_pdf import reinserer_liens
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
    """Return a cached PyMuPDF font and its PostScript name for the requested style."""
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
    """Copy page images and drawings, omitting glyph paths replaced by text."""
    exclure = exclure or []

    def _match_exclusion(rect):
        if rect is None:
            return None
        for w in exclure:
            zones = w.source_glyph_bboxes
            if not zones and w.bbox:
                zones = ((w.bbox.x0, w.bbox.y0, w.bbox.x1, w.bbox.y1),)
            for bounds in zones:
                zone = pymupdf.Rect(*bounds)
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
            logger.warning("Could not copy image xref %s: %s", xref, e)
            report["images_ignorees"] = report.get("images_ignorees", 0) + 1

    # --- Dessins vectoriels ---
    couleurs_echantillonnees = {}
    couleurs_par_mot = {}
    shape = dst_page.new_shape()
    dessins_ignores = 0
    dessins_exclus_glyphes = 0

    for draw in src_page.get_drawings():
        mot_touche = _match_exclusion(draw.get("rect"))
        if mot_touche is not None:
            dessins_exclus_glyphes += 1
            couleur = draw.get("fill") or draw.get("color")
            if couleur is not None:
                couleurs_par_mot.setdefault(id(mot_touche), []).append(tuple(couleur))
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
                logger.debug(
                    "Dessin vectoriel ignoré page %s (commande %r)",
                    getattr(src_page, "number", "?"), typ, exc_info=True,
                )
                dessins_ignores += 1
                continue

        if shape:
            shape.finish(color=color, fill=fill, width=width, dashes=dashes)

    shape.commit()
    # A glyph is often made of several vector paths. Select its dominant
    # sampled color rather than whichever path happened to be visited last.
    for mot_id, couleurs in couleurs_par_mot.items():
        dominante, _ = Counter(tuple(round(c, 3) for c in couleur) for couleur in couleurs).most_common(1)[0]
        couleurs_echantillonnees[mot_id] = dominante
    report["dessins_ignores"] = report.get("dessins_ignores", 0) + dessins_ignores
    report["dessins_exclus_glyphes"] = report.get("dessins_exclus_glyphes", 0) + dessins_exclus_glyphes

    return couleurs_echantillonnees


def _grouper_en_spans(mots, couleurs_echantillonnees=None, tolerance_y=3.0, ecart_max_mot=8.0):
    """Group adjacent words into continuous spans when line, style, color, and source-path handling match."""
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
        # Keep unchanged vectorized text as source glyph paths; the matching
        # PDF text layer is invisible and exists for selection/copying only.
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
    """Compute one shared typographic baseline for each visual line."""
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

        # Les mots de corps normal servent de référence. Un petit mot placé
        # au-dessus de cette baseline (référence légale, par exemple) doit
        # garder sa position source au lieu d'être abaissé sur la ligne.
        natifs = [w for w in mots_ligne if not w.is_vectorized]
        tailles_natives = {
            id(w): (w.font_size or max(4.0, w.bbox.y1 - w.bbox.y0))
            for w in natifs
        }
        taille_reference = max(tailles_natives.values(), default=0.0)
        mots_reference = [
            w for w in natifs
            if tailles_natives[id(w)] >= taille_reference * 0.8
        ]
        if mots_reference:
            baselines = sorted(_calc_baseline_mot(w) for w in mots_reference)
            baseline = baselines[len(baselines) // 2]  # médiane des baselines typographiques
        elif natifs:
            baselines = sorted(_calc_baseline_mot(w) for w in natifs)
            baseline = baselines[len(baselines) // 2]
        else:
            baselines = sorted(_calc_baseline_mot(w) for w in mots_ligne)
            baseline = baselines[len(baselines) // 2]

        for w in mots_ligne:
            baseline_mot = _calc_baseline_mot(w)
            taille_mot = w.font_size or max(4.0, w.bbox.y1 - w.bbox.y0)
            est_exposant = (
                not w.is_vectorized
                and taille_reference > 0
                and taille_mot < taille_reference * 0.8
                and baseline_mot < baseline - 0.75
            )
            baseline_par_id[id(w)] = baseline_mot if est_exposant else baseline
            
    return baseline_par_id


def _recalage_necessaire(mot) -> bool:
    """Decide whether horizontal repositioning is needed; intact native words already carry their exact font size."""
    texte_modifie = mot.resolved_text is not None and mot.resolved_text != mot.text
    return bool(
        mot.reconstructed
        or getattr(mot, "is_corrected", False)
        or mot.is_vectorized
        or mot.source == "ocr_vectoriel"
        or texte_modifie
    )


def _inserer_span(writers, page_rect, span, report, baseline_par_id=None):
    """Insert a complete text span with its color and baseline, compressing reconstructed spans horizontally when needed."""
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
    

def _ecrire_bloc_traduit(page, word, *, baseline_y=None, color=None):
    """Write one translated segment at its source position and source font size."""
    if not word.bbox:
        return None
    rect = pymupdf.Rect(word.bbox.x0, word.bbox.y0, word.bbox.x1, word.bbox.y1)
    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
        return "translated block has an empty layout box"
    font, _ = _font_objet(bool(word.bold), bool(word.italic))
    text = word.resolved_text or word.text or ""
    if not text.strip():
        return None
    base_size = max(0.1, float(getattr(word, "_translation_base_font_size", 10.0) or 10.0))
    baseline = baseline_y
    if baseline is None:
        ascender = getattr(font, "ascender", 0.8)
        if ascender > 10:
            ascender /= 1000.0
        baseline = rect.y0 + base_size * (ascender if ascender > 0 else 0.8)
    script = getattr(word, "_translation_script", "normal")
    script_factor = 0.65 if script in {"superscript", "subscript"} else 1.0
    render_size = base_size * script_factor
    if script == "superscript":
        baseline -= base_size * 0.32
    elif script == "subscript":
        baseline += base_size * 0.16
    writer = pymupdf.TextWriter(page.rect)
    writer.append(
        pymupdf.Point(rect.x0, baseline), text, font=font, fontsize=render_size,
    )
    writer.write_text(page, color=color or _hex_to_rgb(word.color))
    return None


def _annoter_bloc_traduit(page, word):
    """Attach actionable XLIFF review details to a translated PDF block."""
    segments = getattr(word, "_translation_segments", [])
    if not segments or not word.bbox:
        return None
    block_id = getattr(word, "_translation_block_id", "block")
    lines = [
        "DataCompiler — révision de traduction",
        f"Bloc : {block_id}",
        "Le score ci-dessous estime la qualité ; ce n'est pas une probabilité de justesse.",
        "",
    ]
    for segment in segments:
        lines.append(f"Segment {segment['id']}")
        lines.append(f"Source : {segment['source']}")
        lines.append(f"Traduction : {segment['target']}")
        if segment.get("human_reviewed"):
            lines.append("Relecture humaine : effectuée dans Matecat.")
        score = segment.get("quality_score")
        if score is None:
            if not segment.get("human_reviewed"):
                lines.append("Score qualité : non disponible — relecture conseillée.")
            else:
                lines.append("Score qualité : non disponible après la relecture humaine.")
        else:
            model = segment.get("quality_model") or "modèle non renseigné"
            lines.append(
                f"Score qualité estimé : {score * 100:.0f}/100 "
                f"({model}, non calibré ; pas une probabilité)."
            )
            if segment.get("review_recommended"):
                lines.append("Relecture recommandée : oui.")
            else:
                lines.append("Relecture recommandée : non selon le seuil configuré.")
        lines.append(f"Moteur : {segment.get('provider') or 'non renseigné'}.")
        lines.append("")

    rect = pymupdf.Rect(word.bbox.x0, word.bbox.y0, word.bbox.x1, word.bbox.y1)
    icon_size = 20
    if rect.x1 + 2 + icon_size <= page.rect.x1:
        x = rect.x1 + 2
    else:
        x = rect.x0 - icon_size - 2
    x = min(max(x, page.rect.x0), page.rect.x1 - icon_size)
    y = min(max(rect.y0, page.rect.y0), page.rect.y1 - icon_size)
    content = "\n".join(lines)
    annot = page.add_text_annot(pymupdf.Point(x, y), content, icon="Comment")
    annot.set_info(
        content=content,
        title="DataCompiler",
        subject=f"Relecture de traduction — {block_id}",
    )
    annot.update()
    return annot


def render_rebuilt_pdf(doc: Document, output_path: str, source_pdf: str = None,
                       dpi: int = 300, simple_sort=False,
                       include_translation_comments: bool = False) -> str:
    """Rebuild a selectable PDF at the source positions using grouped text spans and visual lines."""
    source_path = source_pdf or doc.metadata.source_pdf
    if not source_path:
        raise ValueError("The source PDF path is required (doc.metadata.source_pdf).")

    source = pymupdf.open(source_path)
    output = None
    try:
        if len(source) != len(doc.pages):
            raise ValueError("The source PDF and document must have the same number of pages.")
        output = pymupdf.open()

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
            translation_sources = {"xliff_translation", "manual_translation"}
            translated_blocks = [w for w in ordre if w.source in translation_sources]
            ordinary_words = [w for w in ordre if w.source not in translation_sources]

            # Exclude recognized vector glyphs: their visible replacement is
            # selectable text emitted below. Unrecognized artwork is retained.
            mots_exclus = [
                w for w in ordre
                if (w.bbox or w.source_glyph_bboxes)
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
            baseline_par_id = _calibrer_lignes(ordinary_words)

            # Regrouper le texte par spans homogènes
            spans = _grouper_en_spans(ordinary_words, couleurs_echantillonnees=couleurs_echantillonnees)
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

            for translated_word in translated_blocks:
                warning = _ecrire_bloc_traduit(
                    dst_page, translated_word,
                    baseline_y=getattr(translated_word, "_translation_baseline", None),
                    color=couleurs_echantillonnees.get(id(translated_word)),
                )
                if warning:
                    translated_word.notes.append(warning)
                    logger.warning(warning)
                if include_translation_comments:
                    _annoter_bloc_traduit(dst_page, translated_word)
                report["mots_inseres"] += 1

            report["liens_inseres"] = reinserer_liens(dst_page, model_page)

            logger.info("page %s: %s", model_page.number, report)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        output.set_metadata({
            "producer": "DataCompiler rebuilt_pdf",
            "title": doc.metadata.filename
        })
        output.subset_fonts()
        # Clean generated page streams and compress eligible object, image,
        # and font streams. On the local three-page corpus sample this reduced
        # the rebuilt output by about 11% with pixel-identical rendering.
        output.save(
            output_path,
            garbage=4,
            clean=True,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            use_objstms=1,
        )

    finally:
        if output is not None:
            output.close()
        source.close()

    return output_path
