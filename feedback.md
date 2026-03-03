# Feedback Integration Log

- Updated: 2026-03-03
- Scope: Week 4 prototype refinement before continuing Week 5

## User Feedback

1. Clicking a node should show its attributes, for both building nodes and geometry nodes.
2. `IfcOpeningElement` should not render as a normal solid object in GLB; it should be transparent or ignored.
3. Double-clicking a node should expand and reveal surrounding nodes.
4. Clicking an edge should show the edge name.
5. Graph interaction feels slow and should be optimized.
6. Graph node names are incomplete and interaction feels rigid; improve toward Neo4j-style behavior.
7. Confirm whether site-building-storey topology exists and color those nodes differently.

## Implementation Plan

1. Add right-side Inspector panel for node/edge attributes.
2. Add `GET /api/geometry/{definition_id}` for on-demand geometry-node detail.
3. Keep neighborhood/full graph payload lightweight by excluding heavy `geometryTreeJson` from list endpoints.
4. Add graph double-click expansion behavior for building nodes.
5. Add edge selection + edge metadata display.
6. Skip `IfcOpeningElement` during viewer GLB asset generation.
7. Improve graph performance with client-side caching + faster layout choices.

## Acceptance Criteria

1. Building node click shows IFC object metadata + extracted attributes.
2. Geometry node click shows geometry definition metadata.
3. Edge click shows relationship name/type.
4. Double-click building node expands graph (additive, not full reset).
5. Viewer build report indicates excluded `IfcOpeningElement`.
6. API and unit tests pass; browser smoke flow works end-to-end.

## Implementation Status

- [x] Feedback 1: Node inspector implemented for building node + geometry node.
- [x] Feedback 2: `IfcOpeningElement` excluded from GLB build pipeline.
- [x] Feedback 3: Building node double-click triggers neighborhood expansion.
- [x] Feedback 4: Edge click now shows relationship name/type in inspector.
- [x] Feedback 5: Graph interaction optimized with:
  - lightweight graph payload (no `geometryTreeJson` in neighborhood/full)
  - on-demand geometry detail endpoint
  - frontend caching (`neighborhood`, `full graph`, object/geometry detail)
  - faster default layouts for neighborhood/full views
  - Cytoscape viewport performance flags

## Validation Summary

1. Unit tests:
   - `python -m unittest discover -s tests -v`
   - Result: `20 tests, all passed`
2. Viewer assets rebuild:
   - Command: `python scripts/build_viewer_assets.py test_trimble/Architecture_v1.ifc test_output/viewer_arch --threads 4`
   - Result: `Excluded IFC types: IfcOpeningElement`, `Excluded elements: 102`
3. Browser checks (Playwright):
   - Building node attributes displayed in inspector.
   - Geometry node attributes loaded via `/api/geometry/{definition_id}`.
   - Edge click shows `edgeName` + `relationshipType`.
   - Double-click expansion increased graph from `20` nodes to `182` nodes in smoke run.

## Week 5 Follow-up Optimizations

1. Added production-style controls for filters (`Type`, `Rel`, geometry/label toggles).
2. Added `Back To Focus` to restore local view after big-picture exploration.
3. Added viewer camera presets (`Fit`, `Iso`, `Top`, `Front`).
4. Added loading/error guarded states to improve interaction stability.
5. Re-validated with browser smoke:
  - big picture: ~139ms
  - back to focus: ~12ms
  - filtered big graph (`IfcSpace`): visible nodes reduced from `868` to `39`
  - expansion sample: `+164` nodes in one expansion flow

## Additional Refinement (Neo4j-like UX + Topology Highlight)

1. Node labels switched from ellipsis truncation to wrapped full labels (name + IFC type), with hover tooltip showing full detail.
2. Added Neo4j-style local-context interaction:
   - click node => immediate neighborhood emphasized
   - non-neighborhood nodes/edges fade
   - hover preview context and restore on mouseout
3. Layout strategy switched to force-directed (`cose`) for neighborhood, expansion, and big picture to improve natural graph motion.
4. Added topology visual semantics:
   - topology node detection by IFC type (`IfcSite`, `IfcBuilding`, `IfcBuildingStorey`)
   - topology edge detection by relation type (`IfcRelAggregates`, `IfcRelContainedInSpatialStructure`)
   - dedicated colors for topology nodes and topology edges
5. Graph status now reports topology node count for loaded view.

### Additional Validation

1. Data confirmation:
   - `example_str/relationships.csv` includes `IfcRelAggregates` and `IfcRelContainedInSpatialStructure`.
2. Browser validation (Playwright CLI):
   - big picture includes topology nodes (`topologyNodeCount=6`) and topology edges (`topologyEdgeCount=625`) on `arch_v1_pm`.
   - topology colors verified from Cytoscape computed styles:
     - topology node: `rgb(37,99,235)`
     - normal building node: `rgb(15,118,110)`
   - neighborhood context fade works (`fadedAfterTap > 0`) and hover class toggles correctly.
   - double-click/expand path still works (`38 -> 202` nodes in one expansion check).
