# Frontend Week 5 (Refinement + Stability)

## Delivered

1. Graph interaction refinement:
   - object-type filter (`Type`)
   - relationship-type filter (`Rel`)
   - geometry toggle (`Geometry`)
   - label toggle (`Labels`)
   - `Reset Filters`
2. Big-picture usability:
   - `Back To Focus` restores the previous local neighborhood context.
3. Viewer controls:
   - camera presets: `Fit`, `Iso`, `Top`, `Front`.
4. Robustness:
   - loading/busy state for graph operations
   - guarded async handlers to avoid unhandled interaction failures
   - explicit graph/viewer error status rendering
5. Readability/performance:
   - in-place hidden-class filtering on Cytoscape elements
   - dynamic filter option generation from loaded graph
   - tuned layout strategy for neighborhood, expansion, and big-picture views
6. Neo4j-style interaction refinement:
   - force-directed graph behavior (`cose`) for more natural graph movement
   - click-to-emphasize local neighborhood with non-neighborhood fading
   - hover preview context + tooltip for full node text
7. Topology semantics:
   - topology node highlighting (`IfcSite`, `IfcBuilding`, `IfcBuildingStorey`)
   - topology edge highlighting (`IfcRelAggregates`, `IfcRelContainedInSpatialStructure`)
   - topology count surfaced in graph status line

## Validation

1. Unit tests:
   - `python -m unittest discover -s tests -v`
   - result: all pass
2. Browser smoke (Playwright MCP):
   - big-picture load and back-to-focus path
   - filter impact on visible nodes/edges
   - node/edge/geometry inspector behavior
   - camera preset movement checks
   - double-click expansion path confirmed with additive node growth
3. Additional browser smoke (Playwright CLI):
   - full-label rendering available for building nodes (`name + ifcType`)
   - hover tooltip displays complete text for dense/long names
   - topology style check passed (distinct node/edge color classes)
