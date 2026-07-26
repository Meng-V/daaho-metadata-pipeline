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

    def _process(self, tmp, side_effect):
        manifest = RunManifest(str(Path(tmp) / "run_manifest.jsonl"))
        with mock.patch.object(app_main, "tesseract_ocr", return_value=("some ocr text here ok", 80.0)), \
             mock.patch.object(app_main, "image_bytes", return_value=(b"\xff\xd8fake", "image/jpeg")), \
             mock.patch.object(app_main, "image_dimensions", return_value=(3400, 4400)), \
             mock.patch.object(app_main, "sent_dimensions", return_value=(3400, 4400)), \
             mock.patch.object(app_main, "extract_metadata", side_effect=side_effect):
            status = app_main.process_path(
                path=__file__,           # any existing file; image IO is mocked
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
            stem = Path(__file__).stem
            self.assertEqual(status, "failed")
            self.assertFalse((Path(tmp) / f"{stem}.loc15.json").exists(),
                             "a failed item must not leave an output file behind")
            failed = Path(tmp) / f"{stem}.failed.json"
            self.assertTrue(failed.exists())
            self.assertIn("rate limited", json.loads(failed.read_text())["error"])
            self.assertEqual(manifest.counts(), {"failed": 1})

    def test_success_clears_a_stale_failure_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            stem = Path(__file__).stem
            (Path(tmp) / f"{stem}.failed.json").write_text("{}", encoding="utf-8")
            status, manifest = self._process(tmp, lambda *a, **k: {"title": "A title, undated"})
            self.assertEqual(status, "ok")
            self.assertTrue((Path(tmp) / f"{stem}.loc15.json").exists())
            self.assertFalse((Path(tmp) / f"{stem}.failed.json").exists())
            self.assertEqual(manifest.counts(), {"ok": 1})


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
