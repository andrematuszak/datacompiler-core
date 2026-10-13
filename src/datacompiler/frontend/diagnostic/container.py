"""Inspect PDF container metadata rather than extracted page content. Suspicious producer rules remain empty until supported by evidence from real documents."""

from typing import Optional

PRODUCTEURS_SUSPECTS = set()


def producteur_suspect(doc) -> Optional[str]:
    producer = (doc.metadata.producer or "").strip()
    creator = (doc.metadata.creator or "").strip()
    for nom in PRODUCTEURS_SUSPECTS:
        if nom.lower() in producer.lower() or nom.lower() in creator.lower():
            return producer or creator
    return None

