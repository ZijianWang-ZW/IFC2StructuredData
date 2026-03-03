# Backlog (V2)

## Priority P0

1. Federated model support:
   - ingest/query across multiple IFC files
   - global namespace strategy for model-scoped IDs
2. Re-introduce optional semantic subgraphs:
   - material
   - classification
   - group
   - with toggleable ingest profiles
3. End-to-end automated acceptance in CI:
   - API checks
   - browser smoke checks
   - artifact validation (`model.glb`, `object_index.json`)

## Priority P1

1. Semantic enrichment pipeline from research direction:
   - `RelSpatial` derivation
   - `correspondsTo` links across disciplines/versions
2. Graph query UX:
   - saved views / pinned nodes
   - advanced filtering (multi-select type/relationship/property)
   - path query between two objects
3. Performance improvements:
   - backend response caching for repeated neighborhoods
   - server-side filtered graph endpoints
   - progressive graph loading for large models

## Priority P2

1. Change analysis and model version comparison:
   - added/removed/changed objects
   - relationship delta view
2. Viewer improvements:
   - clipping section planes
   - layer/floor visibility presets
   - isolate/hide selected branch
3. Export and interoperability:
   - export subgraph as JSON/CSV
   - shareable graph deep links

## Technical Debt

1. Consolidate acceptance scripts and browser scripts into a single `make acceptance` entrypoint.
2. Add structured logging and error taxonomy for backend APIs.
3. Expand unit/integration coverage for frontend state transitions and filter behavior.
