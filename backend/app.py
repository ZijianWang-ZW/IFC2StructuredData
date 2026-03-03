"""FastAPI app for graph and viewer queries."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from backend.errors import EntityNotFoundError
from backend.settings import load_settings
from backend.services.graph_service import GraphService
from backend.services.neo4j_store import Neo4jGraphStore
from backend.services.viewer_index import ViewerIndexRepository


def _build_default_service() -> GraphService:
    settings = load_settings()
    store = Neo4jGraphStore(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
    )
    viewer_repo = ViewerIndexRepository(settings.viewer_index_path)
    return GraphService(store=store, viewer_index_repo=viewer_repo)


def create_app(service: Optional[GraphService] = None) -> FastAPI:
    owned_service = service is None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if _app.state.graph_service is None:
            _app.state.graph_service = _build_default_service()
        try:
            yield
        finally:
            if owned_service and _app.state.graph_service is not None:
                _app.state.graph_service.close()

    app = FastAPI(title="IFC Graph API", version="0.1.0", lifespan=lifespan)
    app.state.graph_service = service

    def _service() -> GraphService:
        svc = app.state.graph_service
        if svc is None:
            raise RuntimeError("Graph service is not initialized")
        return svc

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/object/{global_id}")
    def get_object(global_id: str) -> dict:
        try:
            return _service().get_object_detail(global_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/graph/neighborhood")
    def get_neighborhood(
        globalId: str,
        hops: int = Query(default=1, ge=1, le=2),
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict:
        try:
            return _service().get_neighborhood(globalId, hops=hops, limit=limit)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/graph/overview")
    def get_overview() -> dict:
        return _service().get_overview()

    @app.get("/api/viewer/index")
    def get_viewer_index() -> dict:
        return _service().get_viewer_index()

    return app


app = create_app()
