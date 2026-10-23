"""Optional lightweight desktop editor for translated PDF segment layout."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
try:
    import tkinter as tk
    from tkinter import colorchooser, messagebox, ttk
except ImportError:  # Keep the non-GUI translation API usable without Tk support.
    tk = None
    colorchooser = None
    messagebox = None
    ttk = None

import pymupdf
from datacompiler.model.document import Word
from datacompiler.model.geometry import BBox
from datacompiler.review.divergence import build_review
from datacompiler.utils.colors import normalize_hex_color
from .xliff import TranslationUnit, XliffTranslation, apply_xliff_translation

_LAYOUT_SCHEMA_VERSION = 1


def _all_translation_words(application):
    return [
        word
        for page in application.document.pages
        for word in page.resolved.words
        if word.source in {"xliff_translation", "manual_translation"}
        and word.bbox is not None
    ]


def _translation_words(application):
    return _all_translation_words(application)


def _generic_unit_id(page, word):
    return f"generic-p{page.number}-w{word.id}"


def _apply_editor_text(word, text, *, generic=False):
    if not (generic and word.source != "manual_translation"):
        word.text = text
    word.resolved_text = text


def _prepare_generic_words(document):
    """Give resolved text stable editor IDs without changing reading order."""
    words = []
    for page in document.pages:
        for word in page.resolved.words:
            if word.bbox is None and word.source != "vlm_transcription":
                continue
            unit_id = getattr(word, "_translation_unit_id", "")
            if not (word.source == "manual_translation" and unit_id.startswith("manual-")):
                unit_id = _generic_unit_id(page, word)
            word._translation_unit_id = unit_id
            word._translation_block_id = word._translation_unit_id
            word._editor_generic = True
            if (
                (word.is_vectorized or word.source == "ocr_vectoriel")
                and not word.source_glyph_bboxes
            ):
                word.source_glyph_bboxes = (
                    (word.bbox.x0, word.bbox.y0, word.bbox.x1, word.bbox.y1),
                )
            words.append(word)
    return words


def prepare_vlm_editor_words(document):
    """Prepare one editable line per transcript line and estimate its scan box."""
    for page in document.pages:
        candidates = page.ocr.candidates
        if not candidates:
            continue
        reference = next(
            (
                item for item in candidates
                if "dots-3-note-preview" in f"{item.id} {item.model}".lower()
            ),
            candidates[0],
        )
        if page.review.reference_candidate_id != reference.id:
            page.review = build_review(candidates, reference_id=reference.id)
            for divergence in page.review.divergences:
                divergence.decision = None
            page.review.state = "in_review"
            page.review.reference_candidate_id = reference.id
            page.review.validated_text = None
            page.review.draft_text = reference.text
            page.review.draft_candidate_id = reference.id
        else:
            page.review.draft_candidate_id = reference.id
        line_words = []
        for line_number, raw_line in enumerate(reference.text.splitlines(), start=1):
            if not raw_line.strip():
                continue
            line = raw_line.strip()
            word = Word(
                id=line_number,
                text=line,
                resolved_text=line,
                line=line_number,
                source="vlm_transcription",
                reconstructed=True,
            )
            word._vlm_prefix = raw_line[:len(raw_line) - len(raw_line.lstrip())]
            word._vlm_suffix = raw_line[len(raw_line.rstrip()):]
            line_words.append(word)
        _estimate_vlm_line_boxes(document, page, line_words)
        page.resolved.words = line_words


def _estimate_vlm_line_boxes(document, page, words):
    """Estimate line rectangles from dark-ink row projections on the source scan.

    VLM transcripts do not contain geometry. This creates editable starting
    rectangles from the scan's ink distribution; users can move/resize them or
    draw a missing rectangle in the editor.
    """
    if not words or not document.metadata.source_pdf:
        return
    import numpy as np

    with pymupdf.open(document.metadata.source_pdf) as pdf:
        source_page = pdf[page.number - 1]
        scale = 0.8
        pix = source_page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        rgb = image[:, :, :3].astype(np.int16)
        # Exclude colored notebook rules and the dark photo border while
        # retaining dark pen/pencil strokes inside the page.
        ink = (rgb.max(axis=2) < 80) & ((rgb.max(axis=2) - rgb.min(axis=2)) < 55)
        ink[:, :int(pix.width * .08)] = False
        ink[:, int(pix.width * .92):] = False
        ink[:int(pix.height * .04), :] = False
        ink[int(pix.height * .96):, :] = False
        projection = ink.sum(axis=1).astype(float)
        if len(projection) >= 7:
            projection = np.convolve(projection, np.ones(5) / 5, mode="same")
        threshold = max(5.0, pix.width * 0.01)
        active = projection >= threshold
        runs = []
        start = None
        last = None
        for y, is_active in enumerate(active):
            if is_active:
                if start is None:
                    start = y
                last = y
            elif start is not None and y - last > 4:
                if last - start >= 2:
                    runs.append((start, last))
                start = last = None
        if start is not None and last - start >= 2:
            runs.append((start, last))

        # Reject page/photo edges, long rules and broad background bands.
        rows = []
        for y0, y1 in runs:
            if y0 < pix.height * .06 or y1 - y0 > pix.height * 0.065:
                continue
            ys = slice(max(0, y0 - 2), min(pix.height, y1 + 3))
            xs = np.flatnonzero(ink[ys, :].any(axis=0))
            if len(xs) < 3:
                continue
            x0, x1 = int(xs[0]), int(xs[-1])
            if x1 - x0 > pix.width * 0.88:
                continue
            rows.append((y0, y1, x0, x1))

        # Map OCR lines to detected ink rows in reading order. If projection
        # misses a faint line, interpolate between its nearest detected rows.
        if rows:
            centers = np.array([(row[0] + row[1]) / 2 for row in rows], dtype=float)
            if len(centers) != len(words):
                centers = np.interp(
                    np.linspace(0, max(0, len(centers) - 1), len(words)),
                    np.arange(len(centers)), centers,
                )
            row_indices = np.linspace(0, len(rows) - 1, len(words))
        else:
            centers = np.linspace(pix.height * .1, pix.height * .9, len(words))
            row_indices = np.zeros(len(words))

        for index, word in enumerate(words):
            cy = float(centers[index])
            if rows:
                row = rows[int(round(row_indices[index]))]
                band = ink[max(0, int(cy) - 12):min(pix.height, int(cy) + 13), :]
                xs = np.flatnonzero(band.any(axis=0))
                x0, x1 = (int(xs[0]), int(xs[-1])) if len(xs) >= 3 else (row[2], row[3])
                y0, y1 = row[0], row[1]
            else:
                x0, x1 = int(pix.width * .08), int(pix.width * .92)
                y0, y1 = int(cy - 10), int(cy + 10)
            # Coordinates are stored in PDF points; add a little breathing room.
            word.bbox = BBox(
                max(0, x0 / scale - 3), max(0, y0 / scale - 3),
                min(source_page.rect.width, x1 / scale + 3),
                min(source_page.rect.height, y1 / scale + 3),
            )
            word.font_size = max(6.0, (word.bbox.y1 - word.bbox.y0) * .72)


def _replace_word_with_blocks(page, editor_words, original, replacements):
    page_index = page.resolved.words.index(original)
    editor_index = editor_words.index(original)
    page.resolved.words[page_index:page_index + 1] = replacements
    editor_words[editor_index:editor_index + 1] = replacements


def _editor_word_record(page, word, order):
    generic = bool(getattr(word, "_editor_generic", False))
    return {
        "page": page.number,
        "source": (word._translation_segments[0].get("source")
                   if getattr(word, "_translation_segments", None) else None),
        "base_text": word.text if generic else None,
        "generic": generic,
        "text": word.resolved_text or word.text or "",
        "bbox": ([word.bbox.x0, word.bbox.y0, word.bbox.x1, word.bbox.y1]
                 if word.bbox else None),
        "source_glyph_bboxes": [list(box) for box in word.source_glyph_bboxes],
        "font_size": float(getattr(word, "_translation_base_font_size", word.font_size or 10.0)),
        "bold": bool(word.bold),
        "italic": bool(word.italic),
        "script": getattr(word, "_translation_script", "normal"),
        "editor_color": word.editor_color,
        "deleted": bool(getattr(word, "_translation_deleted", False)),
        "order": order,
    }


def _word_source_ids(word):
    return tuple(
        getattr(word, "_editor_source_ids", ())
        or (getattr(word, "_translation_unit_id", str(word.id)),)
    )


def _merged_unit_id(member_ids):
    stable_value = "\n".join(member_ids).encode("utf-8")
    return "merged-" + hashlib.sha256(stable_value).hexdigest()[:20]


def _merge_words(page, editor_words, selected_words, reference):
    """Merge words in page reading order, using reference formatting and identity."""
    if len(selected_words) < 2:
        raise ValueError("Select at least two blocks to merge")
    if not any(word is reference for word in selected_words):
        raise ValueError("The merge reference must be one of the selected blocks")
    if any(word not in page.resolved.words for word in selected_words):
        raise ValueError("All merged blocks must belong to the same page")
    if any(word not in editor_words for word in selected_words):
        raise ValueError("All merged blocks must be present in the editor list")

    selected_set = {id(word) for word in selected_words}
    ordered = [
        word for word in page.resolved.words
        if id(word) in selected_set
    ]
    if len(ordered) != len(selected_words):
        raise ValueError("A block can only be selected once for merging")
    bbox_words = [word for word in ordered if word.bbox is not None]
    if len(bbox_words) != len(ordered):
        raise ValueError("Every merged block must have a layout box")

    member_ids = tuple(
        member_id
        for word in ordered
        for member_id in _word_source_ids(word)
    )
    if len(member_ids) != len(set(member_ids)):
        raise ValueError("Selected blocks overlap in their source members")

    merged = copy.deepcopy(reference)
    merged.id = max((word.id for word in page.resolved.words), default=0) + 1
    merged.bbox = BBox(
        min(word.bbox.x0 for word in bbox_words),
        min(word.bbox.y0 for word in bbox_words),
        max(word.bbox.x1 for word in bbox_words),
        max(word.bbox.y1 for word in bbox_words),
    )
    merged_text = " ".join(
        (word.resolved_text or word.text or "").strip()
        for word in ordered
        if (word.resolved_text or word.text or "").strip()
    )
    merged.text = merged_text
    merged.resolved_text = merged_text
    merged.source = "manual_translation"
    merged.reconstructed = True
    merged.is_vectorized = False
    merged._translation_unit_id = _merged_unit_id(member_ids)
    merged._translation_block_id = merged._translation_unit_id
    merged._editor_source_ids = member_ids
    merged._editor_composite_members = member_ids
    merged._editor_reference_id = getattr(reference, "_translation_unit_id", str(reference.id))
    merged._editor_generic = any(getattr(word, "_editor_generic", False) for word in ordered)
    merged._translation_segments = [
        segment
        for word in ordered
        for segment in getattr(word, "_translation_segments", [])
    ]
    glyph_bboxes = []
    for word in ordered:
        if word.source_glyph_bboxes:
            glyph_bboxes.extend(word.source_glyph_bboxes)
        elif word.is_vectorized or word.source == "ocr_vectoriel":
            if word.bbox:
                glyph_bboxes.append(
                    (word.bbox.x0, word.bbox.y0, word.bbox.x1, word.bbox.y1)
                )
    merged.source_glyph_bboxes = tuple(dict.fromkeys(glyph_bboxes))

    page_position = min(page.resolved.words.index(word) for word in ordered)
    page.resolved.words[:] = [
        word for word in page.resolved.words
        if id(word) not in selected_set
    ]
    page.resolved.words.insert(page_position, merged)

    editor_positions = [editor_words.index(word) for word in ordered]
    editor_position = min(editor_positions)
    editor_words[:] = [
        word for word in editor_words
        if id(word) not in selected_set
    ]
    editor_words.insert(editor_position, merged)
    return merged, ordered


def _align_words(words, reference, axis, anchor):
    """Align selected word boxes to a reference without changing their sizes or order."""
    coordinates = {
        ("horizontal", "left"): lambda box: box.x0,
        ("horizontal", "center"): lambda box: (box.x0 + box.x1) / 2,
        ("horizontal", "right"): lambda box: box.x1,
        ("vertical", "top"): lambda box: box.y0,
        ("vertical", "center"): lambda box: (box.y0 + box.y1) / 2,
        ("vertical", "bottom"): lambda box: box.y1,
    }
    try:
        coordinate = coordinates[(axis, anchor)]
    except KeyError as exc:
        raise ValueError(f"Unsupported alignment: {axis}/{anchor}") from exc

    reference_position = coordinate(reference.bbox)
    for word in words:
        if word is reference or word.bbox is None:
            continue
        box = word.bbox
        delta = reference_position - coordinate(box)
        if axis == "horizontal":
            word.bbox = BBox(box.x0 + delta, box.y0, box.x1 + delta, box.y1)
        else:
            word.bbox = BBox(box.x0, box.y0 + delta, box.x1, box.y1 + delta)
            baseline = getattr(word, "_translation_baseline", None)
            if baseline is not None:
                word._translation_baseline = baseline + delta


def _save_layout(application, path):
    units = {}
    for page in application.document.pages:
        for order, word in enumerate(page.resolved.words):
            generic = bool(getattr(word, "_editor_generic", False))
            if word.source not in {"xliff_translation", "manual_translation"} and not generic:
                continue
            unit_id = getattr(word, "_translation_unit_id", None)
            if not unit_id:
                continue
            units[unit_id] = _editor_word_record(page, word, order)
            if getattr(word, "_editor_composite_members", None):
                units[unit_id]["composite_members"] = list(word._editor_composite_members)
                units[unit_id]["reference_id"] = word._editor_reference_id
        units.update(getattr(page, "_translation_layout_tombstones", {}))
    payload = {"schema_version": _LAYOUT_SCHEMA_VERSION, "units": units}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_layout(application, path):
    path = Path(path)
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != _LAYOUT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported layout correction schema: {payload.get('schema_version')!r}")
    pages = {page.number: page for page in application.document.pages}
    words = {
        getattr(word, "_translation_unit_id", ""): word
        for page in application.document.pages
        for word in page.resolved.words
        if (
            word.source in {"xliff_translation", "manual_translation"}
            or getattr(word, "_editor_generic", False)
        )
    }
    split_parent_ids = set()
    manual_records = []
    composite_records = []
    for unit_id, record in payload.get("units", {}).items():
        if record.get("composite_members"):
            composite_records.append((unit_id, record))
            continue
        word = words.get(unit_id)
        page = pages.get(record.get("page"))
        if record.get("split_into"):
            split_parent_ids.add(unit_id)
            if page is not None:
                tombstones = getattr(page, "_translation_layout_tombstones", {})
                tombstones[unit_id] = record
                page._translation_layout_tombstones = tombstones
        if word is None:
            if record.get("split_into"):
                continue
            # Entries absent from the fresh XLIFF are manual text blocks.
            box = record.get("bbox")
            if page is None or not box or not unit_id.startswith("manual-"):
                continue
            word = Word(
                id=max((item.id for item in page.resolved.words), default=0) + 1,
                text=record.get("text", ""), bbox=BBox(*box),
                font_size=float(record.get("font_size", 12.0)),
                source="manual_translation", reconstructed=True,
            )
            word.resolved_text = word.text
            word._translation_unit_id = unit_id
            word._translation_block_id = unit_id
            word._editor_generic = bool(record.get("generic", False))
            word._translation_baseline = None
            word._translation_segments = []
            word.source_glyph_bboxes = tuple(
                tuple(box) for box in record.get("source_glyph_bboxes", ())
            )
            page.resolved.words.append(word)
            words[unit_id] = word
        else:
            if record.get("generic"):
                if not getattr(word, "_editor_generic", False):
                    raise ValueError(f"Layout correction for {unit_id} is not a generic editor unit")
                if record.get("base_text") != word.text:
                    raise ValueError(
                        f"Layout correction for {unit_id} belongs to different source text"
                    )
            if "source_glyph_bboxes" in record:
                word.source_glyph_bboxes = tuple(
                    tuple(box) for box in record["source_glyph_bboxes"]
                )
            source_segments = getattr(word, "_translation_segments", [])
            expected_source = source_segments[0].get("source") if source_segments else None
            if record.get("source") is not None and record["source"] != expected_source:
                raise ValueError(
                    f"Layout correction for {unit_id} belongs to different source text"
                )
            if record.get("bbox"):
                corrected_bbox = BBox(*record["bbox"])
                if word.bbox and getattr(word, "_translation_baseline", None) is not None:
                    word._translation_baseline += corrected_bbox.y0 - word.bbox.y0
                word.bbox = corrected_bbox
        if not record.get("generic"):
            word.text = record.get("text", word.text)
        word.resolved_text = record.get("text", word.text)
        word.bold = bool(record.get("bold", word.bold))
        word.italic = bool(record.get("italic", word.italic))
        word.font_size = float(record.get("font_size", word.font_size or 10.0))
        word._translation_base_font_size = word.font_size
        word._translation_script = record.get("script", "normal")
        editor_color = record.get("editor_color")
        word.editor_color = (
            normalize_hex_color(editor_color) if editor_color is not None else None
        )
        word._translation_deleted = bool(record.get("deleted", False))
        if unit_id.startswith("manual-") and page is not None:
            manual_records.append((page, record, word))

    for page in application.document.pages:
        if not split_parent_ids:
            break
        page.resolved.words = [
            word for word in page.resolved.words
            if getattr(word, "_translation_unit_id", None) not in split_parent_ids
        ]

    manual_by_page = {}
    for page, record, word in manual_records:
        manual_by_page.setdefault(page.number, []).append((record, word))
    for page in application.document.pages:
        records = manual_by_page.get(page.number, [])
        if not records:
            continue
        manual_word_ids = {id(word) for _, word in records}
        page.resolved.words = [
            word for word in page.resolved.words if id(word) not in manual_word_ids
        ]
        for record, word in sorted(records, key=lambda item: item[0].get("order", float("inf"))):
            order = record.get("order")
            index = min(max(order, 0), len(page.resolved.words)) if isinstance(order, int) else len(page.resolved.words)
            page.resolved.words.insert(index, word)

    for composite_id, record in composite_records:
        page = pages.get(record.get("page"))
        if page is None:
            continue
        member_ids = record["composite_members"]
        members = {
            getattr(word, "_translation_unit_id", ""): word
            for word in page.resolved.words
        }
        if any(member_id not in members for member_id in member_ids):
            raise ValueError(
                f"Layout correction for {composite_id} references missing merge members"
            )
        source_words = [members[member_id] for member_id in member_ids]
        reference_id = record.get("reference_id")
        reference = members.get(reference_id, source_words[-1])
        merged, _ = _merge_words(
            page, list(page.resolved.words), source_words, reference,
        )
        if merged._translation_unit_id != composite_id:
            raise ValueError(f"Invalid stable composite ID for {composite_id}")
        merged.bbox = BBox(*record["bbox"])
        merged.text = record.get("text", merged.text)
        merged.resolved_text = merged.text
        merged.font_size = float(record.get("font_size", merged.font_size or 10.0))
        merged._translation_base_font_size = merged.font_size
        merged.bold = bool(record.get("bold", merged.bold))
        merged.italic = bool(record.get("italic", merged.italic))
        merged._translation_script = record.get("script", "normal")
        merged.editor_color = (
            normalize_hex_color(record["editor_color"])
            if record.get("editor_color") is not None else None
        )
        merged._translation_deleted = bool(record.get("deleted", False))
        merged.source_glyph_bboxes = tuple(
            tuple(bounds) for bounds in record.get("source_glyph_bboxes", ())
        )
        merged._editor_generic = bool(record.get("generic", False))
        merged._translation_unit_id = composite_id
        merged._translation_block_id = composite_id
        merged._editor_source_ids = tuple(member_ids)
        merged._editor_composite_members = tuple(member_ids)
        merged._editor_reference_id = reference_id
        tombstones = getattr(page, "_translation_layout_tombstones", {})
        page._translation_layout_tombstones = tombstones
        for member_id in member_ids:
            member_record = payload["units"].get(member_id)
            if member_record is not None:
                tombstones[member_id] = {
                    **member_record,
                    "merged_into": composite_id,
                }


class TranslationEditor(tk.Tk if tk is not None else object):
    """A local segment editor; PDF geometry is stored in points in a JSON sidecar."""

    def __init__(self, application, output_path, corrections_path):
        if tk is None:
            raise RuntimeError("The translation editor requires Python Tkinter support.")
        super().__init__()
        self.application = application
        self.output_path = Path(output_path)
        self.corrections_path = Path(corrections_path)
        self.document = application.document
        self.mode = getattr(application, "editor_mode", "translation")
        self.words = (
            _prepare_generic_words(self.document)
            if self.mode in {"generic", "vlm"}
            else _translation_words(application)
        )
        self.by_id = {getattr(word, "_translation_unit_id", str(word.id)): word for word in self.words}
        self.selected = None
        self.scale = 1.0
        self.photo = None
        self.image_item = None
        self.drag = None
        self.draw_box_mode = False
        self.draw_box_start = None
        self.draw_box_item = None
        self.saved = False
        self._preview_dir = tempfile.TemporaryDirectory(prefix="datacompiler-editor-")
        self.preview_path = Path(self._preview_dir.name) / "preview.pdf"
        title = (
            "DataCompiler — placement de transcription VLM"
            if self.mode == "vlm"
            else
            "DataCompiler — édition du document"
            if self.mode == "generic"
            else "DataCompiler — édition légère des segments"
        )
        self.title(title)
        self.geometry("1400x850")
        self.minsize(1100, 650)
        self._build_ui()
        self._refresh_list()
        if self.words:
            self.segment_list.selection_set(0)
            self._select_from_list()
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_ui(self):
        root = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        root.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(root, padding=8)
        right = ttk.Frame(root, padding=8)
        root.add(left, weight=2)
        root.add(right, weight=4)

        list_title = (
            "Lignes de transcription VLM"
            if self.mode == "vlm"
            else
            "Texte résolu et blocs manuels"
            if self.mode == "generic"
            else "Segments traduits et blocs manuels"
        )
        footer = ttk.Frame(left, padding=(0, 4, 0, 0))
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Button(
            footer, text="Enregistrer le PDF et les corrections", command=self._save,
        ).pack(fill=tk.X)
        self.status = tk.StringVar(value=(
            "Vérifiez les boîtes estimées depuis le scan et corrigez celles qui sont mal placées."
            if self.mode == "vlm"
            else "Glissez un segment pour déplacer un bloc ; tirez son coin inférieur droit pour le redimensionner."
        ))
        ttk.Label(footer, textvariable=self.status, wraplength=440).pack(anchor="w", pady=4)

        content = ttk.Frame(left)
        content.pack(fill=tk.BOTH, expand=True)
        ttk.Label(content, text=list_title).pack(anchor="w")
        ttk.Label(
            content,
            text=(
                "Les boîtes sont estimées depuis les traits du scan. Vérifiez-les et corrigez les lignes mal placées."
                if self.mode == "vlm"
                else "Ctrl/Cmd+clic ou Maj+clic pour sélectionner plusieurs blocs."
            ),
            wraplength=330,
        ).pack(anchor="w")
        list_frame = ttk.Frame(content)
        list_frame.pack(fill=tk.X, pady=(4, 8))
        self.segment_list = tk.Listbox(
            list_frame, width=42, height=5, exportselection=False,
        )
        self.segment_list.configure(selectmode=tk.EXTENDED)
        list_scrollbar = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self.segment_list.yview,
        )
        self.segment_list.configure(yscrollcommand=list_scrollbar.set)
        self.segment_list.pack(side=tk.LEFT, fill=tk.X, expand=True)
        list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.segment_list.bind("<<ListboxSelect>>", self._select_from_list)
        self.segment_list.bind("<ButtonRelease-1>", self._list_click_released, add="+")
        self.segment_list.bind("<KeyRelease>", self._list_key_released, add="+")
        if self.mode != "vlm":
            ttk.Button(content, text="Ajouter un bloc texte", command=self._add_text).pack(fill=tk.X)
        if self.mode == "vlm":
            ttk.Button(
                content, text="Ajouter une ligne manquante", command=self._add_text,
            ).pack(fill=tk.X)
            ttk.Button(
                content, text="Tracer / refaire la boîte sélectionnée",
                command=self._start_box_creation,
            ).pack(fill=tk.X, pady=(4, 0))
        if self.mode != "vlm":
            ttk.Button(content, text="Scinder le segment en deux", command=self._split_selected).pack(fill=tk.X, pady=(4, 0))
        self.delete_button = ttk.Button(content, command=self._toggle_deleted)
        self.delete_button.pack(fill=tk.X, pady=(4, 0))
        if self.mode != "vlm":
            ttk.Button(content, text="Fusionner les segments", command=self._merge_selection).pack(fill=tk.X, pady=(4, 0))
        self.reference_value = tk.StringVar(value="Référence : aucune")
        if self.mode != "vlm":
            ttk.Label(content, textvariable=self.reference_value, wraplength=330).pack(
                anchor="w", pady=(8, 2),
            )

        if self.mode != "vlm":
            alignments = ttk.LabelFrame(content, text="Aligner les blocs sélectionnés", padding=6)
            alignments.pack(fill=tk.X, pady=(4, 0))
            for column, (label, axis, anchor) in enumerate((
                ("Bords gauches", "horizontal", "left"),
                ("Centres horizontaux", "horizontal", "center"),
                ("Bords droits", "horizontal", "right"),
                ("Bords hauts", "vertical", "top"),
                ("Centres verticaux", "vertical", "center"),
                ("Bords bas", "vertical", "bottom"),
            )):
                ttk.Button(
                    alignments,
                    text=label,
                    command=lambda a=axis, p=anchor: self._align_selection(a, p),
                ).grid(row=column // 2, column=column % 2, sticky="ew", padx=2, pady=2)
            alignments.columnconfigure(0, weight=1)
            alignments.columnconfigure(1, weight=1)

        controls = ttk.LabelFrame(
            content,
            text="Ligne sélectionnée" if self.mode == "vlm" else "Segment sélectionné",
            padding=8,
        )
        controls.pack(fill=tk.X, pady=8)
        editor_fields = ttk.Frame(controls)
        editor_fields.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        color_controls = ttk.LabelFrame(controls, text="Couleur", padding=6)
        color_controls.grid(row=0, column=1, sticky="sew")
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=0)
        controls.rowconfigure(0, weight=1)
        text_label = "Transcription de la ligne" if self.mode == "vlm" else "Texte édité" if self.mode == "generic" else "Texte cible"
        ttk.Label(editor_fields, text=text_label).grid(row=0, column=0, columnspan=2, sticky="w")
        self.text_value = tk.Text(editor_fields, width=28, height=4, wrap=tk.WORD)
        self.text_value.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 6))
        ttk.Label(editor_fields, text="Taille (pt)").grid(row=2, column=0, sticky="w")
        self.size_value = tk.StringVar(value="10")
        ttk.Spinbox(editor_fields, from_=1, to=120, increment=0.5, textvariable=self.size_value, width=10).grid(row=2, column=1, sticky="e")
        self.bold_value = tk.BooleanVar()
        self.italic_value = tk.BooleanVar()
        ttk.Checkbutton(editor_fields, text="Gras", variable=self.bold_value).grid(row=3, column=0, sticky="w")
        ttk.Checkbutton(editor_fields, text="Italique", variable=self.italic_value).grid(row=3, column=1, sticky="w")
        ttk.Label(editor_fields, text="Position verticale").grid(row=4, column=0, sticky="w", pady=(4, 0))
        self.script_value = tk.StringVar(value="normal")
        ttk.Combobox(
            editor_fields, textvariable=self.script_value, state="readonly", width=14,
            values=("normal", "superscript", "subscript"),
        ).grid(row=4, column=1, sticky="e", pady=(4, 0))
        ttk.Button(editor_fields, text="Appliquer et prévisualiser", command=self._apply_and_preview).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(color_controls, text="Couleur du texte").pack(anchor="w")
        self.color_value = tk.StringVar(value="Source")
        self.color_swatch = tk.Label(
            color_controls, textvariable=self.color_value, relief=tk.SOLID, bd=1,
            padx=6, pady=2,
        )
        self.color_swatch.pack(fill=tk.X, pady=(4, 2))
        ttk.Button(
            color_controls, text="Choisir…", command=self._choose_color,
        ).pack(fill=tk.X, pady=(4, 0))
        ttk.Button(
            color_controls, text="Couleur source", command=self._clear_color,
        ).pack(fill=tk.X, pady=(4, 0))

        canvas_frame = ttk.Frame(right)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(canvas_frame, background="#555", highlightthickness=0)
        vertical = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        horizontal = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        self.canvas.bind("<Button-1>", self._mouse_down)
        self.canvas.bind("<B1-Motion>", self._mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._mouse_up)

    def _refresh_list(self, keep_id=None, selected_ids=()):
        self.segment_list.delete(0, tk.END)
        selected_ids = set(selected_ids)
        for index, word in enumerate(self.words):
            unit_id = getattr(word, "_translation_unit_id", str(word.id))
            page_num = next((page.number for page in self.document.pages if word in page.resolved.words), "?")
            text = (word.resolved_text or word.text or "").replace("\n", " ")
            deleted = " [supprimé]" if getattr(word, "_translation_deleted", False) else ""
            self.segment_list.insert(tk.END, f"p.{page_num}  {unit_id}  |  {text[:46]}{deleted}")
            if unit_id == keep_id or unit_id in selected_ids:
                self.segment_list.selection_set(index)
                self.segment_list.see(index)

    def _select_from_list(self, _event=None):
        selection = self.segment_list.curselection()
        if not selection:
            return
        self.draw_box_mode = False
        self.draw_box_start = None
        reference_index = getattr(self, "_reference_index", None)
        if reference_index not in selection:
            reference_index = selection[-1]
        self._reference_index = reference_index
        self._commit_fields()
        self.selected = self.words[reference_index]
        self._update_reference_label()
        self._load_fields()
        self._draw_page()

    def _list_click_released(self, event):
        index = self.segment_list.nearest(event.y)
        selection = self.segment_list.curselection()
        if selection:
            self._reference_index = index if index in selection else selection[-1]
            self._select_from_list()

    def _list_key_released(self, _event):
        selection = self.segment_list.curselection()
        if selection:
            active_index = self.segment_list.index("active")
            self._reference_index = (
                active_index if active_index in selection else selection[-1]
            )
            self._select_from_list()

    def _update_reference_label(self):
        if self.selected is None or not hasattr(self, "reference_value"):
            return
        unit_id = getattr(self.selected, "_translation_unit_id", str(self.selected.id))
        self.reference_value.set(f"Référence (dernier bloc sélectionné) : {unit_id}")

    def _load_fields(self):
        word = self.selected
        self.text_value.delete("1.0", tk.END)
        self.text_value.insert("1.0", word.resolved_text or word.text or "")
        self.size_value.set(str(getattr(word, "_translation_base_font_size", word.font_size or 10.0)))
        self.bold_value.set(bool(word.bold))
        self.italic_value.set(bool(word.italic))
        self.script_value.set(getattr(word, "_translation_script", "normal"))
        self._update_color_display()
        deleted = bool(getattr(word, "_translation_deleted", False))
        self.delete_button.configure(
            text=(
                ("Restaurer la ligne" if deleted else "Supprimer la ligne")
                if self.mode == "vlm"
                else ("Restaurer le bloc" if deleted else "Supprimer le bloc")
            )
        )

    def _commit_fields(self):
        if self.selected is None:
            return
        text = self.text_value.get("1.0", "end-1c")
        try:
            size = float(self.size_value.get())
            if size <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Taille invalide", "La taille doit être un nombre positif.")
            return
        _apply_editor_text(self.selected, text, generic=self.mode == "generic")
        self.selected.font_size = size
        self.selected._translation_base_font_size = size
        self.selected.bold = self.bold_value.get()
        self.selected.italic = self.italic_value.get()
        self.selected._translation_script = self.script_value.get()

    def _update_color_display(self):
        if self.selected is None or not hasattr(self, "color_value"):
            return
        color = self.selected.editor_color
        if color is None:
            self.color_value.set("Source")
            self.color_swatch.configure(background="#FFFFFF", foreground="#000000")
        else:
            color = normalize_hex_color(color)
            self.color_value.set(color)
            self.color_swatch.configure(
                background=color,
                foreground="#FFFFFF" if sum(
                    int(color[index:index + 2], 16) for index in (1, 3, 5)
                ) < 384 else "#000000",
            )

    def _choose_color(self):
        if self.selected is None:
            return
        initial = self.selected.editor_color or self.selected.color or "#000000"
        try:
            initial = normalize_hex_color(initial)
        except ValueError:
            initial = "#000000"
        _rgb, chosen = colorchooser.askcolor(
            color=initial, parent=self, title="Couleur du texte",
        )
        if chosen is None:
            return
        try:
            self.selected.editor_color = normalize_hex_color(chosen)
        except ValueError as exc:
            messagebox.showerror("Couleur invalide", str(exc), parent=self)
            return
        self._update_color_display()
        self._draw_page()

    def _clear_color(self):
        if self.selected is None:
            return
        self.selected.editor_color = None
        self._update_color_display()
        self._draw_page()

    def _page_for_word(self, word):
        return next((page for page in self.document.pages if word in page.resolved.words), None)

    def _draw_page(self):
        if self.selected is None:
            return
        page = self._page_for_word(self.selected)
        if page is None:
            return
        try:
            from datacompiler.backend.rebuilt_pdf import render_rebuilt_pdf

            render_rebuilt_pdf(self.document, str(self.preview_path))
            with pymupdf.open(self.preview_path) as pdf:
                pdf_page = pdf[self.document.pages.index(page)]
                max_width, max_height = 900, 820
                self.scale = min(max_width / pdf_page.rect.width, max_height / pdf_page.rect.height, 1.5)
                pix = pdf_page.get_pixmap(matrix=pymupdf.Matrix(self.scale, self.scale), alpha=False)
                self.photo = tk.PhotoImage(data=base64.b64encode(pix.tobytes("png")).decode("ascii"))
            self.canvas.delete("all")
            self.image_item = self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
            self.canvas.configure(scrollregion=(0, 0, self.photo.width(), self.photo.height()))
            for word in self.words:
                if self._page_for_word(word) is not page or not word.bbox:
                    continue
                box = word.bbox
                selected = word is self.selected
                color = "#ffb000" if selected else "#00a6ff"
                self.canvas.create_rectangle(
                    box.x0 * self.scale, box.y0 * self.scale,
                    box.x1 * self.scale, box.y1 * self.scale,
                    outline=color, width=2 if selected else 1, tags=("overlay",),
                )
                if selected:
                    x, y = box.x1 * self.scale, box.y1 * self.scale
                    self.canvas.create_rectangle(x - 5, y - 5, x + 5, y + 5, fill=color, outline=color, tags=("overlay",))
        except Exception as exc:
            messagebox.showerror("Aperçu impossible", str(exc))

    def _mouse_down(self, event):
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        page = self._page_for_word(self.selected) if self.selected else None
        if page is None:
            return
        if self.draw_box_mode:
            self.draw_box_start = (x, y)
            self.draw_box_item = self.canvas.create_rectangle(
                x, y, x, y, outline="#00a6ff", width=2, tags=("overlay",),
            )
            return
        for word in reversed(self.words):
            if self._page_for_word(word) is not page or not word.bbox:
                continue
            box = word.bbox
            x0, y0, x1, y1 = box.x0 * self.scale, box.y0 * self.scale, box.x1 * self.scale, box.y1 * self.scale
            if x0 <= x <= x1 and y0 <= y <= y1:
                if word is not self.selected:
                    idx = self.words.index(word)
                    self.segment_list.selection_clear(0, tk.END)
                    self.segment_list.selection_set(idx)
                    self._select_from_list()
                    box = self.selected.bbox
                    x0, y0, x1, y1 = box.x0 * self.scale, box.y0 * self.scale, box.x1 * self.scale, box.y1 * self.scale
                resize = abs(x - x1) <= 12 and abs(y - y1) <= 12
                self.drag = (
                    x, y, BBox(box.x0, box.y0, box.x1, box.y1), resize,
                    getattr(self.selected, "_translation_baseline", None),
                )
                return

    def _mouse_drag(self, event):
        if self.draw_box_start is not None:
            x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            x0, y0 = self.draw_box_start
            self.canvas.coords(self.draw_box_item, x0, y0, x, y)
            return
        if not self.drag or self.selected is None:
            return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        start_x, start_y, original, resize, original_baseline = self.drag
        dx, dy = (x - start_x) / self.scale, (y - start_y) / self.scale
        if resize:
            self.selected.bbox = BBox(original.x0, original.y0, max(original.x0 + 2, original.x1 + dx), max(original.y0 + 2, original.y1 + dy))
        else:
            self.selected.bbox = BBox(original.x0 + dx, original.y0 + dy, original.x1 + dx, original.y1 + dy)
            if original_baseline is not None:
                self.selected._translation_baseline = original_baseline + dy
        self.canvas.delete("overlay")
        box = self.selected.bbox
        x0, y0, x1, y1 = box.x0 * self.scale, box.y0 * self.scale, box.x1 * self.scale, box.y1 * self.scale
        self.canvas.create_rectangle(x0, y0, x1, y1, outline="#ffb000", width=2, tags=("overlay",))
        self.canvas.create_rectangle(x1 - 5, y1 - 5, x1 + 5, y1 + 5, fill="#ffb000", outline="#ffb000", tags=("overlay",))

    def _mouse_up(self, _event):
        if self.draw_box_start is not None:
            x0, y0 = self.draw_box_start
            item = self.draw_box_item
            x1, y1 = self.canvas.coords(item)[2:]
            self.draw_box_start = None
            self.draw_box_item = None
            if abs(x1 - x0) < 8 or abs(y1 - y0) < 8:
                self.canvas.delete(item)
                self.draw_box_mode = False
                self.status.set("Boîte trop petite ; tracez un rectangle autour de la ligne.")
                return
            box = BBox(
                min(x0, x1) / self.scale, min(y0, y1) / self.scale,
                max(x0, x1) / self.scale, max(y0, y1) / self.scale,
            )
            self.selected.bbox = box
            self.selected.font_size = max(4.0, box.height * 0.78)
            self.selected._translation_base_font_size = self.selected.font_size
            self.selected.reconstructed = True
            self.size_value.set(f"{self.selected.font_size:.1f}")
            self.draw_box_mode = False
            self._apply_and_preview()
            return
        if self.drag:
            self.drag = None
            self._apply_and_preview()

    def _start_box_creation(self):
        if self.selected is None or self._page_for_word(self.selected) is None:
            return
        self._commit_fields()
        self.draw_box_mode = True
        self.status.set("Tracez une boîte autour de la ligne sélectionnée sur le scan.")

    def _apply_and_preview(self):
        self._commit_fields()
        if self.selected is None:
            return
        self.status.set("Génération de l'aperçu…")
        self.update_idletasks()
        self._refresh_list(getattr(self.selected, "_translation_unit_id", None))
        self._draw_page()
        self.status.set("Modifications prévisualisées. Enregistrez pour produire le PDF et le fichier de corrections.")

    def _toggle_deleted(self):
        if self.selected is None:
            return
        self._commit_fields()
        self.selected._translation_deleted = not getattr(
            self.selected, "_translation_deleted", False,
        )
        unit_id = getattr(self.selected, "_translation_unit_id", None)
        self._load_fields()
        self._refresh_list(keep_id=unit_id)
        self._draw_page()

    def _align_selection(self, axis, anchor):
        self._commit_fields()
        selection = self.segment_list.curselection()
        if len(selection) < 2:
            self.status.set("Sélectionnez au moins deux blocs pour les aligner.")
            return
        reference_index = getattr(self, "_reference_index", None)
        if reference_index not in selection:
            reference_index = selection[-1]
        selected_words = [self.words[index] for index in selection]
        reference = self.words[reference_index]
        _align_words(selected_words, reference, axis, anchor)
        self.selected = reference
        self._update_reference_label()
        self._draw_page()
        self.status.set(
            f"Blocs alignés : {anchor} sur {reference._translation_unit_id}. "
            "Tailles et ordre de lecture conservés."
        )

    def _merge_selection(self):
        selection = self.segment_list.curselection()
        if len(selection) < 2:
            self.status.set("Sélectionnez au moins deux blocs pour les fusionner.")
            return
        self._commit_fields()
        selected_words = [self.words[index] for index in selection]
        reference_index = getattr(self, "_reference_index", None)
        if reference_index not in selection:
            reference_index = selection[-1]
        reference = self.words[reference_index]
        page = self._page_for_word(reference)
        if page is None or any(self._page_for_word(word) is not page for word in selected_words):
            self.status.set("Les blocs à fusionner doivent appartenir à la même page.")
            return

        page_order = {id(word): index for index, word in enumerate(page.resolved.words)}
        try:
            merged, ordered = _merge_words(page, self.words, selected_words, reference)
        except ValueError as exc:
            self.status.set(str(exc))
            return
        tombstones = getattr(page, "_translation_layout_tombstones", {})
        for word in ordered:
            if getattr(word, "_editor_composite_members", None):
                continue
            unit_id = getattr(word, "_translation_unit_id", str(word.id))
            tombstones.setdefault(
                unit_id, _editor_word_record(page, word, page_order.get(id(word), 0)),
            )
        for member_id in merged._editor_composite_members:
            if member_id in tombstones:
                tombstones[member_id]["merged_into"] = merged._translation_unit_id
        page._translation_layout_tombstones = tombstones

        self.selected = merged
        self._reference_index = self.words.index(merged)
        selected_id = merged._translation_unit_id
        self._refresh_list(keep_id=selected_id, selected_ids=(selected_id,))
        self._update_reference_label()
        self._load_fields()
        self._draw_page()
        self.status.set(
            f"Segments fusionnés en un bloc unique : {selected_id}. "
            "L'ordre de lecture et les tracés sources sont conservés."
        )

    def _add_text(self):
        page = self.document.pages[0] if self.document.pages else None
        if page is None:
            return
        unit_id = self._new_manual_id(page)
        word = Word(
            id=max((item.id for item in page.resolved.words), default=0) + 1,
            text="Nouveau texte", bbox=BBox(36, 36, 220, 58),
            font_size=12.0, source="manual_translation", reconstructed=True,
        )
        word.resolved_text = word.text
        word._translation_unit_id = unit_id
        word._translation_block_id = unit_id
        word._translation_baseline = None
        word._translation_base_font_size = 12.0
        word._translation_script = "normal"
        word._translation_segments = []
        page.resolved.words.append(word)
        self.words.append(word)
        self._refresh_list(keep_id=unit_id)
        self._select_from_list()

    def _new_manual_id(self, page):
        existing = {
            getattr(word, "_translation_unit_id", "")
            for word in page.resolved.words
        }
        existing.update(getattr(page, "_translation_layout_tombstones", {}))
        suffix = 1
        while f"manual-p{page.number}-{suffix}" in existing:
            suffix += 1
        return f"manual-p{page.number}-{suffix}"

    def _split_selected(self):
        if self.selected is None:
            return
        self._commit_fields()
        page = self._page_for_word(self.selected)
        if page is None or not self.selected.bbox:
            return
        source = (self.selected.resolved_text or self.selected.text or "").strip()
        tokens = source.split()
        midpoint = max(1, len(tokens) // 2)
        defaults = (" ".join(tokens[:midpoint]), " ".join(tokens[midpoint:]))
        dialog = tk.Toplevel(self)
        dialog.title("Scinder le segment")
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(
            dialog,
            text="Répartissez le texte traduit entre les deux nouveaux blocs.",
            wraplength=440,
        ).pack(anchor="w", padx=12, pady=(12, 6))
        editors = []
        for label, default in zip(("Bloc 1", "Bloc 2"), defaults):
            ttk.Label(dialog, text=label).pack(anchor="w", padx=12)
            editor = tk.Text(dialog, width=58, height=3, wrap=tk.WORD)
            editor.pack(fill=tk.X, padx=12, pady=(2, 8))
            editor.insert("1.0", default)
            editors.append(editor)

        def create_blocks():
            first_text = editors[0].get("1.0", "end-1c").strip()
            second_text = editors[1].get("1.0", "end-1c").strip()
            if not first_text or not second_text:
                messagebox.showerror("Texte manquant", "Les deux blocs doivent contenir du texte.", parent=dialog)
                return
            original = self.selected
            box = original.bbox
            middle = (box.x0 + box.x1) / 2
            baseline = getattr(original, "_translation_baseline", None)
            source_segments = getattr(original, "_translation_segments", [])
            source_text = source_segments[0].get("source") if source_segments else None
            parent_id = getattr(original, "_translation_unit_id", str(original.id))
            used_unit_ids = {
                getattr(word, "_translation_unit_id", "")
                for word in page.resolved.words
            }
            used_unit_ids.update(getattr(page, "_translation_layout_tombstones", {}))
            next_suffix = 1
            new_words = []
            for text, bounds in (
                (first_text, BBox(box.x0, box.y0, middle, box.y1)),
                (second_text, BBox(middle, box.y0, box.x1, box.y1)),
            ):
                while f"manual-p{page.number}-{next_suffix}" in used_unit_ids:
                    next_suffix += 1
                unit_id = f"manual-p{page.number}-{next_suffix}"
                used_unit_ids.add(unit_id)
                next_suffix += 1
                word = Word(
                    id=max((item.id for item in page.resolved.words), default=0) + len(new_words) + 1,
                    text=text, bbox=bounds,
                    font_size=float(getattr(original, "_translation_base_font_size", original.font_size or 10.0)),
                    bold=bool(original.bold), italic=bool(original.italic),
                    source="manual_translation", reconstructed=True,
                )
                word.resolved_text = text
                word._translation_unit_id = unit_id
                word._translation_block_id = word._translation_unit_id
                word._translation_baseline = baseline
                word._translation_base_font_size = float(
                    getattr(original, "_translation_base_font_size", original.font_size or 10.0)
                )
                word._translation_script = getattr(original, "_translation_script", "normal")
                word._translation_segments = []
                word.source_glyph_bboxes = original.source_glyph_bboxes
                word.editor_color = original.editor_color
                new_words.append(word)
            tombstones = getattr(page, "_translation_layout_tombstones", {})
            tombstones[parent_id] = {
                "page": page.number,
                "source": source_text,
                "text": "",
                "bbox": [box.x0, box.y0, box.x1, box.y1],
                "source_glyph_bboxes": [list(bounds) for bounds in original.source_glyph_bboxes],
                "font_size": float(getattr(original, "_translation_base_font_size", original.font_size or 10.0)),
                "bold": bool(original.bold),
                "italic": bool(original.italic),
                "script": getattr(original, "_translation_script", "normal"),
                "editor_color": original.editor_color,
                "deleted": True,
                "split_into": [word._translation_unit_id for word in new_words],
            }
            page._translation_layout_tombstones = tombstones
            _replace_word_with_blocks(page, self.words, original, new_words)
            dialog.destroy()
            self.selected = new_words[0]
            self._load_fields()
            self._refresh_list(getattr(self.selected, "_translation_unit_id", None))
            self._draw_page()

        ttk.Button(dialog, text="Scinder", command=create_blocks).pack(anchor="e", padx=12, pady=(0, 12))

    def _save(self):
        self._commit_fields()
        if self.mode == "vlm":
            missing_boxes = [
                word for word in self.words
                if word.source == "vlm_transcription"
                and (word.resolved_text or word.text or "").strip()
                and not word.bbox
                and not getattr(word, "_translation_deleted", False)
            ]
            if missing_boxes:
                messagebox.showerror(
                    "Boîtes manquantes",
                    f"Tracez une boîte pour chacune des {len(missing_boxes)} ligne(s) restante(s) avant d'enregistrer le PDF.",
                )
                self.status.set("Certaines lignes n'ont pas encore de boîte.")
                return
        try:
            from datacompiler.backend.rebuilt_pdf import render_rebuilt_pdf

            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            render_rebuilt_pdf(self.document, str(self.output_path))
            _save_layout(self.application, self.corrections_path)
        except Exception as exc:
            messagebox.showerror("Enregistrement impossible", str(exc))
            return
        messagebox.showinfo(
            "Édition enregistrée",
            f"PDF : {self.output_path}\nCorrections : {self.corrections_path}",
        )
        self.saved = True
        self._close()

    def _close(self):
        self._preview_dir.cleanup()
        self.destroy()


def edit_translation_pdf(
    document,
    translation: XliffTranslation,
    output_path: str | Path,
    *,
    expected_units: list[TranslationUnit] | None = None,
    corrections_path: str | Path | None = None,
):
    """Open the lightweight editor and save a reviewed PDF plus JSON layout sidecar.

    The sidecar is a versioned, human-readable record keyed by XLIFF unit ID.
    Existing sidecars are reapplied automatically; manual text blocks are
    preserved alongside the translated units.
    """
    if not document.metadata.source_pdf:
        raise ValueError("The source PDF path is required (doc.metadata.source_pdf).")
    application = apply_xliff_translation(
        document, translation, expected_units=expected_units,
    )
    output_path = Path(output_path)
    corrections_path = Path(corrections_path or output_path.with_suffix(".layout.json"))
    _load_layout(application, corrections_path)
    editor = TranslationEditor(application, output_path, corrections_path)
    editor.mainloop()
    return application if editor.saved else None


def edit_document_pdf(
    document,
    output_path: str | Path,
    *,
    corrections_path: str | Path | None = None,
    editor_mode: str = "generic",
):
    """Open the editor on resolved source text without requiring a translation."""
    if not document.metadata.source_pdf:
        raise ValueError("The source PDF path is required (doc.metadata.source_pdf).")
    output_path = Path(output_path)
    corrections_path = Path(corrections_path or output_path.with_suffix(".layout.json"))
    application = SimpleNamespace(document=document, editor_mode=editor_mode)
    if editor_mode == "vlm":
        prepare_vlm_editor_words(document)
    _prepare_generic_words(document)
    _load_layout(application, corrections_path)
    editor = TranslationEditor(application, output_path, corrections_path)
    editor.mainloop()
    return document if editor.saved else None
