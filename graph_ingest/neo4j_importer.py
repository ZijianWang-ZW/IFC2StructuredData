"""Neo4j importer for graph dataset."""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List

from .dataset import GraphDataset

try:
    from neo4j import GraphDatabase
except Exception:  # pragma: no cover - handled by runtime checks
    GraphDatabase = None  # type: ignore


def _batched(rows: List[Dict[str, Any]], size: int) -> Iterable[List[Dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


class Neo4jImporter:
    """Import prepared records into Neo4j using batched UNWIND writes."""

    def __init__(
        self,
        *,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        batch_size: int = 1000,
    ) -> None:
        if GraphDatabase is None:
            raise ImportError(
                "neo4j package is not installed. Install with: pip install neo4j"
            )
        self.database = database
        self.batch_size = batch_size
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self.driver.close()

    def _run_write_batches(
        self, query: str, rows: List[Dict[str, Any]], batch_size: int
    ) -> None:
        if not rows:
            return
        with self.driver.session(database=self.database) as session:
            for batch in _batched(rows, batch_size):
                with session.begin_transaction() as tx:
                    tx.run(query, rows=batch)
                    tx.commit()

    def _create_schema(self) -> None:
        constraints = [
            (
                "CREATE CONSTRAINT building_object_globalid_unique IF NOT EXISTS "
                "FOR (n:BuildingObject) REQUIRE n.GlobalId IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT geometry_definition_id_unique IF NOT EXISTS "
                "FOR (n:GeometryDefinition) REQUIRE n.definitionId IS UNIQUE"
            ),
        ]
        with self.driver.session(database=self.database) as session:
            for query in constraints:
                session.run(query).consume()

    def _replace_existing_data(self) -> None:
        with self.driver.session(database=self.database) as session:
            session.run("MATCH (n:BuildingObject) DETACH DELETE n").consume()
            session.run("MATCH (n:GeometryDefinition) DETACH DELETE n").consume()

    def import_dataset(self, dataset: GraphDataset, *, replace: bool = False) -> Dict[str, Any]:
        start = time.perf_counter()

        self._create_schema()
        if replace:
            self._replace_existing_data()

        building_query = """
            UNWIND $rows AS row
            MERGE (n:BuildingObject {GlobalId: row.GlobalId})
            SET n += row.props
        """
        geometry_query = """
            UNWIND $rows AS row
            MERGE (n:GeometryDefinition {definitionId: row.definitionId})
            SET n += row.props
        """
        relates_query = """
            UNWIND $rows AS row
            MATCH (a:BuildingObject {GlobalId: row.src})
            MATCH (b:BuildingObject {GlobalId: row.dst})
            MERGE (a)-[r:RELATES_TO {relationshipType: row.relationshipType}]->(b)
        """
        uses_geometry_query = """
            UNWIND $rows AS row
            MATCH (a:BuildingObject {GlobalId: row.src})
            MATCH (b:GeometryDefinition {definitionId: row.definitionId})
            MERGE (a)-[r:USES_GEOMETRY]->(b)
            SET r.instanceParamsJson = row.instanceParamsJson
        """

        self._run_write_batches(building_query, dataset.building_nodes, self.batch_size)
        self._run_write_batches(geometry_query, dataset.geometry_nodes, self.batch_size)
        self._run_write_batches(relates_query, dataset.relates_edges, self.batch_size)
        self._run_write_batches(
            uses_geometry_query, dataset.uses_geometry_edges, self.batch_size
        )

        elapsed = time.perf_counter() - start
        return {
            "replace": replace,
            "batch_size": self.batch_size,
            "imported_counts": {
                "building_nodes": len(dataset.building_nodes),
                "geometry_nodes": len(dataset.geometry_nodes),
                "relates_edges": len(dataset.relates_edges),
                "uses_geometry_edges": len(dataset.uses_geometry_edges),
            },
            "time_seconds": round(elapsed, 3),
        }
