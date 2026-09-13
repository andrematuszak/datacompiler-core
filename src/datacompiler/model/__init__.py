"""model/ — Façade : réexporte tout ce que document.py, geometry.py,
typography.py et metadata.py définissent, pour que le reste du projet
continue d'écrire `from model import Document, Word, BBox, ...` sans avoir
à savoir dans quel sous-module chaque classe vit réellement."""

from datacompiler.model.geometry import BBox, Polygon
from datacompiler.model.font import Font  # Ajouter ici d'éventuelles nouvelles classes (ex: FontFamily)
from datacompiler.model.metadata import Metadata, Diagnostic
from datacompiler.model.document import (
    Document, Page, Word, Decision, Flag,
    NativeContainer, GraphicsContainer, OcrContainer, ResolvedContainer,
    ImageElement, TableElement, GraphicVector, OcrBlock,
)
