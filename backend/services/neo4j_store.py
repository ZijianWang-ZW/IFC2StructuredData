"""Neo4j implementation of graph store."""

from __future__ import annotations

from typing import Any, Dict, List

from .base_store import GraphStore

try:
    from neo4j import GraphDatabase
except Exception:  # pragma: no cover
    GraphDatabase = None  # type: ignore


def _node_to_dict(node: Any) -> Dict[str, Any]:
    return dict(node) if node is not None else {}


class Neo4jGraphStore(GraphStore):
    def __init__(self, *, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        if GraphDatabase is None:
            raise ImportError("neo4j package is required: pip install neo4j")
        self.database = database
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self.driver.close()

    def get_building_object(self, global_id: str) -> Dict[str, Any] | None:
        query = """
            MATCH (o:BuildingObject {GlobalId: $global_id})
            RETURN o
        """
        with self.driver.session(database=self.database) as session:
            record = session.run(query, global_id=global_id).single()
            if not record:
                return None
            data = _node_to_dict(record["o"])
            data["GlobalId"] = data.get("GlobalId", global_id)
            return data

    def get_building_objects(self, global_ids: List[str]) -> List[Dict[str, Any]]:
        if not global_ids:
            return []
        query = """
            MATCH (o:BuildingObject)
            WHERE o.GlobalId IN $global_ids
            RETURN o
        """
        with self.driver.session(database=self.database) as session:
            rows = session.run(query, global_ids=global_ids)
            out = []
            for row in rows:
                data = _node_to_dict(row["o"])
                if "GlobalId" in data:
                    out.append(data)
            return out

    def get_building_object_summaries(self, global_ids: List[str]) -> List[Dict[str, Any]]:
        if not global_ids:
            return []
        query = """
            MATCH (o:BuildingObject)
            WHERE o.GlobalId IN $global_ids
            RETURN o.GlobalId AS GlobalId, o.ifcType AS ifcType, o.name AS name, o.hasGeometry AS hasGeometry, o.geometryMethod AS geometryMethod
        """
        with self.driver.session(database=self.database) as session:
            rows = session.run(query, global_ids=global_ids)
            out = []
            for row in rows:
                gid = row.get("GlobalId")
                if not gid:
                    continue
                out.append(
                    {
                        "GlobalId": gid,
                        "ifcType": row.get("ifcType"),
                        "name": row.get("name"),
                        "hasGeometry": row.get("hasGeometry"),
                        "geometryMethod": row.get("geometryMethod"),
                    }
                )
            return out

    def get_neighborhood_object_ids(self, global_id: str, hops: int, limit: int) -> List[str]:
        if hops not in (1, 2):
            raise ValueError("hops must be 1 or 2")
        query = f"""
            MATCH (center:BuildingObject {{GlobalId: $global_id}})
            MATCH (center)-[:RELATES_TO*0..{hops}]-(n:BuildingObject)
            RETURN DISTINCT n.GlobalId AS global_id
            LIMIT $limit
        """
        with self.driver.session(database=self.database) as session:
            rows = session.run(query, global_id=global_id, limit=limit)
            return [row["global_id"] for row in rows if row.get("global_id")]

    def get_relates_edges(self, global_ids: List[str]) -> List[Dict[str, Any]]:
        if not global_ids:
            return []
        query = """
            MATCH (a:BuildingObject)-[r:RELATES_TO]->(b:BuildingObject)
            WHERE a.GlobalId IN $global_ids AND b.GlobalId IN $global_ids
            RETURN a.GlobalId AS src, b.GlobalId AS dst, r.relationshipType AS relationship_type
        """
        with self.driver.session(database=self.database) as session:
            rows = session.run(query, global_ids=global_ids)
            return [
                {
                    "src": row["src"],
                    "dst": row["dst"],
                    "relationshipType": row["relationship_type"],
                }
                for row in rows
            ]

    def get_geometry_for_objects(self, global_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        if not global_ids:
            return {"geometry_nodes": [], "uses_geometry_edges": []}
        query = """
            MATCH (o:BuildingObject)-[r:USES_GEOMETRY]->(g:GeometryDefinition)
            WHERE o.GlobalId IN $global_ids
            RETURN o.GlobalId AS src, r.instanceParamsJson AS instance_params_json, g
        """
        geometry_nodes_by_id: Dict[int, Dict[str, Any]] = {}
        uses_edges: List[Dict[str, Any]] = []
        with self.driver.session(database=self.database) as session:
            rows = session.run(query, global_ids=global_ids)
            for row in rows:
                g = _node_to_dict(row["g"])
                definition_id = g.get("definitionId")
                if definition_id is None:
                    continue
                geometry_nodes_by_id[int(definition_id)] = g
                uses_edges.append(
                    {
                        "src": row["src"],
                        "definitionId": int(definition_id),
                        "instanceParamsJson": row["instance_params_json"],
                    }
                )
        return {
            "geometry_nodes": list(geometry_nodes_by_id.values()),
            "uses_geometry_edges": uses_edges,
        }

    def get_overview(self) -> Dict[str, Any]:
        count_query = """
            CALL {
              MATCH (o:BuildingObject) RETURN count(o) AS c1
            }
            CALL {
              MATCH (g:GeometryDefinition) RETURN count(g) AS c2
            }
            CALL {
              MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS c3
            }
            CALL {
              MATCH ()-[r:USES_GEOMETRY]->() RETURN count(r) AS c4
            }
            RETURN c1 AS building_objects, c2 AS geometry_definitions, c3 AS relates_edges, c4 AS uses_geometry_edges
        """
        rel_types_query = """
            MATCH ()-[r:RELATES_TO]->()
            RETURN r.relationshipType AS relationship_type, count(*) AS count
            ORDER BY count DESC
            LIMIT 20
        """
        with self.driver.session(database=self.database) as session:
            counts = session.run(count_query).single()
            type_rows = session.run(rel_types_query)

            overview = {
                "building_objects": counts["building_objects"] if counts else 0,
                "geometry_definitions": counts["geometry_definitions"] if counts else 0,
                "relates_edges": counts["relates_edges"] if counts else 0,
                "uses_geometry_edges": counts["uses_geometry_edges"] if counts else 0,
                "relationship_type_counts": [],
            }
            for row in type_rows:
                overview["relationship_type_counts"].append(
                    {
                        "relationshipType": row["relationship_type"],
                        "count": row["count"],
                    }
                )
            return overview

    def get_geometry_definition(self, definition_id: int) -> Dict[str, Any] | None:
        query = """
            MATCH (g:GeometryDefinition {definitionId: $definition_id})
            RETURN g
        """
        with self.driver.session(database=self.database) as session:
            record = session.run(query, definition_id=int(definition_id)).single()
            if not record:
                return None
            return _node_to_dict(record["g"])

    def get_all_object_ids(self, limit: int) -> List[str]:
        query = """
            MATCH (o:BuildingObject)
            RETURN o.GlobalId AS global_id
            ORDER BY global_id
            LIMIT $limit
        """
        with self.driver.session(database=self.database) as session:
            rows = session.run(query, limit=limit)
            return [row["global_id"] for row in rows if row.get("global_id")]
