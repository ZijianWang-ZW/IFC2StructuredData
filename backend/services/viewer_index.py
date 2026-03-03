"""Viewer index loader with simple file cache."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional


class ViewerIndexRepository:
    def __init__(self, index_path: Optional[str]) -> None:
        self.index_path = index_path
        self._cache_mtime: Optional[float] = None
        self._cache_data: Dict[str, Dict[str, Any]] = {}

    def _load_if_needed(self) -> None:
        if not self.index_path:
            self._cache_data = {}
            self._cache_mtime = None
            return
        if not os.path.isfile(self.index_path):
            self._cache_data = {}
            self._cache_mtime = None
            return
        mtime = os.path.getmtime(self.index_path)
        if self._cache_mtime is not None and mtime == self._cache_mtime:
            return
        with open(self.index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
        self._cache_data = data
        self._cache_mtime = mtime

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        self._load_if_needed()
        return dict(self._cache_data)

    def get(self, global_id: str) -> Optional[Dict[str, Any]]:
        self._load_if_needed()
        return self._cache_data.get(global_id)

