"""Regressions for the two failure modes that would corrupt a large batch.

Both were silent: they produced output that looked complete. Neither would have been caught by
inspecting the output directory, which is why they are pinned here.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import main as app_main
from app.ai_metadata import ExtractionFailed, _is_retryable
from app.main import (
    RunManifest,
    _enforce_approved_genre,
    _enforce_approved_places,
    _enforce_approved_subjects,
)


class VocabFallbackTests(unittest.TestCase):
    """A pilot-sized vocabulary must not stamp unrelated terms onto out-of-scope items."""

    SUBJECTS = {"Correspondence", "Japanese Americans", "Miami University (Oxford, Ohio)"}
    GENRE = {"correspondence", "letters (correspondence)"}
    PLACES = {"Ohio--Oxford", "Ohio--Cincinnati"}

    def test_empty_metadata_does_not_gain_a_subject(self):
        """The old fallback wrote 'Correspondence' -- or sorted(approved)[0] -- onto empty input."""
        md = {}
        notes = _enforce_approved_subjects(md, self.SUBJECTS)
        self.assertEqual(md["subjects"], [])
        self.assertTrue(any("NEEDS VOCAB REVIEW" in n for n in notes))

    def test_unmatched_subjects_are_rejected_by_name(self):
        md = {"subjects": ["Railroads", "Mining"]}
        notes = _enforce_approved_subjects(md, self.SUBJECTS)
        self.assertEqual(md["subjects"], [])
        joined = " ".join(notes)
        self.assertIn("Railroads", joined)
        self.assertIn("Mining", joined)

    def test_matched_subjects_still_pass_through(self):
        md = {"subjects": ["Japanese Americans"]}
        _enforce_approved_subjects(md, self.SUBJECTS)
        self.assertEqual(md["subjects"], ["Japanese Americans"])

    def test_unmatched_genre_is_not_relabelled_correspondence(self):
        md = {"genre": ["ledgers"]}
        notes = _enforce_approved_genre(md, self.GENRE)
        self.assertEqual(md["genre"], [])
        self.assertIn("ledgers", " ".join(notes))

    def test_dropped_place_token_is_recorded(self):
        """A partial match used to silently rewrite the field, losing the unmatched token."""
        md = {"place": "Illinois--Chicago; Ohio--Oxford"}
        notes = _enforce_approved_places(md, self.PLACES)
        self.assertEqual(md["place"], "Ohio--Oxford")
        self.assertIn("Illinois--Chicago", " ".join(notes))

    def test_wholly_unmatched_place_is_kept_unvalidated(self):
        md = {"place": "Illinois--Chicago"}
        notes = _enforce_approved_places(md, self.PLACES)
        self.assertEqual(md["place"], "Illinois--Chicago")
        self.assertTrue(any("NEEDS VOCAB REVIEW" in n for n in notes))


class ExtractionFailureTests(unittest.TestCase):
    """A failed extraction must leave no output, or a resume skips a permanent hole."""

    ITEM_ID = "TEST-0001"

    def _process(self, tmp, side_effect, paths=None):
        manifest = RunManifest(str(Path(tmp) / "run_manifest.jsonl"))
        with mock.patch.object(app_main, "tesseract_ocr", return_value=("some ocr text here ok", 80.0)), \
             mock.patch.object(app_main, "image_bytes", return_value=(b"\xff\xd8fake", "image/jpeg")), \
             mock.patch.object(app_main, "image_dimensions", return_value=(3400, 4400)), \
             mock.patch.object(app_main, "sent_dimensions", return_value=(3400, 4400)), \
             mock.patch.object(app_main, "extract_metadata", side_effect=side_effect):
            status = app_main.process_item(
                paths=paths or [__file__],   # any existing file; image IO is mocked
                item_id=self.ITEM_ID,
                out_dir=tmp,
                collection="", repository="", permalink="",
                model="gpt-5.6-terra",
                approved_places=set(), approved_subjects=set(), approved_genre=set(),
                online_vocab_advisory=False,
                ocr_fallback=False,
                manifest=manifest,
            )
        return status, manifest

    def test_failure_writes_no_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, manifest = self._process(tmp, ExtractionFailed("rate limited after 5 attempts"))
            self.assertEqual(status, "failed")
            self.assertFalse((Path(tmp) / f"{self.ITEM_ID}.loc15.json").exists(),
                             "a failed item must not leave an output file behind")
            failed = Path(tmp) / f"{self.ITEM_ID}.failed.json"
            self.assertTrue(failed.exists())
            self.assertIn("rate limited", json.loads(failed.read_text())["error"])
            self.assertEqual(manifest.counts(), {"failed": 1})

    def test_success_clears_a_stale_failure_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / f"{self.ITEM_ID}.failed.json").write_text("{}", encoding="utf-8")
            status, manifest = self._process(tmp, lambda *a, **k: {"title": "A title, undated"})
            self.assertEqual(status, "ok")
            self.assertTrue((Path(tmp) / f"{self.ITEM_ID}.loc15.json").exists())
            self.assertFalse((Path(tmp) / f"{self.ITEM_ID}.failed.json").exists())
            self.assertEqual(manifest.counts(), {"ok": 1})

    def test_multi_page_item_makes_one_record(self):
        """Two sides of one sheet must not become two records."""
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def capture(images, ocr_text, **kwargs):
                calls.append((len(images), kwargs.get("page_labels")))
                return {"title": "A letter, undated", "transcript": "[page 1] a\n\n[page 2] b"}

            status, manifest = self._process(tmp, capture, paths=[__file__, __file__])
            self.assertEqual(status, "ok")
            self.assertEqual(len(calls), 1, "both pages belong in one request")
            self.assertEqual(calls[0][0], 2)
            outputs = list(Path(tmp).glob("*.loc15.json"))
            self.assertEqual(len(outputs), 1)
            envelope = json.loads(outputs[0].read_text())
            self.assertEqual(envelope["context"]["page_count"], 2)
            self.assertEqual(envelope["context"]["api_calls"], 1)

    def test_oversized_item_is_chunked_and_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = RunManifest(str(Path(tmp) / "m.jsonl"))
            chunk_no = {"n": 0}

            def per_chunk(images, ocr_text, **kwargs):
                chunk_no["n"] += 1
                first = chunk_no["n"] == 1
                return {
                    "title": "Volume, 1940" if first else None,
                    "date": None if first else "1940-05-01",
                    "transcript": f"[page x] chunk {chunk_no['n']}",
                    "subjects": ["a"] if first else ["b"],
                    "field_confidence": {"transcript": 90 if first else 40},
                }

            with mock.patch.object(app_main, "tesseract_ocr", return_value=("", 0.0)), \
                 mock.patch.object(app_main, "image_bytes", return_value=(b"\xff\xd8fake", "image/jpeg")), \
                 mock.patch.object(app_main, "image_dimensions", return_value=(3400, 4400)), \
                 mock.patch.object(app_main, "sent_dimensions", return_value=(3400, 4400)), \
                 mock.patch.object(app_main, "extract_metadata", side_effect=per_chunk):
                status = app_main.process_item(
                    paths=[__file__] * 5, item_id="VOL-0001", out_dir=tmp,
                    collection="", repository="", permalink="", model="gpt-5.6-terra",
                    approved_places=set(), approved_subjects=set(), approved_genre=set(),
                    online_vocab_advisory=False, ocr_fallback=False, manifest=manifest,
                    max_pages_per_call=2,
                )
            self.assertEqual(status, "ok")
            self.assertEqual(chunk_no["n"], 3, "5 pages at 2 per call -> 3 requests")
            envelope = json.loads((Path(tmp) / "VOL-0001.loc15.json").read_text())
            md = envelope["metadata"]
            self.assertIn("chunk 1", md["transcript"])
            self.assertIn("chunk 3", md["transcript"])
            self.assertEqual(md["date"], "1940-05-01", "a scalar missing from chunk 1 fills from later")
            self.assertEqual(sorted(md["subjects"] or []), ["a", "b"], "lists union")
            self.assertEqual(md["field_confidence"]["transcript"], 40, "confidence is the minimum")
            self.assertEqual(envelope["context"]["api_calls"], 3)


class VocabReviewFlagTests(unittest.TestCase):
    """A rejected term must flag the item even when the field is not left empty."""

    def test_partial_rejection_still_flags_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = RunManifest(str(Path(tmp) / "m.jsonl"))
            metadata = {
                "title": "A memo, 26 April 1977",
                # only the first is in the approved set below
                "subjects": ["Correspondence", "affirmative action programs", "women"],
            }
            with mock.patch.object(app_main, "tesseract_ocr", return_value=("", 0.0)), \
                 mock.patch.object(app_main, "image_bytes", return_value=(b"\xff\xd8fake", "image/jpeg")), \
                 mock.patch.object(app_main, "image_dimensions", return_value=(3400, 4400)), \
                 mock.patch.object(app_main, "sent_dimensions", return_value=(3400, 4400)), \
                 mock.patch.object(app_main, "extract_metadata", return_value=metadata):
                app_main.process_item(
                    paths=[__file__], item_id="MEMO-1", out_dir=tmp,
                    collection="", repository="", permalink="", model="gpt-5.6-terra",
                    approved_places=set(), approved_subjects={"Correspondence"}, approved_genre=set(),
                    online_vocab_advisory=False, ocr_fallback=False, manifest=manifest,
                )
            record = manifest.records[0]
            self.assertEqual(record["status"], "ok")
            self.assertTrue(record["needs_vocab_review"],
                            "two of three proposed subjects were dropped; that needs review")
            self.assertTrue(any("affirmative action" in n for n in record["vocab_notes"]))


class ConcurrentCostAttributionTests(unittest.TestCase):
    """Per-item cost must come from that item's own records, not a global running total."""

    def test_total_for_isolates_items(self):
        from app.cost import CostLedger, record_from_usage

        ledger = CostLedger(None)
        usage = {"prompt_tokens": 20000, "completion_tokens": 2000,
                 "prompt_tokens_details": {"cached_tokens": 0}}
        ledger.add(record_from_usage("ITEM-A", "extraction", "gpt-5.6-terra", usage))
        # Another worker finishes in the middle of A's window.
        ledger.add(record_from_usage("ITEM-B", "extraction", "gpt-5.6-terra", usage))
        ledger.add(record_from_usage("ITEM-B", "extraction", "gpt-5.6-terra", usage))

        self.assertAlmostEqual(ledger.total_for("ITEM-A"), 0.08, places=4)
        self.assertAlmostEqual(ledger.total_for("ITEM-B"), 0.16, places=4)
        self.assertAlmostEqual(ledger.total, 0.24, places=4)
        self.assertNotAlmostEqual(ledger.total_for("ITEM-A"), ledger.total, places=4,
                                  msg="a global delta would have charged A for B's work")

    def test_recorded_item_cost_excludes_other_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            from app.cost import CostLedger, record_from_usage

            ledger = CostLedger(None)
            manifest = RunManifest(None)
            usage = {"prompt_tokens": 20000, "completion_tokens": 2000,
                     "prompt_tokens_details": {"cached_tokens": 0}}
            # Simulate a concurrent worker having already billed a large amount.
            for _ in range(5):
                ledger.add(record_from_usage("OTHER", "extraction", "gpt-5.6-terra", usage))

            with mock.patch.object(app_main, "tesseract_ocr", return_value=("", 0.0)), \
                 mock.patch.object(app_main, "image_bytes", return_value=(b"\xff\xd8fake", "image/jpeg")), \
                 mock.patch.object(app_main, "image_dimensions", return_value=(3400, 4400)), \
                 mock.patch.object(app_main, "sent_dimensions", return_value=(3400, 4400)), \
                 mock.patch.object(app_main, "extract_metadata", return_value={"title": "T, undated"}):
                app_main.process_item(
                    paths=[__file__], item_id="MINE", out_dir=tmp,
                    collection="", repository="", permalink="", model="gpt-5.6-terra",
                    approved_places=set(), approved_subjects=set(), approved_genre=set(),
                    online_vocab_advisory=False, ocr_fallback=False,
                    ledger=ledger, manifest=manifest,
                )
            envelope = json.loads((Path(tmp) / "MINE.loc15.json").read_text())
            # extract_metadata is mocked, so no billable call is recorded for MINE.
            self.assertEqual(envelope["context"]["cost_usd"], 0.0)
            self.assertEqual(manifest.records[0]["cost_usd"], 0.0)


class RetryPolicyTests(unittest.TestCase):
    def test_transient_errors_retry_and_permanent_ones_do_not(self):
        class ApiError(Exception):
            def __init__(self, message, status=None):
                super().__init__(message)
                self.status_code = status

        for message, status in [("Rate limit reached", 429), ("server error", 503),
                                ("connection reset by peer", None)]:
            self.assertTrue(_is_retryable(ApiError(message, status)), message)
        for message, status in [("invalid api key", 401), ("unknown parameter", 400)]:
            self.assertFalse(_is_retryable(ApiError(message, status)), message)


class ManifestTests(unittest.TestCase):
    def test_manifest_is_append_only_and_tallies(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.jsonl"
            manifest = RunManifest(str(path))
            manifest.add("BC-0001", "ok", cost_usd=0.07)
            manifest.add("BC-0002", "failed", error="boom")
            manifest.add("BC-0003", "skipped")
            self.assertEqual(manifest.counts(), {"ok": 1, "failed": 1, "skipped": 1})
            self.assertEqual([r["item_id"] for r in manifest.failures()], ["BC-0002"])
            lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[0]["cost_usd"], 0.07)


if __name__ == "__main__":
    unittest.main()
