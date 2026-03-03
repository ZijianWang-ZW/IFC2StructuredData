"""Application-level graph API service."""

from __future__ import annotations

from typing import Any, Dict, List

from backend.errors import EntityNotFoundError
from .base_store import GraphStore
from .viewer_index import ViewerIndexRepository


class GraphService:
    def __init__(self, *, store: GraphStore, viewer_index_repo: ViewerIndexRepository) -> None:
        self.store = store
        self.viewer_index_repo = viewer_index_repo

    def close(self) -> None:
        self.store.close()

    def get_object_detail(self, global_id: str) -> Dict[str, Any]:
        node = self.store.get_building_object(global_id)
        if node is None:
            raise EntityNotFoundError(f"BuildingObject not found: {global_id}")
        geometry = self.store.get_geometry_for_objects([global_id])
        return {
            "object": node,
            "geometry": geometry,
            "viewer": self.viewer_index_repo.get(global_id),
        }

    @staticmethod
    def _compact_geometry_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        compact_nodes: List[Dict[str, Any]] = []
        for node in nodes:
            out = dict(node)
            tree = out.pop("geometryTreeJson", None)
            out["hasGeometryTree"] = bool(tree)
            out["geometryTreeLength"] = len(tree) if isinstance(tree, str) else 0
            compact_nodes.append(out)
        return compact_nodes

    def get_geometry_detail(self, definition_id: int) -> Dict[str, Any]:
        node = self.store.get_geometry_definition(definition_id)
        if node is None:
            raise EntityNotFoundError(f"GeometryDefinition not found: {definition_id}")
        return {"geometry": node}

    def get_neighborhood(self, global_id: str, *, hops: int, limit: int) -> Dict[str, Any]:
        center = self.store.get_building_object(global_id)
        if center is None:
            raise EntityNotFoundError(f"BuildingObject not found: {global_id}")

        object_ids = self.store.get_neighborhood_object_ids(global_id, hops, limit)
        if global_id not in object_ids:
            object_ids.append(global_id)

        building_nodes = self.store.get_building_object_summaries(object_ids)
        relates_edges = self.store.get_relates_edges(object_ids)
        geometry = self.store.get_geometry_for_objects(object_ids)

        return {
            "centerGlobalId": global_id,
            "hops": hops,
            "limit": limit,
            "nodes": {
                "buildingObjects": building_nodes,
                "geometryDefinitions": self._compact_geometry_nodes(geometry["geometry_nodes"]),
            },
            "edges": {
                "relatesTo": relates_edges,
                "usesGeometry": geometry["uses_geometry_edges"],
            },
        }

    def get_overview(self) -> Dict[str, Any]:
        overview = self.store.get_overview()
        overview["viewer_index_count"] = len(self.viewer_index_repo.get_all())
        return overview

    def get_viewer_index(self) -> Dict[str, Dict[str, Any]]:
        return self.viewer_index_repo.get_all()

    def get_full_graph(self, *, limit: int) -> Dict[str, Any]:
        object_ids = self.store.get_all_object_ids(limit)
        building_nodes = self.store.get_building_object_summaries(object_ids)
        relates_edges = self.store.get_relates_edges(object_ids)
        geometry = self.store.get_geometry_for_objects(object_ids)
        return {
            "limit": limit,
            "nodes": {
                "buildingObjects": building_nodes,
                "geometryDefinitions": self._compact_geometry_nodes(geometry["geometry_nodes"]),
            },
            "edges": {
                "relatesTo": relates_edges,
                "usesGeometry": geometry["uses_geometry_edges"],
            },
        }
