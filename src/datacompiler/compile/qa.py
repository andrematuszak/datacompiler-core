"""qa.py — Détection d'anomalies post-résolution : ANNOTE resolved.words
(champ .flags), ne modifie jamais texte ni bbox. Chaque sous-vérification
est indépendante et n'est activée que si elle a une base fiable pour
fonctionner.

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

def _ordre_suspect(mots: list, seuil_regression: float = 50.0) -> None:
    """Détecte les sauts arrière significatifs dans l'ordre de sortie final
    (resolved.words) : un mot dont le y0 retombe nettement en dessous du
    maximum déjà atteint plus tôt dans la séquence.

    CANARI, pas un correctif : indépendant du travail en cours sur
    reading_order.py (colonnes vs blocs). Reste utile même après cette
    correction, comme filet de non-régression permanent sur tout le corpus
    -- pas seulement pour le cas déjà identifié à la main sur
    test-impots-revenu.

    LIMITE CONNUE : va se déclencher aussi sur un vrai document multi-
    colonnes légitime (le passage colonne gauche -> colonne droite EST un
    saut arrière en y). Tant que reading_order.py ne distingue pas
    colonnes réelles et blocs séquentiels, ce flag doit être lu comme "à
    vérifier", pas comme une preuve de bug -- à recalibrer une fois cette
    distinction en place côté reading_order.py."""
    max_y_vu = None
    for mot in mots:
        if not mot.bbox:
            continue
        if max_y_vu is not None and mot.bbox.y0 < max_y_vu - seuil_regression:
            mot.flags.append(Flag(
                type="ordre_suspect",
                detail=f"y0={mot.bbox.y0:.0f} après un maximum déjà atteint de {max_y_vu:.0f} "
                       f"-- saut arrière possible dans l'ordre de lecture",
                severity="warning",
            ))
        max_y_vu = mot.bbox.y0 if max_y_vu is None else max(max_y_vu, mot.bbox.y0)


def annoter(mots: list) -> list:
    """Point d'entrée : annote `mots` (resolved.words) en place, retourne
    la même liste -- convention identique à conflict_resolution.resoudre_page."""
    _confiance_basse(mots)
    _ordre_suspect(mots)
    return mots