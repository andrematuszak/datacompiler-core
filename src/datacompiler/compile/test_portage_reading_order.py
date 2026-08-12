"""Auto-test minimal du portage boîtes/rangées dans reading_order.py, avec
des objets factices mimant Word/BBox -- reproduit le cas N5/N21-N26 déjà
corrigé (un bloc PyMuPDF multi-lignes face à une colonne de montants une-
ligne) pour vérifier qu'aucune régression n'a été introduite pendant le
portage, avant tout test sur le vrai document.json.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from . import reading_order as ro


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
    def __init__(self, words, tables=None, width=600.0):
        self.native = Native(words)
        self.graphics = Graphics(tables)
        self.width = width


def _texte(mots):
    return [m.text for m in mots]


# --- Cas 1 : reproduction fidèle du bug N5/N21-N26 --------------------------
# Un seul bloc PyMuPDF (block=5) contenant 3 lignes de libellés empilées,
# face à une colonne de montants (block différent), une ligne chacun.
mots_cas1 = [
    Word("Salaires", 15, 244, 100, 257, block=5),
    Word("Heures", 15, 255, 100, 268, block=5),
    Word("Total", 15, 266, 100, 279, block=5),

    Word("30050", 260, 244, 300, 257, block=6),
    Word("0", 260, 255, 300, 268, block=7),
    Word("30050", 260, 266, 300, 279, block=8),
]

page1 = Page(mots_cas1)
resultat1 = ro.ordonner(page1)
attendu1 = ["Salaires", "30050", "Heures", "0", "Total", "30050"]
assert _texte(resultat1) == attendu1, f"CAS 1 ÉCHEC : {_texte(resultat1)} != {attendu1}"
print("CAS 1 (paragraphe multi-lignes vs colonne de montants) : OK")
print(f"  -> {_texte(resultat1)}")


# --- Cas 2 : mots vectorisés fusionnés en un cluster multi-lignes ----------
# 3 mots vectorisés proches (même cluster union-find) mais sur 2 lignes
# distinctes, face à 2 mots natifs alignés ligne par ligne.
mots_cas2 = [
    Word("Numéro", 21, 281, 60, 288, is_vectorized=True),
    Word("rôle", 21, 292, 60, 299, is_vectorized=True),

    Word("011", 188, 281, 210, 288, block=1),
    Word("099", 188, 292, 210, 299, block=2),
]

page2 = Page(mots_cas2)
resultat2 = ro.ordonner(page2)
attendu2 = ["Numéro", "011", "rôle", "099"]
assert _texte(resultat2) == attendu2, f"CAS 2 ÉCHEC : {_texte(resultat2)} != {attendu2}"
print("CAS 2 (cluster vectorisé multi-lignes vs mots natifs alignés) : OK")
print(f"  -> {_texte(resultat2)}")


# --- Cas 3 : anti-dérive transitive -----------------------------------------
# A et B se chevauchent, B et C se chevauchent, mais A et C ne se chevauchent
# PAS -- ne doivent PAS finir dans la même rangée (bug #3 du docstring).
# x0 de C choisi ENTRE celui de A et B : si (à tort) fusionnés en une seule
# rangée, le tri par x0 donnerait A,C,B -- alors qu'une scission correcte en
# deux rangées ([A,B] puis [C]) donne A,B,C. Sans cet écart de x0, les deux
# scénarios produiraient la même séquence à plat (piège rencontré au premier
# essai de ce test -- corrigé ici).
mots_cas3 = [
    Word("A", 15, 277, 60, 290, block=1),   # y 277-290
    Word("B", 300, 285, 340, 306, block=2),  # y 285-306 (chevauche A: 285-290)
    Word("C", 50, 299, 90, 312, block=3),    # y 299-312 (chevauche B: 299-306, PAS A) -- x0 entre A et B
]

page3 = Page(mots_cas3)
resultat3 = ro.ordonner(page3)
texte3 = _texte(resultat3)
attendu3 = ["A", "B", "C"]  # scission correcte : rangée [A,B] (triée x0) puis rangée [C]
fusion_fautive3 = ["A", "C", "B"]  # si A,B,C fusionnés à tort en une rangée, triés par x0
assert texte3 == attendu3, (
    f"CAS 3 ÉCHEC : {texte3} -- "
    f"{'dérive transitive reproduite (fusion fautive)' if texte3 == fusion_fautive3 else 'résultat inattendu, à investiguer'}"
)
print("CAS 3 (anti-dérive transitive) : OK")
print(f"  -> {texte3}")


# --- Cas 4 : table exclue puis réintégrée -----------------------------------
mots_cas4 = [
    Word("Hors", 15, 10, 60, 23, block=1),
    Word("table", 65, 10, 110, 23, block=1),
    Word("DansTable", 15, 100, 60, 113, block=2),
]
table4 = Table(bbox=BBox(0, 90, 200, 200))
page4 = Page(mots_cas4, tables=[table4])
resultat4 = ro.ordonner(page4)
texte4 = _texte(resultat4)
assert texte4 == ["Hors", "table", "DansTable"], f"CAS 4 ÉCHEC : {texte4}"
print("CAS 4 (exclusion puis réintégration table) : OK")
print(f"  -> {texte4}")

print("\nTous les cas factices passent.")
