"""FAST place headings: the variant table, the approved list, and verification.

Pinned to the 16 place tokens the 2026-07 batch produced that were absent from the old 9-entry list.
See docs/DECISIONS.md D-015.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import _enforce_approved_places, _load_controlled_list
from app.places import DEFAULT_VARIANTS_PATH, PLACE_VARIANTS, canonical_place, load_place_variants
from app.validation_core import validate_core

VOCAB = Path(__file__).resolve().parent.parent / "vocab"
APPROVED = _load_controlled_list(str(VOCAB / "fast_places.txt"))


class VocabularyConsistency(unittest.TestCase):
    def test_every_variant_maps_to_an_approved_heading(self):
        # A mapping to a heading that is not approved would rewrite a place and then reject it.
        missing = sorted({target for target in PLACE_VARIANTS.values() if target not in APPROVED})
        self.assertEqual(missing, [])

    def test_no_variant_is_itself_approved(self):
        # If a variant were also approved, records would carry both forms of the same place.
        approved_lower = {p.lower() for p in APPROVED}
        self.assertEqual(sorted(v for v in PLACE_VARIANTS if v in approved_lower), [])

    def test_old_collection_form_for_washington_is_retired(self):
        self.assertNotIn("District of Columbia--Washington", APPROVED)
        self.assertIn("Washington (D.C.)", APPROVED)


class CanonicalPlace(unittest.TestCase):
    def test_variant_forms_found_in_the_batch(self):
        cases = {
            "New York--New York": "New York (State)--New York",
            "New York--Long Beach": "New York (State)--Long Beach",
            "China--Peking": "China--Beijing",
            "Japan--Kobe": "Japan--Kōbe-shi",
            "Tokyo--Tokyo": "Japan--Tokyo",
            "District of Columbia--Washington": "Washington (D.C.)",
            "Massachusetts--Glouchester": "Massachusetts--Gloucester",
            "Singapore--Singapore": "Singapore",
        }
        for variant, authorized in cases.items():
            with self.subTest(variant=variant):
                self.assertEqual(canonical_place(variant), authorized)

    def test_matching_ignores_case_and_spacing(self):
        self.assertEqual(canonical_place("  china--PEKING "), "China--Beijing")

    def test_unknown_places_pass_through_unchanged(self):
        self.assertEqual(canonical_place("Ohio--Oxford"), "Ohio--Oxford")
        self.assertEqual(canonical_place("Atlantis--Lost City"), "Atlantis--Lost City")

    def test_decomposed_macron_matches(self):
        decomposed = "Japan--Kōbe-shi"  # o + combining macron
        self.assertIn(canonical_place(decomposed), APPROVED)

    def test_malformed_variant_file_is_an_error_not_a_silent_skip(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Ohio--Oxford -> Ohio--Columbus\n")
        with self.assertRaises(ValueError):
            load_place_variants(f.name)


class EnforcementOnTheBatch(unittest.TestCase):
    # The 16 tokens rejected by the old 9-entry list.
    BATCH_TOKENS = [
        "New York--New York", "Japan--Tokyo", "China--Peking", "Philippines--Manila", "Japan--Kobe",
        "Burma--Rangoon", "Colorado--Colorado Springs", "France--Avignon", "Egypt--Cairo",
        "China--Shanghai", "Massachusetts--Williamstown", "New York--Long Beach", "Ohio--Yellow Springs",
        "Illinois--Chicago", "California--Los Angeles", "Tokyo--Tokyo",
        # Dropped silently by the pre-D-014 code and found only in its notes.
        "Singapore--Singapore", "Michigan--Highland Park",
    ]

    def test_every_batch_token_now_resolves_to_an_approved_heading(self):
        for token in self.BATCH_TOKENS:
            with self.subTest(token=token):
                md = {"place": [token]}
                notes = _enforce_approved_places(md, APPROVED)
                self.assertTrue(md["place"], f"{token} was cleared; notes: {notes}")
                self.assertIn(md["place"][0], APPROVED)

    def test_a_corrected_place_is_recorded_in_the_notes(self):
        md = {"place": ["China--Peking", "Ohio--Oxford"]}
        notes = _enforce_approved_places(md, APPROVED)
        self.assertEqual(md["place"], ["China--Beijing", "Ohio--Oxford"])  # sender stays first
        self.assertTrue(any("China--Peking" in n and "China--Beijing" in n for n in notes))

    def test_two_variants_of_one_place_collapse_to_one(self):
        md = {"place": ["Japan--Tokyo", "Tokyo--Tokyo"]}
        _enforce_approved_places(md, APPROVED)
        self.assertEqual(md["place"], ["Japan--Tokyo"])

    def test_an_unknown_place_is_still_rejected(self):
        md = {"place": ["Atlantis--Lost City"]}
        notes = _enforce_approved_places(md, APPROVED)
        self.assertIsNone(md["place"])
        self.assertTrue(any("Atlantis--Lost City" in n for n in notes))


class RebuildReviewTrail(unittest.TestCase):
    def test_a_rejection_note_does_not_outlive_the_rejection(self):
        """AAMU-0013 kept "France--Avignon absent from the approved list" after Avignon was approved."""
        import json
        import tempfile
        from app.main import rebuild_existing_outputs
        stale = {
            "metadata": {
                "title": "Letter from Avignon, 1950", "date": "1950-01-01", "decade": "1950-1959",
                "transcript": "[page 1]\nDear Sir,", "subjects": ["Correspondence"],
                "genre": ["correspondence"], "place": "France--Avignon",
            },
            "metadata_tiers": {}, "field_provenance": {},
            "context": {"policy_notes": [
                "Place tokens absent from the approved FAST list: France--Avignon",
                "NEEDS VOCAB REVIEW: no approved FAST place matched; original value kept unvalidated.",
            ]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "X-0001.loc15.json"
            path.write_text(json.dumps(stale), encoding="utf-8")
            rebuild_existing_outputs(
                out_dir=tmp, defaults={}, apply_reviews=False, approved_places=APPROVED,
                approved_subjects={"Correspondence"}, approved_genre={"correspondence"},
                online_vocab_advisory=False,
            )
            rebuilt = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(rebuilt["metadata"]["place"], ["France--Avignon"])
        notes = rebuilt["context"].get("policy_notes") or []
        self.assertFalse([n for n in notes if "France--Avignon" in n or "NEEDS VOCAB REVIEW" in n], notes)


class SchemaShape(unittest.TestCase):
    def test_schema_accepts_every_approved_heading(self):
        from jsonschema import Draft7Validator
        from app.schema import LOC15_SCHEMA
        item = Draft7Validator(LOC15_SCHEMA["properties"]["place"]["items"])
        rejected = sorted(h for h in APPROVED if not item.is_valid(h))
        self.assertEqual(rejected, [], "the schema must not reject an approved FAST heading")

    def test_schema_still_rejects_joined_and_city_state_forms(self):
        from jsonschema import Draft7Validator
        from app.schema import LOC15_SCHEMA
        item = Draft7Validator(LOC15_SCHEMA["properties"]["place"]["items"])
        for bad in ("Ohio--Oxford; Ohio--Columbus", "Oxford, Ohio"):
            with self.subTest(value=bad):
                self.assertFalse(item.is_valid(bad))


class CoreValidation(unittest.TestCase):
    def test_jurisdiction_heading_without_double_dash_is_valid(self):
        # "Washington (D.C.)" is not State--City shaped, but it is FAST's authorized heading.
        issues = validate_core({"place": ["Washington (D.C.)"]}, transcript=None, approved_places=APPROVED)
        place_errors = [e for e in issues.get("errors", []) if e.get("field") == "place"]
        self.assertEqual(place_errors, [])


class FastVerificationRequiresAnId(unittest.TestCase):
    """A label with no FAST id is a see-reference. Both verifiers used to accept it."""

    def _response(self, docs):
        resp = mock.Mock()
        resp.raise_for_status = mock.Mock()
        resp.json = mock.Mock(return_value={"response": {"docs": docs}})
        resp.content = b"{}"
        return resp

    def test_vocab_builder_rejects_a_see_reference(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import expand_vocab_from_run as builder
        see_reference = [{"suggestall": ["China--Peking"]}]
        with mock.patch.object(builder.requests, "get", return_value=self._response(see_reference)):
            ok, _, _, _ = builder.verify_fast("China--Peking", "places")
        self.assertFalse(ok)
        authorized = [{"suggestall": ["China--Beijing"], "idroot": ["fst01205740"]}]
        with mock.patch.object(builder.requests, "get", return_value=self._response(authorized)):
            ok, heading, fst, _ = builder.verify_fast("China--Beijing", "places")
        self.assertEqual((ok, heading, fst), (True, "China--Beijing", "fst01205740"))

    def test_runtime_validator_rejects_a_see_reference(self):
        from app import vocab_validation
        with mock.patch.object(vocab_validation, "_get_cache", return_value=None), \
             mock.patch.object(vocab_validation, "_set_cache"), \
             mock.patch.object(vocab_validation.requests, "get",
                               return_value=self._response([{"suggestall": ["China--Peking"]}])):
            result = vocab_validation.validate_fast_subject("China--Peking")
        self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main()


class ReviewedPlaces(unittest.TestCase):
    """D-017: a reviewer can set place; the vocabulary still applies; provenance says who set it."""

    def _record(self, tmp, stem="X-0001", **md):
        import json
        base = {
            "title": "Letter, 1925", "date": "1925-04-24", "decade": "1920-1929",
            "transcript": "[page 1]\nDear Mr. Huang:", "subjects": ["Correspondence"],
            "genre": ["correspondence"], "place": None,
        }
        base.update(md)
        path = Path(tmp) / f"{stem}.loc15.json"
        path.write_text(json.dumps({"metadata": base, "metadata_tiers": {}, "field_provenance": {}, "context": {}}),
                        encoding="utf-8")
        return path

    def _rebuild(self, tmp, apply_reviews=True):
        from app.main import rebuild_existing_outputs
        rebuild_existing_outputs(
            out_dir=tmp, defaults={}, apply_reviews=apply_reviews, approved_places=APPROVED,
            approved_subjects={"Correspondence"}, approved_genre={"correspondence"}, online_vocab_advisory=False,
        )

    def test_override_accepts_a_list_or_a_semicolon_string(self):
        from app.ai_metadata import apply_review_overrides, reviewed_fields
        md, _ = apply_review_overrides({"place": None}, {"overrides": {"place": ["Ohio--Oxford"]}})
        self.assertEqual(md["place"], ["Ohio--Oxford"])
        md, _ = apply_review_overrides({"place": None}, {"overrides": {"place": "Ohio--Cincinnati; Ohio--Oxford"}})
        self.assertEqual(md["place"], ["Ohio--Cincinnati", "Ohio--Oxford"])
        self.assertEqual(reviewed_fields({"overrides": {"place": ["Ohio--Oxford"]}}), ["place"])

    def test_rebuild_applies_the_review_and_records_why_and_by_whom(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self._record(tmp)
            (Path(tmp) / "X-0001.review.json").write_text(json.dumps({
                "overrides": {"place": ["Ohio--Oxford"]},
                "evidence": {"place": "Written by President R. M. Hughes."},
                "reviewer": "Meng Qu", "reviewed_on": "2026-10-05",
            }), encoding="utf-8")
            self._rebuild(tmp)
            env = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(env["metadata"]["place"], ["Ohio--Oxford"])
            self.assertEqual(env["field_provenance"]["place"], "Human-Reviewed")
            note = next(n for n in env["context"]["policy_notes"] if "review override for 'place'" in n)
            self.assertIn("R. M. Hughes", note)
            self.assertIn("Meng Qu", note)

            # The reviewed value stays on a later rebuild that does not re-apply reviews.
            self._rebuild(tmp, apply_reviews=False)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["metadata"]["place"], ["Ohio--Oxford"])

    def test_a_review_cannot_bypass_the_vocabulary(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self._record(tmp)
            (Path(tmp) / "X-0001.review.json").write_text(
                json.dumps({"overrides": {"place": ["Ohio--Oxfrod"]}}), encoding="utf-8")
            self._rebuild(tmp)
            env = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsNone(env["metadata"]["place"])
            self.assertTrue(any("Ohio--Oxfrod" in n for n in env["context"]["policy_notes"]))
