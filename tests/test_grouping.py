"""Grouping image files into archival items, and ordering their pages."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.grouping import chunk_pages, group_items, page_label, parse_name


class ParseNameTests(unittest.TestCase):
    def test_sequence_numbered_volume_page(self):
        self.assertEqual(parse_name("04_AAMU-0069_Page_1"), ("AAMU-0069", "Page_1", 4))

    def test_item_with_page_label(self):
        self.assertEqual(parse_name("AAMU-0003_Page_12"), ("AAMU-0003", "Page_12", None))

    def test_recto_verso(self):
        self.assertEqual(parse_name("AAMU-0001_Recto"), ("AAMU-0001", "Recto", None))

    def test_unstructured_name_is_its_own_item(self):
        self.assertEqual(parse_name("loose_scan"), ("loose_scan", "", None))


class GroupingTests(unittest.TestCase):
    def test_recto_and_verso_are_one_item(self):
        groups = group_items(["AAMU-0001_Verso.jpg", "AAMU-0001_Recto.jpg"])
        self.assertEqual(list(groups), ["AAMU-0001"])
        self.assertEqual([p.name for p in groups["AAMU-0001"]],
                         ["AAMU-0001_Recto.jpg", "AAMU-0001_Verso.jpg"],
                         "recto sorts before verso")

    def test_pages_sort_numerically_not_lexically(self):
        files = [f"AAMU-0003_Page_{n}.jpg" for n in (10, 2, 1, 11)]
        groups = group_items(files)
        self.assertEqual([p.name for p in groups["AAMU-0003"]],
                         ["AAMU-0003_Page_1.jpg", "AAMU-0003_Page_2.jpg",
                          "AAMU-0003_Page_10.jpg", "AAMU-0003_Page_11.jpg"])

    def test_stray_space_in_page_number_still_sorts(self):
        """AAMU-0093_Page_ 8.jpg exists in the real batch."""
        files = ["AAMU-0093_Page_9.jpg", "AAMU-0093_Page_ 8.jpg", "AAMU-0093_Page_10.jpg"]
        groups = group_items(files)
        self.assertEqual([p.name for p in groups["AAMU-0093"]],
                         ["AAMU-0093_Page_ 8.jpg", "AAMU-0093_Page_9.jpg", "AAMU-0093_Page_10.jpg"])

    def test_volume_front_matter_leads_and_back_cover_trails(self):
        files = [
            "38_AAMU-0069_Back_cover.jpg",
            "04_AAMU-0069_Page_1.jpg",
            "01_AAMU-0069_Front_cover.jpg",
            "02_AAMU-0069_Title_page.jpg",
        ]
        ordered = [p.name for p in group_items(files)["AAMU-0069"]]
        self.assertEqual(ordered[0], "01_AAMU-0069_Front_cover.jpg")
        self.assertEqual(ordered[-1], "38_AAMU-0069_Back_cover.jpg")

    def test_letter_suffixed_item_numbers_group(self):
        """AAMU-0073a..e are five distinct items under one accession number."""
        files = [
            "AAMU-0073a_Page_1.jpg", "AAMU-0073a_Page_2.jpg",
            "AAMU-0073b_Page_1.jpg", "AAMU-0073b_Page_2-3.jpg",
            "AAMU-0073c_Recto.jpg",
        ]
        groups = group_items(files)
        self.assertEqual(sorted(groups), ["AAMU-0073a", "AAMU-0073b", "AAMU-0073c"])
        self.assertEqual(len(groups["AAMU-0073a"]), 2, "both pages belong to one item")
        self.assertEqual([p.name for p in groups["AAMU-0073b"]],
                         ["AAMU-0073b_Page_1.jpg", "AAMU-0073b_Page_2-3.jpg"])

    def test_page_range_sorts_by_first_page(self):
        """One image can capture a two-page spread: Page_2-3."""
        files = ["AAMU-0073b_Page_4.jpg", "AAMU-0073b_Page_2-3.jpg", "AAMU-0073b_Page_1.jpg"]
        ordered = [p.name for p in group_items(files)["AAMU-0073b"]]
        self.assertEqual(ordered, ["AAMU-0073b_Page_1.jpg", "AAMU-0073b_Page_2-3.jpg",
                                   "AAMU-0073b_Page_4.jpg"])

    def test_letter_suffix_does_not_swallow_the_base_item(self):
        groups = group_items(["AAMU-0073_Page_1.jpg", "AAMU-0073a_Page_1.jpg"])
        self.assertEqual(sorted(groups), ["AAMU-0073", "AAMU-0073a"])

    def test_different_items_stay_separate(self):
        groups = group_items(["AAMU-0001_Recto.jpg", "AAMU-0002_Recto.jpg", "BC-0692_Recto.jpg"])
        self.assertEqual(sorted(groups), ["AAMU-0001", "AAMU-0002", "BC-0692"])


class PageLabelTests(unittest.TestCase):
    def test_labels_are_readable(self):
        self.assertEqual(page_label(Path("AAMU-0001_Recto.jpg")), "Recto")
        self.assertEqual(page_label(Path("AAMU-0003_Page_12.jpg")), "page 12")
        self.assertEqual(page_label(Path("01_AAMU-0069_Front_cover.jpg")), "Front cover (01)")


class ChunkingTests(unittest.TestCase):
    def test_chunks_preserve_order_and_size(self):
        pages = [Path(f"p{n}.jpg") for n in range(1, 8)]
        chunks = chunk_pages(pages, 3)
        self.assertEqual([len(c) for c in chunks], [3, 3, 1])
        self.assertEqual([p.name for p in chunks[0]], ["p1.jpg", "p2.jpg", "p3.jpg"])

    def test_small_item_is_a_single_chunk(self):
        self.assertEqual(len(chunk_pages([Path("a.jpg"), Path("b.jpg")], 6)), 1)

    def test_zero_or_negative_cap_degrades_to_one_page_per_call(self):
        self.assertEqual(len(chunk_pages([Path("a.jpg"), Path("b.jpg")], 0)), 2)


if __name__ == "__main__":
    unittest.main()
