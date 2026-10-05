"""Post-extraction field validation, pinned to the defects found importing the 128-item batch.

Every rejected string below is verbatim from out_batch/ (2026-07 run). See docs/DECISIONS.md D-014.
"""

import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.exporters import to_sample_row
from app.field_validation import name_problem, place_tokens, validate_name_fields
from app.main import Draft7Validator, _enforce_post_extraction, _validate, rebuild_existing_outputs
from export_csv import map_json_to_csv_row

PLACES = {"Ohio--Oxford", "Washington (D.C.)", "Japan--Osaka"}
EMPTY_DEFAULTS = {
    "series": None, "folder": None, "box": None, "identifier": None, "call_number": None,
    "digital_identifier": None, "reproduction_number": None, "digital_collection": None,
    "digital_publisher": None, "digitized": None,
}

# (item, string, expected reason fragment)
REJECTED = [
    ("AAMU-0003", "Iso, J. Yun H. T., I. S. O.? No. Need exact. Wait.", "reasoning"),
    ("AAMU-0003", "Dockery, F. Jean`,`Ellis, Gloria B.`", "joined by quote"),
    ("AAMU-0058", "Rifat, Fereed','Wang, Sadie','Wang, Helen','Chalufour-Bishop, Marguerite", "joined by quote"),
    ("AAMU-0098", "Brooks, Ronald, Burton, Kay", "more than one comma"),
    ("AAMU-0076", "Spadaro, Anita Zucco, Maria Elisabetta?", "reasoning"),
    ("AAMU-0020", "Runyon, Louisa Runyon Shera, [unclear]", "more than one comma"),
    ("AAMU-0088", "Bendbow, Sodienyehyeh?", "reasoning"),
]

# Real single names from the same batch that must survive.
ACCEPTED = [
    "Cox, Joseph III",
    "Davis, Willis (Bing)",
    "Lasmarias, Vincente Benigno [sic]",
    "Boateng, Agyenim [unclear]",
    "Emerson, [first name unknown]",
    "McDonald, Ozzie [first name not provided]",
    "Sarmiento Reva, Maria de la Asuncion Olga",
    "Lindegren, Alina M. (Alina M. Lindegren)",
    "Au Yeung, Chun Kwan",
    "Rama V",
    "Peggy",
    "Alfred H. Upham",
    "Y. M. C. A.",
    "Leland Stanford Junior University",
    # Not in the batch, but standard forms the comma rule must not break.
    "King, Martin Luther, Jr.",
    "Upham, Alfred H., 1877-1945",
    "O'Brien, Patrick",
]


def _envelope(**metadata):
    base = {
        "title": "Letter to the president, 19 October 1937",
        "date": "1937-10-19",
        "decade": "1930-1939",
        "transcript": "[page 1]\nDear Sir,",
        "subjects": ["Correspondence"],
        "genre": ["correspondence"],
    }
    base.update(metadata)
    return {"metadata": base, "metadata_tiers": {}, "field_provenance": {}, "context": {}}


def _rebuild(tmp, approved_places=PLACES):
    rebuild_existing_outputs(
        out_dir=tmp, defaults=dict(EMPTY_DEFAULTS), apply_reviews=False,
        approved_places=approved_places, approved_subjects={"Correspondence"},
        approved_genre={"correspondence"}, online_vocab_advisory=False,
    )


class NameProblemTests(unittest.TestCase):
    def test_real_defects_are_rejected_with_a_reason(self):
        for item, value, reason in REJECTED:
            with self.subTest(item=item, value=value):
                problem = name_problem(value)
                self.assertIsNotNone(problem)
                self.assertIn(reason, problem)

    def test_real_single_names_are_accepted(self):
        for value in ACCEPTED:
            with self.subTest(value=value):
                self.assertIsNone(name_problem(value))


class NameFieldTests(unittest.TestCase):
    def test_aamu_0003_keeps_good_names_and_drops_both_bad_ones(self):
        md = {"contributors": ["Bennett, Samuel", "Dockery, F. Jean`,`Ellis, Gloria B.`",
                               "Terrell, Willie", "Iso, J. Yun H. T., I. S. O.? No. Need exact. Wait."]}
        rejected = validate_name_fields(md)
        self.assertEqual(md["contributors"], ["Bennett, Samuel", "Terrell, Willie"])
        self.assertEqual(len(rejected["contributors"]), 2)

    def test_quote_joined_entry_carries_a_suggested_split_but_is_not_split(self):
        md = {"contributors": ["Hasegawa, Koichi",
                               "Rifat, Fereed','Wang, Sadie','Wang, Helen','Chalufour-Bishop, Marguerite"]}
        rejected = validate_name_fields(md)
        self.assertEqual(md["contributors"], ["Hasegawa, Koichi"])
        self.assertEqual(rejected["contributors"][0]["suggested_split"],
                         ["Rifat, Fereed", "Wang, Sadie", "Wang, Helen", "Chalufour-Bishop, Marguerite"])

    def test_creator_string_is_cleared_and_list_emptied_to_none(self):
        md = {"creator": "Spadaro, Anita Zucco, Maria Elisabetta?",
              "correspondents": ["Brooks, Ronald, Burton, Kay"]}
        validate_name_fields(md)
        self.assertIsNone(md["creator"])
        self.assertIsNone(md["correspondents"])

    def test_clean_fields_are_untouched(self):
        md = {"creator": "Upham, Alfred H.", "correspondents": ["Upham, Alfred H.", "Sheehan, Murray"]}
        self.assertEqual(validate_name_fields(md), {})
        self.assertEqual(md["correspondents"], ["Upham, Alfred H.", "Sheehan, Murray"])

    def test_rejections_reach_the_notes_and_context(self):
        md = {"contributors": ["Brooks, Ronald, Burton, Kay"], "subjects": ["Correspondence"]}
        notes, context = _enforce_post_extraction(md, PLACES, {"Correspondence"}, set())
        self.assertTrue(any(n.startswith("NEEDS NAME REVIEW") and "Brooks, Ronald, Burton, Kay" in n
                            for n in notes))
        self.assertEqual(context["rejected_names"]["contributors"][0]["value"], "Brooks, Ronald, Burton, Kay")


class PlaceTests(unittest.TestCase):
    def test_semicolon_string_becomes_an_array(self):
        md = {"place": "Ohio--Oxford; Washington (D.C.)"}
        _enforce_post_extraction(md, PLACES, set(), set())
        self.assertEqual(md["place"], ["Ohio--Oxford", "Washington (D.C.)"])

    def test_tokyo_tokyo_is_rejected_not_kept(self):
        """AAMU-0102. Not a FAST heading; it used to survive as 'unvalidated'."""
        md = {"place": "Tokyo--Tokyo"}
        notes, _ = _enforce_post_extraction(md, PLACES, set(), set())
        self.assertIsNone(md["place"])
        self.assertIn("Place tokens absent from the approved FAST list: Tokyo--Tokyo", notes)

    @unittest.skipIf(Draft7Validator is None, "jsonschema not installed")
    def test_array_place_passes_the_schema_and_a_string_does_not(self):
        md = _envelope(place=["Ohio--Oxford", "Japan--Osaka"])["metadata"]
        self.assertNotIn("place", _validate(md))
        md["place"] = "Ohio--Oxford; Japan--Osaka"
        self.assertIn("place", _validate(md))
        md["place"] = ["Ohio--Oxford; Japan--Osaka"]
        self.assertIn("place", _validate(md))

    def test_place_tokens_reads_both_shapes(self):
        self.assertEqual(place_tokens("Ohio--Oxford;  Japan--Osaka "), ["Ohio--Oxford", "Japan--Osaka"])
        self.assertEqual(place_tokens(["Ohio--Oxford"]), ["Ohio--Oxford"])
        self.assertEqual(place_tokens(None), [])


class TypeTests(unittest.TestCase):
    def test_model_type_is_dropped_with_a_note(self):
        for value in ("Text", "text", "memorandum", "correspondence"):
            with self.subTest(value=value):
                md = {"type": value}
                notes, _ = _enforce_post_extraction(md, set(), set(), set())
                self.assertIsNone(md["type"])
                self.assertTrue(any(value in n for n in notes))


class CsvCompatibilityTests(unittest.TestCase):
    """The April spreadsheet's Location column must come out byte-identical for either shape."""

    def test_location_column_is_unchanged_by_the_array_shape(self):
        legacy = _envelope(place="Ohio--Oxford; Washington (D.C.)")
        current = _envelope(place=["Ohio--Oxford", "Washington (D.C.)"])
        for mapper in (lambda e: map_json_to_csv_row(e, "X.loc15.json"), to_sample_row):
            self.assertEqual(mapper(current)["Location"], mapper(legacy)["Location"])
            self.assertEqual(mapper(current)["Location"], "Ohio--Oxford; Washington (D.C.)")
        buffer = io.StringIO()
        csv.writer(buffer).writerow([map_json_to_csv_row(current, "X.loc15.json")["Location"]])
        self.assertEqual(buffer.getvalue().strip(), "Ohio--Oxford; Washington (D.C.)")


class RebuildTests(unittest.TestCase):
    def _write(self, tmp, **metadata):
        path = Path(tmp) / "AAMU-0003.loc15.json"
        path.write_text(json.dumps(_envelope(**metadata)), encoding="utf-8")
        return path

    def test_rebuild_is_idempotent_and_keeps_the_review_trail(self):
        """A second rebuild must not lose rejections the first one removed from the metadata."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, contributors=["Bennett, Samuel", "Brooks, Ronald, Burton, Kay"],
                               place="Tokyo--Tokyo", type="text")
            _rebuild(tmp)
            first = json.loads(path.read_text())
            _rebuild(tmp)
            second = json.loads(path.read_text())
            for envelope in (first, second):
                self.assertEqual(envelope["metadata"]["contributors"], ["Bennett, Samuel"])
                self.assertIsNone(envelope["metadata"]["place"])
                notes = " ".join(envelope["context"]["policy_notes"])
                self.assertIn("Brooks, Ronald, Burton, Kay", notes)
                self.assertIn("Tokyo--Tokyo", notes)
            self.assertEqual(first["context"]["rejected_names"], second["context"]["rejected_names"])

    def test_vocab_growth_restores_a_place_in_its_original_position(self):
        """The first token means sender; re-offering must not move it behind the recipient."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, place="Japan--Tokyo; Ohio--Oxford")
            _rebuild(tmp)
            self.assertEqual(json.loads(path.read_text())["metadata"]["place"], ["Ohio--Oxford"])
            _rebuild(tmp, approved_places=PLACES | {"Japan--Tokyo"})
            after = json.loads(path.read_text())
            self.assertEqual(after["metadata"]["place"], ["Japan--Tokyo", "Ohio--Oxford"])
            self.assertNotIn("place_as_extracted", after["context"])


if __name__ == "__main__":
    unittest.main()


class NameListsAreNotCapped(unittest.TestCase):
    """D-016: a schema limit must never remove a person from the record."""

    def test_no_name_field_has_a_maximum(self):
        from app.schema import LOC15_SCHEMA
        for field in ("contributors", "correspondents"):
            with self.subTest(field=field):
                self.assertNotIn("maxItems", LOC15_SCHEMA["properties"][field])

    def test_a_document_naming_22_people_validates(self):
        md = _envelope(contributors=[f"Person{i}, Test" for i in range(22)])["metadata"]
        problems = [e for e in Draft7Validator(__import__("app.schema", fromlist=["LOC15_SCHEMA"]).LOC15_SCHEMA).iter_errors(md)
                    if list(e.path)[:1] == ["contributors"]]
        self.assertEqual(problems, [])


class RebuildClearsStaleValidationError(unittest.TestCase):
    def test_a_fixed_record_is_no_longer_flagged(self):
        from app.main import _validate
        from app.schema import LOC15_SCHEMA
        envelope = _envelope(contributors=[f"Person{i}, Test" for i in range(22)])
        md = envelope["metadata"]
        for key in LOC15_SCHEMA["required"]:  # a complete, valid record: only the stale flag is wrong
            if key not in md:
                spec = LOC15_SCHEMA["properties"][key]
                md[key] = {k: None for k in spec["properties"]} if key == "field_confidence" else None
        self.assertEqual(_validate(md), "", "fixture must be valid, or the test proves nothing")
        envelope["context"]["validation_error"] = "contributors: [...] is too long"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "X-0001.loc15.json"
            path.write_text(json.dumps(envelope), encoding="utf-8")
            _rebuild(tmp)
            rebuilt = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(rebuilt["metadata"]["contributors"]), 22)
        self.assertNotIn("validation_error", rebuilt["context"])
