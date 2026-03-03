# Workplan Status (Handoff)

- Updated: 2026-03-03
- Branch: `dev/pm`

## Progress Snapshot

1. Week 1: Done
2. Week 2: Done
3. Week 3: Done
4. Week 4: In queue
5. Week 5: Pending
6. Week 6: Pending

## Completed Milestones

### Week 1 - Graph Ingest

1. Neo4j schema and batch import pipeline implemented.
2. Relationship filtering rules implemented (material/classification/group excluded).
3. Import report generated (`graph_import_report.json`).

### Week 2 - Viewer Asset Builder

1. IFC -> `viewer/model.glb` build path implemented.
2. `viewer/object_index.json` generated from GLB node extras.
3. Real run validated on `Architecture_v1.ifc`.

### Week 3 - Backend API

1. Object detail endpoint.
2. Neighborhood subgraph endpoint (`hops=1/2`).
3. Overview endpoint.
4. Viewer index endpoint.
5. Browser smoke test on Swagger and health endpoint.

## Immediate Next Work (Week 4)

1. Scaffold frontend app (single-page split layout: left viewer, right graph).
2. Integrate Three.js GLB viewer with object picking by `GlobalId`.
3. Integrate graph panel with neighborhood fetch from backend.
4. Implement bidirectional selection sync:
   - Viewer select -> graph focus
   - Graph select -> viewer focus/highlight
5. Add minimal E2E smoke scenario for sync path.

## Environment Requirements Before Continue

1. Neo4j service running and reachable.
2. Backend env vars configured:
   - `NEO4J_URI`
   - `NEO4J_USER`
   - `NEO4J_PASSWORD`
   - `NEO4J_DATABASE`
   - `VIEWER_INDEX_PATH`
