"""XLIFF 1.2 exchange for stable, reading-order text segments."""

from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from datacompiler.compile.layout import grouper_par_ligne
from datacompiler.model.document import Document
from .language import detect_language

NS = "urn:oasis:names:tc:xliff:document:1.2"
ET.register_namespace("", NS)


@dataclass
class TranslationUnit:
    """A translatable line and the references needed to map it back to a PDF."""

    id: str
    page: int
    word_ids: list[int]
    source: str
    target: str | None = None
    source_language: str | None = None
    quality_score: float | None = None
    quality_model: str | None = None
    review_recommended: bool = False
    provider: str | None = None
    block_id: str | None = None
    human_reviewed: bool = False


@dataclass
class XliffTranslation:
    """Imported target text keyed by stable unit ID, with source metadata."""

    source_language: str | None
    target_language: str
    units: dict[str, TranslationUnit]


@dataclass
class TranslationApplication:
    """Summary of target units applied to a translated document copy."""

    document: Document
    translated_units: list[str]
    missing_units: list[str]
    layout_warnings: list[str] = field(default_factory=list)


def _tag(name: str) -> str:
    return f"{{{NS}}}{name}"


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


def _bbox_of_words(words):
    boxes = [word.bbox for word in words if word.bbox]
    if not boxes:
        return None
    return (
        min(box.x0 for box in boxes), min(box.y0 for box in boxes),
        max(box.x1 for box in boxes), max(box.y1 for box in boxes),
    )


def _block_for_line(page, line, line_number):
    """Find a table/vector layout region, or fall back to the native PDF block."""
    bounds = _bbox_of_words(line)
    if bounds:
        cx, cy = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        for table in page.graphics.tables:
            for row_index, row in enumerate(table.cell_bboxes):
                for column_index, cell in enumerate(row):
                    if cell and cell.x0 <= cx <= cell.x1 and cell.y0 <= cy <= cell.y1:
                        return f"p{page.number}-t{table.id}-r{row_index}-c{column_index}"
        root = page.layout_root
        for box in sorted(getattr(root, "children", []), key=lambda item: item.bbox.x1-item.bbox.x0 if item.bbox else float("inf")):
            region = box.bbox
            if (box.type == "vector_zone" and region
                    and region.x0 <= cx <= region.x1 and region.y0 <= cy <= region.y1):
                region_id = box.metadata.get("id") or "zone{}".format(box.reading_order)
                return f"p{page.number}-{region_id}"
    if line and all(
        word.source == "native" and word.block == line[0].block for word in line
    ):
        return f"p{page.number}-b{line[0].block}"
    return f"p{page.number}-l{line_number}"


def _split_line_by_table_cells(page, line):
    """Split a visual line into cell-local word groups when it crosses a table."""
    table_cells = []
    for table in page.graphics.tables:
        for row_index, row in enumerate(table.cell_bboxes):
            for column_index, cell in enumerate(row):
                if cell:
                    table_cells.append((
                        f"p{page.number}-t{table.id}-r{row_index}-c{column_index}",
                        cell,
                    ))
    if not table_cells:
        return [(line, None)]

    groups = []
    current_key = None
    current_words = []
    for word in line:
        box = word.bbox
        center = ((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2) if box else None
        cell_id = None
        if center:
            matches = [
                key for key, cell in table_cells
                if cell.x0 <= center[0] <= cell.x1 and cell.y0 <= center[1] <= cell.y1
            ]
            if matches:
                cell_id = matches[0]

        # Preserve the line as a whole if table geometry did not locate any
        # word. Otherwise keep consecutive words in each cell together.
        key = cell_id if cell_id is not None else f"unassigned-{len(groups)}"
        if current_words and key != current_key:
            groups.append((current_words, current_key if not current_key.startswith("unassigned-") else None))
            current_words = []
        current_key = key
        current_words.append(word)
    if current_words:
        groups.append((current_words, current_key if not current_key.startswith("unassigned-") else None))

    if not any(cell_id for _, cell_id in groups):
        return [(line, None)]
    return groups


def build_translation_units(document: Document) -> list[TranslationUnit]:
    """Build one segment per resolved visual line."""
    result = []
    for page in document.pages:
        words = page.resolved.words
        if not words:
            continue
        groups = grouper_par_ligne(words)
        # JSON round-trips do not preserve the transient layout_line attribute.
        # In that case, split by vertical position while keeping original order.
        if len(groups) == 1 and len(words) > 1 and not hasattr(words[0], "layout_line"):
            groups = []
            current = []
            y0 = None
            for word in words:
                y = word.bbox.y0 if word.bbox else y0
                if current and y is not None and y0 is not None and abs(y-y0) > 3:
                    groups.append(current)
                    current = []
                current.append(word)
                if y is not None:
                    y0 = y
            if current:
                groups.append(current)
        line_number = 0
        for line in groups:
            for segment, cell_id in _split_line_by_table_cells(page, line):
                source = " ".join((word.output_text or "").strip() for word in segment).strip()
                if not source:
                    continue
                line_number += 1
                languages = [word.language for word in segment if word.language]
                language = languages[0] if languages and len(set(languages)) == 1 else None
                if not language and len(source.split()) >= 5:
                    try:
                        language = detect_language(source)
                    except RuntimeError:
                        # Explicit source-language still permits XLIFF export
                        # without installing the optional detection dependency.
                        pass
                result.append(TranslationUnit(
                    id=f"p{page.number}-l{line_number}", page=page.number,
                    word_ids=[word.id for word in segment], source=source,
                    source_language=language,
                    block_id=cell_id or _block_for_line(page, segment, line_number),
                ))
    return result


def _layout_block_bounds(document: Document) -> dict[str, tuple[float, float]]:
    """Return horizontal bounds for recognized table cells and vector regions."""
    bounds = {}
    for page in document.pages:
        for table in page.graphics.tables:
            for row_index, row in enumerate(table.cell_bboxes):
                for column_index, cell in enumerate(row):
                    if cell:
                        bounds[f"p{page.number}-t{table.id}-r{row_index}-c{column_index}"] = (
                            cell.x0, cell.y0, cell.x1, cell.y1,
                        )
        for box in getattr(page.layout_root, "children", []):
            if box.type == "vector_zone" and box.bbox:
                region_id = box.metadata.get("id") or "zone{}".format(box.reading_order)
                key = f"p{page.number}-{region_id}"
                bounds[key] = (box.bbox.x0, box.bbox.y0, box.bbox.x1, box.bbox.y1)
    return bounds


def export_xliff(
    document: Document,
    path: str | Path,
    *,
    target_language: str,
    source_language: str | None = None,
) -> list[TranslationUnit]:
    """Write an XLIFF 1.2 file and return the exact exported units.

    Source language is taken from the explicit argument, unanimous per-word
    metadata, or optional automatic detection over the document text.
    """
    units = build_translation_units(document)
    if not source_language:
        known = {u.source_language for u in units if u.source_language}
        source_language = next(iter(known)) if len(known) == 1 else None
    if not source_language:
        source_language = detect_language(" ".join(u.source for u in units))
    if not source_language:
        raise ValueError(
            "Could not determine source language; pass source_language (for "
            "example 'fr') or install datacompiler[language]."
        )

    root = ET.Element(_tag("xliff"), {"version": "1.2"})
    file_node = ET.SubElement(root, _tag("file"), {
        "source-language": source_language,
        "target-language": target_language,
        "datatype": "plaintext",
        "original": str(document.metadata.filename or "document"),
    })
    body = ET.SubElement(file_node, _tag("body"))
    for unit in units:
        tu = ET.SubElement(body, _tag("trans-unit"), {
            "id": _safe_id(unit.id), "approved": "no",
        })
        ET.SubElement(tu, _tag("source")).text = unit.source
        note = ET.SubElement(tu, _tag("note"), {"from": "DataCompiler"})
        note.text = (
            f"page={unit.page}; word_ids={','.join(map(str, unit.word_ids))}; "
            f"block_id={unit.block_id or unit.id}"
        )
    tree = ET.ElementTree(root)
    if hasattr(ET, "indent"):
        ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return units


def import_xliff(
    path: str | Path,
    *,
    expected_units: list[TranslationUnit] | None = None,
) -> XliffTranslation:
    """Read target segments, validating their source IDs when supplied.

    DTD/entity declarations are rejected before parsing. Units without targets
    are retained with ``target=None`` so an automatic provider can fill them.
    Source text is never modified by this function.
    """
    raw = Path(path).read_bytes()
    if re.search(br"<!\s*(DOCTYPE|ENTITY)\b", raw, flags=re.IGNORECASE):
        raise ValueError("XLIFF with DTD or entity declarations is not accepted")
    root = ET.fromstring(raw)
    if root.tag != _tag("xliff") or root.get("version") != "1.2":
        raise ValueError("Expected an XLIFF 1.2 document")
    file_node = root.find(_tag("file"))
    if file_node is None:
        raise ValueError("XLIFF document has no file element")
    target_language = file_node.get("target-language")
    if not target_language:
        raise ValueError("XLIFF file is missing target-language")
    known = {unit.id: unit for unit in (expected_units or [])}
    imported: dict[str, TranslationUnit] = {}
    body = file_node.find(_tag("body"))
    for tu in body.findall(_tag("trans-unit")) if body is not None else []:
        unit_id = tu.get("id")
        if not unit_id:
            raise ValueError("XLIFF trans-unit is missing its id")
        if expected_units is not None and unit_id not in known:
            raise ValueError(f"Unknown XLIFF unit id: {unit_id}")
        source_node = tu.find(_tag("source"))
        target_node = tu.find(_tag("target"))
        source_text = "".join(source_node.itertext()) if source_node is not None else ""
        if unit_id in known and source_text != known[unit_id].source:
            raise ValueError(f"Source text changed for XLIFF unit {unit_id}")
        original = known.get(unit_id)
        page_number, word_ids = (original.page, list(original.word_ids)) if original else (0, [])
        if original is None:
            note_node = tu.find(_tag("note"))
            note = (note_node.text or "") if note_node is not None else ""
            page_match = re.search(r"(?:^|;\s*)page=(\d+)", note)
            words_match = re.search(r"(?:^|;\s*)word_ids=([\d,]*)", note)
            block_match = re.search(r"(?:^|;\s*)block_id=([A-Za-z0-9_.-]+)", note)
            if page_match:
                page_number = int(page_match.group(1))
            if words_match:
                word_ids = [int(value) for value in words_match.group(1).split(",") if value]
        if unit_id in imported:
            raise ValueError(f"Duplicate XLIFF unit id: {unit_id}")
        note_texts = [n.text or "" for n in tu.findall(_tag("note"))]
        quality_match = next((re.search(r"quality_score=([0-9]*\.?[0-9]+)", note) for note in note_texts
                              if "quality_score=" in note), None)
        review_match = next((re.search(r"review_recommended=(true|false)", note, re.I) for note in note_texts
                             if "review_recommended=" in note), None)
        provider_match = next((re.search(r"provider=([A-Za-z0-9_.-]+)", note) for note in note_texts
                               if "provider=" in note), None)
        model_match = next((re.search(r"quality_model=([A-Za-z0-9_./-]+)", note)
                            for note in note_texts if "quality_model=" in note), None)
        human_review_match = next((re.search(r"human_reviewed=(true|false)", note, re.I)
                                   for note in note_texts if "human_reviewed=" in note), None)
        imported[unit_id] = TranslationUnit(
            id=unit_id,
            page=page_number,
            word_ids=word_ids,
            source=source_text,
            target=("".join(target_node.itertext())
                    if target_node is not None and "".join(target_node.itertext()).strip()
                    else None),
            source_language=file_node.get("source-language"),
            quality_score=float(quality_match.group(1)) if quality_match else None,
            quality_model=model_match.group(1) if model_match else None,
            review_recommended=bool(review_match and review_match.group(1).lower() == "true"),
            provider=provider_match.group(1) if provider_match else None,
            block_id=(block_match.group(1) if original is None and block_match
                      else original.block_id if original else None),
            human_reviewed=bool(
                human_review_match and human_review_match.group(1).lower() == "true"
            ),
        )
    return XliffTranslation(
        source_language=file_node.get("source-language"),
        target_language=target_language,
        units=imported,
    )


def write_xliff_translation(translation: XliffTranslation, path: str | Path) -> None:
    """Write translated units as XLIFF 1.2, preserving IDs and review metadata."""
    root = ET.Element(_tag("xliff"), {"version": "1.2"})
    file_node = ET.SubElement(root, _tag("file"), {
        "source-language": translation.source_language or "und",
        "target-language": translation.target_language,
        "datatype": "plaintext",
        "original": "document",
    })
    body = ET.SubElement(file_node, _tag("body"))
    for unit in translation.units.values():
        tu = ET.SubElement(body, _tag("trans-unit"), {
            "id": _safe_id(unit.id),
            # Machine-generated targets remain unapproved until a human has
            # reviewed them in a CAT tool.
            "approved": "no",
        })
        ET.SubElement(tu, _tag("source")).text = unit.source
        if unit.target is not None:
            ET.SubElement(tu, _tag("target")).text = unit.target
        if unit.page and unit.word_ids:
            note = ET.SubElement(tu, _tag("note"), {"from": "DataCompiler"})
            note.text = (
                f"page={unit.page}; word_ids={','.join(map(str, unit.word_ids))}; "
                f"block_id={unit.block_id or unit.id}"
            )
        if unit.quality_score is not None:
            note = ET.SubElement(tu, _tag("note"), {"from": "DataCompiler"})
            note.text = (
                f"quality_score={unit.quality_score:.4f}; "
                f"review_recommended={str(unit.review_recommended).lower()}; "
                f"provider={unit.provider or 'unknown'}; "
                f"quality_model={unit.quality_model or 'unknown'}"
            )
        if unit.human_reviewed:
            note = ET.SubElement(tu, _tag("note"), {"from": "DataCompiler"})
            note.text = "human_reviewed=true"
    tree = ET.ElementTree(root)
    if hasattr(ET, "indent"):
        ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def apply_xliff_translation(
    document: Document,
    translation: XliffTranslation,
    *,
    expected_units: list[TranslationUnit] | None = None,
) -> TranslationApplication:
    """Apply translated XLIFF units in their original segment boxes on a copy."""
    source_units = expected_units if expected_units is not None else build_translation_units(document)
    source_by_id = {unit.id: unit for unit in source_units}
    translated_by_id = translation.units
    unknown_ids = set(translated_by_id) - set(source_by_id)
    if unknown_ids:
        raise ValueError(f"Translation contains unknown unit ids: {', '.join(sorted(unknown_ids))}")

    translated = deepcopy(document)
    pages = {page.number: page for page in translated.pages}
    # Keep the exact source baseline before replacing any source words.
    from datacompiler.backend.rebuilt_pdf import _calibrer_lignes
    baseline_by_page = {
        page.number: _calibrer_lignes(page.resolved.words) for page in translated.pages
    }
    translated_units = []
    for source_unit in source_units:
        target_unit = translated_by_id.get(source_unit.id)
        if target_unit and target_unit.source and target_unit.source != source_unit.source:
            raise ValueError(f"Source text changed for XLIFF unit {source_unit.id}")
        if target_unit and (target_unit.target or "").strip():
            translated_units.append((source_unit, target_unit))

    applied = []
    for source_unit, target_unit in translated_units:
        page_number, unit_id = source_unit.page, source_unit.id
        block_id = source_unit.block_id or unit_id
        page = pages.get(page_number)
        if page is None:
            raise ValueError(f"Source page {page_number} for {block_id} is missing")
        word_by_id = {word.id: word for word in page.resolved.words}
        text = (target_unit.target or "").strip()
        words = [word_by_id[word_id] for word_id in source_unit.word_ids
                 if word_id in word_by_id]
        if len(words) != len(source_unit.word_ids) or not words:
            raise ValueError(
                f"Source words for {source_unit.id} are missing from the document"
            )
        all_words = words

        if not all_words:
            continue
        # Keep one replacement per source segment so neighboring fields retain
        # their own coordinates instead of flowing together as a paragraph.
        replacement = deepcopy(all_words[0])
        boxes = [word.bbox for word in all_words if word.bbox is not None]
        if boxes:
            replacement.bbox = type(boxes[0])(
                min(box.x0 for box in boxes), min(box.y0 for box in boxes),
                max(box.x1 for box in boxes), max(box.y1 for box in boxes),
            )
        replacement._translation_block_id = block_id
        replacement._translation_unit_id = source_unit.id
        source_glyph_bboxes = []
        for word in all_words:
            if word.source_glyph_bboxes:
                source_glyph_bboxes.extend(word.source_glyph_bboxes)
            elif word.bbox is not None:
                source_glyph_bboxes.append(
                    (word.bbox.x0, word.bbox.y0, word.bbox.x1, word.bbox.y1)
                )
        replacement.source_glyph_bboxes = tuple(source_glyph_bboxes)
        replacement._translation_segments = [{
            "id": source_unit.id,
            "source": source_unit.source,
            "target": target_unit.target,
            "quality_score": target_unit.quality_score,
            "quality_model": target_unit.quality_model,
            "provider": target_unit.provider,
            "review_recommended": target_unit.review_recommended,
            "human_reviewed": target_unit.human_reviewed,
        }]
        replacement._translation_base_font_size = max(
            (word.font_size for word in all_words if word.font_size > 0), default=10.0,
        )
        replacement._translation_baseline = baseline_by_page[page_number].get(
            id(all_words[0]),
        )
        replacement.text = text
        replacement.resolved_text = replacement.text
        replacement.replacement = None
        replacement.is_corrected = True
        replacement.reconstructed = True
        replacement.is_vectorized = False
        replacement.source = "xliff_translation"
        replacement.language = translation.target_language
        replacement.notes = list(replacement.notes) + [
            f"XLIFF translation applied to block {block_id}"
        ]
        remove_ids = {word.id for word in all_words}
        first_id = all_words[0].id
        new_words = []
        inserted = False
        for word in page.resolved.words:
            if word.id == first_id and not inserted:
                new_words.append(replacement)
                inserted = True
            if word.id not in remove_ids:
                new_words.append(word)
        page.resolved.words = new_words
        applied.append(source_unit.id)

    missing = [
        unit_id for unit_id in source_by_id
        if unit_id not in translated_by_id
        or not (translated_by_id[unit_id].target or "").strip()
    ]
    return TranslationApplication(translated, applied, missing)
