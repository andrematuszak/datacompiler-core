"""metadata.py — Informations descriptives au niveau document : provenance
du fichier (Metadata) et résultat du diagnostic (Diagnostic). Ni l'une ni
l'autre ne référence Word/Page."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Metadata:
    filename: str = ""
    source_pdf: str = ""
    page_count: int = 0
    producer: str = ""
    creator: str = ""
    creation_date: str = ""
    modification_date: str = ""
    pdf_version: str = ""
    encrypted: bool = False


@dataclass
class Diagnostic:
    has_native_text: bool = False
    has_images: bool = False
    has_tables: bool = False
    has_full_page_images: bool = False
    embedded_ocr_detected: bool = False
    reading_order_score: Optional[float] = None
    native_text_quality: Optional[float] = None
    native_text_coverage: Optional[float] = None
    image_quality: Optional[float] = None
    # OCR ciblé : vecteurs, images avec texte, ou texte natif dégradé.
    recommend_ocr: bool = False
    # OCR page entière : réservé aux scans / pages images, jamais à une
    # page hybride dont seules quelques zones doivent être enrichies.
    recommend_full_ocr: bool = False
    notes: List[str] = field(default_factory=list)
    ocr_reasons: List[str] = field(default_factory=list)
    encrypted: bool = False
    suspect_producer: Optional[str] = None
    low_dpi_images_detected: bool = False
    overlapping_text_detected: bool = False
    out_of_bounds_detected: bool = False
    empty_pages: List[int] = field(default_factory=list)
    confiance_suffisante: Optional[bool] = None
    symboles_suspects: Dict[str, int] = field(default_factory=dict)
    mots_suspects_ngrammes: List[Any] = field(default_factory=list)
    categorie: Optional[str] = None
    vectorized_text_detected: bool = False
    has_images_with_text: Optional[bool] = None


