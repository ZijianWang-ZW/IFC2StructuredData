# Workplan Status (Handoff)

- Updated: 2026-03-03
- Branch: `dev/pm`

## Progress Snapshot

1. Week 1: Done
2. Week 2: Done
3. Week 3: Done
4. Week 4: Done
5. Week 5: Done
6. Week 6: Done

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

### Week 4 - Frontend Dual Pane

1. Frontend scaffolded at `frontend/` and served from backend.
2. Three.js model viewer integrated with GLB loading.
3. Cytoscape graph panel integrated with neighborhood API.
4. Bidirectional sync implemented between viewer and graph selection.
5. Added `CSV` backend mode for no-Neo4j local runs.
6. Browser smoke test completed with working interactions.

## Immediate Next Work (Post Week 6 / V2)

1. Start V2 federation + semantic enrichment track.
2. Add CI automation for acceptance script + browser smoke.
3. Expand scalability testing beyond 1000-node target.

## Week 5 Update (Feedback Batch 1)

1. Added Inspector panel to show building node, geometry node, and edge attributes.
2. Added double-click node expansion in graph panel.
3. Added graph performance optimizations:
   - lighter graph payloads (defer `geometryTreeJson` to detail endpoint)
   - frontend request/result caching
   - faster layout defaults + viewport performance flags
4. Updated viewer asset pipeline to exclude `IfcOpeningElement` from exported GLB.

## Week 5 Update (Interaction + Stability Batch 2)

1. Added graph filters:
   - object type filter
   - relationship type filter
   - geometry node visibility toggle
   - label visibility toggle
2. Added big-picture navigation control:
   - `Back To Focus` to restore last local neighborhood context
3. Added camera presets:
   - `Fit`, `Iso`, `Top`, `Front`
4. Added frontend robustness:
   - busy/disabled states during graph data loads
   - explicit graph/viewer error messages
   - empty-data handling and safer async task guards
5. Improved graph readability and responsiveness:
   - hidden-class based in-place filtering
   - dynamic filter options from current graph
   - faster layout path for neighborhood vs big-picture scenarios

## Week 6 Update (Acceptance + Docs Closure)

1. Added automated acceptance script:
   - `scripts/week6_acceptance.py`
   - report output: `docs/week6_acceptance_report.json`
2. Completed `example_str` acceptance run (PASS):
   - dataset + drop-stat checks
   - dry-run Neo4j import checks
   - backend API contract checks
3. Completed browser smoke on `example_str` runtime:
   - no-viewer-index graceful behavior
   - manual focus, big-picture, and back-to-focus verified
4. Delivered Week6 documentation set:
   - `docs/week6_acceptance.md`
   - `docs/runbook.md`
   - `docs/limitations_v1.md`
   - `docs/backlog_v2.md`

## Environment Requirements Before Continue

1. Neo4j service running and reachable.
2. Backend env vars configured:
   - `NEO4J_URI`
   - `NEO4J_USER`
   - `NEO4J_PASSWORD`
   - `NEO4J_DATABASE`
   - `VIEWER_INDEX_PATH`
