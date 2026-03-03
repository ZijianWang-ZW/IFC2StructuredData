from __future__ import annotations

import os
import tempfile
import unittest

from utils.parquet2glb import convert_geometry_to_glb
from viewer_assets.builder import extract_object_index_from_glb


class TestViewerAssets(unittest.TestCase):
    def test_extract_object_index_from_glb(self) -> None:
        geometry_data = [
            {
                "GlobalId": "TEST_GUID_A",
                "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                "faces": [[0, 1, 2]],
                "material_groups": [{"rgba": [1.0, 0.0, 0.0, 1.0], "face_indices": [0]}],
            },
            {
                "GlobalId": "TEST_GUID_B",
                "vertices": [[0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [0.0, 1.0, 1.0]],
                "faces": [[0, 1, 2]],
                "material_groups": [{"rgba": [0.0, 1.0, 0.0, 1.0], "face_indices": [0]}],
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            glb_path = os.path.join(tmpdir, "test.glb")
            convert_geometry_to_glb(geometry_data, glb_path)

            index = extract_object_index_from_glb(glb_path)
            self.assertIn("TEST_GUID_A", index)
            self.assertIn("TEST_GUID_B", index)
            self.assertIsNotNone(index["TEST_GUID_A"]["node_index"])
            self.assertIsNotNone(index["TEST_GUID_A"]["mesh_index"])
            self.assertEqual(index["TEST_GUID_A"]["node_name"], "TEST_GUID_A")


if __name__ == "__main__":
    unittest.main()
