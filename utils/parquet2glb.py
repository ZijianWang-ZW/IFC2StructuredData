"""
In-memory geometry → GLB converter.

Accepts a list of geometry dicts (GlobalId, vertices, faces, material_groups)
with vertices already in world coordinates (meters).
Only applies IFC→glTF coordinate conversion (Y-up) at root level.
"""

from __future__ import annotations
import os
import gc
import logging
from typing import Dict, List, Any, Optional
from time import time

import numpy as np

from pygltflib import (
    GLTF2, Scene as GLTFScene, Node as GLTFNode, Mesh as GLTFMesh,
    Primitive as GLTFPrimitive, Buffer as GLTFBuffer, BufferView as GLTFBufferView,
    Accessor as GLTFAccessor, Asset as GLTFAsset, Material as GLTFMaterial,
    PbrMetallicRoughness, ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER,
    FLOAT, UNSIGNED_SHORT, UNSIGNED_INT
)

logger = logging.getLogger(__name__)

LOG_PROGRESS_INTERVAL = 5000


class GLBConverter:
    """GLB converter — one mesh per element, no instancing."""

    def __init__(self):
        self.gltf = GLTF2()
        self.gltf.asset = GLTFAsset(version='2.0', generator='ifc-parser')
        self.gltf.scenes = [GLTFScene(nodes=[0])]
        self.gltf.nodes = []
        self.gltf.meshes = []
        self.gltf.materials = []
        self.gltf.buffers = []
        self.gltf.bufferViews = []
        self.gltf.accessors = []

        # Root node with IFC→glTF coordinate conversion (Z-up to Y-up)
        self.root_node = GLTFNode(
            children=[],
            matrix=[
                1, 0, 0, 0,
                0, 0, -1, 0,
                0, 1, 0, 0,
                0, 0, 0, 1
            ]
        )
        self.gltf.nodes.append(self.root_node)

        self.bin_blob = bytearray()

        # Caches
        self.material_cache: Dict[tuple, int] = {}

        # Stats
        self.meshes_created = 0
        self.nodes_created = 0
        self.objects_skipped = 0

    def cleanup(self) -> None:
        """Release memory held by converter."""
        self.bin_blob = bytearray()
        self.material_cache.clear()

        if self.gltf:
            self.gltf.nodes = []
            self.gltf.meshes = []
            self.gltf.materials = []
            self.gltf.buffers = []
            self.gltf.bufferViews = []
            self.gltf.accessors = []
            self.gltf.scenes = []
            self.gltf = None

        self.root_node = None

    def _align4(self, n: int) -> int:
        """Align to 4-byte boundary (glTF requirement)."""
        return (n + 3) & ~3

    def _append_bytes(self, data: bytes) -> int:
        """Append data to binary blob with 4-byte alignment."""
        offset = self._align4(len(self.bin_blob))
        if offset > len(self.bin_blob):
            self.bin_blob.extend(b"\x00" * (offset - len(self.bin_blob)))
        self.bin_blob.extend(data)
        return offset

    def _get_material(self, rgba: List[float]) -> int:
        """Get or create material, returns material index."""
        key = tuple(round(c, 3) for c in rgba[:4])
        if key in self.material_cache:
            return self.material_cache[key]

        mat_idx = len(self.gltf.materials)
        self.material_cache[key] = mat_idx

        r, g, b, a = key
        self.gltf.materials.append(GLTFMaterial(
            pbrMetallicRoughness=PbrMetallicRoughness(
                baseColorFactor=[r, g, b, a],
                metallicFactor=0.0,
                roughnessFactor=0.9
            ),
            alphaMode='BLEND' if a < 0.999 else 'OPAQUE',
            doubleSided=True
        ))
        return mat_idx

    def _create_mesh_from_data(self, vertices: List, faces: List, material_groups: List[Dict]) -> Optional[int]:
        """Create GLTFMesh directly from vertex/face/material data. Returns mesh index or None."""
        if not vertices or not faces:
            return None

        v_np = np.array(vertices, dtype=np.float32)
        if v_np.ndim != 2 or v_np.shape[1] != 3:
            return None
        if not np.isfinite(v_np).all():
            return None

        # Add vertices to buffer
        v_bytes = v_np.tobytes()
        v_offset = self._append_bytes(v_bytes)
        v_bv_idx = len(self.gltf.bufferViews)
        self.gltf.bufferViews.append(GLTFBufferView(
            buffer=0, byteOffset=v_offset, byteLength=len(v_bytes), target=ARRAY_BUFFER
        ))

        v_min = v_np.min(axis=0).tolist()
        v_max = v_np.max(axis=0).tolist()
        v_acc_idx = len(self.gltf.accessors)
        self.gltf.accessors.append(GLTFAccessor(
            bufferView=v_bv_idx, byteOffset=0, componentType=FLOAT,
            count=len(vertices), type='VEC3', min=v_min, max=v_max
        ))

        # Convert faces
        faces_np = np.array(faces, dtype=np.int32)
        max_idx = int(faces_np.max()) if faces_np.size > 0 else 0
        use_u16 = max_idx < 65536

        if not material_groups:
            material_groups = [{'rgba': [0.5, 0.5, 0.5, 1.0], 'face_indices': list(range(len(faces)))}]

        primitives = []
        for group in material_groups:
            face_indices = group.get('face_indices', [])
            if not face_indices:
                continue

            group_faces = faces_np[face_indices]
            indices = group_faces.flatten()
            indices_np = indices.astype(np.uint16 if use_u16 else np.uint32)

            idx_bytes = indices_np.tobytes()
            idx_offset = self._append_bytes(idx_bytes)
            idx_bv_idx = len(self.gltf.bufferViews)
            self.gltf.bufferViews.append(GLTFBufferView(
                buffer=0, byteOffset=idx_offset, byteLength=len(idx_bytes), target=ELEMENT_ARRAY_BUFFER
            ))

            idx_acc_idx = len(self.gltf.accessors)
            self.gltf.accessors.append(GLTFAccessor(
                bufferView=idx_bv_idx, byteOffset=0,
                componentType=UNSIGNED_SHORT if use_u16 else UNSIGNED_INT,
                count=len(indices_np), type='SCALAR'
            ))

            mat_idx = self._get_material(group.get('rgba', [0.5, 0.5, 0.5, 1.0]))
            primitives.append(GLTFPrimitive(
                attributes={'POSITION': v_acc_idx},
                indices=idx_acc_idx,
                material=mat_idx
            ))

        if not primitives:
            return None

        mesh_idx = len(self.gltf.meshes)
        self.gltf.meshes.append(GLTFMesh(primitives=primitives))
        self.meshes_created += 1

        return mesh_idx

    def convert(self, geometry_data: List[Dict], output_path: str) -> str:
        """Convert list of geometry dicts to GLB.

        Each dict has: GlobalId, vertices, faces, material_groups.
        Vertices are already in world coordinates — no per-node transform needed.
        """
        start = time()
        logger.info(f"[GLB] Converting {len(geometry_data)} elements to GLB")

        for idx, item in enumerate(geometry_data):
            guid = item.get('GlobalId', '')
            vertices = item.get('vertices', [])
            faces = item.get('faces', [])
            material_groups = item.get('material_groups', [])

            mesh_idx = self._create_mesh_from_data(vertices, faces, material_groups)
            if mesh_idx is None:
                self.objects_skipped += 1
                continue

            node = GLTFNode(
                name=guid,
                mesh=mesh_idx,
                extras={"globalId": guid}
            )
            node_idx = len(self.gltf.nodes)
            self.gltf.nodes.append(node)
            self.root_node.children.append(node_idx)
            self.nodes_created += 1

            if (idx + 1) % LOG_PROGRESS_INTERVAL == 0:
                gc.collect()
                logger.info(f"[GLB] Processed {idx + 1}/{len(geometry_data)} elements...")

        gc.collect()

        if self.nodes_created == 0:
            raise RuntimeError("No valid objects to export")

        # Finalize buffer
        buffer_length = self._align4(len(self.bin_blob))
        if len(self.bin_blob) < buffer_length:
            self.bin_blob.extend(b"\x00" * (buffer_length - len(self.bin_blob)))

        self.gltf.buffers = [GLTFBuffer(byteLength=buffer_length)]
        self.gltf.set_binary_blob(bytes(self.bin_blob))

        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        self.gltf.save_binary(output_path)

        file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        elapsed = time() - start

        logger.info(f"[GLB] Saved: {output_path} ({file_size_mb:.2f} MB)")
        logger.info(f"[GLB] Nodes: {self.nodes_created}, Meshes: {self.meshes_created}")
        logger.info(f"[GLB] Skipped: {self.objects_skipped}, Time: {elapsed:.2f}s")

        return output_path


def convert_geometry_to_glb(
    geometry_data: List[Dict],
    output_path: str,
) -> str:
    """
    Convert in-memory geometry data to GLB.

    Args:
        geometry_data: List of dicts with keys: GlobalId, vertices, faces, material_groups
        output_path: Output GLB file path

    Returns:
        Output file path
    """
    converter = GLBConverter()
    try:
        result = converter.convert(geometry_data, output_path)
        return result
    finally:
        converter.cleanup()
        gc.collect()
