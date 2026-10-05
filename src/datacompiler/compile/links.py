"""links.py -- rattache les mots résolus d'une page à ses liens cliquables.

Le texte sous un lien est souvent vectorisé (« La notice de cet avis est disponible en cliquant
ici… » sur l'avis d'impôt) : il est lu par OCR comme les autres zones vectorielles, puis
associé ici au LinkElement correspondant, par position. La zone cliquable d'origine (link.bbox)
n'est PAS modifiée : le rendu PDF remet l'annotation exactement où elle était.

Un mot appartient à un lien si son CENTRE tombe dans link.bbox. link.word_ids est dans l'ordre
de lecture (ordre de page.resolved.words) et sert, côté traduction, à garder le lien attaché au
segment qui contient ces mots.
"""


def associer_liens(page) -> None:
    for lien in page.links:
        lien.word_ids = []
        if lien.bbox is None:
            continue
        for mot in page.resolved.words:
            if mot.bbox is None:
                continue
            cx = (mot.bbox.x0 + mot.bbox.x1) / 2
            cy = (mot.bbox.y0 + mot.bbox.y1) / 2
            if lien.bbox.x0 <= cx <= lien.bbox.x1 and lien.bbox.y0 <= cy <= lien.bbox.y1:
                lien.word_ids.append(mot.id)
