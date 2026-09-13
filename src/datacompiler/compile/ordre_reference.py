"""ordre_mistral.py — Réordonne des mots natifs selon une séquence de
référence externe (typiquement les tokens du markdown Mistral OCR), par
appariement de rang plutôt que par diff de séquences.

Pourquoi pas SequenceMatcher (cf. alignment.py) : un diff LCS ne peut
JAMAIS faire correspondre deux occurrences du même texte dont l'ordre
relatif est inversé entre les deux séquences -- ça violerait sa
contrainte de monotonie. Une transposition locale (deux mots adjacents
échangés -- cas réel rencontré : "majeurs"/"célibataires" sur
test-impots-revenu.pdf) est donc invisible pour un diff, qui la traite
comme un insert+delete sans rapport et laisse l'ordre natif inchangé.
Vérifié empiriquement (prototype à la main) avant d'écrire ce module,
pas supposé.

SCOPE VOLONTAIREMENT LIMITÉ : ce module réordonne des mots natifs déjà
existants. Il n'insère JAMAIS de nouveau contenu depuis la séquence de
référence, même si elle contient des tokens sans correspondance native
(ex. ':' ou '/' détectés par Mistral mais absents du natif) -- ces
tokens de référence restent simplement inutilisés. Insérer du contenu
manquant est un problème différent et plus risqué : c'est la stratégie
d'interpolation de bbox qui avait cassé le rendu la première fois que
Mistral a été branché (texte collé, cf. historique du projet). Ce
module résout l'ORDRE, pas les trous de contenu.
"""

from collections import defaultdict, deque


def ordre_par_correspondance(mots_natifs, tokens_reference, cle_texte=lambda m: m.text):
    """Trie `mots_natifs` selon le rang de leur texte dans
    `tokens_reference` -- la PREMIÈRE occurrence non encore consommée de
    ce texte, dans l'ordre de `tokens_reference` (désambiguïsation des
    doublons par une file FIFO par texte, pas par position dans
    `mots_natifs` -- c'est ce qui permet de corriger une transposition).

    Un mot natif dont le texte n'apparaît dans AUCUN token de référence
    (aucune correspondance, ou doublons épuisés) est poussé en fin de
    liste (rang infini) -- jamais perdu, jamais placé au hasard.

    `cle_texte` : fonction extrayant le texte à comparer depuis un mot
    natif -- par défaut `.text`, personnalisable si la comparaison doit
    se faire sur un texte normalisé (casse, accents) plutôt que le texte
    brut, ce qui sera probablement nécessaire en pratique (accents/casse
    différents entre extraction native et OCR Mistral).

    Ne modifie NI le texte NI la bbox des mots -- seulement leur ordre
    dans la liste retournée (nouvelle liste, mots_natifs non muté)."""
    files_par_texte = defaultdict(deque)
    for j, tok in enumerate(tokens_reference):
        files_par_texte[tok].append(j)

    rangs = {}
    for m in mots_natifs:
        file_ = files_par_texte.get(cle_texte(m))
        rangs[id(m)] = file_.popleft() if file_ else float("inf")

    return sorted(mots_natifs, key=lambda m: rangs[id(m)])
