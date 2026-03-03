# Week 6 Acceptance Report

- Date: 2026-03-03
- Branch: `dev/pm`
- Scope: End-to-end V1 acceptance + documentation closure

## Acceptance Inputs

1. Graph dataset: `example_str`
2. Viewer asset baseline: `test_output/viewer_arch/viewer/model.glb`
3. Backend mode: `GRAPH_STORE_MODE=csv`

## Automated Acceptance (example_str)

Command:

```bash
python scripts/week6_acceptance.py \
  --output-dir example_str \
  --report-path docs/week6_acceptance_report.json \
  --viewer-files-dir /Users/zijian/Desktop/IFC2StructuredData/test_output/viewer_arch/viewer \
  --frontend-dir /Users/zijian/Desktop/IFC2StructuredData/frontend
```

Strict dual-pane command (viewer/graph overlap required):

```bash
python scripts/week6_acceptance.py \
  --output-dir /Users/zijian/Desktop/IFC2StructuredData/test_output/arch_v1_pm \
  --viewer-index-path /Users/zijian/Desktop/IFC2StructuredData/test_output/viewer_arch/viewer/object_index.json \
  --report-path docs/week6_acceptance_arch_v1_strict.json \
  --viewer-files-dir /Users/zijian/Desktop/IFC2StructuredData/test_output/viewer_arch/viewer \
  --frontend-dir /Users/zijian/Desktop/IFC2StructuredData/frontend \
  --require-viewer-index \
  --min-viewer-overlap 100
```

Result:

1. PASS = `true`
2. Dataset counts:
   - `building_nodes = 719`
   - `geometry_nodes = 68`
   - `relates_edges = 718`
   - `uses_geometry_edges = 350`
3. Filter/drop verification:
   - dropped `IfcRelAssociatesMaterial = 328`
   - dropped `IfcRelAssociatesClassification = 0`
   - dropped `IfcRelAssignsToGroup = 0`
4. API checks:
   - `/api/health` 200
   - `/api/graph/overview` 200
   - `/api/graph/full` 200
   - `/api/graph/neighborhood` 200
   - `/api/object/{globalId}` 200
   - `/api/geometry/{definitionId}` 200
5. Dry import:
   - `scripts/import_to_neo4j.py example_str --dry-run` return code 0
6. Strict mode:
   - viewer index non-empty and overlap check enforced by script flags

## Browser Validation (example_str runtime)

Runtime setup:

```bash
GRAPH_STORE_MODE=csv \
GRAPH_OUTPUT_DIR=/Users/zijian/Desktop/IFC2StructuredData/example_str \
VIEWER_INDEX_PATH=/Users/zijian/Desktop/IFC2StructuredData/example_str/viewer/object_index.json \
VIEWER_FILES_DIR=/Users/zijian/Desktop/IFC2StructuredData/test_output/viewer_arch/viewer \
FRONTEND_DIR=/Users/zijian/Desktop/IFC2StructuredData/frontend \
VIEWER_MODEL_URL=/viewer-files/model.glb \
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8011
```

Observed:

1. Page opens without frontend errors.
2. When viewer index is missing, UI degrades gracefully (`Graph: no viewer index data available`).
3. Manual `Focus` by valid `GlobalId` still returns neighborhood and inspector data.
4. Big-picture and back-to-focus controls remain functional (`~115ms` / `~5ms` in smoke run).
5. Focus failure keeps previous selection unchanged (two-phase selection commit).

## Final Verdict

V1 acceptance is complete for Week 6 based on:

1. Data-contract and API pass on `example_str`
2. Frontend interaction path pass in no-viewer-index scenario
3. Week 6 documentation set delivered (`runbook`, `limitations_v1`, `backlog_v2`)
