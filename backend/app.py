"""FastAPI app for graph and viewer queries."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.errors import EntityNotFoundError
from backend.settings import Settings, load_settings
from backend.services.csv_store import CsvGraphStore
from backend.services.graph_service import GraphService
from backend.services.neo4j_store import Neo4jGraphStore
from backend.services.viewer_index import ViewerIndexRepository


def _build_default_service(settings: Settings) -> GraphService:
    if settings.graph_store_mode == "csv":
        if not settings.graph_output_dir:
            raise RuntimeError(
                "GRAPH_OUTPUT_DIR is required when GRAPH_STORE_MODE=csv"
            )
        store = CsvGraphStore(settings.graph_output_dir)
    else:
        store = Neo4jGraphStore(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
        )
    viewer_repo = ViewerIndexRepository(settings.viewer_index_path)
    return GraphService(store=store, viewer_index_repo=viewer_repo)


def create_app(service: Optional[GraphService] = None, settings: Optional[Settings] = None) -> FastAPI:
    app_settings = settings or load_settings()
    owned_service = service is None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if _app.state.graph_service is None:
            _app.state.graph_service = _build_default_service(app_settings)
        try:
            yield
        finally:
            if owned_service and _app.state.graph_service is not None:
                _app.state.graph_service.close()

    app = FastAPI(title=app_settings.api_title, version="0.1.0", lifespan=lifespan)
    app.state.graph_service = service
    app.state.settings = app_settings

    if app_settings.frontend_dir and os.path.isdir(app_settings.frontend_dir):
        app.mount(
            "/static",
            StaticFiles(directory=app_settings.frontend_dir),
            name="frontend-static",
        )

    if app_settings.viewer_files_dir and os.path.isdir(app_settings.viewer_files_dir):
        app.mount(
            "/viewer-files",
            StaticFiles(directory=app_settings.viewer_files_dir),
            name="viewer-files",
        )

    def _service() -> GraphService:
        svc = app.state.graph_service
        if svc is None:
            raise RuntimeError("Graph service is not initialized")
        return svc

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/config")
    def get_config() -> dict:
        return {
            "viewerModelUrl": app_settings.viewer_model_url,
            "graphStoreMode": app_settings.graph_store_mode,
        }

    @app.get("/api/object/{global_id}")
    def get_object(global_id: str) -> dict:
        try:
            return _service().get_object_detail(global_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/geometry/{definition_id}")
    def get_geometry(definition_id: int) -> dict:
        try:
            return _service().get_geometry_detail(definition_id)
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

    @app.get("/api/graph/full")
    def get_full_graph(limit: int = Query(default=1000, ge=1, le=5000)) -> dict:
        return _service().get_full_graph(limit=limit)

    @app.get("/api/viewer/index")
    def get_viewer_index() -> dict:
        return _service().get_viewer_index()

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        if app_settings.frontend_dir:
            index_path = os.path.join(app_settings.frontend_dir, "index.html")
            if os.path.isfile(index_path):
                return FileResponse(index_path)
        raise HTTPException(status_code=404, detail="Frontend not configured")

    return app


app = create_app()
