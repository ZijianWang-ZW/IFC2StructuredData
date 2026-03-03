from __future__ import annotations

import os
import unittest

from backend.services.csv_store import CsvGraphStore


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "example_str")


class TestCsvGraphStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = CsvGraphStore(SAMPLE_OUTPUT_DIR)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.store.close()

    def test_overview_counts(self) -> None:
        overview = self.store.get_overview()
        self.assertGreater(overview["building_objects"], 0)
        self.assertGreater(overview["relates_edges"], 0)

    def test_neighborhood_and_edges(self) -> None:
        ids = self.store.get_all_object_ids(limit=10)
        self.assertGreater(len(ids), 0)
        center = ids[0]
        nhood = self.store.get_neighborhood_object_ids(center, hops=1, limit=100)
        self.assertIn(center, nhood)
        edges = self.store.get_relates_edges(nhood)
        for edge in edges:
            self.assertIn(edge["src"], nhood)
            self.assertIn(edge["dst"], nhood)

    def test_geometry_lookup(self) -> None:
        ids = self.store.get_all_object_ids(limit=200)
        geometry = self.store.get_geometry_for_objects(ids)
        self.assertIn("geometry_nodes", geometry)
        self.assertIn("uses_geometry_edges", geometry)

    def test_building_object_summaries(self) -> None:
        ids = self.store.get_all_object_ids(limit=5)
        summaries = self.store.get_building_object_summaries(ids)
        self.assertGreaterEqual(len(summaries), 1)
        sample = summaries[0]
        self.assertIn("GlobalId", sample)
        self.assertIn("ifcType", sample)
        self.assertNotIn("attributesJson", sample)


if __name__ == "__main__":
    unittest.main()
