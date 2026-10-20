"""Public type declarations for DataCompiler."""

from os import PathLike
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Union

__version__: Literal["0.2.0"]
__all__: List[str]

# Rendering strategies accepted by executer_pipeline().
Strategy = Literal[
    "overlay", "clean_overlay", "rasterized", "flow", "rebuilt",
    "markdown", "html", "docx", "faithful-pdf",
]
# "force" is recognized but raises NotImplementedError; full-page OCR is not
# implemented in this release.
OcrMode = Literal["auto", "force", "skip", "vector"]

EXTENSIONS: Dict[str, str]
FORMATS: Dict[str, Callable[..., Any]]

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
    confiance_suffisante: Optional[bool]
    symboles_suspects: Dict[str, int]
    mots_suspects_ngrammes: List[Any]
    categorie: Optional[str]
    vectorized_text_detected: bool
    has_images_with_text: Optional[bool]
    recommend_segmentation: bool
    segmentation_reasons: List[str]

class BBox:
    x0: float
    y0: float
    x1: float
    y1: float

class Polygon:
    points: List[Tuple[float, float]]

class Font:
    name: str
    sizes: List[float]
    is_bold: bool
    is_italic: bool
    is_serif: bool
    is_monospace: bool
    is_condensed: bool
    generic_family: str

class Decision:
    regle: str
    detail: str

class Flag:
    type: str
    detail: str
    severity: str

class Word:
    id: int
    text: str
    bbox: Optional[BBox]
    block: int
    line: int
    word: int
    font: str
    font_size: float
    bold: bool
    italic: bool
    color: str
    rotation: float
    confidence: Optional[float]
    language: Optional[str]
    source: Optional[str]
    resolved_text: Optional[str]
    reconstructed: bool
    is_corrected: bool
    replacement: Optional[str]
    decision: Optional[Decision]
    notes: List[str]
    is_vectorized: bool
    flags: List[Flag]
    ink_ratio: Optional[float]
    stroke_width: Optional[float]
    source_glyph_bboxes: Tuple[Tuple[float, float, float, float], ...]
    editor_color: Optional[str]
    output_text: str

class Page:
    number: int
    width: float
    height: float
    rotation: float
    diagnostic: Diagnostic
    native: "NativeContainer"
    graphics: "GraphicsContainer"
    ocr: "OcrContainer"
    resolved: "ResolvedContainer"
    layout_root: Optional["LayoutBox"]
    links: List["LinkElement"]
    link_rects: List[Tuple[float, float, float, float]]

class LayoutBox:
    bbox: Optional[BBox]
    type: str
    reading_order: int
    word_ids: List[int]
    children: List["LayoutBox"]
    metadata: Dict[str, Any]

class NativeContainer:
    words: List[Word]
    fonts: List[Font]

class ImageElement:
    id: int
    bbox: Optional[BBox]
    width: Optional[int]
    height: Optional[int]
    source: str
    keep_original: bool
    contains_text: Optional[bool]

class TableElement:
    id: int
    bbox: Optional[BBox]
    source: str
    rows: List[List[Optional[str]]]
    cell_bboxes: List[List[Optional[BBox]]]
    keep_original: bool

class GraphicVector:
    bbox: Optional[BBox]
    keep_original: bool
    color: Optional[str]

class GraphicsContainer:
    images: List[ImageElement]
    tables: List[TableElement]
    lines: List[GraphicVector]
    rects: List[GraphicVector]
    curves: List[GraphicVector]

class LinkElement:
    id: int
    bbox: Optional[BBox]
    kind: str
    uri: Optional[str]
    target_page: Optional[int]
    word_ids: List[int]

class OcrBlock:
    bbox: Optional[BBox]
    type: str
    content: str

class OcrContainer:
    engine: Optional[str]
    words: List[Word]
    blocks: List[OcrBlock]

class ResolvedContainer:
    words: List[Word]
    images: List[ImageElement]
    tables: List[TableElement]
    fonts: List[Font]

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

def extract_document(doc_obj: Document, pdf_path: Union[str, PathLike[str]]) -> Document: ...
def diagnose_document(doc: Document) -> Document: ...
def run_ocr(
    doc: Document,
    pdf_path: Union[str, PathLike[str]],
    backend_name: str = "paddle",
    pages: Optional[List[int]] = None,
    **kwargs: Any,
) -> Document: ...
def resolve_document(doc: Document) -> Document: ...
def display_report(doc: Document) -> None: ...

def extraire(doc_obj: Document, pdf_path: Union[str, PathLike[str]]) -> Document: ...
def diagnostiquer(doc: Document) -> Document: ...
def ocraliser(
    doc: Document,
    pdf_path: Union[str, PathLike[str]],
    backend_name: str = "paddle",
    pages: Optional[List[int]] = None,
    **kwargs: Any,
) -> Document: ...
def resoudre(doc: Document) -> Document: ...

def executer_pipeline(
    pdf_path: Union[str, "PathLike[str]"],
    strategy: Strategy = "rebuilt",
    sauver_json: bool = False,
    dpi: int = 300,
    dpi_ocr_vectoriel: int = 300,
    paddle_lang: Optional[str] = None,
    ocr_mode: OcrMode = "auto",
    render: bool = True,
) -> Document: ...

run_pipeline = executer_pipeline

def main() -> None: ...
