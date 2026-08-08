"""qa.py — Détection d'anomalies post-résolution : ANNOTE resolved.words
(champ .flags), ne modifie jamais texte ni bbox. Chaque sous-vérification
est indépendante et n'est activée que si elle a une base fiable pour
fonctionner.

Point 1 (confiance basse) seul implémenté ici : lit un champ déjà présent
sur Word, ne dépend d'aucun ordre ni regroupement -- fiable dès maintenant.

Points différés, PAS oubliés -- dépendent tous d'un ordre/regroupement
stable que reading_order.py ne garantit pas encore (cf.
_colonnes_depuis_fragments, correction en cours) :
  - motifs de corruption connus (ex. €->e, CMap corrompu) : nécessite un
    dictionnaire fr + catalogue de substitutions, risque de faux positifs
    élevé sur identifiants/sigles/noms propres -- calibration séparée
    avant activation, pas un simple ajout.
  - incohérence de valeurs répétées (numéro fiscal/montant/date identiques
    en théorie mais divergents entre deux occurrences) : nécessite de
    regrouper fiablement les occurrences d'un même champ, donc un ordre de
    lecture stable en amont.
  - duplication signalée explicitement (flag duplique_de: <id>) : la
    session du [date] a montré plusieurs faux positifs de ce type
    (KENNEDY, ORLEANS, PUBLIQUES -- occurrences légitimes différentes prises
    pour des doublons) tant que l'ordre/regroupement n'est pas fiable.
"""

from datacompiler.model.document import Flag

# Valeur de départ arbitraire, non calibrée -- cf. roadmap (étape
# calibration confidence vs exactitude réelle sur échantillon annoté).
SEUIL_CONFIANCE_A_VERIFIER = 0.6


def _confiance_basse(mots: list) -> None:
    """Ajoute un Flag 'confiance_basse' aux mots dont confidence est
    renseignée et sous le seuil. Strictement additif sur mot.flags --
    mot.text/mot.output_text ne sont jamais touchés."""
    for mot in mots:
        if mot.confidence is not None and mot.confidence < SEUIL_CONFIANCE_A_VERIFIER:
            mot.flags.append(Flag(
                type="confiance_basse",
                detail=f"confidence={mot.confidence:.2f} < seuil {SEUIL_CONFIANCE_A_VERIFIER}",
                severity="warning",
            ))


def annoter(mots: list) -> list:
    """Point d'entrée : annote `mots` (resolved.words) en place, retourne
    la même liste -- convention identique à conflict_resolution.resoudre_page."""
    _confiance_basse(mots)
    return mots