import json
import unittest
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:  # The schema validator is installed by the optional dev extra.
    Draft202012Validator = None

from datacompiler.model.document import Document, Page, Word


SCHEMA_PATH = Path(__file__).parents[1] / "docs" / "schemas" / "document.schema.json"


class DocumentJsonSchemaTests(unittest.TestCase):
    @unittest.skipIf(Draft202012Validator is None, "install the dev extra to validate JSON Schema")
    def test_json_is_utf8_readable_and_matches_schema(self):
        document = Document(pages=[Page(number=1, width=612, height=792)])
        document.pages[0].resolved.words.append(Word(id=1, text="Éléphant déjà vu"))

        payload = document.to_json()
        data = json.loads(payload)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertIn("Éléphant déjà vu", payload)
        self.assertEqual(data["schema_version"], "1.0")
        Draft202012Validator(schema).validate(data)

    @unittest.skipIf(Draft202012Validator is None, "install the dev extra to validate JSON Schema")
    def test_schema_rejects_missing_version_and_malformed_words(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        invalid = {"metadata": {}, "pages": [{"number": 1, "width": 1, "height": 1,
                                                    "resolved": {"words": [{"id": 1}]}}]}
        self.assertFalse(validator.is_valid(invalid))

    def test_legacy_json_without_version_remains_loadable(self):
        document = Document.from_dict({"metadata": {}, "pages": []})
        self.assertEqual(document.pages, [])

    def test_unknown_schema_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported JSON schema version"):
            Document.from_dict({"schema_version": "99.0", "pages": []})


if __name__ == "__main__":
    unittest.main()
