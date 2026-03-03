"""CSV-backed graph store for local development and frontend integration."""

from __future__ import annotations

import json
from collections import Counter, deque
from typing import Any, Dict, List, Set

from graph_ingest.dataset import build_graph_dataset

from .base_store import GraphStore


class CsvGraphStore(GraphStore):
    def __init__(self, output_dir: str) -> None:
        dataset, _report = build_graph_dataset(output_dir)
        self.objects: Dict[str, Dict[str, Any]] = {}
        for row in dataset.building_nodes:
            gid = row["GlobalId"]
            props = row["props"].copy()
            attrs_json = props.get("attributesJson")
            if attrs_json:
                try:
                    props["attributes"] = json.loads(attrs_json)
                except Exception:
                    props["attributes"] = None
            props["GlobalId"] = gid
            self.objects[gid] = props

        self.geometry_nodes: Dict[int, Dict[str, Any]] = {}
        for row in dataset.geometry_nodes:
            definition_id = int(row["definitionId"])
            props = row["props"].copy()
            props["definitionId"] = definition_id
            self.geometry_nodes[definition_id] = props

        self.relates_edges = dataset.relates_edges
        self.uses_geometry_edges = dataset.uses_geometry_edges
        self._adjacency = self._build_adjacency(self.relates_edges)

    @staticmethod
    def _build_adjacency(edges: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
        adj: Dict[str, Set[str]] = {}
        for edge in edges:
            src = edge["src"]
            dst = edge["dst"]
            adj.setdefault(src, set()).add(dst)
            adj.setdefault(dst, set()).add(src)
        return adj

    def close(self) -> None:
        return None

    def get_building_object(self, global_id: str) -> Dict[str, Any] | None:
        obj = self.objects.get(global_id)
        return obj.copy() if obj else None

    def get_building_objects(self, global_ids: List[str]) -> List[Dict[str, Any]]:
        out = []
        for gid in global_ids:
            obj = self.objects.get(gid)
            if obj is not None:
                out.append(obj.copy())
        return out

    def get_building_object_summaries(self, global_ids: List[str]) -> List[Dict[str, Any]]:
        out = []
        for gid in global_ids:
            obj = self.objects.get(gid)
            if obj is None:
                continue
            out.append(
                {
                    "GlobalId": gid,
                    "ifcType": obj.get("ifcType"),
                    "name": obj.get("name"),
                    "hasGeometry": obj.get("hasGeometry"),
                    "geometryMethod": obj.get("geometryMethod"),
                }
            )
        return out

    def get_neighborhood_object_ids(self, global_id: str, hops: int, limit: int) -> List[str]:
        if global_id not in self.objects:
            return []
        if hops not in (1, 2):
            raise ValueError("hops must be 1 or 2")

        visited: Set[str] = {global_id}
        queue = deque([(global_id, 0)])
        ordered: List[str] = [global_id]

        while queue and len(ordered) < limit:
            current, depth = queue.popleft()
            if depth >= hops:
                continue
            for neighbor in sorted(self._adjacency.get(current, set())):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                ordered.append(neighbor)
                if len(ordered) >= limit:
                    break
                queue.append((neighbor, depth + 1))
        return ordered

    def get_relates_edges(self, global_ids: List[str]) -> List[Dict[str, Any]]:
        id_set = set(global_ids)
        return [
            edge.copy()
            for edge in self.relates_edges
            if edge["src"] in id_set and edge["dst"] in id_set
        ]

    def get_geometry_for_objects(self, global_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        id_set = set(global_ids)
        uses_edges = [
            edge.copy() for edge in self.uses_geometry_edges if edge["src"] in id_set
        ]
        used_definition_ids = {edge["definitionId"] for edge in uses_edges}
        geometry_nodes = [
            self.geometry_nodes[definition_id].copy()
            for definition_id in sorted(used_definition_ids)
            if definition_id in self.geometry_nodes
        ]
        return {
            "geometry_nodes": geometry_nodes,
            "uses_geometry_edges": uses_edges,
        }

    def get_geometry_definition(self, definition_id: int) -> Dict[str, Any] | None:
        node = self.geometry_nodes.get(int(definition_id))
        return node.copy() if node else None

    def get_overview(self) -> Dict[str, Any]:
        counter = Counter(edge["relationshipType"] for edge in self.relates_edges)
        rel_type_counts = [
            {"relationshipType": rel_type, "count": count}
            for rel_type, count in counter.most_common(20)
        ]
        return {
            "building_objects": len(self.objects),
            "geometry_definitions": len(self.geometry_nodes),
            "relates_edges": len(self.relates_edges),
            "uses_geometry_edges": len(self.uses_geometry_edges),
            "relationship_type_counts": rel_type_counts,
        }

    def get_all_object_ids(self, limit: int) -> List[str]:
        return sorted(self.objects.keys())[:limit]
