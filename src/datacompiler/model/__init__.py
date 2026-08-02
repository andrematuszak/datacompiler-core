"""model/ — Façade : réexporte tout ce que document.py, geometry.py,
typography.py et metadata.py définissent, pour que le reste du projet
continue d'écrire `from model import Document, Word, BBox, ...` sans avoir
à savoir dans quel sous-module chaque classe vit réellement."""

from .geometry import BBox, Polygon
from .typography import Font
from .metadata import Metadata, Diagnostic
from .document import (
    Document, Page, Word, Decision,
    NativeContainer, GraphicsContainer, OcrContainer, ResolvedContainer,
    ImageElement, TableElement, GraphicVector, OcrBlock,
)


