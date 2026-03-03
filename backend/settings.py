"""Runtime settings for backend API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Settings:
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_database: str
    viewer_index_path: Optional[str]
    api_title: str = "IFC Graph API"


def load_settings() -> Settings:
    return Settings(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
        neo4j_database=os.getenv("NEO4J_DATABASE", "neo4j"),
        viewer_index_path=os.getenv("VIEWER_INDEX_PATH"),
    )

