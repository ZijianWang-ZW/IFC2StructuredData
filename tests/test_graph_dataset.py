from __future__ import annotations

import os
import unittest

from graph_ingest.dataset import EXCLUDED_RELATIONSHIP_TYPES, build_graph_dataset


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "example_str")


class TestGraphDataset(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset, cls.report = build_graph_dataset(EXAMPLE_OUTPUT_DIR)
        cls.object_ids = {n["GlobalId"] for n in cls.dataset.building_nodes}
        cls.geometry_ids = {n["definitionId"] for n in cls.dataset.geometry_nodes}

    def test_building_nodes_exist(self) -> None:
        self.assertGreater(len(self.dataset.building_nodes), 0)
        self.assertEqual(len(self.dataset.building_nodes), len(self.object_ids))

    def test_relates_edges_only_connect_objects(self) -> None:
        self.assertGreater(len(self.dataset.relates_edges), 0)
        for edge in self.dataset.relates_edges:
            self.assertIn(edge["src"], self.object_ids)
            self.assertIn(edge["dst"], self.object_ids)
            self.assertNotIn(edge["relationshipType"], EXCLUDED_RELATIONSHIP_TYPES)

    def test_uses_geometry_edges_reference_definitions(self) -> None:
        self.assertGreater(len(self.dataset.uses_geometry_edges), 0)
        for edge in self.dataset.uses_geometry_edges:
            self.assertIn(edge["src"], self.object_ids)
            self.assertIn(edge["definitionId"], self.geometry_ids)

    def test_faceted_brep_paths_are_relative(self) -> None:
        faceted_count = 0
        for node in self.dataset.building_nodes:
            props = node["props"]
            method = props.get("geometryMethod")
            path = props.get("hasGeometryFilePath")
            if method == "faceted_brep":
                faceted_count += 1
                self.assertTrue(path)
                self.assertFalse(os.path.isabs(path))
                self.assertTrue(path.startswith("geometry/"))
                self.assertTrue(path.endswith(".obj"))
            else:
                self.assertIsNone(path)
        self.assertGreater(faceted_count, 0)

    def test_report_has_drop_stats(self) -> None:
        dropped_relationships = self.report["dropped_relationships"]
        self.assertIn("excluded_types", dropped_relationships)
        for rel_type in EXCLUDED_RELATIONSHIP_TYPES:
            self.assertIn(rel_type, dropped_relationships["excluded_types"])


if __name__ == "__main__":
    unittest.main()
