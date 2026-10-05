import unittest

from app.evidence_qc import find_header_places


class EvidenceQCTests(unittest.TestCase):
    def test_find_header_places_canonicalizes_city_case_dc(self):
        hits = find_header_places(["WASHINGTON, D.C."])
        places = [hit.get("fast_place") for hit in hits]
        # Compared in FAST's authorized form, which is what the Location field now holds (D-015).
        self.assertIn("Washington (D.C.)", places)

    def test_find_header_places_strips_address_prefix(self):
        hits = find_header_places(["Address -- Oxford, Ohio"])
        places = [hit.get("fast_place") for hit in hits]
        self.assertIn("Ohio--Oxford", places)


if __name__ == "__main__":
    unittest.main()

