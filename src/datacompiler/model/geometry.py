"""geometry.py — Primitives spatiales pures, sans dépendance vers le reste
du modèle."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float

    @classmethod
    def from_dict(cls, value: Optional[Dict[str, Any]]) -> Optional["BBox"]:
        return cls(**value) if value else None


@dataclass
class Polygon:
    """Forme non rectangulaire (région OCR incurvée, bloc pivoté...).
    Squelette en attente d'un cas d'usage réel -- pas encore consommé
    par extract.py, ocr/ ni compile/. Même prudence que la limite de
    détection de colonnes documentée dans compile/reading_order.py :
    pas de champs inventés tant qu'un test réel n'en précise le besoin."""
    points: List[tuple] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: Optional[Dict[str, Any]]) -> Optional["Polygon"]:
        return cls(points=[tuple(p) for p in value["points"]]) if value else None

