# Frontend Week 4 (Dual Pane + Sync)

## Delivered

1. Split layout frontend at `frontend/`:
   - left: Three.js GLB viewer
   - right: Cytoscape graph view
2. Bidirectional sync:
   - viewer/object pick -> graph focus + neighborhood refresh
   - graph node pick -> viewer focus/highlight
3. Added controls:
   - hop selector (1/2)
   - focus by GlobalId
   - big picture view (`/api/graph/full`)

## Backend Extensions

1. `GET /api/config`
2. `GET /api/graph/full`
3. Static mounts:
   - `/static` for frontend assets
   - `/viewer-files` for `model.glb`
4. Added `CSV` graph store mode for local run without Neo4j.

## Run (CSV Mode, no Neo4j needed)

```bash
GRAPH_STORE_MODE=csv \\
GRAPH_OUTPUT_DIR=/abs/path/to/parser_output \\
VIEWER_INDEX_PATH=/abs/path/to/viewer/object_index.json \\
VIEWER_FILES_DIR=/abs/path/to/viewer \\
FRONTEND_DIR=/abs/path/to/frontend \\
VIEWER_MODEL_URL=/viewer-files/model.glb \\
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open: `http://127.0.0.1:8000/`

## Notes

1. `GRAPH_OUTPUT_DIR` and `VIEWER_INDEX_PATH` should come from the same IFC model output.
2. `window.ifcApp` is exposed for debug and automated smoke checks.
