"""conflict_resolution.py — Décide, pour chaque UniteAlignement produite par
alignment.py, quel texte final retenir dans page.resolved.words.

Règle de base : la bbox vient TOUJOURS du mot natif quand il existe (seul
des deux à en avoir une, cf. alignment.py) -- un conflit ne fait jamais
perdre le positionnement, seulement potentiellement le texte.

En second passage, `_interpoler_bboxes` attribue une bbox estimée aux mots
présents uniquement en OCR (`ocr_seul`) afin d'assurer leur rendu.
"""

from datacompiler.model.document import Word, Decision, BBox

from . import confidence


def _resoudre_conflit(unite) -> Word:
    conf_native = confidence.confiance_native(unite.native)
    conf_ocr = confidence.confiance_ocr(unite.ocr)
    native_gagne, conf_gagnante, ecart_net = confidence.meilleur(conf_native, conf_ocr)

    mot = unite.native  # bbox conservée quoi qu'il arrive
    if native_gagne or not ecart_net:
        mot.notes.append(
            f"conflit natif/OCR : texte natif conservé "
            f"('{unite.native.text}' vs OCR '{unite.ocr.text}', "
            f"confiance native={conf_native:.2f}, ocr={conf_ocr:.2f}"
            f"{', écart faible -> natif par défaut' if not ecart_net else ''})"
        )
        mot.decision = Decision(
            regle="conflit_natif_conserve",
            detail=f"'{unite.native.text}' vs OCR '{unite.ocr.text}'",
        )
    else:
        mot.resolved_text = unite.ocr.text
        mot.replacement = unite.ocr.text
        mot.is_corrected = True
        mot.source = "ocr"
        mot.notes.append(
            f"conflit natif/OCR : corrigé '{unite.native.text}' -> '{unite.ocr.text}' "
            f"(confiance native={conf_native:.2f}, ocr={conf_ocr:.2f})"
        )
        mot.decision = Decision(
            regle="conflit_ocr_corrige",
            detail=f"'{unite.native.text}' -> '{unite.ocr.text}'",
        )
    return mot


def _interpoler_bboxes(mots: list) -> None:
    """Comble les bbox manquantes des mots ocr_seul par interpolation
    linéaire entre le mot positionné précédent et le mot positionné
    suivant dans resolved.words. Modifie `mots` en place.
    """
    i, n = 0, len(mots)
    while i < n:
        if mots[i].bbox is not None:
            i += 1
            continue

        debut = i
        while i < n and mots[i].bbox is None:
            i += 1
        fin = i  # exclusif
        groupe = mots[debut:fin]

        gauche = mots[debut - 1] if debut > 0 and mots[debut - 1].bbox else None
        droite = mots[fin] if fin < n and mots[fin].bbox else None

        if gauche is None and droite is None:
            # Aucune ancre native disponible sur toute la page
            for mot in groupe:
                mot.notes.append("bbox non interpolable : aucune ancre native disponible")
            continue

        poids = [max(len(m.text), 1) for m in groupe]
        total_poids = sum(poids)

        # Ancre de référence pour les dimensions relatives
        ancre_ref = gauche or droite
        hauteur_ref = max(ancre_ref.bbox.y1 - ancre_ref.bbox.y0, 8.0)
        char_width_ref = max(hauteur_ref * 0.5, 3.0)

        meme_ligne = False
        if gauche and droite:
            meme_ligne = abs(gauche.bbox.y1 - droite.bbox.y1) < (hauteur_ref * 0.8)

        # --- Détermination du segment géométrique (x_debut, x_fin) ---
        if gauche and droite and meme_ligne and droite.bbox.x0 > gauche.bbox.x1:
            # Cas idéal : deux ancres sur la même ligne avec espace X valide
            x_debut = gauche.bbox.x1
            x_fin = droite.bbox.x0
            largeur_dispo = x_fin - x_debut
            y0 = min(gauche.bbox.y0, droite.bbox.y0)
            y1 = max(gauche.bbox.y1, droite.bbox.y1)
        elif gauche:
            # Ancre gauche seule OU saut de ligne (prolongement à droite de l'ancre gauche)
            x_debut = gauche.bbox.x1
            largeur_dispo = total_poids * char_width_ref
            y0, y1 = gauche.bbox.y0, gauche.bbox.y1
        else:
            # Ancre droite seule en début de bloc/page (positionnement à gauche de l'ancre droite)
            y0, y1 = droite.bbox.y0, droite.bbox.y1
            largeur_dispo = total_poids * char_width_ref
            x_debut = max(0.0, droite.bbox.x0 - largeur_dispo)

        # --- Attributs et répartition pour chaque mot du groupe ---
        x = x_debut
        for mot, p in zip(groupe, poids):
            largeur_mot = largeur_dispo * (p / total_poids)
            mot.bbox = BBox(x0=x, y0=y0, x1=x + largeur_mot, y1=y1)
            mot.reconstructed = True

            note = "bbox interpolée entre mots natifs voisins"
            if gauche and droite and not meme_ligne:
                note += " -- ancres sur lignes différentes, prolongation depuis l'ancre gauche"
            elif not (gauche and droite):
                note += " -- ancre unique disponible"

            mot.notes.append(note)
            x += largeur_mot


def resoudre_page(unites: list) -> list:
    """Transforme une liste de UniteAlignement en liste de Word prête pour
    page.resolved.words."""
    resultat = []

    for unite in unites:
        if unite.type == "equal":
            resultat.append(unite.native)

        elif unite.type == "conflit":
            resultat.append(_resoudre_conflit(unite))

        elif unite.type == "natif_seul":
            mot = unite.native
            if confidence.confiance_native(mot) < 0.5:
                mot.notes.append(
                    "mot natif sans correspondance OCR et de confiance heuristique "
                    "faible -- à vérifier manuellement"
                )
            resultat.append(mot)

        elif unite.type == "ocr_seul":
            # PROBLÈME OUVERT, documenté plutôt que masqué : ce mot n'existe
            # que côté OCR, donc SANS bbox (Mistral ne fournit pas de bbox
            # au niveau mot, cf. ocr.py). Tous les renderers actuels
            # (faithful_pdf via _grouper_mots_en_lignes, markdown, html)
            # filtrent sur `if w.bbox` -- un Word sans bbox y est donc
            # aujourd'hui silencieusement invisible. On l'ajoute quand même
            # à resolved.words pour ne pas perdre l'information dans le
            # modèle de données, mais ce cas n'est PAS résolu tant qu'une
            # stratégie de positionnement approximatif (ex. interpolation
            # entre le mot natif précédent et le mot natif suivant) n'a pas
            # été décidée et implémentée dans les renderers concernés.
            mot = Word(
                id=-1,  # ré-attribué par resolve/__init__.py / compiler.py (renumérotation finale)
                text=unite.ocr.text,
                resolved_text=unite.ocr.text,
                bbox=None,  # Sera calculé dans _interpoler_bboxes ci-dessous
                reconstructed=True,
                source="ocr",
                confidence=unite.ocr.confidence,
                notes=["mot présent uniquement en OCR -- en attente d'interpolation de bbox"],
            )
            resultat.append(mot)

    # Passe secondaire pour calculer les bbox manquantes des mots ocr_seul
    _interpoler_bboxes(resultat)

    return resultat