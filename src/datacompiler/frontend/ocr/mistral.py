"""Run Mistral OCR on selected pages and retain its semantic and structured output."""

import base64
import logging
import os

from datacompiler.frontend.ocr.base import OcrBackend
from datacompiler.model.document import Document, OcrBlock, TableElement, Word
from datacompiler.model.geometry import BBox

logger = logging.getLogger(__name__)
MODEL_NAME = "mistral-ocr-latest"


def _value(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _serializable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _serializable(item)
            for key, item in value.items()
            if "base64" not in str(key).lower()
        }
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _serializable(value.model_dump(mode="json"))
    if hasattr(value, "__dict__"):
        return _serializable(vars(value))
    return str(value)


def _bbox(value, page, dimensions):
    bounds = _value(value, "bbox", value)
    if isinstance(bounds, dict):
        coordinates = [
            _value(bounds, key)
            for key in ("x0", "y0", "x1", "y1")
        ]
        if any(item is None for item in coordinates):
            coordinates = [
                _value(bounds, key)
                for key in ("top_left_x", "top_left_y", "bottom_right_x", "bottom_right_y")
            ]
    elif isinstance(bounds, (list, tuple)) and len(bounds) == 4:
        coordinates = list(bounds)
    else:
        return None
    try:
        x0, y0, x1, y1 = (float(value) for value in coordinates)
    except (TypeError, ValueError):
        return None

    width = _value(dimensions, "width")
    height = _value(dimensions, "height")
    if width and height:
        x_scale, y_scale = page.width / float(width), page.height / float(height)
        x0, x1 = x0 * x_scale, x1 * x_scale
        y0, y1 = y0 * y_scale, y1 * y_scale
    return BBox(x0, y0, x1, y1)


def _table_element(raw_table, page, index, dimensions):
    raw_rows = _value(raw_table, "rows", [])
    rows = []
    cell_bboxes = []
    for raw_row in raw_rows or []:
        row, boxes = [], []
        for raw_cell in raw_row:
            content = _value(raw_cell, "content", _value(raw_cell, "text", raw_cell))
            row.append(str(content) if content is not None else "")
            boxes.append(_bbox(raw_cell, page, dimensions))
        rows.append(row)
        cell_bboxes.append(boxes)
    return TableElement(
        id=index,
        bbox=_bbox(raw_table, page, dimensions),
        source="mistral",
        rows=rows,
        cell_bboxes=cell_bboxes,
    )


class MistralBackend(OcrBackend):
    name = "mistral"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY")

    def ocraliser(self, doc: Document, pdf_path: str, pages: list = None, **kwargs) -> Document:
        api_key = kwargs.get("api_key") or self.api_key
        if not api_key:
            raise ValueError(
                "Missing Mistral API key. Set the MISTRAL_API_KEY environment "
                "variable or pass the key when creating the backend."
            )

        page_numbers = sorted(set(pages)) if pages is not None else None
        if page_numbers == []:
            return doc

        from mistralai.client import Mistral

        client = Mistral(api_key=api_key)
        with open(pdf_path, "rb") as pdf_file:
            pdf_base64 = base64.b64encode(pdf_file.read()).decode("utf-8")

        request = {
            "model": MODEL_NAME,
            "document": {
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{pdf_base64}",
            },
        }
        if page_numbers is not None:
            request["pages"] = [number - 1 for number in page_numbers]
        response = client.ocr.process(**request)
        logger.debug("Mistral OCR returned %d pages", len(response.pages))

        for page_result in response.pages:
            page_index = _value(page_result, "index")
            if page_index is None:
                raise ValueError("Mistral OCR returned a page without an index.")
            if page_index < 0 or page_index >= len(doc.pages):
                continue
            if page_numbers is not None and page_index + 1 not in page_numbers:
                continue

            page_obj = doc.pages[page_index]
            markdown = _value(page_result, "markdown") or ""
            page_obj.ocr.engine = f"mistral-{MODEL_NAME}"
            page_obj.ocr.words = [
                Word(
                    id=-1,
                    text=token,
                    resolved_text=token,
                    source="ocr",
                )
                for token in markdown.split()
            ]

            dimensions = _value(page_result, "dimensions")
            raw_blocks = _value(page_result, "blocks", None)
            blocks = []
            for raw_block in raw_blocks or []:
                content = _value(raw_block, "content", _value(raw_block, "text", ""))
                blocks.append(
                    OcrBlock(
                        bbox=_bbox(raw_block, page_obj, dimensions),
                        type=str(_value(raw_block, "type", "text")),
                        content=str(content or ""),
                        confidence=_value(raw_block, "confidence"),
                        metadata={"source": "mistral"},
                    )
                )
            if markdown:
                blocks.append(
                    OcrBlock(
                        type="markdown",
                        content=markdown,
                        metadata={"source": "mistral"},
                    )
                )
            page_obj.ocr.blocks = blocks

            page_obj.graphics.tables = [
                table for table in page_obj.graphics.tables
                if table.source != "mistral"
            ]
            raw_tables = _value(page_result, "tables", None)
            if raw_tables:
                first_table_id = max(
                    (table.id for table in page_obj.graphics.tables),
                    default=0,
                ) + 1
                page_obj.graphics.tables.extend(
                    _table_element(table, page_obj, first_table_id + offset, dimensions)
                    for offset, table in enumerate(raw_tables)
                )

            structured_metadata = {
                key: _serializable(_value(page_result, key))
                for key in ("dimensions", "images", "confidence")
                if _value(page_result, key) is not None
            }
            for block in page_obj.ocr.blocks:
                block.metadata.update(structured_metadata)

        return doc
