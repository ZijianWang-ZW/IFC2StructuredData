"""Abstract interface for graph data access."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class GraphStore(ABC):
    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_building_object(self, global_id: str) -> Dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def get_building_objects(self, global_ids: List[str]) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_building_object_summaries(self, global_ids: List[str]) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_neighborhood_object_ids(self, global_id: str, hops: int, limit: int) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def get_relates_edges(self, global_ids: List[str]) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_geometry_for_objects(self, global_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    def get_geometry_definition(self, definition_id: int) -> Dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def get_overview(self) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_all_object_ids(self, limit: int) -> List[str]:
        raise NotImplementedError
