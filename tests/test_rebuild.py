"""Rebuild must be lossless, or it cannot be used to re-apply an expanded vocabulary.

The reported "few-shot rebuild strips transcript" bug does not reproduce: rebuild preserves every
metadata key, top-level key and context key across both the gpt-4o baseline and current v4 output.
What it DID do was silently wipe Tier 3, which is the real blocker for the intended workflow of
expanding the controlled vocabularies and rebuilding.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import rebuild_existing_outputs

EMPTY_DEFAULTS = {
    "series": None, "folder": None, "box": None, "identifier": None, "call_number": None,
    "digital_identifier": None, "reproduction_number": None, "digital_collection": None,
    "digital_publisher": None, "digitized": None,
}


def _envelope(**metadata):
    base = {
        "title": "Letter to the president, 19 October 1937",
        "date": "1937-10-19",
        "transcript": "[page 1]\nDear Sir,\n\nSincerly [Sincerely] yours",
        "language": "English",
        "subjects": ["Correspondence"],
        "genre": ["correspondence"],
        "description": "A letter.",
    }
    base.update(metadata)
    return {
        "metadata": base,
        "metadata_tiers": {},
        "field_provenance": {},
        "context": {"model": "gpt-5.6-terra", "custom_note": "keep me"},
    }


def _rebuild(tmp, defaults=None, **kwargs):
    rebuild_existing_outputs(
        out_dir=tmp,
        defaults=dict(defaults or EMPTY_DEFAULTS),
        apply_reviews=False,
        approved_places=set(),
        approved_subjects={"Correspondence"},
        approved_genre={"correspondence"},
        online_vocab_advisory=False,
        **kwargs,
    )


class RebuildLosslessTests(unittest.TestCase):
    def test_transcript_and_other_fields_survive(self):
        """The originally reported failure mode. It does not occur."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "BC-0692_Recto.loc15.json"
            before = _envelope()
            path.write_text(json.dumps(before), encoding="utf-8")
            _rebuild(tmp)
            after = json.loads(path.read_text())
            self.assertEqual(after["metadata"]["transcript"], before["metadata"]["transcript"])
            self.assertEqual(after["metadata"]["language"], "English")
            for key in before["metadata"]:
                self.assertIn(key, after["metadata"], f"{key} disappeared from metadata")

    def test_context_entries_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "X.loc15.json"
            path.write_text(json.dumps(_envelope()), encoding="utf-8")
            _rebuild(tmp)
            context = json.loads(path.read_text())["context"]
            self.assertEqual(context["custom_note"], "keep me")
            self.assertTrue(context["rebuilt_from_existing"])


class RebuildTier3Tests(unittest.TestCase):
    """Tier 3 is archival placement. Losing it on rebuild is real data loss."""

    def test_existing_tier3_is_carried_forward(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "BC-0692_Recto.loc15.json"
            path.write_text(json.dumps(_envelope(
                box="Box 12", folder="Folder 3", identifier="BC-0692",
                repository="Miami University Libraries",
            )), encoding="utf-8")
            _rebuild(tmp)
            envelope = json.loads(path.read_text())
            md = envelope["metadata"]
            self.assertEqual(md["box"], "Box 12")
            self.assertEqual(md["folder"], "Folder 3")
            self.assertEqual(md["identifier"], "BC-0692")
            self.assertEqual(md["repository"], "Miami University Libraries")
            self.assertTrue(any("Preserved existing Tier 3" in n
                                for n in envelope["context"].get("policy_notes", [])))

    def test_explicit_default_overrides_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Y.loc15.json"
            path.write_text(json.dumps(_envelope(box="Box 12", folder="Folder 3")), encoding="utf-8")
            _rebuild(tmp, defaults={**EMPTY_DEFAULTS, "box": "Box 99"})
            md = json.loads(path.read_text())["metadata"]
            self.assertEqual(md["box"], "Box 99", "an explicit flag must win")
            self.assertEqual(md["folder"], "Folder 3", "unsupplied fields still carry forward")

    def test_absent_tier3_stays_absent(self):
        """A fresh extraction must never invent Tier 3; rebuild must not either."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Z.loc15.json"
            path.write_text(json.dumps(_envelope()), encoding="utf-8")
            _rebuild(tmp)
            md = json.loads(path.read_text())["metadata"]
            for field in ("box", "folder", "identifier", "repository", "call_number"):
                self.assertIn(md.get(field), (None, ""), f"{field} was invented")

    def test_repeated_rebuilds_are_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "W.loc15.json"
            path.write_text(json.dumps(_envelope(box="Box 12")), encoding="utf-8")
            _rebuild(tmp)
            first = json.loads(path.read_text())["metadata"]
            _rebuild(tmp)
            second = json.loads(path.read_text())["metadata"]
            self.assertEqual(first["box"], "Box 12")
            self.assertEqual(second["box"], "Box 12", "a second rebuild must not wipe it")
            self.assertEqual(first["transcript"], second["transcript"])


class RebuildReoffersRejectedTermsTests(unittest.TestCase):
    """After a vocabulary expansion, a rebuild must recover terms the previous run discarded.

    Enforcement strips out-of-vocabulary terms from the metadata, so they only survive as text in
    policy_notes. Without reading them back, expanding the vocabulary would help future runs but
    could not repair existing records -- which is the whole point of the expand-then-rebuild loop.
    """

    def _with_rejection_note(self, subjects, rejected):
        envelope = _envelope(subjects=list(subjects))
        envelope["context"]["policy_notes"] = [
            "Rejected subject terms absent from the approved FAST list: " + "; ".join(rejected)
        ]
        return envelope

    def test_previously_rejected_term_returns_once_vocab_covers_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "A.loc15.json"
            path.write_text(json.dumps(
                self._with_rejection_note(["Correspondence"], ["Japan", "minorities"])
            ), encoding="utf-8")

            rebuild_existing_outputs(
                out_dir=tmp, defaults=dict(EMPTY_DEFAULTS), apply_reviews=False,
                approved_places=set(),
                approved_subjects={"Correspondence", "Japan", "minorities"},
                approved_genre={"correspondence"}, online_vocab_advisory=False,
            )
            envelope = json.loads(path.read_text())
            self.assertEqual(sorted(envelope["metadata"]["subjects"]),
                             ["Correspondence", "Japan", "minorities"])
            self.assertTrue(any("Re-offered previously rejected terms" in n
                                for n in envelope["context"]["policy_notes"]))

    def test_still_unapproved_terms_stay_out_and_stay_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "B.loc15.json"
            path.write_text(json.dumps(
                self._with_rejection_note(["Correspondence"], ["Railroads"])
            ), encoding="utf-8")

            for _ in range(2):  # idempotent across repeated rebuilds
                rebuild_existing_outputs(
                    out_dir=tmp, defaults=dict(EMPTY_DEFAULTS), apply_reviews=False,
                    approved_places=set(), approved_subjects={"Correspondence"},
                    approved_genre={"correspondence"}, online_vocab_advisory=False,
                )
            envelope = json.loads(path.read_text())
            self.assertEqual(envelope["metadata"]["subjects"], ["Correspondence"])
            notes = envelope["context"]["policy_notes"]
            self.assertTrue(any("Railroads" in n and n.startswith("Rejected subject") for n in notes),
                            "the rejection must still be recorded for the next expansion round")


if __name__ == "__main__":
    unittest.main()
