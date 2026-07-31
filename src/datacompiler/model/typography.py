"""typography.py — Métadonnées typographiques pures. Homonyme volontaire de
compile/typography.py (données ici, transformations là-bas)."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Font:
    name: str
    sizes: List[float] = field(default_factory=list)


