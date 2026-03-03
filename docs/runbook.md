# Runbook (V1)

## 1. Environment

```bash
cd /Users/zijian/Desktop/IFC2StructuredData
pip install -r requirements.txt
```

## 2. Parse IFC to Structured Output

```bash
python ifc2structureddata.py /abs/path/model.ifc /abs/path/output_dir
```

Expected core files:

1. `attribute.csv`
2. `relationships.csv`
3. `geometry_instance.csv`
4. `geometry_library.csv`
5. `meta.json`

## 3. Build Viewer Assets (GLB + object index)

```bash
python scripts/build_viewer_assets.py /abs/path/model.ifc /abs/path/output_dir --threads 4
```

Expected outputs:

1. `/abs/path/output_dir/viewer/model.glb`
2. `/abs/path/output_dir/viewer/object_index.json`
3. `/abs/path/output_dir/viewer/viewer_build_report.json`

Note:

1. `IfcOpeningElement` is intentionally excluded from GLB export in V1.

## 4. Graph Import (Neo4j)

Dry-run:

```bash
python scripts/import_to_neo4j.py /abs/path/output_dir --dry-run
```

Real import:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD='your_password'
export NEO4J_DATABASE=neo4j

python scripts/import_to_neo4j.py /abs/path/output_dir --replace
```

## 5. Run Backend + Frontend (CSV mode, no Neo4j)

```bash
GRAPH_STORE_MODE=csv \
GRAPH_OUTPUT_DIR=/abs/path/output_dir \
VIEWER_INDEX_PATH=/abs/path/output_dir/viewer/object_index.json \
VIEWER_FILES_DIR=/abs/path/output_dir/viewer \
FRONTEND_DIR=/Users/zijian/Desktop/IFC2StructuredData/frontend \
VIEWER_MODEL_URL=/viewer-files/model.glb \
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open:

1. `http://127.0.0.1:8000/` (UI)
2. `http://127.0.0.1:8000/docs` (Swagger)

## 6. Run Backend (Neo4j mode)

```bash
GRAPH_STORE_MODE=neo4j \
NEO4J_URI=bolt://localhost:7687 \
NEO4J_USER=neo4j \
NEO4J_PASSWORD='your_password' \
NEO4J_DATABASE=neo4j \
VIEWER_INDEX_PATH=/abs/path/output_dir/viewer/object_index.json \
VIEWER_FILES_DIR=/abs/path/output_dir/viewer \
FRONTEND_DIR=/Users/zijian/Desktop/IFC2StructuredData/frontend \
VIEWER_MODEL_URL=/viewer-files/model.glb \
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

## 7. Key API Smoke Checks

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/graph/overview
curl "http://127.0.0.1:8000/api/graph/full?limit=1000"
curl "http://127.0.0.1:8000/api/graph/neighborhood?globalId=<GlobalId>&hops=1&limit=500"
curl "http://127.0.0.1:8000/api/object/<GlobalId>"
curl "http://127.0.0.1:8000/api/geometry/<definition_id>"
curl http://127.0.0.1:8000/api/viewer/index
```

## 8. Week 6 Acceptance

Dataset/API baseline (allows empty viewer index):

```bash
python scripts/week6_acceptance.py \
  --output-dir example_str \
  --report-path docs/week6_acceptance_report.json \
  --viewer-files-dir /Users/zijian/Desktop/IFC2StructuredData/test_output/viewer_arch/viewer \
  --frontend-dir /Users/zijian/Desktop/IFC2StructuredData/frontend
```

Strict dual-pane acceptance (requires viewer index overlap with graph):

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

Interpretation:

1. `PASS=True` means acceptance passed.
2. In strict mode, script fails if:
   - viewer index is empty, or
   - viewer index has insufficient overlap with graph object IDs.

## 9. Troubleshooting

1. `RuntimeError: Graph service is not initialized`
   - Use `with TestClient(app)` when testing FastAPI lifespan.
2. `Viewer: mapped 0 objects`
   - `VIEWER_INDEX_PATH` missing or model/index mismatch.
3. Graph is dense/slow in big picture
   - keep `limit<=1000`, apply filters (`Type`, `Rel`, `Geometry`, `Labels`).
4. Viewer shows openings as solids
   - rebuild assets using current builder (V1 excludes `IfcOpeningElement`).
