"""Render a faithful PDF while preserving the source appearance.

The overlay strategy adds invisible resolved text to the source. The clean-overlay strategy recreates images and vector graphics, then writes resolved text as a single text layer. The rasterized strategy uses a page image with an invisible text layer. Each strategy returns a report of copied, skipped, and recovered elements."""

from pathlib import Path
import gc
import logging
import pymupdf

from datacompiler.backend.liens_pdf import reinserer_liens
from datacompiler.model.document import Document
from datacompiler.compile.layout import grouper_par_ligne

logger = logging.getLogger(__name__)

_FALLBACK_FONTNAME = "Helvetica"  # police standard disponible par défaut
_FALLBACK_FONTFILE = None  # pas de fichier, on utilise une police standard

_polices_chargees = {}  # cache global (nom -> pymupdf.Font) pour éviter de recharger


def _hex_to_rgb(hex_color):
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


def _font_objet(fontname, fontfile=None):
    """Return a cached PyMuPDF font, falling back when the requested font name cannot be resolved."""
    if fontname not in _polices_chargees:
        try:
            _polices_chargees[fontname] = (
                pymupdf.Font(fontfile=fontfile) if fontfile else pymupdf.Font(fontname)
            )
        except Exception as e:
            logger.warning(
                f"Police '{fontname}' non résolvable par PyMuPDF ({e}) -- "
                f"repli sur {_FALLBACK_FONTNAME}"
            )
            if _FALLBACK_FONTNAME not in _polices_chargees:
                _polices_chargees[_FALLBACK_FONTNAME] = pymupdf.Font(_FALLBACK_FONTNAME)
            _polices_chargees[fontname] = _polices_chargees[_FALLBACK_FONTNAME]
    return _polices_chargees[fontname]


def _inserer_texte(page, x0, y1, texte, largeur_cible, taille_nominale,
                   nom_police, couleur_hex, render_mode=0):
    """Insert one word, adjusting its font size to fit the target width."""
    police = _font_objet(nom_police, _FALLBACK_FONTFILE)
    # Le nom RÉELLEMENT utilisable, après repli éventuel dans _font_objet --
    # PAS nom_police tel quel. _font_objet gère déjà le cas d'un nom
    # invalide (ex. sentinelle "Unknown") en interne pour pymupdf.Font(), mais
    # ce repli ne vivait que dans l'objet retourné -- insert_text() en
    # aval refait sa PROPRE résolution à partir du nom passé en paramètre,
    # indépendamment du cache Python, et plantait donc à nouveau si on lui
    # transmettait nom_police brut plutôt que le nom déjà validé.
    nom_police_resolu = police.name
    largeur_rendue = police.text_length(texte, fontsize=taille_nominale)
    taille = (taille_nominale * (largeur_cible / largeur_rendue)
              if largeur_rendue else taille_nominale)
    couleur_rgb = _hex_to_rgb(couleur_hex)
    page.insert_text((x0, y1), texte,
                     fontsize=taille,
                     fontname=nom_police_resolu,
                     fontfile=_FALLBACK_FONTFILE,
                     color=couleur_rgb,
                     render_mode=render_mode,
                     fill_opacity=0.015,
                     overlay=True)


def _inserer_tous_les_mots(page, words, render_mode=0, font_mapping=None):
    """Insert all words in the requested order, preserving spacing and resolving source font names through the mapping."""
    if font_mapping is None:
        font_mapping = {}
    for ligne in grouper_par_ligne(words):
        ligne_triee = sorted(
            [w for w in ligne if w.bbox and w.resolved_text.strip()],
            key=lambda w: w.bbox.x0
        )
        for i, word in enumerate(ligne_triee):
            box = word.bbox
            largeur_cible = max(box.x1 - box.x0, 0.1)
            taille_nominale = word.font_size or max(4.0, box.y1 - box.y0)
            couleur = word.color or "#000000"
            # Résolution du nom de police
            police_nom = _FALLBACK_FONTNAME
            if word.font and word.font in font_mapping:
                police_nom = font_mapping[word.font]
            elif word.font:
                police_nom = word.font  # on espère qu'elle existe déjà dans le document
            _inserer_texte(page, box.x0, box.y1, word.resolved_text,
                           largeur_cible, taille_nominale,
                           police_nom, couleur, render_mode)
            # Espace entre mots si nécessaire
            if i + 1 < len(ligne_triee):
                suivant = ligne_triee[i + 1]
                if suivant.bbox.x0 > box.x1:
                    espace_largeur = max(suivant.bbox.x0 - box.x1, 0.1)
                    _inserer_texte(page, box.x1, box.y1, " ",
                                   espace_largeur, taille_nominale,
                                   police_nom, couleur, render_mode)


def _extraire_et_ajouter_polices(source_doc, dest_doc, mots, report):
    """Extract embedded fonts used by the words and add them to the destination document. Return a source-to-destination font map and update the report counters."""
    # Récupérer tous les noms de polices uniques utilisés dans les mots
    font_names = set()
    for w in mots:
        if w.font:
            font_names.add(w.font)
    if not font_names:
        return {}

    mapping = {}
    # On parcourt toutes les pages pour collecter les polices intégrées
    for page_num in range(len(source_doc)):
        for font_info in source_doc[page_num].get_fonts():
            # format: (xref, ext, name, type, encoding, embedded)
            if len(font_info) < 6:
                continue
            xref, ext, name, type_, encoding, embedded = font_info[:6]
            if not embedded:
                continue
            # Si ce nom est utilisé dans les mots, on l'extrait
            if name in font_names and name not in mapping:
                try:
                    # Méthode 1 : via pymupdf.Font(xref)
                    font_obj = pymupdf.Font(xref=xref)
                    font_buffer = font_obj.buffer
                    if not font_buffer:
                        raise ValueError("Empty font buffer")
                    # Ajouter au document destination avec un nom unique
                    dest_name = f"F{xref}_{name.replace('+', '_')}"
                    dest_doc.insert_font(fontname=dest_name, fontbuffer=font_buffer)
                    mapping[name] = dest_name
                    report.setdefault("polices_extraites", []).append(name)
                except Exception as e:
                    logger.warning(f"Could not extract font '{name}' (xref {xref}): {e}")
                    # Fallback : on utilise la police standard
                    mapping[name] = _FALLBACK_FONTNAME
                    report.setdefault("polices_fallback", []).append(name)
            # Si la police est déjà dans le mapping, on ne fait rien
        # Si toutes les polices sont trouvées, on peut arrêter la recherche
        if all(n in mapping for n in font_names):
            break

    # Pour les polices non trouvées (non intégrées ou introuvables), fallback
    for name in font_names:
        if name not in mapping:
            mapping[name] = _FALLBACK_FONTNAME
            report.setdefault("polices_fallback", []).append(name)

    return mapping


def _copier_images_et_dessins(src_page, dst_page, report):
    """Copy page images and vector drawings, recording copied and skipped elements in the report."""
    # --- Images ---
    for img in src_page.get_images():
        xref = img[0]
        rects = src_page.get_image_rects(xref)
        if not rects:
            # Référencée par get_images() mais aucune occurrence trouvée sur
            # cette page précise (ex. via un Form XObject/annotation non
            # résolu par get_image_rects) -- à surveiller si ça persiste
            # après ce fix, mais ce n'est pas la même cause que le bug
            # liste/objet ci-dessous.
            report["images_ignorees"] = report.get("images_ignorees", 0) + 1
            logger.warning(f"No occurrence found for image xref {xref} on this page; skipping it")
            continue
        try:
            # Extraction brute du flux original (pas de Pixmap)
            img_dict = src_page.parent.extract_image(xref)
            if img_dict and "image" in img_dict:
                stream = img_dict["image"]
                for rect in rects:  # une même image peut apparaître plusieurs fois sur la page
                    dst_page.insert_image(rect, stream=stream)
                report["images_copiees"] = report.get("images_copiees", 0) + len(rects)
            else:
                report["images_ignorees"] = report.get("images_ignorees", 0) + 1
        except Exception as e:
            logger.warning(f"Could not copy image xref {xref}: {e}")
            report["images_ignorees"] = report.get("images_ignorees", 0) + 1

    # --- Dessins vectoriels ---
    shape = dst_page.new_shape()
    dessins_ignores = 0
    for draw in src_page.get_drawings():
        items = draw.get("items", [])
        color = draw.get("color", None)      # tuple RGB ou None
        fill = draw.get("fill", None)        # tuple RGB ou None
        width = draw.get("width", 1.0)
        dashes = draw.get("dashes", None)    # liste [phase, ...] ou None
        for item in items:
            typ = item[0]
            try:
                if typ == "l":   # ligne
                    p1, p2 = item[1], item[2]
                    shape.draw_line(p1, p2)
                elif typ == "re":  # rectangle
                    rect = item[1]
                    shape.draw_rect(rect)
                elif typ == "c":   # courbe de Bézier (4 points)
                    pts = item[1:]
                    if len(pts) == 4:
                        shape.draw_bezier(pts[0], pts[1], pts[2], pts[3])
                elif typ == "qu":  # quadrilatère (4 points)
                    pts = item[1:]
                    if len(pts) == 4:
                        shape.draw_polyline(pts)
                else:
                    # Autres types non gérés (ovale, chemin complexe)
                    dessins_ignores += 1
                    continue
            except Exception:
                logger.debug(
                    "Dessin vectoriel ignoré page %s (commande %r)",
                    getattr(src_page, "number", "?"), typ, exc_info=True,
                )
                dessins_ignores += 1
                continue
        # Appliquer les propriétés à tout le dessin
        if shape:
            shape.finish(color=color, fill=fill, width=width, dashes=dashes)
    shape.commit()
    report["dessins_ignores"] = report.get("dessins_ignores", 0) + dessins_ignores


def render_faithful_pdf(doc: Document, output_path: str,
                        source_pdf: str = None,
                        strategy: str = "overlay",
                        dpi: int = 300) -> tuple[str, dict]:
    """Render a document with the selected faithful-PDF strategy and return the output path and a report of rendering actions."""
    source_path = source_pdf or doc.metadata.source_pdf
    if not source_path:
        raise ValueError("The source PDF path is required.")
    if strategy not in {"overlay", "clean_overlay", "rasterized"}:
        raise ValueError("strategy must be 'overlay', 'clean_overlay', or 'rasterized'.")
    if strategy == "clean_overlay":
        logger.warning("Strategy 'clean_overlay' is deprecated; use render_rebuilt_pdf instead.")

    source = pymupdf.open(source_path)
    report = {
        "strategy": strategy,
        "mots_inseres": 0,
        "polices_extraites": [],
        "polices_fallback": [],
        "images_copiees": 0,
        "images_ignorees": 0,
        "dessins_ignores": 0,
    }

    output = None
    try:
        if len(source) != len(doc.pages):
            raise ValueError("The source PDF and document must have the same number of pages.")

        if strategy == "rasterized":
            output = pymupdf.open()
            scale = dpi / 72.0
            matrix = pymupdf.Matrix(scale, scale)
            for src_page, model_page in zip(source, doc.pages):
                target = output.new_page(width=src_page.rect.width, height=src_page.rect.height)
                pix = src_page.get_pixmap(matrix=matrix, alpha=False)
                target.insert_image(target.rect, stream=pix.tobytes("png"))
                del pix
                # Insérer les mots en mode invisible
                _inserer_tous_les_mots(target, model_page.resolved.words, render_mode=3)
                reinserer_liens(target, model_page)
                report["mots_inseres"] += len([w for w in model_page.resolved.words if w.resolved_text.strip()])

            output.set_metadata({"producer": "DataCompiler faithful_pdf (rasterized)",
                                 "title": doc.metadata.filename})
            output.save(output_path, garbage=4, deflate=True)

        elif strategy == "clean_overlay":
            output = pymupdf.open()
            # On prépare le mapping des polices en fonction de tous les mots résolus
            all_words = []
            for p in doc.pages:
                all_words.extend(p.resolved.words)
            font_mapping = _extraire_et_ajouter_polices(source, output, all_words, report)

            for src_page, model_page in zip(source, doc.pages):
                new_page = output.new_page(width=src_page.rect.width, height=src_page.rect.height)

                # Copier images et dessins
                _copier_images_et_dessins(src_page, new_page, report)

                # Insérer le texte résolu en mode visible (render_mode=0)
                _inserer_tous_les_mots(new_page, model_page.resolved.words,
                                       render_mode=0, font_mapping=font_mapping)
                reinserer_liens(new_page, model_page)
                report["mots_inseres"] += len([w for w in model_page.resolved.words if w.resolved_text.strip()])

            output.set_metadata({"producer": "DataCompiler faithful_pdf (clean_overlay)",
                                 "title": doc.metadata.filename})
            output.save(output_path, garbage=4, deflate=True)

        else:  # overlay classique
            output = pymupdf.open(source_path)
            for page, model_page in zip(output, doc.pages):
                mots_visibles = [w for w in model_page.resolved.words
                                 if w.resolved_text != w.text or w.reconstructed]
                # render_mode différencié : visible (0) pour le texte
                # vectorisé récupéré par vector_zones.py (rien de sélectionnable
                # en dessous, seulement des tracés -- pas de duplication
                # possible), invisible (3) pour les corrections sur du texte
                # natif déjà existant (là, la duplication visuelle EST un
                # risque réel, déjà rencontré et corrigé une fois cette
                # session -- cf. bug 'duplication de rendu invisible').
                mots_vectorises = [w for w in mots_visibles if getattr(w, "is_vectorized", False)]
                mots_corriges = [w for w in mots_visibles if not getattr(w, "is_vectorized", False)]
                if mots_vectorises:
                    _inserer_tous_les_mots(page, mots_vectorises, render_mode=0)
                if mots_corriges:
                    _inserer_tous_les_mots(page, mots_corriges, render_mode=3)
                if mots_visibles:
                    report["mots_inseres"] += len([w for w in mots_visibles if w.resolved_text.strip()])
                # Fusionne tous les streams de contenu de la page en UN SEUL
                # objet physique. Hypothèse à tester : insert_text(overlay=True)
                # ajoute un stream séparé (/Contents devient un tableau), et un
                # extracteur "flux plat" comme celui d'Okapi/Matecat (confirmé
                # par la doc officielle cette session) pourrait ne lire
                # correctement qu'un seul stream -- indépendamment du
                # render_mode, ce qui expliquerait que même du texte VISIBLE
                # ajouté en overlay reste invisible à Matecat.
                page.clean_contents()
            output.set_metadata({"producer": "DataCompiler faithful_pdf (overlay)",
                                 "title": doc.metadata.filename})
            output.save(output_path, garbage=4, deflate=True)

    finally:
        gc.collect()  # Nettoyer les références résiduelles
        if output is not None:
            output.close()
        source.close()
        gc.collect()

    return output_path, report
