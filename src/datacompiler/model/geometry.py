"""Provide dependency-free spatial primitives used by the rest of the document model."""

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
    """Represent a non-rectangular region, such as curved OCR text or a rotated block."""
    points: List[tuple] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: Optional[Dict[str, Any]]) -> Optional["Polygon"]:
        return cls(points=[tuple(p) for p in value["points"]]) if value else None

