"""Optional lightweight desktop editor for translated PDF segment layout."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError:  # Keep the non-GUI translation API usable without Tk support.
    tk = None
    messagebox = None
    ttk = None

import pymupdf
from datacompiler.model.document import Word
from datacompiler.model.geometry import BBox
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
            if word.bbox is None:
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


def _replace_word_with_blocks(page, editor_words, original, replacements):
    page_index = page.resolved.words.index(original)
    editor_index = editor_words.index(original)
    page.resolved.words[page_index:page_index + 1] = replacements
    editor_words[editor_index:editor_index + 1] = replacements


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
            units[unit_id] = {
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
                "deleted": bool(getattr(word, "_translation_deleted", False)),
                "order": order,
            }
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
        if word.bbox is not None
        and (
            word.source in {"xliff_translation", "manual_translation"}
            or getattr(word, "_editor_generic", False)
        )
    }
    split_parent_ids = set()
    manual_records = []
    for unit_id, record in payload.get("units", {}).items():
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
            if self.mode == "generic"
            else _translation_words(application)
        )
        self.by_id = {getattr(word, "_translation_unit_id", str(word.id)): word for word in self.words}
        self.selected = None
        self.scale = 1.0
        self.photo = None
        self.image_item = None
        self.drag = None
        self.saved = False
        self._preview_dir = tempfile.TemporaryDirectory(prefix="datacompiler-editor-")
        self.preview_path = Path(self._preview_dir.name) / "preview.pdf"
        title = (
            "DataCompiler — édition du document"
            if self.mode == "generic"
            else "DataCompiler — édition légère des segments"
        )
        self.title(title)
        self.geometry("1320x900")
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
        root.add(left, weight=1)
        root.add(right, weight=4)

        list_title = (
            "Texte résolu et blocs manuels"
            if self.mode == "generic"
            else "Segments traduits et blocs manuels"
        )
        ttk.Label(left, text=list_title).pack(anchor="w")
        ttk.Label(
            left,
            text="Ctrl/Cmd+clic ou Maj+clic pour sélectionner plusieurs blocs.",
            wraplength=330,
        ).pack(anchor="w")
        self.segment_list = tk.Listbox(left, width=48, exportselection=False)
        self.segment_list.configure(selectmode=tk.EXTENDED)
        self.segment_list.pack(fill=tk.BOTH, expand=True, pady=(4, 8))
        self.segment_list.bind("<<ListboxSelect>>", self._select_from_list)
        self.segment_list.bind("<ButtonRelease-1>", self._list_click_released, add="+")
        self.segment_list.bind("<KeyRelease>", self._list_key_released, add="+")
        ttk.Button(left, text="Ajouter un bloc texte", command=self._add_text).pack(fill=tk.X)
        ttk.Button(left, text="Scinder le segment en deux", command=self._split_selected).pack(fill=tk.X, pady=(4, 0))
        self.delete_button = ttk.Button(left, command=self._toggle_deleted)
        self.delete_button.pack(fill=tk.X, pady=(4, 0))
        self.reference_value = tk.StringVar(value="Référence : aucune")
        ttk.Label(left, textvariable=self.reference_value, wraplength=330).pack(
            anchor="w", pady=(8, 2),
        )

        alignments = ttk.LabelFrame(left, text="Aligner les blocs sélectionnés", padding=6)
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

        controls = ttk.LabelFrame(left, text="Segment sélectionné", padding=8)
        controls.pack(fill=tk.X, pady=8)
        text_label = "Texte édité" if self.mode == "generic" else "Texte cible"
        ttk.Label(controls, text=text_label).grid(row=0, column=0, columnspan=2, sticky="w")
        self.text_value = tk.Text(controls, width=36, height=5, wrap=tk.WORD)
        self.text_value.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 6))
        ttk.Label(controls, text="Taille (pt)").grid(row=2, column=0, sticky="w")
        self.size_value = tk.StringVar(value="10")
        ttk.Spinbox(controls, from_=1, to=120, increment=0.5, textvariable=self.size_value, width=10).grid(row=2, column=1, sticky="e")
        self.bold_value = tk.BooleanVar()
        self.italic_value = tk.BooleanVar()
        ttk.Checkbutton(controls, text="Gras", variable=self.bold_value).grid(row=3, column=0, sticky="w")
        ttk.Checkbutton(controls, text="Italique", variable=self.italic_value).grid(row=3, column=1, sticky="w")
        ttk.Label(controls, text="Position verticale").grid(row=4, column=0, sticky="w", pady=(4, 0))
        self.script_value = tk.StringVar(value="normal")
        ttk.Combobox(
            controls, textvariable=self.script_value, state="readonly", width=14,
            values=("normal", "superscript", "subscript"),
        ).grid(row=4, column=1, sticky="e", pady=(4, 0))
        ttk.Button(controls, text="Appliquer et prévisualiser", command=self._apply_and_preview).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        footer = ttk.Frame(left)
        footer.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(footer, text="Enregistrer le PDF et les corrections", command=self._save).pack(fill=tk.X)
        self.status = tk.StringVar(value="Glissez un segment pour le déplacer ; tirez son coin inférieur droit pour le redimensionner.")
        ttk.Label(left, textvariable=self.status, wraplength=330).pack(anchor="w", pady=6)

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

    def _refresh_list(self, keep_id=None):
        self.segment_list.delete(0, tk.END)
        for word in self.words:
            unit_id = getattr(word, "_translation_unit_id", str(word.id))
            page_num = next((page.number for page in self.document.pages if word in page.resolved.words), "?")
            text = (word.resolved_text or word.text or "").replace("\n", " ")
            deleted = " [supprimé]" if getattr(word, "_translation_deleted", False) else ""
            self.segment_list.insert(tk.END, f"p.{page_num}  {unit_id}  |  {text[:46]}{deleted}")
            if unit_id == keep_id:
                self.segment_list.selection_set(tk.END)
                self.segment_list.see(tk.END)

    def _select_from_list(self, _event=None):
        selection = self.segment_list.curselection()
        if not selection:
            return
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
        deleted = bool(getattr(word, "_translation_deleted", False))
        self.delete_button.configure(
            text="Restaurer le bloc" if deleted else "Supprimer le bloc"
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
        if self.drag:
            self.drag = None
            self._apply_and_preview()

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
):
    """Open the editor on resolved source text without requiring a translation."""
    if not document.metadata.source_pdf:
        raise ValueError("The source PDF path is required (doc.metadata.source_pdf).")
    output_path = Path(output_path)
    corrections_path = Path(corrections_path or output_path.with_suffix(".layout.json"))
    application = SimpleNamespace(document=document, editor_mode="generic")
    _prepare_generic_words(document)
    _load_layout(application, corrections_path)
    editor = TranslationEditor(application, output_path, corrections_path)
    editor.mainloop()
    return document if editor.saved else None
