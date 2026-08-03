"""
datacompiler/frontend/extract/pymupdf.py
Moteur 1 — Extraction des données textuelles et métadonnées via PyMuPDF.
"""

from pathlib import Path
from typing import Dict, Tuple, Set, Any, List
import fitz

from datacompiler.model.document import Page, Word, Font, BBox


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


def extraire_page_pymupdf(
    page_fitz: fitz.Page, 
    page_number: int, 
    start_word_id: int
) -> Tuple[Page, int]:
    """
    Extrait le texte natif, les Bounding Boxes et la typographie d'une page.
    Gère la ré-indexation des blocs de texte pour éliminer les décalages avec les images.
    Détecte également le texte vectorisé (dessiné géométriquement).
    """
    page_obj = Page(
        number=page_number,
        width=float(page_fitz.rect.width),
        height=float(page_fitz.rect.height),
        rotation=float(page_fitz.rotation)
    )

    page_dict = page_fitz.get_text("dict")
    words_fitz = page_fitz.get_text("words")
    font_map: Dict[str, Set[float]] = {}
    word_global_id = start_word_id

    # Détection des zones vectorielles (potentiellement du texte dessiné)
    zones_vectorielles = _grouper_zones_vectorielles_proches(_extraire_zones_vectorielles(page_fitz))
    zones_bboxes = [z["bbox"] for z in zones_vectorielles]

    # Alignement d'index : ignorer les blocs non-texte (images)
    text_block_idx = 0
    for b in page_dict.get("blocks", []):
        if b.get("type") != 0:
            continue

        block_idx = text_block_idx
        text_block_idx += 1

        for line_idx, l in enumerate(b.get("lines", [])):
            font_name, font_size, bold, italic, color_hex = "Unknown", 0.0, False, False, "#000000"
            
            # Récupération de la typographie via les spans
            for s in l.get("spans", []):
                font_name = s.get("font", "Unknown")
                font_size = float(s.get("size", 0.0))
                bold = bool(s.get("flags", 0) & 4)
                italic = bool(s.get("flags", 0) & 2)
                color_hex = _convertir_couleur(s.get("color"))
                font_map.setdefault(font_name, set()).add(round(font_size, 1))

            # Récupération géométrique des mots
            for w in words_fitz:
                if w[5] == block_idx and w[6] == line_idx:
                    word_bbox = BBox(w[0], w[1], w[2], w[3])
                    # Vérifier si le mot est dans une zone vectorielle
                    is_vectorized = any(_mot_dans_zone_vectorielle(word_bbox, z_bbox) for z_bbox in zones_bboxes)
                    
                    page_obj.native.words.append(Word(
                        id=word_global_id,
                        text=w[4],
                        bbox=word_bbox,
                        block=int(w[5]),
                        line=int(w[6]),
                        word=int(w[7]),
                        font=font_name,
                        font_size=font_size,
                        bold=bold,
                        italic=italic,
                        color=color_hex,
                        rotation=float(page_fitz.rotation),
                        is_vectorized=is_vectorized
                    ))
                    word_global_id += 1

    # Ingestion des polices recensées
    for name, sizes in font_map.items():
        page_obj.native.fonts.append(Font(name=name, sizes=sorted(list(sizes))))

    return page_obj, word_global_id
