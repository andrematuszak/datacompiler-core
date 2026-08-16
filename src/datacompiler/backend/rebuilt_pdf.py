"""
rebuilt_pdf.py — Reconstruction fidèle d'un PDF neuf, texte VISIBLE et
sélectionnable, à la même position que le source.

Reprend et corrige _copier_images_et_dessins / _inserer_texte de
faithful_pdf.py (clean_overlay), adaptées pour tourner directement sur le
modèle Document (pas de JSON brut). Correctifs appliqués :

  1. bug 'qu'/fitz.Quad : pts = item[1:] -> pts = list(item[1])
  2. fill_opacity=1.0 (opacité pleine, car c'est le SEUL contenu textuel)
  3. police de repli : LiberationSans (contient '€') au lieu de Helvetica
  4. fitz.TextWriter au lieu d'insert_text() mot par mot — un writer par
     segment de couleur contiguë, pas un writer par couleur globale
  5. output.subset_fonts() juste avant la sauvegarde
  6. calibrage de ligne de base par ligne visuelle (`_calibrer_lignes`)
  7. échantillonnage des couleurs des glyphes vectoriels pour les mots
     blancs sur fond bleu (les mots vectorisés ont `color="#000000"` dans
     le JSON, mais sont en réalité blancs)
  8. Ordre de lecture : reading_order.ordonner() sur native.words pour
     TOUTES les pages (une seule source de vérité)

La fonction render_rebuilt_pdf() est l'entrée principale, appelée depuis pipeline.py.
"""

import logging
from pathlib import Path

import fitz

from datacompiler.compile.reading_order import ordonner
from datacompiler.model.document import Document

logger = logging.getLogger(__name__)

# --- Polices embarquées dans le package (backend/fonts/) ---
_FONTS_DIR = Path(__file__).parent / "fonts"
_FONT_REGULAR = _FONTS_DIR / "LiberationSans-Regular.ttf"
_FONT_BOLD = _FONTS_DIR / "LiberationSans-Bold.ttf"
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


def _calibrer_lignes(ordre, tolerance=3.0):
    """
    Calcule une ligne de base COMMUNE par ligne visuelle, au lieu
    d'utiliser bbox.y1 de chaque mot individuellement.

    Les bbox des mots vectorisés/OCR sont des boîtes d'encre SERRÉES :
    leur hauteur dépend de si le mot contient une descendante (ex: 'p')
    ou non. Résultat : au sein d'une même ligne, des mots sans descendante
    ont un y1 plus petit qu'un mot avec descendante — d'où le flottement.

    Parcourt `ordre` (déjà dans l'ordre de lecture) SÉQUENTIELLEMENT pour
    éviter de fusionner des colonnes différentes (bug corrigé).

    Retourne un dict id(mot) -> y_ligne_de_base.
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
        # Utiliser les mots natifs comme référence (métrique de ligne fiable)
        natifs = [w for w in mots_ligne if not w.is_vectorized]
        if natifs:
            y1s = sorted(w.bbox.y1 for w in natifs)
            baseline = y1s[len(y1s) // 2]  # médiane
        else:
            baseline = max(w.bbox.y1 for w in mots_ligne)
        for w in mots_ligne:
            baseline_par_id[id(w)] = baseline
    return baseline_par_id


def _copier_images_et_dessins(src_page, dst_page, report, exclure=None):
    """
    Copie les images et dessins vectoriels du source vers la page de destination.

    `exclure` : liste de mots (Word) reconstruits/vectorisés.
    Un dessin dont le rectangle tombe majoritairement dans la bbox d'un
    de ces mots est un tracé de GLYPHE — on ne le copie pas (double impression).

    Retourne un dict id(mot) -> couleur échantillonnée, pour les mots
    vectorisés dont la couleur réelle est différente de mot.color
    (ex: blanc sur fond bleu).
    """
    exclure = exclure or []

    def _match_exclusion(rect):
        if rect is None:
            return None
        for w in exclure:
            if not w.bbox:
                continue
            zone = fitz.Rect(w.bbox.x0, w.bbox.y0, w.bbox.x1, w.bbox.y1)
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
            # Échantillonner la couleur du glyphe (fill ou color)
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
                    q = item[1]  # fitz.Quad
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


def _inserer_mot(etat, page_rect, mot, baseline_par_id, report):
    """
    Ajoute le mot à un fitz.TextWriter.

    TextWriter accumule en mémoire et n'écrit qu'UN SEUL stream par
    write_text(). Un nouveau writer est ouvert seulement quand la couleur
    CHANGE dans la séquence — l'ordre de lecture est préservé.
    """
    texte = mot.resolved_text or mot.text or ""
    if not texte.strip():
        return

    bbox = mot.bbox
    if bbox is None:
        return

    gras = bool(mot.bold) or "bold" in (mot.font or "").lower()
    police, _ = _font_objet(gras)

    taille_nominale = mot.font_size or 0.0
    if not taille_nominale:
        taille_nominale = max(4.0, bbox.y1 - bbox.y0)
        report["taille_heuristique"] = report.get("taille_heuristique", 0) + 1

    largeur_cible = max(bbox.x1 - bbox.x0, 0.1)
    largeur_rendue = police.text_length(texte, fontsize=taille_nominale)
    taille = (taille_nominale * (largeur_cible / largeur_rendue)
              if largeur_rendue else taille_nominale)

    # Couleur : priorité à la couleur échantillonnée (pour les mots blancs
    # sur fond bleu), sinon utiliser mot.color
    mot_id = id(mot)
    couleurs_echantillonnees = etat.get("couleurs_echantillonnees", {})
    if mot_id in couleurs_echantillonnees:
        couleur_rgb = tuple(couleurs_echantillonnees[mot_id])
    else:
        couleur_rgb = _hex_to_rgb(mot.color)

    couleur_cle = tuple(round(c, 3) for c in couleur_rgb)
    if couleur_cle != etat["couleur_cle"]:
        etat["segments"].append((etat["couleur_cle"], etat["tw"]))
        etat["tw"] = fitz.TextWriter(page_rect)
        etat["couleur_cle"] = couleur_cle

    point = fitz.Point(bbox.x0, baseline_par_id.get(mot_id, bbox.y1))
    etat["tw"].append(point, texte, font=police, fontsize=taille)
    report["mots_inseres"] = report.get("mots_inseres", 0) + 1


def render_rebuilt_pdf(doc: Document, output_path: str, source_pdf: str = None,
                       dpi: int = 300, simple_sort=False) -> str:
    """
    Reconstruit un PDF neuf, texte visible et sélectionnable, à la même
    position que le source.

    - Copie les images et dessins du PDF source (en excluant les tracés de
      glyphes des mots vectorisés/OCRisés).
    - Réinjecte le texte résolu dans l'ordre de lecture réel
      (reading_order.ordonner sur native.words), à la même position.
    - Calibre les lignes de base pour un alignement vertical parfait.
    - Échantillonne les couleurs des glyphes vectoriels.
    - Utilise LiberationSans (embarquée) pour couvrir '€'.

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

            report = {
                "images_copiees": 0,
                "images_ignorees": 0,
                "dessins_ignores": 0,
                "dessins_exclus_glyphes": 0,
                "mots_inseres": 0,
                "taille_heuristique": 0,
            }

            # Ordre de lecture réel, directement depuis native.words
            ordre = model_page.resolved.words
            baseline_par_id = _calibrer_lignes(ordre)

            # Bbox des mots reconstruits/vectorisés : leurs tracés de glyphes
            # dans le source ne doivent pas être recopiés (double impression).
            mots_exclus = [
                w for w in ordre
                if w.bbox and (w.reconstructed or w.is_vectorized or w.source == "ocr_vectoriel")
            ]

            # Copier images et dessins, et récupérer les couleurs échantillonnées
            couleurs_echantillonnees = _copier_images_et_dessins(
                src_page, dst_page, report, exclure=mots_exclus
            )

            # Insérer les mots avec TextWriter (un writer par couleur)
            writers = {
                "tw": fitz.TextWriter(dst_page.rect),
                "couleur_cle": (0.0, 0.0, 0.0),
                "segments": [],
                "couleurs_echantillonnees": couleurs_echantillonnees,
            }

            for mot in ordre:
                _inserer_mot(writers, dst_page.rect, mot, baseline_par_id, report)

            writers["segments"].append((writers["couleur_cle"], writers["tw"]))
            for couleur_rgb, tw in writers["segments"]:
                tw.write_text(dst_page, color=couleur_rgb, render_mode=0, opacity=1.0)

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