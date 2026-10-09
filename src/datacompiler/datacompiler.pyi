# Interface publique de DataCompiler 0.1.0 (stub de typage).
# Ce fichier décrit l'API utilisable ; il ne contient aucune implémentation.
from os import PathLike
from typing import Any, Dict, List, Literal, Optional, Union

__version__: str

# Stratégies de rendu acceptées par executer_pipeline().
# Note : en ligne de commande, --strategy n'accepte pour l'instant que
# overlay, clean_overlay, rasterized, flow et rebuilt.
Strategy = Literal[
    "overlay", "clean_overlay", "rasterized", "flow", "rebuilt",
    "markdown", "html", "docx",
]
OcrMode = Literal["auto", "force", "skip", "vector"]

# Extension du fichier produit pour chaque stratégie ("pdf", "md", "html", "docx").
EXTENSIONS: Dict[str, str]

class Metadata:
    filename: str
    source_pdf: str
    page_count: int
    producer: str
    creator: str
    creation_date: str
    modification_date: str
    pdf_version: str
    encrypted: bool

class Diagnostic:
    has_native_text: bool
    has_images: bool
    has_tables: bool
    has_full_page_images: bool
    embedded_ocr_detected: bool
    reading_order_score: Optional[float]
    native_text_quality: Optional[float]
    native_text_coverage: Optional[float]
    image_quality: Optional[float]
    recommend_ocr: bool
    recommend_full_ocr: bool
    notes: List[str]
    ocr_reasons: List[str]
    encrypted: bool
    suspect_producer: Optional[str]
    low_dpi_images_detected: bool
    overlapping_text_detected: bool
    out_of_bounds_detected: bool
    empty_pages: List[int]

class Page:
    number: int
    width: float
    height: float
    rotation: float
    diagnostic: Diagnostic

class Document:
    metadata: Metadata
    diagnostic: Diagnostic
    pages: List[Page]
    def to_dict(self) -> Dict[str, Any]: ...
    def to_json(self) -> str: ...
    def save(self, path: str) -> None: ...
    @classmethod
    def load(cls, path: str) -> "Document": ...
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Document": ...

def executer_pipeline(
    pdf_path: Union[str, "PathLike[str]"],
    strategy: Strategy = "overlay",
    sauver_json: bool = True,
    dpi: int = 300,
    dpi_ocr_vectoriel: int = 300,
    paddle_lang: str = "fr",
    ocr_mode: OcrMode = "auto",
) -> Document: ...

def main() -> None: ...
