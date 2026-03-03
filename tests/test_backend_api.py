from __future__ import annotations

import json
import os
import tempfile
import unittest
from typing import Any, Dict, List

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.services.base_store import GraphStore
from backend.services.graph_service import GraphService
from backend.services.viewer_index import ViewerIndexRepository


class FakeGraphStore(GraphStore):
    def __init__(self) -> None:
        self.objects = {
            "A": {"GlobalId": "A", "ifcType": "IfcWall"},
            "B": {"GlobalId": "B", "ifcType": "IfcDoor"},
            "C": {"GlobalId": "C", "ifcType": "IfcWindow"},
        }
        self.relates = [
            {"src": "A", "dst": "B", "relationshipType": "IfcRelAggregates"},
            {"src": "B", "dst": "C", "relationshipType": "IfcRelConnectsPathElements"},
        ]
        self.geometry_nodes = {
            1: {"definitionId": 1, "method": "extrusion"},
        }
        self.uses = [
            {"src": "A", "definitionId": 1, "instanceParamsJson": '{"position":{}}'},
        ]

    def close(self) -> None:
        return None

    def get_building_object(self, global_id: str) -> Dict[str, Any] | None:
        return self.objects.get(global_id)

    def get_building_objects(self, global_ids: List[str]) -> List[Dict[str, Any]]:
        return [self.objects[g] for g in global_ids if g in self.objects]

    def get_neighborhood_object_ids(self, global_id: str, hops: int, limit: int) -> List[str]:
        if global_id not in self.objects:
            return []
        if hops == 1:
            ids = ["A", "B"] if global_id == "A" else [global_id]
        else:
            ids = ["A", "B", "C"] if global_id == "A" else [global_id]
        return ids[:limit]

    def get_relates_edges(self, global_ids: List[str]) -> List[Dict[str, Any]]:
        id_set = set(global_ids)
        return [e for e in self.relates if e["src"] in id_set and e["dst"] in id_set]

    def get_geometry_for_objects(self, global_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        id_set = set(global_ids)
        uses = [e for e in self.uses if e["src"] in id_set]
        used_ids = {e["definitionId"] for e in uses}
        nodes = [self.geometry_nodes[i] for i in used_ids if i in self.geometry_nodes]
        return {"geometry_nodes": nodes, "uses_geometry_edges": uses}

    def get_overview(self) -> Dict[str, Any]:
        return {
            "building_objects": len(self.objects),
            "geometry_definitions": len(self.geometry_nodes),
            "relates_edges": len(self.relates),
            "uses_geometry_edges": len(self.uses),
            "relationship_type_counts": [{"relationshipType": "IfcRelAggregates", "count": 1}],
        }


class TestBackendAPI(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json")
        json.dump({"A": {"node_index": 1, "mesh_index": 0}}, tmp)
        tmp.close()
        self.tmp_path = tmp.name

        repo = ViewerIndexRepository(self.tmp_path)
        service = GraphService(store=FakeGraphStore(), viewer_index_repo=repo)
        app = create_app(service)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        if os.path.exists(self.tmp_path):
            os.unlink(self.tmp_path)

    def test_health(self) -> None:
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_object_found(self) -> None:
        r = self.client.get("/api/object/A")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["object"]["GlobalId"], "A")
        self.assertEqual(len(data["geometry"]["geometry_nodes"]), 1)
        self.assertIsNotNone(data["viewer"])

    def test_object_not_found(self) -> None:
        r = self.client.get("/api/object/NOT_EXIST")
        self.assertEqual(r.status_code, 404)

    def test_neighborhood(self) -> None:
        r = self.client.get("/api/graph/neighborhood", params={"globalId": "A", "hops": 2, "limit": 100})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["centerGlobalId"], "A")
        self.assertGreaterEqual(len(data["nodes"]["buildingObjects"]), 2)
        self.assertGreaterEqual(len(data["edges"]["relatesTo"]), 1)

    def test_overview(self) -> None:
        r = self.client.get("/api/graph/overview")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["building_objects"], 3)

    def test_viewer_index(self) -> None:
        r = self.client.get("/api/viewer/index")
        self.assertEqual(r.status_code, 200)
        self.assertIn("A", r.json())


if __name__ == "__main__":
    unittest.main()
