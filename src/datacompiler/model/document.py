"""document.py — Assemblage du modèle : Word (le nœud central, référencé
depuis native/ocr/resolved), conteneurs de page, Page, Document."""

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .geometry import BBox, Polygon
from .typography import Font
from .metadata import Diagnostic, Metadata


@dataclass
class Decision:
    regle: str
    detail: str = ""


@dataclass
class Word:
    id: int
    text: str
    bbox: Optional[BBox] = None
    block: int = 0
    line: int = 0
    word: int = 0
    font: str = "Unknown"
    font_size: float = 0.0
    bold: bool = False
    italic: bool = False
    color: str = "#000000"
    rotation: float = 0.0
    confidence: Optional[float] = None
    language: Optional[str] = None
    source: Optional[str] = None
    resolved_text: Optional[str] = None
    reconstructed: bool = False
    is_corrected: bool = False
    replacement: Optional[str] = None
    decision: Optional[Decision] = None
    notes: List[str] = field(default_factory=list)

    @property
    def output_text(self) -> str:
        return self.resolved_text or self.replacement or self.text


@dataclass
class NativeContainer:
    words: List[Word] = field(default_factory=list)
    fonts: List[Font] = field(default_factory=list)


@dataclass
class ImageElement:
    id: int
    bbox: Optional[BBox] = None
    width: Optional[int] = None
    height: Optional[int] = None
    source: str = "original_pdf"
    keep_original: bool = True


@dataclass
class TableElement:
    id: int
    bbox: Optional[BBox] = None
    source: str = "pdfplumber"
    rows: List[List[Optional[str]]] = field(default_factory=list)
    keep_original: bool = True


@dataclass
class GraphicVector:
    bbox: Optional[BBox] = None
    keep_original: bool = True


@dataclass
class GraphicsContainer:
    images: List[ImageElement] = field(default_factory=list)
    tables: List[TableElement] = field(default_factory=list)
    lines: List[GraphicVector] = field(default_factory=list)
    rects: List[GraphicVector] = field(default_factory=list)
    curves: List[GraphicVector] = field(default_factory=list)


@dataclass
class OcrBlock:
    bbox: Optional[BBox] = None
    type: str = "text"
    content: str = ""


@dataclass
class OcrContainer:
    engine: Optional[str] = None
    words: List[Word] = field(default_factory=list)
    blocks: List[OcrBlock] = field(default_factory=list)


@dataclass
class ResolvedContainer:
    words: List[Word] = field(default_factory=list)
    images: List[ImageElement] = field(default_factory=list)
    tables: List[TableElement] = field(default_factory=list)


@dataclass
class Page:
    number: int
    width: float
    height: float
    rotation: float = 0.0
    diagnostic: Diagnostic = field(default_factory=Diagnostic)
    native: NativeContainer = field(default_factory=NativeContainer)
    graphics: GraphicsContainer = field(default_factory=GraphicsContainer)
    ocr: OcrContainer = field(default_factory=OcrContainer)
    resolved: ResolvedContainer = field(default_factory=ResolvedContainer)


@dataclass
class Document:
    metadata: Metadata = field(default_factory=Metadata)
    diagnostic: Diagnostic = field(default_factory=Diagnostic)
    pages: List[Page] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("diagnostic", None)
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.to_json())

    @classmethod
    def load(cls, path: str) -> "Document":
        with open(path, encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Document":
        def decision(d):
            if not d:
                return None
            return Decision(**{k: v for k, v in d.items() if k in Decision.__dataclass_fields__})

        def word(d):
            d = dict(d)
            d["bbox"] = BBox.from_dict(d.get("bbox"))
            d["decision"] = decision(d.get("decision"))
            return Word(**{k: v for k, v in d.items() if k in Word.__dataclass_fields__})

        def page_diagnostic(d):
            if not d:
                return Diagnostic()
            return Diagnostic(**{k: v for k, v in d.items() if k in Diagnostic.__dataclass_fields__})
        def image(d):
            d = dict(d); d["bbox"] = BBox.from_dict(d.get("bbox"))
            return ImageElement(**{k: v for k, v in d.items() if k in ImageElement.__dataclass_fields__})
        def table(d):
            d = dict(d); d["bbox"] = BBox.from_dict(d.get("bbox"))
            return TableElement(**{k: v for k, v in d.items() if k in TableElement.__dataclass_fields__})
        pages = []
        for raw in data.get("pages", []):
            native = raw.get("native", {})
            graphics = raw.get("graphics", {})
            ocr = raw.get("ocr", {})
            resolved = raw.get("resolved", {})
            page = Page(number=raw["number"], width=raw["width"], height=raw["height"], rotation=raw.get("rotation", 0.0))
            page.diagnostic = page_diagnostic(raw.get("diagnostic", {}))
            page.native = NativeContainer(words=[word(x) for x in native.get("words", [])], fonts=[Font(**x) for x in native.get("fonts", [])])
            page.graphics = GraphicsContainer(images=[image(x) for x in graphics.get("images", [])], tables=[table(x) for x in graphics.get("tables", [])])
            page.ocr = OcrContainer(engine=ocr.get("engine"), words=[word(x) for x in ocr.get("words", [])], blocks=[OcrBlock(BBox.from_dict(x.get("bbox")), x.get("type", "text"), x.get("content", "")) for x in ocr.get("blocks", [])])
            page.resolved = ResolvedContainer(words=[word(x) for x in resolved.get("words", [])], images=[image(x) for x in resolved.get("images", [])], tables=[table(x) for x in resolved.get("tables", [])])
            pages.append(page)
        metadata = Metadata(**{k: v for k, v in data.get("metadata", {}).items() if k in Metadata.__dataclass_fields__})
        diagnostic = Diagnostic(**{k: v for k, v in data.get("diagnostic", {}).items() if k in Diagnostic.__dataclass_fields__})
        return cls(metadata=metadata, diagnostic=diagnostic, pages=pages)


