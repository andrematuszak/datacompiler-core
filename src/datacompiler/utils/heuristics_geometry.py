"""utils/heuristics_geometry.py — Fonctions géométriques pures agissant sur les BBox.

Aucune dépendance vers Word, Page ou Document : uniquement du calcul spatial.
"""

import math
from typing import List, Optional, Tuple
from datacompiler.model.geometry import BBox


def surface_bbox(box: BBox) -> float:
    """Calcule la surface (aire) d'une BBox."""
    width = max(0.0, box.x1 - box.x0)
    height = max(0.0, box.y1 - box.y0)
    return width * height


def calculer_intersection(box1: BBox, box2: BBox) -> float:
    """Calcule la surface de l'intersection entre deux BBox."""
    x0 = max(box1.x0, box2.x0)
    y0 = max(box1.y0, box2.y0)
    x1 = min(box1.x1, box2.x1)
    y1 = min(box1.y1, box2.y1)

    if x0 < x1 and y0 < y1:
        return (x1 - x0) * (y1 - y0)
    return 0.0


def calculer_union(box1: BBox, box2: BBox) -> float:
    """Calcule l'aire de l'union de deux BBox."""
    s1 = surface_bbox(box1)
    s2 = surface_bbox(box2)
    intersection = calculer_intersection(box1, box2)
    return s1 + s2 - intersection


def calculer_iou(box1: BBox, box2: BBox) -> float:
    """Calcule le score IoU (Intersection over Union) entre deux BBox.
    
    Retourne une valeur float entre 0.0 (aucun chevauchement) et 1.0 (superposition parfaite).
    """
    union = calculer_union(box1, box2)
    if union <= 0.0:
        return 0.0
    return calculer_intersection(box1, box2) / union


def contient_spatiale(parent: BBox, enfant: BBox, seuil_recouvrement: float = 0.85) -> bool:
    """Vérifie si la BBox 'enfant' est contenue dans la BBox 'parent'.
    
    Le seuil définit le pourcentage minimum de la surface de l'enfant qui doit se trouver
    à l'intérieur du parent (ex: 0.85 = 85%).
    """
    s_enfant = surface_bbox(enfant)
    if s_enfant <= 0.0:
        return False
    
    intersection = calculer_intersection(parent, enfant)
    return (intersection / s_enfant) >= seuil_recouvrement


def chevauche_significativement(
    box1: BBox, box2: BBox, seuil_recouvrement: float = 0.5
) -> bool:
    """Détermine si box1 recouvre box2 au-delà d'un seuil donné relatif à box1[cite: 10]."""
    s1 = surface_bbox(box1)
    if s1 <= 0.0:
        return False
    intersection = calculer_intersection(box1, box2)
    return (intersection / s1) >= seuil_recouvrement


def calculer_ecarts(box1: BBox, box2: BBox) -> Tuple[float, float, float]:
    """Calcule les écarts (delta_x, delta_y) et la distance euclidienne minimale entre deux BBox.
    
    Si les boîtes se chevauchent sur un axe, la distance sur cet axe est 0.0.
    Retourne (delta_x, delta_y, distance_euclidienne).
    """
    # Écart horizontal
    if box1.x1 < box2.x0:
        dx = box2.x0 - box1.x1
    elif box2.x1 < box1.x0:
        dx = box1.x0 - box2.x1
    else:
        dx = 0.0

    # Écart vertical
    if box1.y1 < box2.y0:
        dy = box2.y0 - box1.y1
    elif box2.y1 < box1.y0:
        dy = box1.y0 - box2.y1
    else:
        dy = 0.0

    dist_euclidienne = math.sqrt(dx**2 + dy**2)
    return dx, dy, dist_euclidienne


def dans_un_tableau(mot, tables):
    """Vérifie si le centre d'un mot tombe dans une table."""
    if not mot.bbox:
        return False
    cx = (mot.bbox.x0 + mot.bbox.x1) / 2
    cy = (mot.bbox.y0 + mot.bbox.y1) / 2
    for table in tables:
        if not table.bbox:
            continue
        if table.bbox.x0 <= cx <= table.bbox.x1 and table.bbox.y0 <= cy <= table.bbox.y1:
            return True
    return False


def fusionner_bboxes(bboxes: List[BBox]) -> Optional[BBox]:
    """Calcule la BBox minimale englobante à partir d'une liste de BBox[cite: 8]."""
    valides = [b for b in bboxes if b is not None]
    if not valides:
        return None

    x0 = min(b.x0 for b in valides)
    y0 = min(b.y0 for b in valides)
    x1 = max(b.x1 for b in valides)
    y1 = max(b.y1 for b in valides)

    return BBox(x0=x0, y0=y0, x1=x1, y1=y1)


def mot_dans_cellule(mot, cell_bbox) -> bool:
    """True si le CENTRE de la bbox du mot tombe dans la cellule --
    plus robuste qu'un simple chevauchement pour un mot à cheval sur une
    frontière (le chevauchement partiel avec la cellule voisine ne le
    fait pas basculer dedans à tort)."""
    if not mot.bbox or cell_bbox is None:
        return False
    cx = (mot.bbox.x0 + mot.bbox.x1) / 2
    cy = (mot.bbox.y0 + mot.bbox.y1) / 2
    return cell_bbox.x0 <= cx <= cell_bbox.x1 and cell_bbox.y0 <= cy <= cell_bbox.y1

def ordonner_par_lignes(boites, seuil_chevauchement=0.3):
    """Regroupe des boîtes hétérogènes (tout objet portant un `.bbox` avec
    x0/y0/x1/y1) en rangées par chevauchement vertical, PUIS trie chaque
    rangée par x0 -- jamais un tri plat (y0, x0) global.

    Une nouvelle boîte est comparée à la BANDE COMMUNE de la rangée en
    cours (intersection courante des bornes y de tous les membres déjà
    admis), pas à un membre pris isolément. La bande ne peut que RÉTRÉCIR
    à chaque ajout, jamais s'élargir -- ça borne la dérive à l'ancre
    initiale de la rangée. Sans ça, une rangée peut dériver
    transitivement loin de son ancre : A chevauche B, B chevauche C, mais
    A et C ne se chevauchent jamais -- A, B et C finiraient quand même
    dans la même rangée avec une comparaison "n'importe quel membre déjà
    présent". Confirmé empiriquement plusieurs fois sur ce projet.

    Même algorithme que reading_order.py::_ordonner_par_boites,
    généralisé ici pour ne pas être limité aux Word -- réutilisable par
    layout/builder.py sur des LayoutBox (images, tables, zones
    vectorielles mélangées)."""
    boites_triees = sorted(boites, key=lambda b: b.bbox.y0)
    rangees = []
    rangee_courante = []
    bande_y0 = bande_y1 = None

    def chevauchement_bande(boite):
        inter = min(bande_y1, boite.bbox.y1) - max(bande_y0, boite.bbox.y0)
        if inter <= 0:
            return 0.0
        plus_petite_hauteur = min(bande_y1 - bande_y0, boite.bbox.y1 - boite.bbox.y0)
        if plus_petite_hauteur <= 0:
            return 0.0
        return inter / plus_petite_hauteur

    for boite in boites_triees:
        if not rangee_courante:
            rangee_courante = [boite]
            bande_y0, bande_y1 = boite.bbox.y0, boite.bbox.y1
            continue
        if chevauchement_bande(boite) >= seuil_chevauchement:
            rangee_courante.append(boite)
            bande_y0 = max(bande_y0, boite.bbox.y0)
            bande_y1 = min(bande_y1, boite.bbox.y1)
        else:
            rangees.append(rangee_courante)
            rangee_courante = [boite]
            bande_y0, bande_y1 = boite.bbox.y0, boite.bbox.y1
    if rangee_courante:
        rangees.append(rangee_courante)

    resultat = []
    for rangee in rangees:
        resultat.extend(sorted(rangee, key=lambda b: b.bbox.x0))
    return resultat
    