"""Runtime settings for backend API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Settings:
    graph_store_mode: str
    graph_output_dir: Optional[str]
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_database: str
    viewer_index_path: Optional[str]
    viewer_files_dir: Optional[str]
    viewer_model_url: str
    frontend_dir: Optional[str]
    api_title: str = "IFC Graph API"


def load_settings() -> Settings:
    return Settings(
        graph_store_mode=os.getenv("GRAPH_STORE_MODE", "neo4j").lower(),
        graph_output_dir=os.getenv("GRAPH_OUTPUT_DIR"),
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
        neo4j_database=os.getenv("NEO4J_DATABASE", "neo4j"),
        viewer_index_path=os.getenv("VIEWER_INDEX_PATH"),
        viewer_files_dir=os.getenv("VIEWER_FILES_DIR"),
        viewer_model_url=os.getenv("VIEWER_MODEL_URL", "/viewer-files/model.glb"),
        frontend_dir=os.getenv("FRONTEND_DIR", "frontend"),
    )
