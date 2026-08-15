"""test_reading_order_regression.py — Suite de non-régression pour
reading_order.py. Consolide les 4 cas factices de test_portage_reading_order.py
et ajoute deux cas issus de vrais bugs rencontrés en production sur
test-impots-revenu.pdf :

  - Cas 5 : reproduit le mécanisme exact de désordre "1 2 Feuillet" /
    "RÉSIDENCE RÉSIDENCE ALTERNÉE NOMBREEXCLUSIVE" observé quand
    simple_sort=True est utilisé -- jitter de y0 de quelques dixièmes de
    point entre mots d'une même ligne visuelle.
  - Cas 6 : garde-fou explicite -- ordonner(page) SANS argument (donc avec
    la valeur par défaut de simple_sort) doit passer par le moteur
    boîtes/rangées, pas par le tri plat. Si ce test échoue un jour, c'est
    que le défaut de simple_sort a changé ou qu'un appel a été modifié
    quelque part en amont -- exactement le type de régression trouvée le
    15/08 dans rebuilt_pdf.py (`ordonner(model_page, simple_sort=True)`
    câblé en dur, moteur boîtes/rangées entièrement court-circuité).

À lancer avant tout commit touchant reading_order.py ou son câblage dans
les renderers (rebuilt_pdf.py, faithful_pdf.py, etc.).
"""

import sys
sys.path.insert(0, ".")
import reading_order as ro


class BBox:
    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1


class Word:
    def __init__(self, text, x0, y0, x1, y1, block=0, is_vectorized=False):
        self.text = text
        self.bbox = BBox(x0, y0, x1, y1)
        self.block = block
        self.is_vectorized = is_vectorized

    def __repr__(self):
        return f"Word({self.text!r})"


class Table:
    def __init__(self, bbox=None):
        self.bbox = bbox


class Graphics:
    def __init__(self, tables=None):
        self.tables = tables or []


class Native:
    def __init__(self, words):
        self.words = words


class Page:
    def __init__(self, words, tables=None):
        self.native = Native(words)
        self.graphics = Graphics(tables)


def _texte(mots):
    return [m.text for m in mots]


echecs = []


def verifier(nom, condition, detail=""):
    marque = "OK" if condition else "ÉCHEC"
    print(f"{nom} : {marque}" + (f"  -- {detail}" if detail and not condition else ""))
    if not condition:
        echecs.append(nom)


# --- Cas 1 : paragraphe multi-lignes vs colonne de montants (bug N5) -------
mots_cas1 = [
    Word("Salaires", 15, 244, 100, 257, block=5),
    Word("Heures", 15, 255, 100, 268, block=5),
    Word("Total", 15, 266, 100, 279, block=5),
    Word("30050", 260, 244, 300, 257, block=6),
    Word("0", 260, 255, 300, 268, block=7),
    Word("30050", 260, 266, 300, 279, block=8),
]
resultat1 = ro.ordonner(Page(mots_cas1))
attendu1 = ["Salaires", "30050", "Heures", "0", "Total", "30050"]
verifier("Cas 1 (paragraphe multi-lignes vs colonne de montants)",
         _texte(resultat1) == attendu1, f"{_texte(resultat1)} != {attendu1}")

# --- Cas 2 : cluster vectorisé multi-lignes vs mots natifs alignés (V12) ---
mots_cas2 = [
    Word("Numéro", 21, 281, 60, 288, is_vectorized=True),
    Word("rôle", 21, 292, 60, 299, is_vectorized=True),
    Word("011", 188, 281, 210, 288, block=1),
    Word("099", 188, 292, 210, 299, block=2),
]
resultat2 = ro.ordonner(Page(mots_cas2))
attendu2 = ["Numéro", "011", "rôle", "099"]
verifier("Cas 2 (cluster vectorisé multi-lignes vs mots natifs alignés)",
         _texte(resultat2) == attendu2, f"{_texte(resultat2)} != {attendu2}")

# --- Cas 3 : anti-dérive transitive ----------------------------------------
mots_cas3 = [
    Word("A", 15, 277, 60, 290, block=1),
    Word("B", 300, 285, 340, 306, block=2),
    Word("C", 50, 299, 90, 312, block=3),
]
resultat3 = ro.ordonner(Page(mots_cas3))
verifier("Cas 3 (anti-dérive transitive)",
         _texte(resultat3) == ["A", "B", "C"], f"{_texte(resultat3)}")

# --- Cas 4 : exclusion puis réintégration de table -------------------------
mots_cas4 = [
    Word("Hors", 15, 10, 60, 23, block=1),
    Word("table", 65, 10, 110, 23, block=1),
    Word("DansTable", 15, 100, 60, 113, block=2),
]
table4 = Table(bbox=BBox(0, 90, 200, 200))
resultat4 = ro.ordonner(Page(mots_cas4, tables=[table4]))
verifier("Cas 4 (exclusion puis réintégration table)",
         _texte(resultat4) == ["Hors", "table", "DansTable"], f"{_texte(resultat4)}")

# --- Cas 5 : jitter de y0 sur une même ligne visuelle -----------------------
# Reproduit le mécanisme exact du bug "1 2 Feuillet" / "RÉSIDENCE RÉSIDENCE
# ALTERNÉE NOMBREEXCLUSIVE" -- des mots visuellement sur la MÊME ligne mais
# avec un y0 qui diffère de quelques dixièmes de point (jitter d'extraction
# réel, pas construit artificiellement pour le test). Un tri plat (y0, x0)
# par mot individuel se fait piéger : "1"/"2" (y0=44.7) trient avant
# "Feuillet" (y0=45.0) alors qu'ils sont visuellement APRÈS.
mots_cas5 = [
    Word("Feuillet", 500, 45.0, 545, 58.0, block=1),
    Word("1", 560, 44.7, 566, 57.7, block=1),
    Word("2", 575, 44.7, 581, 57.7, block=1),
]
resultat5 = ro.ordonner(Page(mots_cas5))
attendu5 = ["Feuillet", "1", "2"]
verifier("Cas 5 (jitter y0 même ligne -- reproduction bug 'Feuillet 1 2')",
         _texte(resultat5) == attendu5, f"{_texte(resultat5)} != {attendu5}")

# --- Cas 6 : garde-fou anti-simple_sort --------------------------------------
# ordonner(page) SANS argument doit passer par le moteur boîtes/rangées.
# On vérifie sur le Cas 5 (le plus discriminant : simple_sort=True donne un
# résultat DIFFÉRENT et FAUX sur ce cas précis) que le défaut se comporte
# bien comme le moteur boîtes/rangées, PAS comme le tri plat.
resultat6_defaut = ro.ordonner(Page(mots_cas5))
resultat6_simple = ro.ordonner(Page(mots_cas5), simple_sort=True)
verifier("Cas 6a (ordonner() par défaut == moteur boîtes/rangées)",
         _texte(resultat6_defaut) == attendu5, f"{_texte(resultat6_defaut)} != {attendu5}")
verifier("Cas 6b (simple_sort=True donne un résultat différent -- confirme le piège)",
         _texte(resultat6_simple) != attendu5,
         f"simple_sort=True donne {_texte(resultat6_simple)} -- si égal à {attendu5}, "
         f"soit le cas ne discrimine plus, soit simple_sort a été corrigé (auquel cas "
         f"ce test devient obsolète et peut être retiré)")

print()
if echecs:
    print(f"{len(echecs)} ÉCHEC(S) : {echecs}")
    sys.exit(1)
else:
    print("Tous les cas passent.")
