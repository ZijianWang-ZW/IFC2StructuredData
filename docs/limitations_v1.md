# Limitations (V1)

## Scope Constraints

1. Single IFC model per run; no federated multi-IFC graph merge.
2. Graph stores only `BuildingObject` and `GeometryDefinition` node classes.
3. Relationship model keeps only native IFC relationships between building objects plus `USES_GEOMETRY`.

## Explicitly Dropped Data

1. `IfcRelAssociatesMaterial`
2. `IfcRelAssociatesClassification`
3. `IfcRelAssignsToGroup`

Impact:

1. Material/classification/group semantics are not queryable in V1.
2. Related relationships are intentionally filtered out during ingest.

## Geometry & Viewer Constraints

1. `IfcOpeningElement` is excluded from GLB export (to avoid opening solids in viewer).
2. Viewer-object mapping depends on `object_index.json`; if missing, viewer<->graph bidirectional selection is limited.
3. In `example_str`, no viewer index is provided by default; UI supports manual focus but no initial auto-selection.
4. For faceted BRep, object-level geometry path is stored as relative OBJ path in node properties.

## Graph Interaction Constraints

1. Neighborhood query supports only `hops=1|2`.
2. Big-picture graph is capped by API limit (default 1000 nodes).
3. Dense graphs still require filtering for readability/performance despite V1 optimizations.

## API / Product Constraints

1. No authentication/authorization layer.
2. No write API for graph editing (read/query only).
3. No semantic enrichment edges (`RelSpatial`, `correspondsTo`) in V1.
4. No versioned model comparison/change propagation workflow.

## Operational Constraints

1. Full viewer asset generation requires source IFC (cannot generate GLB from CSV-only output alone).
2. Neo4j mode requires external Neo4j service availability and credentials.
