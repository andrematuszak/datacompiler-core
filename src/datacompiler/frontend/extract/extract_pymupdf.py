"""
datacompiler/frontend/extract/pymupdf.py
Moteur 1 — Extraction des données textuelles et métadonnées via PyMuPDF.
"""

from pathlib import Path
import re
from typing import Dict, Tuple, Set, Any, List
import pymupdf

from datacompiler.model.document import BBox, Font, GraphicVector, Page, Word


_MONTANT_EURO_CMAP = re.compile(r"(?<=\d[.,]\d{2}\s)[\ufffd\u00a4]$")


def _reparer_texte_cmap(texte: str) -> str:
    """Répare un cas CMap observé dans les avis d'impôt.

    Certains PDF encodent le signe euro dans une police Helvetica sans une
    table Unicode exploitable : PyMuPDF retourne alors U+FFFD ou U+00A4,
    alors que le glyphe visible est bien « € ». La correction est volontairement bornée
    à la position monétaire ``123,45 �`` ; tout autre U+FFFD reste visible
    au diagnostic plutôt que d'être deviné.
    """
    return _MONTANT_EURO_CMAP.sub("€", texte)


def _convertir_couleur(srgb_int: int | None) -> str:
    """Convertit un entier sRGB en format Hexadécimal."""
    if srgb_int is None:
        return "#000000"
    r = (srgb_int >> 16) & 255
    g = (srgb_int >> 8) & 255
    b = srgb_int & 255
    return f"#{r:02x}{g:02x}{b:02x}"


def _convertir_couleur_float(rgb: tuple | None) -> str | None:
    """Convertit un tuple couleur PyMuPDF (r, g, b) en flottants 0-1, tel que
    retourné par `drawing.get("color")`/`drawing.get("fill")` de
    `page.get_drawings()`, en hexadécimal -- même format que
    `_convertir_couleur` (sRGB int), mais source différente : les dessins
    vectoriels (drawings) exposent leur couleur en float RGB, pas en int
    sRGB comme les spans de texte. Pas de fusion des deux fonctions : deux
    formats d'entrée différents, pas de bénéfice à les unifier."""
    if rgb is None:
        return None
    r, g, b = (round(c * 255) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _extraire_zones_vectorielles(page_pymupdf: pymupdf.Page) -> List[Dict[str, Any]]:
    """
    Extrait les zones vectorielles (dessins) de la page qui pourraient correspondre
    à du texte dessiné géométriquement. Retourne une liste de bbox avec leurs
    caractéristiques.
    """
    drawings = page_pymupdf.get_drawings()
    zones_vectorielles = []
    
    for drawing in drawings:
        # Couleur portée par le drawing entier (pas par item) -- priorité au
        # trait (`color`), repli sur le remplissage (`fill`) si le trait est
        # absent. Confirmé empiriquement sur un document réel (avis
        # d'impôt) : les encadrés de section ("Vos références", "Vos
        # contacts") sont des quads non remplis (fill=None), la couleur qui
        # les caractérise est le trait.
        couleur = _convertir_couleur_float(drawing.get("color") or drawing.get("fill"))
        for item in drawing.get("items", []):
            if item[0] == "l":  # ligne
                p1, p2 = item[1], item[2]
                x0, y0 = min(p1.x, p2.x), min(p1.y, p2.y)
                x1, y1 = max(p1.x, p2.x), max(p1.y, p2.y)
                zones_vectorielles.append({
                    "type": "line",
                    "bbox": (x0, y0, x1, y1),
                    "width": x1 - x0,
                    "height": y1 - y0,
                    "color": couleur,
                })
            elif item[0] == "re":  # rectangle
                rect = item[1]
                zones_vectorielles.append({
                    "type": "rect",
                    "bbox": (rect.x0, rect.y0, rect.x1, rect.y1),
                    "width": rect.x1 - rect.x0,
                    "height": rect.y1 - rect.y0,
                    "color": couleur,
                })
            elif item[0] == "qu":  # quad -- confirmé être le type utilisé pour
                # les encadrés de section sur le document de test (pas "re") ;
                # `.rect` donne la bbox englobante axis-aligned du quadrilatère.
                rect = item[1].rect
                zones_vectorielles.append({
                    "type": "rect",
                    "bbox": (rect.x0, rect.y0, rect.x1, rect.y1),
                    "width": rect.x1 - rect.x0,
                    "height": rect.y1 - rect.y0,
                    "color": couleur,
                })
            elif item[0] == "c":  # courbe (bezier)
                # Pour les courbes, on prend la bbox englobante des points de contrôle
                points = item[1:]
                xs = [p.x for p in points]
                ys = [p.y for p in points]
                zones_vectorielles.append({
                    "type": "curve",
                    "bbox": (min(xs), min(ys), max(xs), max(ys)),
                    "width": max(xs) - min(xs),
                    "height": max(ys) - min(ys),
                    "color": couleur,
                })
    
    return zones_vectorielles


def _grouper_zones_vectorielles_proches(zones: List[Dict[str, Any]], tolerance: float = 5.0) -> List[Dict[str, Any]]:
    """
    Regroupe les zones vectorielles proches en zones plus larges.
    Utilise une fusion transitive simple basée sur la proximité des bbox.
    """
    if not zones:
        return []
    
    groupes = []
    for zone in zones:
        bbox = zone["bbox"]
        rattache = None
        for g in groupes:
            gbbox = g["bbox"]
            # Vérifier si la zone est proche du groupe
            if not (bbox[2] < gbbox[0] - tolerance or bbox[0] > gbbox[2] + tolerance or
                    bbox[3] < gbbox[1] - tolerance or bbox[1] > gbbox[3] + tolerance):
                rattache = g
                break
        
        if rattache is None:
            groupes.append({
                "elements": [zone],
                "bbox": list(bbox),
                "count": 1
            })
        else:
            rattache["elements"].append(zone)
            rattache["bbox"][0] = min(rattache["bbox"][0], bbox[0])
            rattache["bbox"][1] = min(rattache["bbox"][1], bbox[1])
            rattache["bbox"][2] = max(rattache["bbox"][2], bbox[2])
            rattache["bbox"][3] = max(rattache["bbox"][3], bbox[3])
            rattache["count"] += 1
    
    # Filtrer les groupes qui ressemblent à du texte (beaucoup d'éléments, forme allongée)
    resultat = []
    for g in groupes:
        width = g["bbox"][2] - g["bbox"][0]
        height = g["bbox"][3] - g["bbox"][1]
        # Heuristique: au moins 5 éléments, ratio largeur/hauteur > 2, hauteur entre 4 et 30pt
        if g["count"] >= 5 and width > 0 and height > 0:
            ratio = width / height
            if ratio > 2.0 and 4.0 <= height <= 30.0:
                resultat.append(g)
    
    return resultat


def _mot_dans_zone_vectorielle(word_bbox: BBox, zone_bbox: List[float]) -> bool:
    """
    Vérifie si le centre d'un mot est dans une zone vectorielle.
    """
    if not word_bbox:
        return False
    cx = (word_bbox.x0 + word_bbox.x1) / 2
    cy = (word_bbox.y0 + word_bbox.y1) / 2
    x0, y0, x1, y1 = zone_bbox
    return x0 <= cx <= x1 and y0 <= cy <= y1


def _sous_mots_typographiques(word_bbox, texte, spans_typo):
    """Sépare un token PyMuPDF lorsque ses glyphes traversent plusieurs
    spans de styles différents (ex. référence en exposant suivie de pointillés).
    PyMuPDF regroupe parfois ces glyphes en un seul mot et le centre du mot
    attribue alors à tort la typographie du span le plus long."""
    if not texte or any(caractere.isspace() for caractere in texte):
        return []

    x0, y0, x1, y1 = word_bbox
    candidats = []
    for span in spans_typo:
        sx0, sy0, sx1, sy1 = span["bbox"]
        ix0, iy0 = max(x0, sx0), max(y0, sy0)
        ix1, iy1 = min(x1, sx1), min(y1, sy1)
        aire_span = (sx1 - sx0) * (sy1 - sy0)
        if ix0 >= ix1 or iy0 >= iy1 or aire_span <= 0:
            continue
        if (ix1 - ix0) * (iy1 - iy0) / aire_span < 0.5:
            continue
        texte_span = re.sub(r"\s+", "", span.get("text", ""))
        if texte_span:
            candidats.append((span, texte_span))
    candidats.sort(key=lambda element: element[0]["bbox"][0])

    texte_normalise = re.sub(r"\s+", "", texte)
    if len(candidats) < 2 or "".join(t for _, t in candidats) != texte_normalise:
        return []

    styles = {
        (
            span["font"], span["font_size"], span["bold"], span["italic"], span["color"]
        )
        for span, _ in candidats
    }
    if len(styles) < 2:
        return []
    return [span for span, _ in candidats]


def extraire_metadonnees(doc_pymupdf: pymupdf.Document, pdf_path: str) -> dict:
    """Extrait l'ensemble des métadonnées système du fichier PDF."""
    return {
        "filename": Path(pdf_path).name,
        "source_pdf": str(Path(pdf_path).resolve()),
        "page_count": len(doc_pymupdf),
        "producer": doc_pymupdf.metadata.get("producer", ""),
        "creator": doc_pymupdf.metadata.get("creator", ""),
        "creation_date": doc_pymupdf.metadata.get("creationDate", ""),
        "modification_date": doc_pymupdf.metadata.get("modDate", ""),
        "pdf_version": doc_pymupdf.metadata.get("format", ""),
        "encrypted": bool(doc_pymupdf.is_encrypted),
    }


def extraire_page_pymupdf(page_pymupdf, page_number, start_word_id):
    page_obj = Page(
        number=page_number,
        width=float(page_pymupdf.rect.width),
        height=float(page_pymupdf.rect.height),
        rotation=float(page_pymupdf.rotation),
    )

    page_dict = page_pymupdf.get_text("dict")
    words_pymupdf = page_pymupdf.get_text("words")
    font_map = {}
    word_global_id = start_word_id

    for zone in _extraire_zones_vectorielles(page_pymupdf):
        x0, y0, x1, y1 = zone["bbox"]
        vector = GraphicVector(bbox=BBox(x0, y0, x1, y1), color=zone.get("color"))
        if zone["type"] == "line":
            page_obj.graphics.lines.append(vector)
        elif zone["type"] == "rect":
            page_obj.graphics.rects.append(vector)
        elif zone["type"] == "curve":
            page_obj.graphics.curves.append(vector)

    # CORRECTIF : plus d'appariement par égalité d'index (block_idx ==
    # w[5], line_idx == w[6]). get_text("dict") et get_text("words")
    # n'utilisent pas les mêmes règles de numérotation de bloc par défaut
    # (images comptées dans l'un, ignorées dans l'autre -- confirmé par
    # les mainteneurs PyMuPDF) : sur une page avec des images intercalées,
    # ça fait dériver silencieusement des mots entiers hors de toute
    # correspondance -- perdus sans erreur (confirmé : "virement",
    # page avec has_images=True).
    #
    # On itère directement sur words_pymupdf (garanti exhaustif : c'est LA
    # source de vérité pour "quels mots existent"), et on retrouve la
    # typographie par containment géométrique du centre du mot dans la
    # bbox de ligne du dict, avec repli sur la ligne verticalement la plus
    # proche si aucun containment exact (tolérance aux petits écarts
    # d'arrondi de bbox entre les deux extractions). Un mot ne peut plus
    # jamais disparaître : au pire, sa typographie est mal attribuée --
    # jamais son existence.
    # Une ligne peut mélanger plusieurs spans (gras, normal, couleurs,
    # polices). Attribuer le style du dernier span à tous ses mots est la
    # cause directe des passages natifs rendus à tort en gras.
    spans_typo = []
    lignes_typo = []
    text_block_idx = 0
    for b in page_dict.get("blocks", []):
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                font_name = s.get("font", "Unknown")
                font_size = float(s.get("size", 0.0))
                # PyMuPDF : bit 4 (valeur 16) = bold. La valeur 4 est le
                # bit "serifed" ; la confondre avec bold transformait par
                # exemple les spans Helvetica normaux en LiberationSans-Bold.
                bold = bool(s.get("flags", 0) & 16)
                italic = bool(s.get("flags", 0) & 2)
                color_hex = _convertir_couleur(s.get("color"))
                font_map.setdefault(font_name, set()).add(round(font_size, 1))
                bbox_span = s.get("bbox")
                if bbox_span:
                    spans_typo.append({
                        "bbox": bbox_span, "block": text_block_idx,
                        "font": font_name, "font_size": font_size,
                        "bold": bold, "italic": italic, "color": color_hex,
                        "text": s.get("text", ""),
                    })
            bbox_ligne = l.get("bbox")
            if bbox_ligne:
                # Repli seulement lorsqu'aucun span ne couvre le mot.
                premier_span = next((s for s in spans_typo[::-1]
                                      if s["block"] == text_block_idx), None)
                lignes_typo.append({
                    "bbox": bbox_ligne, "block": text_block_idx,
                    "font": premier_span["font"] if premier_span else "Unknown",
                    "font_size": premier_span["font_size"] if premier_span else 0.0,
                    "bold": premier_span["bold"] if premier_span else False,
                    "italic": premier_span["italic"] if premier_span else False,
                    "color": premier_span["color"] if premier_span else "#000000",
                })
        text_block_idx += 1

    def _typo_correspondante(word_bbox):
        cx, cy = (word_bbox[0] + word_bbox[2]) / 2, (word_bbox[1] + word_bbox[3]) / 2
        # Le centre est plus robuste que le chevauchement pour les mots aux
        # bornes de deux spans adjacents ; choisir le plus petit span qui le
        # contient évite qu'un span de fond trop large absorbe le mot.
        candidates = []
        for span in spans_typo:
            bx0, by0, bx1, by1 = span["bbox"]
            if bx0 - 1 <= cx <= bx1 + 1 and by0 - 1 <= cy <= by1 + 1:
                candidates.append(span)
        if candidates:
            return min(candidates, key=lambda s: (s["bbox"][2] - s["bbox"][0]) * (s["bbox"][3] - s["bbox"][1]))

        meilleure, meilleure_dist = None, None
        for lt in lignes_typo:
            bx0, by0, bx1, by1 = lt["bbox"]
            if bx0 - 1 <= cx <= bx1 + 1 and by0 - 1 <= cy <= by1 + 1:
                return lt
            dist = abs((by0 + by1) / 2 - cy)
            if meilleure_dist is None or dist < meilleure_dist:
                meilleure, meilleure_dist = lt, dist
        return meilleure

    texte_precedent = ""
    for w in words_pymupdf:
        x0, y0, x1, y1, texte = w[0], w[1], w[2], w[3], _reparer_texte_cmap(w[4])
        # get_text("words") sépare parfois le montant et son symbole en deux
        # mots. Le contexte doit donc aussi couvrir le token isolé « � » / « ¤ ».
        if texte in {"�", "¤"} and re.search(r"\d[.,]\d{2}$", texte_precedent):
            texte = "€"
        sous_mots = _sous_mots_typographiques((x0, y0, x1, y1), texte, spans_typo)
        if sous_mots:
            for span in sous_mots:
                sx0, sy0, sx1, sy1 = span["bbox"]
                page_obj.native.words.append(Word(
                    id=word_global_id,
                    text=_reparer_texte_cmap(span["text"].strip()),
                    bbox=BBox(sx0, sy0, sx1, sy1),
                    block=int(w[5]),
                    line=int(w[6]),
                    word=int(w[7]),
                    font=span["font"],
                    font_size=span["font_size"],
                    bold=span["bold"],
                    italic=span["italic"],
                    color=span["color"],
                    rotation=float(page_pymupdf.rotation),
                ))
                word_global_id += 1
            texte_precedent = texte
            continue
        lt = _typo_correspondante((x0, y0, x1, y1))
        page_obj.native.words.append(Word(
            id=word_global_id,
            text=texte,
            bbox=BBox(x0, y0, x1, y1),
            block=int(w[5]),
            line=int(w[6]),
            word=int(w[7]),
            font=lt["font"] if lt else "Unknown",
            font_size=lt["font_size"] if lt else 0.0,
            bold=lt["bold"] if lt else False,
            italic=lt["italic"] if lt else False,
            color=lt["color"] if lt else "#000000",
            rotation=float(page_pymupdf.rotation),
        ))
        word_global_id += 1
        texte_precedent = texte

    for name, sizes in font_map.items():
        page_obj.native.fonts.append(Font(name=name, sizes=sorted(list(sizes))))

    return page_obj, word_global_id


def rendre_zone_image(page_pymupdf: pymupdf.Page, bbox: BBox, dpi: int = 300):
    """Rend en pixels UNE zone précise de la page (crop), pas la page
    entière -- pendant de get_pixmap() plein page déjà utilisé côté OCR
    page-entière. Retourne (image PIL, scale) ; scale nécessaire côté
    appelant pour reconvertir les coordonnées pixel -> points PDF."""
    from PIL import Image
    import io

    scale = dpi / 72.0
    matrix = pymupdf.Matrix(scale, scale)
    clip = pymupdf.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
    pix = page_pymupdf.get_pixmap(matrix=matrix, clip=clip, alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png"))), scale
