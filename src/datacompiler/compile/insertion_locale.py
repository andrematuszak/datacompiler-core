"""Conservatively insert OCR reference tokens missing from native text only when they fit a small gap between adjacent native words. Tokens without nearby anchors are omitted rather than placed speculatively."""

from collections import defaultdict, deque

from datacompiler.model.document import Word, BBox

# Même ordre de grandeur que SEUIL_PROXIMITE_MOT (layout_tree.py) --
# calibré sur les mêmes observations empiriques limitées (un seul
# document à ce stade). À recalibrer si besoin sur un corpus plus large.
SEUIL_ECART_INSERTION = 15.0


def inserer_tokens_manquants(mots_ordonnes, tokens_reference, cle_texte=lambda m: m.text, seuil=SEUIL_ECART_INSERTION):
    """Return a new word list with reference tokens inserted only into small gaps between adjacent native words."""
    files_par_texte = defaultdict(deque)
    for j, tok in enumerate(tokens_reference):
        files_par_texte[tok].append(j)

    rang_par_mot = []
    for m in mots_ordonnes:
        file_ = files_par_texte.get(cle_texte(m))
        rang_par_mot.append(file_.popleft() if file_ else None)

    resultat = []
    n = len(mots_ordonnes)
    for idx, m in enumerate(mots_ordonnes):
        resultat.append(m)
        rang_actuel = rang_par_mot[idx]
        rang_suivant = rang_par_mot[idx + 1] if idx + 1 < n else None
        if rang_actuel is None or rang_suivant is None:
            continue

        manquants_ici = list(range(rang_actuel + 1, rang_suivant))
        if not manquants_ici:
            continue

        voisin = mots_ordonnes[idx + 1]
        if not m.bbox or not voisin.bbox:
            continue

        ecart = voisin.bbox.x0 - m.bbox.x1
        if ecart <= 0 or ecart > seuil:
            # Négatif/nul : mots qui se chevauchent ou lignes différentes --
            # pas assez fiable pour synthétiser une position. Trop grand :
            # exactement le cas qu'on refuse de combler.
            continue

        textes_manquants = [tokens_reference[j] for j in manquants_ici]
        poids = [max(len(t), 1) for t in textes_manquants]
        total_poids = sum(poids)
        n_mots = len(textes_manquants)

        # Marge réservée UNIQUEMENT entre mots insérés consécutifs (pas
        # aux bords, envers l'ancre ou le voisin) -- le collage signalé
        # ne concernait que plusieurs mots insérés à la suite, jamais le
        # cas à un seul mot (qui remplit tout l'écart sans marge, comme
        # avant, et ça marche bien : cf. "de" entre "Numéro" et "rôle").
        # Réserver une marge aux DEUX bords en plus cassait ce cas à un
        # seul mot sur un petit écart (largeur nulle, "de" invisible) --
        # trouvé en testant, pas supposé.
        espace_inter_mot = 2.0  # pt -- approximation d'un espace typographique, à affiner
        espace_reserve = espace_inter_mot * max(n_mots - 1, 0)
        largeur_disponible = ecart - espace_reserve

        if largeur_disponible <= 0:
            # Même les marges entre mots ne rentrent pas dans l'écart
            # disponible -- trop de tokens pour un espace aussi serré.
            # Rien de fiable à insérer ici, on saute ce groupe entier
            # plutôt que produire des mots à largeur nulle ou négative.
            continue

        x = m.bbox.x1
        y0 = min(m.bbox.y0, voisin.bbox.y0)
        y1 = max(m.bbox.y1, voisin.bbox.y1)
        for i, (texte, p) in enumerate(zip(textes_manquants, poids)):
            largeur = largeur_disponible * (p / total_poids) if total_poids else 0.0
            resultat.append(Word(
                id=-1,  # renumérotation finale par compile/compiler.py
                text=texte,
                resolved_text=texte,
                bbox=BBox(x, y0, x + largeur, y1),
                reconstructed=True,
                source="ocr_insere_local",
                notes=[f"inséré entre '{m.text}' et '{voisin.text}' (écart={ecart:.1f}pt < seuil={seuil}pt)"],
            ))
            x += largeur
            if i < n_mots - 1:
                x += espace_inter_mot

    return resultat
