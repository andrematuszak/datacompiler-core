"""Store plain typographic metadata. This module describes font data; transformations live in ``compile.typography``."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Font:
    name: str
    sizes: List[float] = field(default_factory=list)
    is_bold: bool = False
    is_italic: bool = False
    is_serif: bool = False
    is_monospace: bool = False
    is_condensed: bool = False
    generic_family: str = "sans-serif"
