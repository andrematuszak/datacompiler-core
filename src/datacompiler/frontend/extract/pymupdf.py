"""
datacompiler/frontend/extract/pymupdf.py
Moteur 1 — Extraction des données textuelles et métadonnées via PyMuPDF.
"""

from pathlib import Path
from typing import Dict, Tuple, Set, Any, List
import fitz

from datacompiler.model.document import BBox, Font, GraphicVector, Page, Word


def _convertir_couleur(srgb_int: int | None) -> str:
    """Convertit un entier sRGB en format Hexadécimal."""
    if srgb_int is None:
        return "#000000"
    r = (srgb_int >> 16) & 255
    g = (srgb_int >> 8) & 255
    b = srgb_int & 255
    return f"#{r:02x}{g:02x}{b:02x}"


def _extraire_zones_vectorielles(page_fitz: fitz.Page) -> List[Dict[str, Any]]:
    """
    Extrait les zones vectorielles (dessins) de la page qui pourraient correspondre
    à du texte dessiné géométriquement. Retourne une liste de bbox avec leurs
    caractéristiques.
    """
    drawings = page_fitz.get_drawings()
    zones_vectorielles = []
    
    for drawing in drawings:
        for item in drawing.get("items", []):
            if item[0] == "l":  # ligne
                p1, p2 = item[1], item[2]
                x0, y0 = min(p1.x, p2.x), min(p1.y, p2.y)
                x1, y1 = max(p1.x, p2.x), max(p1.y, p2.y)
                zones_vectorielles.append({
                    "type": "line",
                    "bbox": (x0, y0, x1, y1),
                    "width": x1 - x0,
                    "height": y1 - y0
                })
            elif item[0] == "re":  # rectangle
                rect = item[1]
                zones_vectorielles.append({
                    "type": "rect",
                    "bbox": (rect.x0, rect.y0, rect.x1, rect.y1),
                    "width": rect.x1 - rect.x0,
                    "height": rect.y1 - rect.y0
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
                    "height": max(ys) - min(ys)
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


def extraire_metadonnees(doc_fitz: fitz.Document, pdf_path: str) -> dict:
    """Extrait l'ensemble des métadonnées système du fichier PDF."""
    return {
        "filename": Path(pdf_path).name,
        "source_pdf": str(Path(pdf_path).resolve()),
        "page_count": len(doc_fitz),
        "producer": doc_fitz.metadata.get("producer", ""),
        "creator": doc_fitz.metadata.get("creator", ""),
        "creation_date": doc_fitz.metadata.get("creationDate", ""),
        "modification_date": doc_fitz.metadata.get("modDate", ""),
        "pdf_version": doc_fitz.metadata.get("format", ""),
        "encrypted": bool(doc_fitz.is_encrypted),
    }


def extraire_page_pymupdf(page_fitz, page_number, start_word_id):
    page_obj = Page(
        number=page_number,
        width=float(page_fitz.rect.width),
        height=float(page_fitz.rect.height),
        rotation=float(page_fitz.rotation),
    )

    page_dict = page_fitz.get_text("dict")
    words_fitz = page_fitz.get_text("words")
    font_map = {}
    word_global_id = start_word_id

    for zone in _extraire_zones_vectorielles(page_fitz):
        x0, y0, x1, y1 = zone["bbox"]
        vector = GraphicVector(bbox=BBox(x0, y0, x1, y1))
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
    # On itère directement sur words_fitz (garanti exhaustif : c'est LA
    # source de vérité pour "quels mots existent"), et on retrouve la
    # typographie par containment géométrique du centre du mot dans la
    # bbox de ligne du dict, avec repli sur la ligne verticalement la plus
    # proche si aucun containment exact (tolérance aux petits écarts
    # d'arrondi de bbox entre les deux extractions). Un mot ne peut plus
    # jamais disparaître : au pire, sa typographie est mal attribuée --
    # jamais son existence.
    lignes_typo = []
    text_block_idx = 0
    for b in page_dict.get("blocks", []):
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            font_name, font_size, bold, italic, color_hex = "Unknown", 0.0, False, False, "#000000"
            for s in l.get("spans", []):
                font_name = s.get("font", "Unknown")
                font_size = float(s.get("size", 0.0))
                bold = bool(s.get("flags", 0) & 4)
                italic = bool(s.get("flags", 0) & 2)
                color_hex = _convertir_couleur(s.get("color"))
                font_map.setdefault(font_name, set()).add(round(font_size, 1))
            bbox_ligne = l.get("bbox")
            if bbox_ligne:
                lignes_typo.append({
                    "bbox": bbox_ligne, "block": text_block_idx, "font": font_name,
                    "font_size": font_size, "bold": bold, "italic": italic, "color": color_hex,
                })
        text_block_idx += 1

    def _ligne_correspondante(word_bbox):
        cx, cy = (word_bbox[0] + word_bbox[2]) / 2, (word_bbox[1] + word_bbox[3]) / 2
        meilleure, meilleure_dist = None, None
        for lt in lignes_typo:
            bx0, by0, bx1, by1 = lt["bbox"]
            if bx0 - 1 <= cx <= bx1 + 1 and by0 - 1 <= cy <= by1 + 1:
                return lt
            dist = abs((by0 + by1) / 2 - cy)
            if meilleure_dist is None or dist < meilleure_dist:
                meilleure, meilleure_dist = lt, dist
        return meilleure

    for w in words_fitz:
        x0, y0, x1, y1, texte = w[0], w[1], w[2], w[3], w[4]
        lt = _ligne_correspondante((x0, y0, x1, y1))
        page_obj.native.words.append(Word(
            id=word_global_id,
            text=texte,
            bbox=BBox(x0, y0, x1, y1),
            block=lt["block"] if lt else 0,
            line=0,
            word=0,
            font=lt["font"] if lt else "Unknown",
            font_size=lt["font_size"] if lt else 0.0,
            bold=lt["bold"] if lt else False,
            italic=lt["italic"] if lt else False,
            color=lt["color"] if lt else "#000000",
            rotation=float(page_fitz.rotation),
        ))
        word_global_id += 1

    for name, sizes in font_map.items():
        page_obj.native.fonts.append(Font(name=name, sizes=sorted(list(sizes))))

    return page_obj, word_global_id


def rendre_zone_image(page_fitz: fitz.Page, bbox: BBox, dpi: int = 300):
    """Rend en pixels UNE zone précise de la page (crop), pas la page
    entière -- pendant de get_pixmap() plein page déjà utilisé côté OCR
    page-entière. Retourne (image PIL, scale) ; scale nécessaire côté
    appelant pour reconvertir les coordonnées pixel -> points PDF."""
    from PIL import Image
    import io

    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    clip = fitz.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
    pix = page_fitz.get_pixmap(matrix=matrix, clip=clip, alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png"))), scale
