"""[page N] markers across request batches.

The nine sequences below are the real ones from the 2026-07 batch, before the fix.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ai_metadata
from app.page_markers import page_numbers, renumber_restarted_pages

BATCH = {  # item: (pages, markers as written)
    "AAMU-0003": (15, [1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6, 1, 2, 3]),
    "AAMU-0028": (7, [1, 2, 3, 4, 5, 6, 1]),
    "AAMU-0069": (36, [1, 2, 3, 4, 5, 6] * 6),
    "AAMU-0074": (8, [1, 2, 3, 4, 5, 6, 1, 2]),
    "AAMU-0075": (12, [1, 2, 3, 4, 5, 6] * 2),
    "AAMU-0086": (14, [1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6, 1, 2]),
    "AAMU-0093": (10, [1, 2, 3, 4, 5, 6, 1, 2, 3, 4]),
}


def _transcript(numbers):
    return "\n\n".join(f"[page {n}]\nText of a page." for n in numbers)


class Renumbering(unittest.TestCase):
    def test_every_batch_sequence_becomes_one_to_n(self):
        for item, (pages, written) in BATCH.items():
            with self.subTest(item=item):
                fixed, record, note = renumber_restarted_pages(_transcript(written), pages)
                self.assertEqual(page_numbers(fixed), list(range(1, pages + 1)))
                self.assertEqual(record["from"], written)
                self.assertIn("Renumbered", note)

    def test_text_between_markers_is_untouched(self):
        text = "[page 1]\nSee [page 2] of the enclosure.\n\n[page 1]\nSecond sheet."
        fixed, _, _ = renumber_restarted_pages(text, 2)
        self.assertEqual(fixed, "[page 1]\nSee [page 2] of the enclosure.\n\n[page 2]\nSecond sheet.")

    def test_a_correct_transcript_is_left_alone(self):
        text = _transcript([1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(renumber_restarted_pages(text, 7), (text, None, None))
        self.assertEqual(renumber_restarted_pages("[page 1]\nOne page.", 1), ("[page 1]\nOne page.", None, None))
        self.assertEqual(renumber_restarted_pages(None, 1), (None, None, None))

    def test_an_ambiguous_restart_is_reported_not_guessed(self):
        text = _transcript([1, 2, 3, 1])  # four markers for a five-page item: something is missing
        fixed, record, note = renumber_restarted_pages(text, 5)
        self.assertEqual(fixed, text)
        self.assertIsNone(record)
        self.assertTrue(note.startswith("NEEDS PAGE REVIEW"))


class Manifest(unittest.TestCase):
    def test_a_later_request_numbers_images_by_their_place_in_the_item(self):
        note = ai_metadata._page_manifest_note(["Page_7"], first_page=7, total_pages=7)
        self.assertIn("THIS ITEM CONSISTS OF 7 IMAGES", note)
        self.assertIn("images 7-7", note)
        self.assertIn("Image 7: Page_7", note)

    def test_a_whole_item_in_one_request_reads_as_before(self):
        note = ai_metadata._page_manifest_note(["Recto", "Verso"])
        self.assertIn("THIS ITEM CONSISTS OF 2 IMAGES, supplied below in order", note)
        self.assertIn("Image 1: Recto", note)
        self.assertNotIn("separate requests", note)

    def _sent_content(self, **kwargs):
        sent = {}

        def create(**call):
            sent["messages"] = call["messages"]
            msg = SimpleNamespace(content='{"title": "x"}')
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with mock.patch.object(ai_metadata, "_get_client", return_value=client):
            ai_metadata.extract_metadata([(b"\xff\xd8fake", "image/jpeg")], "", "p7.jpg", **kwargs)
        return " ".join(part.get("text", "") for part in sent["messages"][1]["content"] if isinstance(part, dict))

    def test_a_lone_image_that_is_one_page_of_many_gets_the_manifest(self):
        # Without it the request falls back to the prompt's own "[page 1]": AAMU-0028's page 7.
        text = self._sent_content(page_labels=["Page_7"], first_page=7, total_pages=7)
        self.assertIn("Image 7: Page_7", text)

    def test_a_single_page_item_gets_no_manifest(self):
        self.assertNotIn("THIS ITEM CONSISTS OF", self._sent_content())


class ProcessItem(unittest.TestCase):
    def test_requests_are_told_their_pages_and_a_restart_is_repaired(self):
        import app.main as app_main
        from app.main import RunManifest
        calls = []

        def fake_extract(images, *args, first_page=1, total_pages=None, **kwargs):
            calls.append((first_page, total_pages, len(images)))
            # A model that still numbers from 1 in every request.
            return {"title": "Itinerary", "transcript": _transcript(range(1, len(images) + 1))}

        with tempfile.TemporaryDirectory() as tmp:
            pages = []
            for n in range(1, 8):
                page = Path(tmp) / f"TEST-0002_Page_{n}.jpg"
                page.write_bytes(b"\xff\xd8fake")
                pages.append(str(page))
            out = Path(tmp) / "out"
            out.mkdir()
            with mock.patch.object(app_main, "tesseract_ocr", return_value=("", 0.0)), \
                 mock.patch.object(app_main, "image_bytes", return_value=(b"\xff\xd8fake", "image/jpeg")), \
                 mock.patch.object(app_main, "image_dimensions", return_value=(3400, 4400)), \
                 mock.patch.object(app_main, "sent_dimensions", return_value=(3400, 4400)), \
                 mock.patch.object(app_main, "extract_metadata", side_effect=fake_extract):
                status = app_main.process_item(
                    paths=pages, item_id="TEST-0002", out_dir=str(out),
                    collection="", repository="", permalink="", model="gpt-5.6-terra",
                    approved_places=set(), approved_subjects=set(), approved_genre=set(),
                    online_vocab_advisory=False, ocr_fallback=False,
                    manifest=RunManifest(str(out / "run_manifest.jsonl")),
                )
            self.assertEqual(status, "ok")
            self.assertEqual(calls, [(1, 7, 6), (7, 7, 1)])
            import json
            env = json.loads(next(out.glob("*.loc15.json")).read_text(encoding="utf-8"))
            self.assertEqual(page_numbers(env["metadata"]["transcript"]), list(range(1, 8)))
            self.assertEqual(env["context"]["page_markers_renumbered"]["from"], [1, 2, 3, 4, 5, 6, 1])


if __name__ == "__main__":
    unittest.main()
