"""typography.py — Normalisation typographique sur une liste de Word DÉJÀ
DANS L'ORDRE DE LECTURE (c'est reading_order.py qui garantit cet ordre --
la césure de fin de ligne ne peut se détecter que si on sait quel mot suit
réellement quel mot à l'écran).

Deux opérations, volontairement séparées :
  - ligatures : substitution de caractères, indépendante de l'ordre.
  - césures   : fusion de deux mots consécutifs quand le premier se termine
                par un trait d'union en fin de ligne et que le second
                commence la ligne suivante.

LIMITE CONNUE (documentée plutôt que masquée) : rien ne distingue de façon
fiable un trait d'union de CÉSURE (mot coupé, à refusionner) d'un trait
d'union LEXICAL (mot composé qui se termine légitimement par un tiret en
fin de ligne, ex. "avant-" / "avant-garde" coupé pile à l'endroit du tiret
existant). L'heuristique fusionne systématiquement -- c'est le choix qui
minimise l'erreur la plus fréquente (mots coupés) au prix, plus rare, de
mots composés mal refusionnés. À affiner plus tard si besoin (dictionnaire,
liste d'exceptions) plutôt que bloquant pour cette première version.
"""

from datacompiler.model.document import Word

_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}


def normaliser_ligatures(texte: str) -> str:
    for ligature, expansion in _LIGATURES.items():
        if ligature in texte:
            texte = texte.replace(ligature, expansion)
    return texte


def _a_des_ligatures(texte: str) -> bool:
    return any(l in texte for l in _LIGATURES)


def _rupture_de_ligne(mot_a: Word, mot_b: Word, tolerance_y: float = 3.0) -> bool:
    """True si mot_b commence une nouvelle ligne visuelle par rapport à
    mot_a (saut vertical + retour vers la gauche), sans reconstruire tout
    le regroupement en lignes -- comparaison locale entre deux mots
    consécutifs de la séquence déjà ordonnée."""
    if not mot_a.bbox or not mot_b.bbox:
        return False
    saut_y = mot_b.bbox.y0 - mot_a.bbox.y0
    retour_x = mot_b.bbox.x0 < mot_a.bbox.x0
    return saut_y > tolerance_y and retour_x


def _ressemble_a_une_cesure(mot_a: Word, mot_b: Word) -> bool:
    texte_a = mot_a.output_text
    if not texte_a.endswith("-") or len(texte_a) < 2:
        return False
    if not mot_b.output_text:
        return False
    # Un tiret cadratin/demi-cadratin n'est pas une césure typographique.
    if texte_a[-1] not in ("-",):
        return False
    return _rupture_de_ligne(mot_a, mot_b)


def normaliser(mots: list) -> list:
    """Applique ligatures + fusion de césures sur une liste de Word déjà en
    ordre de lecture. Retourne une NOUVELLE liste (les mots absorbés par une
    fusion de césure sont retirés plutôt que laissés vides, pour ne pas
    dépendre d'une convention "texte vide = ignorer mot" côté renderers)."""
    resultat = []
    i = 0
    n = len(mots)
    while i < n:
        mot = mots[i]
        texte = mot.output_text

        if _a_des_ligatures(texte):
            mot.resolved_text = normaliser_ligatures(texte)
            mot.notes.append("ligature(s) normalisée(s)")
            texte = mot.resolved_text

        if i + 1 < n and _ressemble_a_une_cesure(mot, mots[i + 1]):
            suivant = mots[i + 1]
            fusion = texte[:-1] + normaliser_ligatures(suivant.output_text)
            mot.resolved_text = fusion
            mot.reconstructed = True
            mot.notes.append(f"césure fusionnée avec le mot suivant ({suivant.text!r})")
            resultat.append(mot)
            i += 2  # le mot suivant est absorbé, on ne l'ajoute pas au résultat
            continue

        resultat.append(mot)
        i += 1

    return resultat
