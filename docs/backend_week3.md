# Backend API (Week 3)

## Scope

Implemented endpoints:

1. `GET /api/health`
2. `GET /api/object/{global_id}`
3. `GET /api/graph/neighborhood?globalId=...&hops=1|2&limit=...`
4. `GET /api/graph/overview`
5. `GET /api/viewer/index`

## Architecture

1. `backend/services/base_store.py`: Graph data access interface.
2. `backend/services/neo4j_store.py`: Neo4j implementation.
3. `backend/services/viewer_index.py`: cached JSON index loader.
4. `backend/services/graph_service.py`: application service and response assembly.
5. `backend/app.py`: FastAPI routes and error mapping.

## Run

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD='your_password'
export NEO4J_DATABASE=neo4j
export VIEWER_INDEX_PATH=/abs/path/to/viewer/object_index.json

uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```

## Notes

1. `hops` is intentionally limited to `1..2` in V1.
2. Neighborhood query keeps `RELATES_TO` direction as stored.
3. Viewer index is optional; if file path is missing, `/api/viewer/index` returns `{}`.
