# IFC2StructuredData

Convert IFC (Industry Foundation Classes) building models into structured, portable formats: CSV for attributes, relationships, and **parametric geometry**; OBJ/MTL only for non-parametric mesh elements.

## Why

IFC files are complex and difficult to work with programmatically. This tool extracts the useful parts into simple, widely-supported formats that can be consumed by any language or tool -- no IFC SDK required downstream.

Most IFC geometry is **parametric** (extrusions, booleans, mapped instances) rather than raw mesh. This tool preserves that parametric structure in a JSON-based CSG tree, enabling downstream consumers to reconstruct, analyze, or transform geometry without loss of modeling intent.

## Quick Start

```bash
pip install -r requirements.txt
python ifc2structureddata.py model.ifc output/
```

Output:

```
output/
├── attribute.csv              # Element attributes (type, name, properties, psets)
├── geometry_library.csv       # Unique geometry definitions (deduplicated)
├── geometry_instance.csv      # Per-element geometry index (every element with geometry)
├── relationships.csv          # Spatial and hierarchical relationships
├── meta.json                  # Model metadata and units
├── geometry/                  # OBJ + MTL only for non-parametric elements
│   ├── {safe_id}.obj
│   ├── {safe_id}.mtl
│   └── ...
└── ifc_parser.log
```

## Geometry: Principles

### No duplicate storage

Each element's geometry is stored exactly **once**:

- **Parametric elements** (extrusion, boolean, mapped, etc.) → stored in `geometry_library.csv` + `geometry_instance.csv`
- **Non-parametric elements** (faceted brep, tessellated mesh) → stored in `geometry/{id}.obj`

### Instancing and deduplication

BIM models are inherently object-oriented: the same door profile, the same window frame, the same structural column appears hundreds of times with different positions. Instead of duplicating geometry for each instance, we store each **unique shape definition once** in the library, and each element references it with its own placement.

```
geometry_library.csv (3,452 unique definitions)
  definition_id=1258: 50x150mm rectangle extruded 500mm

geometry_instance.csv (15,074 elements)
  Element A → definition_id=1258, position=[1000, 2000, 0]
  Element B → definition_id=1258, position=[3000, 2000, 0]
  Element C → definition_id=1258, position=[5000, 2000, 0]
  ...250 elements share this single definition
```

On a typical architectural model (15K elements): 14,737 parametric elements compress to 3,452 unique definitions. Total geometry storage is reduced ~88% compared to storing mesh for every element.

### How to look up geometry

**Start from `geometry_instance.csv`** — every element with geometry has one row here. Check the `definition_id` column:

```
definition_id has value?
  ├── YES → Parametric. JOIN with geometry_library.csv on definition_id.
  │         The geometry_tree column contains the full parametric description.
  │         The instance_params column contains this element's placement/transform.
  │
  └── NULL → Non-parametric mesh. Look in geometry/{safe_guid}.obj
```

## Output Format

### geometry_instance.csv

One row per element that has geometry. This is the **routing table** for all geometry lookups.

| Column | Type | Description |
|--------|------|-------------|
| `GlobalId` | str | Element identifier (FK to `attribute.csv`) |
| `ifc_type` | str | `IfcWall`, `IfcDoor`, `IfcSlab`, etc. |
| `method` | str | Geometry category: `extrusion`, `boolean`, `mapped`, `faceted_brep`, etc. |
| `definition_id` | int / null | FK to `geometry_library.csv`. Null for non-parametric elements. |
| `instance_params` | JSON / null | Per-instance data: position, transform. Null when not applicable. |

### geometry_library.csv

One row per unique geometry definition. Multiple elements can share the same definition.

| Column | Type | Description |
|--------|------|-------------|
| `definition_id` | int | Primary key |
| `method` | str | `extrusion`, `boolean`, `mapped`, etc. |
| `representation_type` | str | IFC RepresentationType (`SweptSolid`, `Clipping`, etc.) |
| `geometry_tree` | JSON | Full parametric geometry description (CSG tree) |
| `instance_count` | int | Number of elements using this definition |

### geometry/ (OBJ/MTL)

Only **non-parametric elements** (faceted brep, tessellated mesh) get files here:

- **`{safe_id}.obj`** -- Wavefront OBJ with vertices in world coordinates (meters)
- **`{safe_id}.mtl`** -- Companion material file with diffuse colors

No additional transforms needed; vertices are already in their final world position.

### attribute.csv

One row per IFC element.

| Column | Description |
|--------|-------------|
| `GlobalId` | IFC GlobalId (unique per element) |
| `type` | Entity type (`IfcWall`, `IfcDoor`, etc.) |
| `Name` | Element name |
| `has_geometry` | `True` if this element has geometry (in CSV or OBJ) |
| *...* | All extracted IFC property sets and quantities |

### relationships.csv

| Column | Description |
|--------|-------------|
| `Relating_Object_GUID` | Parent element GlobalId |
| `Related_Object_GUID` | Child element GlobalId |
| `Relationship_Type` | e.g., `IfcRelContainedInSpatialStructure`, `IfcRelAggregates` |
| `Relating_Object_Type` | Parent IFC type |
| `Related_Object_Type` | Child IFC type |

### meta.json

Model-level information: schema version, authoring application, export date, units, and object count.

## Geometry Types Explained

### Extrusion (`method = extrusion`)

The most common type in architectural models. A 2D profile is swept along a direction for a given depth.

```
geometry_library.csv:
{
  "type": "IfcExtrudedAreaSolid",
  "profile": {
    "type": "IfcRectangleProfileDef",    ← 2D cross-section shape
    "x_dim": 200.0,                      ← width in mm
    "y_dim": 3000.0                      ← height in mm
  },
  "depth": 3500.0,                       ← extrusion length in mm
  "direction": [0.0, 0.0, 1.0]          ← extrusion direction (up)
}

geometry_instance.csv:
  instance_params = {
    "position": {                        ← where this instance is placed
      "location": [5000.0, 2000.0, 0.0],
      "axis": [0.0, 0.0, 1.0],
      "ref_direction": [1.0, 0.0, 0.0]
    }
  }
```

**How to reconstruct**: Take the 2D profile, extrude it along `direction` for `depth`, then place the result at the instance's `position`.

Supported profile types include `IfcRectangleProfileDef`, `IfcCircleProfileDef`, `IfcIShapeProfileDef`, `IfcArbitraryClosedProfileDef` (any closed curve), and many more.

### Boolean / Clipping (`method = boolean`)

A CSG (Constructive Solid Geometry) operation. Typically used for walls with openings, slabs with holes, etc.

```
geometry_library.csv:
{
  "type": "IfcBooleanClippingResult",
  "operator": "DIFFERENCE",               ← subtract second from first
  "first_operand": {                       ← the base solid
    "type": "IfcExtrudedAreaSolid",
    "profile": {...},
    "depth": 3500.0
  },
  "second_operand": {                      ← the cutting shape
    "type": "IfcHalfSpaceSolid",
    "base_surface": {
      "type": "IfcPlane",
      "position": {...}
    },
    "agreement_flag": true
  }
}
```

**How to reconstruct**: Build the `first_operand` solid, build the `second_operand` solid, then apply the boolean `operator` (DIFFERENCE, UNION, or INTERSECTION). Boolean trees can be recursive — a `first_operand` can itself be another `IfcBooleanClippingResult`.

### Mapped Item (`method = mapped`)

IFC's native instancing mechanism — equivalent to a "block reference" in CAD or a class/object relationship in OOP. One source geometry is defined once, then placed multiple times with different transforms.

```
geometry_library.csv:
{
  "type": "IfcMappedItem",
  "mapping_source_id": 1063099,            ← IFC entity ID for traceability
  "mapping_source": {                      ← the shared geometry definition
    "representation_type": "SweptSolid",
    "items": [                             ← can contain extrusions, booleans, etc.
      {"type": "IfcExtrudedAreaSolid", "profile": {...}, "depth": 1522.0},
      {"type": "IfcExtrudedAreaSolid", "profile": {...}, "depth": 40.0}
    ]
  },
  "mapping_origin": {                      ← source coordinate system
    "location": [0.0, 0.0, 0.0]
  }
}

geometry_instance.csv:
  instance_params = {
    "mapping_target": {                    ← how to place this instance
      "type": "IfcCartesianTransformationOperator3D",
      "local_origin": [12000.0, 5000.0, 3200.0],
      "axis1": [1.0, 0.0, 0.0],
      "axis2": [0.0, 1.0, 0.0],
      "scale": 1.0
    }
  }
```

**How to reconstruct**: Build the geometry described in `mapping_source.items`, position it at `mapping_origin`, then apply the instance's `mapping_target` transform (translation, rotation, scale).

This is where the biggest storage savings come from. A single solar panel definition shared by 413 instances, a single door type used across every floor — all stored once.

### Advanced Brep (`method = advanced_brep`)

NURBS-based boundary representation. Each face is defined by an analytical surface (cylindrical, spherical, B-spline, etc.) bounded by edge curves.

```
geometry_library.csv:
{
  "type": "IfcAdvancedBrep",
  "faces": [
    {
      "type": "IfcAdvancedFace",
      "surface": {
        "type": "IfcCylindricalSurface",
        "radius": 50.0,
        "position": {...}
      },
      "bounds": [
        {
          "type": "IfcFaceBound",
          "loop": {
            "type": "IfcEdgeLoop",
            "edges": [...]
          }
        }
      ]
    }
  ]
}
```

**How to reconstruct**: Evaluate each face's analytical surface, trim it with the boundary edge loops. This requires a NURBS/B-rep kernel (e.g., OpenCASCADE).

### Other Parametric Types

| Method | IFC Type | Description |
|--------|----------|-------------|
| `revolution` | IfcRevolvedAreaSolid | 2D profile rotated around an axis |
| `swept_disk` | IfcSweptDiskSolid | Circle swept along a 3D curve (pipes) |
| `swept_curve` | IfcSurfaceCurveSweptAreaSolid | Profile swept along curve on a surface |
| `csg` | IfcCsgSolid | CSG tree root node |

All follow the same pattern: `geometry_library.csv` stores the parametric definition, `geometry_instance.csv` stores per-element placement.

### Faceted Brep / Mesh (`method = faceted_brep`)

Non-parametric geometry — the shape is defined only as a triangulated mesh. There is no parametric description to extract.

```
geometry_instance.csv:
  GlobalId:        1qLFz3eN1Anw3p2RKHqagQ
  method:          faceted_brep
  definition_id:   null          ← no library entry
  instance_params: null

geometry/1q_l_fz3e_n1_anw3p2_r_k_hqag_q.obj:
  v 9.998 125.642 165.986
  v 10.021 125.634 166.011
  ...
  f 1 2 3
  f 3 4 1
  ...
```

**How to use**: Read the OBJ file directly. Vertices are in world coordinates (meters). Material colors are in the companion MTL file.

## Filename Encoding

IFC GlobalIds are Base64-encoded and case-sensitive (`QS` and `Qs` are different elements). Since macOS and Windows filesystems are case-insensitive, we encode filenames to avoid collisions:

- Uppercase letter `A` becomes `_a`
- Literal underscore `_` becomes `__`
- Everything else (lowercase, digits, `$`) stays as-is

Example: `2FQJHKdH` becomes `2_f_q_j_h_kd_h`

To decode back to a GlobalId: `__` -> `_`, then `_x` -> `X`.

## Units

- **Geometry (OBJ files)**: Vertices are in **meters**, converted automatically by the geometry engine.
- **Parametric geometry (CSV)**: Values are in **original IFC units** (typically millimeters). Check `meta.json` → `units` → `length_unit` for the source unit system.
- **Properties (attribute.csv)**: Values remain in original IFC units.

## Options

```
python ifc2structureddata.py <ifc_file> <output_dir> [options]

  --threads N      Geometry processing threads (default: 4)
```

## Dependencies

- [ifcopenshell](https://ifcopenshell.org/) -- IFC file parsing and geometry tessellation
- [numpy](https://numpy.org/) -- Array operations
- [pandas](https://pandas.pydata.org/) -- DataFrame handling and CSV output
- [psutil](https://github.com/giampaolo/psutil) -- Optional, for memory usage logging

## Project Structure

```
ifc2structureddata.py    # Entry point and pipeline orchestration
utils/
├── parametric.py        # Parametric geometry extraction, instancing, dedup
├── geometry.py          # Mesh tessellation, OBJ/MTL writing (non-parametric only)
├── attributes.py        # IFC property and quantity extraction
├── relationships.py     # Spatial and hierarchical relationship extraction
├── metadata.py          # Model metadata and unit detection
└── color.py             # Material color resolution
```

## Delivery Docs

1. Product/architecture: [docs/PRD_graph_bim_platform.md](docs/PRD_graph_bim_platform.md)
2. Week 6 acceptance summary: [docs/week6_acceptance.md](docs/week6_acceptance.md)
3. Operations guide: [docs/runbook.md](docs/runbook.md)
4. V1 constraints: [docs/limitations_v1.md](docs/limitations_v1.md)
5. V2 planning: [docs/backlog_v2.md](docs/backlog_v2.md)

## Testing (Refactor + Prototype)

1. Run all unit tests:

```bash
python -m unittest discover -s tests -v
```

2. Run Week6 dataset/API acceptance (`example_str`):

```bash
python scripts/week6_acceptance.py --output-dir example_str --report-path docs/week6_acceptance_report.json
```

3. Run strict viewer+graph acceptance (requires non-empty viewer index overlap):

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

4. Manual browser check (CSV mode):

```bash
GRAPH_STORE_MODE=csv \
GRAPH_OUTPUT_DIR=/Users/zijian/Desktop/IFC2StructuredData/test_output/arch_v1_pm \
VIEWER_INDEX_PATH=/Users/zijian/Desktop/IFC2StructuredData/test_output/viewer_arch/viewer/object_index.json \
VIEWER_FILES_DIR=/Users/zijian/Desktop/IFC2StructuredData/test_output/viewer_arch/viewer \
FRONTEND_DIR=/Users/zijian/Desktop/IFC2StructuredData/frontend \
VIEWER_MODEL_URL=/viewer-files/model.glb \
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/` and verify:

1. click viewer object <-> graph node bidirectional sync
2. node/edge inspector details
3. double-click expansion
4. filters + big-picture/back-to-focus + camera presets
5. invalid `GlobalId` focus does not overwrite existing selection

## License

MIT. See [LICENSE](LICENSE).
