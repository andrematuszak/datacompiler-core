"""Group resolved words into visual lines once during compilation so output renderers share the same layout decisions."""




def assigner_lignes(mots, tolerance_y=3) -> list:
    """Assign a zero-based ``layout_line`` to each word and return the same list."""
    ligne_courante = 0
    dernier_y = None


    for mot in mots:
        if mot.bbox is None:
            mot.layout_line = ligne_courante
            continue


        y = mot.bbox.y0
        if dernier_y is not None and abs(y - dernier_y) > tolerance_y:
            ligne_courante += 1
        mot.layout_line = ligne_courante
        dernier_y = y


    return mots




def grouper_par_ligne(mots) -> list:
    """Group words by their previously assigned ``layout_line`` value."""
    # 🛡️ Protection contre None ou liste vide
    if not mots:
        return []

    groupes = {}
    ordre = []
    for mot in mots:
        cle = getattr(mot, "layout_line", 0)
        if cle not in groupes:
            groupes[cle] = []
            ordre.append(cle)
        groupes[cle].append(mot)
    return [groupes[cle] for cle in ordre]
