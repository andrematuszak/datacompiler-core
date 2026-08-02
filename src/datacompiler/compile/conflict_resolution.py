"""conflict_resolution.py — Décide, pour chaque UniteAlignement produite par
alignment.py, quel texte final retenir dans page.resolved.words.

Règle de base : la bbox vient TOUJOURS du mot natif quand il existe (seul
des deux à en avoir une, cf. alignment.py) -- un conflit ne fait jamais
perdre le positionnement, seulement potentiellement le texte.
"""

from datacompiler.model.document import Word, Decision

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
                id=-1,  # ré-attribué par resolve/__init__.py (renumérotation finale)
                text=unite.ocr.text,
                resolved_text=unite.ocr.text,
                bbox=None,
                reconstructed=True,
                source="ocr",
                confidence=unite.ocr.confidence,
                notes=["mot présent uniquement en OCR -- bbox indisponible, non positionné"],
            )
            resultat.append(mot)

    return resultat
