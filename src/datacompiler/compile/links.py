"""Associate resolved words with clickable links using source link geometry. Link text can be vectorized, so matching uses geometry and tolerates small extraction differences."""


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
