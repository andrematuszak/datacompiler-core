"""PDF fidèle : conserve le contenu source et ajoute au besoin une couche texte résolue.

Par défaut, le mode ``overlay`` ouvre le PDF source et ne crée une couche
texte invisible que si la résolution a modifié du texte. Ses vecteurs, images
et compression sont donc préservés. Le mode ``rasterized`` reste disponible à
titre exceptionnel pour aplatir l'ancienne couche texte, mais transforme
inévitablement chaque page en image et ne doit pas être utilisé pour le rendu
normal.
"""

from pathlib import Path
import fitz
from datacompiler.model.document import Document
from datacompiler.compile.layout import grouper_par_ligne

# On insère TOUJOURS la couche invisible avec une police Unicode large
# (DejaVu Sans) plutôt que "helv" (Helvetica base-14 de PyMuPDF).
#
# Tentative précédente : basculer entre "helv" et une police de secours
# selon que le texte semble encodable en WinAnsi (texte.encode("cp1252")).
# Ça s'est révélé un mauvais test : "€" s'encode très bien en cp1252, mais
# la police "helv" telle qu'implémentée par PyMuPDF n'a apparemment pas ce
# glyphe -- le caractère inséré ne correspondait donc pas à celui attendu
# lors de l'extraction. Vérifier la couverture réelle de "helv" existe
# (fitz.Font.has_glyph) mais son comportement/disponibilité varie selon les
# versions de PyMuPDF, comme on vient de le voir avec get_text_length.
#
# Comme cette couche est de toute façon invisible (render_mode=3), il n'y a
# aucun coût visuel à toujours utiliser la police de secours : ça élimine
# la détection fragile et garantit la couverture (Latin étendu, €, etc.)
# indépendamment de la version de PyMuPDF installée.
_FALLBACK_FONTNAME = "df-fallback"
# Chemin RELATIF au module plutôt qu'un chemin système (ex.
# /usr/share/fonts/...) : un chemin système est spécifique à l'OS/à la
# machine et casse dès qu'on change d'environnement (Linux -> macOS -> prod).
# La police doit être committée dans le repo, à côté de ce fichier :
# faithful_pdf.py
# fonts/DejaVuSans.ttf   <- fichier fourni séparément, à copier ici
_FALLBACK_FONTFILE = str(Path(__file__).parent / "fonts" / "DejaVuSans.ttf")

_polices_chargees = {}  # cache : nom de police -> fitz.Font


def _font_objet(fontname, fontfile=None):
    if fontname not in _polices_chargees:
        _polices_chargees[fontname] = (
            fitz.Font(fontfile=fontfile) if fontfile else fitz.Font(fontname)
        )
    return _polices_chargees[fontname]


def _inserer_texte(page, x0, y1, texte, largeur_cible, taille_nominale):
    """Insère `texte` en mode invisible, en rescalant sa taille de police
    pour que sa largeur rendue corresponde exactement à `largeur_cible`."""
    police = _font_objet(_FALLBACK_FONTNAME, _FALLBACK_FONTFILE)
    largeur_rendue = police.text_length(texte, fontsize=taille_nominale)
    taille = (taille_nominale * (largeur_cible / largeur_rendue)
             if largeur_rendue else taille_nominale)
    page.insert_text((x0, y1), texte, fontsize=taille,
                     fontname=_FALLBACK_FONTNAME, fontfile=_FALLBACK_FONTFILE,
                     render_mode=3, overlay=True)


def _insert_invisible_words(page, words):
    # Regroupement en lignes (même logique que render.py) : nécessaire pour
    # savoir quels mots sont adjacents et mériter un espace explicite entre
    # eux, plutôt que de traiter chaque mot isolément.
    a_inserer = [w for w in words if w.output_text != w.text or w.reconstructed]
    for ligne in grouper_par_ligne(a_inserer):
        mots_valides = [w for w in ligne if w.bbox and w.output_text.strip()]
        for i, word in enumerate(mots_valides):
            box = word.bbox
            largeur_cible = max(box.x1 - box.x0, 0.1)
            taille_nominale = word.font_size or max(4.0, box.y1 - box.y0)
            _inserer_texte(page, box.x0, box.y1, word.output_text,
                          largeur_cible, taille_nominale)

            if i + 1 < len(mots_valides):
                suivant = mots_valides[i + 1]
                if suivant.bbox.x0 > box.x1:
                    # Espace EXPLICITE entre deux mots voisins d'une même
                    # ligne : on ne compte plus sur l'extracteur de texte
                    # (pdftotext, etc.) pour déduire une coupure de mot à
                    # partir d'un écart géométrique -- un seuil ambigu qui
                    # dépend du moteur d'extraction, de la police de
                    # substitution et de la taille rescalée. Un vrai
                    # caractère espace dans le flux est sans ambiguïté.
                    _inserer_texte(page, box.x1, box.y1, " ",
                                  max(suivant.bbox.x0 - box.x1, 0.1), taille_nominale)


def _texte_modifie(words):
    """Indique si la couche résolue apporte quelque chose que le PDF source
    n'a pas déjà : soit une correction de texte natif existant
    (output_text != text), soit un mot entièrement reconstruit et absent du
    PDF source (OCR-seul, texte vectorisé) -- ce dernier cas n'a par
    définition aucun texte natif à comparer, donc output_text == text n'y
    signifie PAS "rien à faire"."""
    return any(word.output_text != word.text or word.reconstructed for word in words)

def render_faithful_pdf(doc: Document, output_path: str, source_pdf: str = None,
                        strategy: str = "overlay", dpi: int = 300) -> str:
    source_path = source_pdf or doc.metadata.source_pdf
    if not source_path:
        raise ValueError("Le chemin du PDF source est requis pour le rendu fidèle.")
    if strategy not in {"rasterized", "overlay"}:
        raise ValueError("strategy doit être 'rasterized' ou 'overlay'.")

    source = fitz.open(source_path)
    if len(source) != len(doc.pages):
        raise ValueError("Le PDF source et Document n'ont pas le même nombre de pages.")
    if strategy == "overlay":
        output = fitz.open(source_path)
        for page, model_page in zip(output, doc.pages):
            # Tant que le texte résolu est identique au texte natif, le PDF
            # source est déjà la représentation la plus compacte et fidèle.
            if _texte_modifie(model_page.resolved.words):
                _insert_invisible_words(page, model_page.resolved.words)
    else:
        output = fitz.open()
        scale = dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        for source_page, model_page in zip(source, doc.pages):
            target = output.new_page(width=source_page.rect.width, height=source_page.rect.height)
            pix = source_page.get_pixmap(matrix=matrix, alpha=False)
            target.insert_image(target.rect, stream=pix.tobytes("png"))
            _insert_invisible_words(target, model_page.resolved.words)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    output.set_metadata({"producer": "DataCleaner faithful_pdf", "title": doc.metadata.filename})
    # La police Unicode de la couche invisible ne doit pas embarquer tout
    # DejaVu Sans (plusieurs centaines de Ko) : conserver uniquement les
    # glyphes effectivement présents dans le document.
    output.subset_fonts()
    output.save(output_path, garbage=4, deflate=True)
    output.close()
    source.close()
    return output_path
