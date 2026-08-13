#!/usr/bin/env python3
"""
rebuild_pdf_v3.py — Prototype v3.

Reprend et corrige _copier_images_et_dessins / _inserer_texte de
faithful_pdf.py (clean_overlay), adaptées pour tourner directement sur le
JSON (pas de package datacompiler dans ce bac à sable). Correctifs
appliqués par rapport au faithful_pdf.py uploadé :

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
pour LES TROIS PAGES, sans exception ni cas particulier par page.

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

`reading_order.ordonner()` prend `native.words` (qui porte déjà
font_size/font/bold/color/resolved_text) et rend une copie triée dans le
bon ordre -- plus besoin de réappariement du tout, plus besoin de
`simulate_reading_order.py`. Une seule source de vérité pour les 3 pages.
"""

import json
import sys

import pymupdf as fitz

sys.path.insert(0, '.')
import reading_order as ro

FONT_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

_polices = {}


def _font_objet(gras):
    fichier = FONT_BOLD if gras else FONT_REGULAR
    nom = "LiberationSans-Bold" if gras else "LiberationSans"
    if fichier not in _polices:
        _polices[fichier] = (fitz.Font(fontfile=fichier), nom)
    return _polices[fichier]


def _hex_to_rgb(hex_color):
    hex_color = (hex_color or "#000000").lstrip("#")
    if len(hex_color) != 6:
        return (0, 0, 0)
    return tuple(int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))


# --- Adaptateurs minimalistes dict JSON -> objets attendus par reading_order.py ---
# reading_order.ordonner() attend des objets avec .bbox.x0/.y0/.x1/.y1,
# .block, .is_vectorized, et page.native.words / page.graphics.tables.
# On garde une référence au dict JSON d'origine (`_d`) pour ne rien perdre
# des champs (font_size, font, bold, color, resolved_text...) dont
# `inserer_mot` a besoin en aval -- ordonner() ne fait que réordonner,
# jamais de recalcul de champs.

class _BBox:
    def __init__(self, d):
        self.x0, self.y0, self.x1, self.y1 = d["x0"], d["y0"], d["x1"], d["y1"]


class _Word:
    def __init__(self, d):
        self._d = d
        self.text = d.get("resolved_text") or d.get("text") or ""
        self.bbox = _BBox(d["bbox"]) if d.get("bbox") else None
        self.block = d.get("block")
        self.is_vectorized = bool(d.get("is_vectorized"))


class _Table:
    def __init__(self, d):
        self.bbox = _BBox(d["bbox"]) if d.get("bbox") else None


class _Native:
    def __init__(self, words):
        self.words = words


class _Graphics:
    def __init__(self, tables):
        self.tables = tables


class _Page:
    def __init__(self, page_json):
        self.native = _Native([_Word(w) for w in page_json["native"]["words"]])
        self.graphics = _Graphics([_Table(t) for t in page_json["graphics"]["tables"]])


def ordre_page(document_json, numero):
    """Ordre de lecture réel d'une page, directement depuis native.words --
    remplace à la fois `resolved.words tel quel` (ancien moteur, pages 1/3)
    et `simulate_reading_order` + réappariement par position (page 2) de la
    version précédente. Retourne les dicts JSON d'origine (mêmes clés que
    resolved.words : bbox, font_size, font, bold, color, resolved_text...),
    juste réordonnés -- `inserer_mot` n'a besoin d'aucun changement."""
    page_json = next(p for p in document_json["pages"] if p["number"] == numero)
    mots_ordonnes = ro.ordonner(_Page(page_json))
    return [w._d for w in mots_ordonnes]


def copier_images_et_dessins(src_page, dst_page, report, exclure=None):
    """Version corrigée de _copier_images_et_dessins (faithful_pdf.py).

    `exclure` : liste de bbox (dict x0/y0/x1/y1) des mots reconstruits/
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
            zone = fitz.Rect(b["x0"], b["y0"], b["x1"], b["y1"])
            inter = rect & zone
            if not inter.is_empty and inter.get_area() >= 0.6 * rect.get_area():
                return True
        return False

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
            print(f"  échec copie image xref {xref}: {e}", file=sys.stderr)
            report["images_ignorees"] += 1

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


def inserer_mot(etat, page_rect, mot, report):
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

    NOTE (désalignement Numéro/fiscal, session précédente) : pas touché
    ici volontairement -- pris en charge séparément.
    """
    texte = mot.get("resolved_text") or mot.get("text") or ""
    if not texte.strip():
        return
    bbox = mot["bbox"]
    gras = bool(mot.get("bold")) or "bold" in (mot.get("font") or "").lower()
    police, nom_police = _font_objet(gras)

    taille_nominale = mot.get("font_size") or 0.0
    if not taille_nominale:
        taille_nominale = max(4.0, bbox["y1"] - bbox["y0"])
        report["taille_heuristique"] += 1

    largeur_cible = max(bbox["x1"] - bbox["x0"], 0.1)
    largeur_rendue = police.text_length(texte, fontsize=taille_nominale)
    taille = (taille_nominale * (largeur_cible / largeur_rendue)
              if largeur_rendue else taille_nominale)

    couleur_cle = mot.get("color") or "#000000"
    if couleur_cle != etat["couleur_cle"]:
        etat["segments"].append((etat["couleur_cle"], etat["tw"]))
        etat["tw"] = fitz.TextWriter(page_rect)
        etat["couleur_cle"] = couleur_cle

    point = fitz.Point(bbox["x0"], bbox["y1"])
    etat["tw"].append(point, texte, font=police, fontsize=taille)
    report["mots_inseres"] += 1


def main():
    with open("/mnt/user-data/uploads/test-impots-revenu_document.json", encoding="utf-8") as f:
        document_json = json.load(f)

    source = fitz.open("/mnt/user-data/uploads/test-impots-revenu.pdf")
    output = fitz.open()

    for src_page, page_json in zip(source, document_json["pages"]):
        num = page_json["number"]
        dst_page = output.new_page(width=src_page.rect.width, height=src_page.rect.height)

        report = {"images_copiees": 0, "images_ignorees": 0, "dessins_ignores": 0,
                   "mots_inseres": 0, "taille_heuristique": 0}

        bbox_vectorisees = [w["bbox"] for w in page_json["resolved"]["words"]
                            if w.get("reconstructed") or w.get("is_vectorized")
                            or w.get("source") == "ocr_vectoriel"]
        copier_images_et_dessins(src_page, dst_page, report, exclure=bbox_vectorisees)

        ordre = ordre_page(document_json, num)

        writers = {"tw": fitz.TextWriter(dst_page.rect), "couleur_cle": "#000000",
                   "segments": []}
        for mot in ordre:
            inserer_mot(writers, dst_page.rect, mot, report)
        writers["segments"].append((writers["couleur_cle"], writers["tw"]))
        for couleur_cle, tw in writers["segments"]:
            tw.write_text(dst_page, color=_hex_to_rgb(couleur_cle), render_mode=0, opacity=1.0)

        print(f"page {num}: {report}", file=sys.stderr)

    output.set_metadata({"producer": "DataCompiler rebuild_pdf_v3 (prototype)",
                         "title": "test-impots-revenu"})
    output.subset_fonts()  # vérifié empiriquement : texte identique avant/après
                           # (get_text() comparé sur les 3 pages), -63% -> -10%
                           # de la part police dans le budget total du fichier
    output.save("/home/claude/rebuild_v3.pdf", garbage=4, deflate=True)
    source.close()
    output.close()
    print("écrit rebuild_v3.pdf", file=sys.stderr)


if __name__ == "__main__":
    main()
