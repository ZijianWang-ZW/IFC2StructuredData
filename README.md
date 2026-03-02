# IFC2StructuredData

Convert IFC (Industry Foundation Classes) building models into structured, portable formats: CSV for attributes and relationships, OBJ/MTL for per-element 3D geometry, and optionally GLB for visualization.

## Why

IFC files are complex and difficult to work with programmatically. This tool extracts the useful parts into simple, widely-supported formats that can be consumed by any language or tool -- no IFC SDK required downstream.

## Quick Start

```bash
pip install -r requirements.txt
python ifc2structureddata.py model.ifc output/
```

Output:

```
output/
├── attribute.csv        # Element attributes (type, name, properties, psets)
├── relationships.csv    # Spatial and hierarchical relationships
├── meta.json            # Model metadata and units
├── geometry/            # One OBJ + MTL pair per element
│   ├── 1q_l_fz3e_n.obj
│   ├── 1q_l_fz3e_n.mtl
│   └── ...
└── ifc_parser.log
```

To also generate a GLB file for 3D viewing:

```bash
python ifc2structureddata.py model.ifc output/ --glb
```

## Output Format

### attribute.csv

One row per IFC element. Columns include:

| Column | Description |
|--------|-------------|
| `GlobalId` | IFC GlobalId (unique per element) |
| `type` | Entity type (`IfcWall`, `IfcDoor`, etc.) |
| `Name` | Element name |
| `has_geometry` | `True` if geometry files exist for this element |
| *...* | All extracted IFC property sets and quantities |

### relationships.csv

| Column | Description |
|--------|-------------|
| `Relating_Object_GUID` | Parent element GlobalId |
| `Related_Object_GUID` | Child element GlobalId |
| `Relationship_Type` | e.g., `IfcRelContainedInSpatialStructure`, `IfcRelAggregates` |
| `Relating_Object_Type` | Parent IFC type |
| `Related_Object_Type` | Child IFC type |

### geometry/

Each element with geometry gets two files:

- **`{safe_id}.obj`** -- Wavefront OBJ with vertices in world coordinates (meters)
- **`{safe_id}.mtl`** -- Companion material file with diffuse colors

No additional transforms are needed; vertices are already in their final world position.

### meta.json

Model-level information: schema version, authoring application, export date, units, and object count.

## Filename Encoding

IFC GlobalIds are Base64-encoded and case-sensitive (`QS` and `Qs` are different elements). Since macOS and Windows filesystems are case-insensitive, we encode filenames to avoid collisions:

- Uppercase letter `A` becomes `_a`
- Literal underscore `_` becomes `__`
- Everything else (lowercase, digits, `$`) stays as-is

Example: `2FQJHKdH` becomes `2_f_q_j_h_kd_h`

To decode back to a GlobalId: `__` -> `_`, then `_x` -> `X`.

## Units

- **Geometry (OBJ files)**: Vertices are in meters, converted automatically by the geometry engine.
- **Properties (attribute.csv)**: Values remain in original IFC units. Check `meta.json` -> `units` -> `length_unit` for the source unit system (e.g., `mm`, `m`, `ft`).

## Options

```
python ifc2structureddata.py <ifc_file> <output_dir> [options]

  --glb [PATH]     Generate GLB file (default: output_dir/model.glb)
  --threads N      Geometry processing threads (default: 4)
```

## Dependencies

- [ifcopenshell](https://ifcopenshell.org/) -- IFC file parsing and geometry tessellation
- [numpy](https://numpy.org/) -- Array operations
- [pandas](https://pandas.pydata.org/) -- DataFrame handling and CSV output
- [pygltflib](https://gitlab.com/dodgyville/pygltflib) -- GLB generation (only needed with `--glb`)
- [psutil](https://github.com/giampaolo/psutil) -- Optional, for memory usage logging

## Project Structure

```
ifc2structureddata.py    # Entry point and pipeline orchestration
utils/
├── geometry.py          # Geometry extraction, OBJ/MTL writing
├── attributes.py        # IFC property and quantity extraction
├── relationships.py     # Spatial and hierarchical relationship extraction
├── metadata.py          # Model metadata and unit detection
├── color.py             # Material color resolution
└── parquet2glb.py       # In-memory geometry to GLB conversion
```

## License

MIT. See [LICENSE](LICENSE).
