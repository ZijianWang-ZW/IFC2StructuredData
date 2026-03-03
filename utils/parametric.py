"""
Parametric geometry extraction with instancing/deduplication.

Outputs two tables:
  geometry_library.csv  — unique geometry definitions (deduplicated)
  geometry_instance.csv — per-element instances referencing the library

Dedup strategy by method:
  mapped:     key = mapping_source_id;  instance_params = mapping_target
  extrusion:  key = hash(profile+depth+direction);  instance_params = position
  revolution: key = hash(profile+axis+angle);  instance_params = position
  boolean/csg/advanced_brep:  key = hash(full tree);  instance_params = null
  faceted_brep:  no library entry (geometry in OBJ);  definition_id = null
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

MAX_RECURSION_DEPTH = 50
LOG_PROGRESS_INTERVAL = 500
ROUND_DIGITS = 4

# Method classification for non-parametric types (geometry_tree = null)
NON_PARAMETRIC_METHODS = frozenset({"faceted_brep"})

# ── Helpers ──────────────────────────────────────────────────────────

def _round(v: float) -> float:
    return round(float(v), ROUND_DIGITS)


def _serialize_cartesian_point(pt: Any) -> Optional[List[float]]:
    if pt is None:
        return None
    try:
        coords = pt.Coordinates
        return [_round(c) for c in coords]
    except Exception:
        return None


def _serialize_direction(d: Any) -> Optional[List[float]]:
    if d is None:
        return None
    try:
        ratios = d.DirectionRatios
        return [_round(r) for r in ratios]
    except Exception:
        return None


def _serialize_axis2_placement_3d(p: Any) -> Optional[Dict]:
    if p is None:
        return None
    try:
        result: Dict[str, Any] = {"type": p.is_a()}
        result["location"] = _serialize_cartesian_point(p.Location)
        if hasattr(p, "Axis"):
            result["axis"] = _serialize_direction(p.Axis)
        if hasattr(p, "RefDirection"):
            result["ref_direction"] = _serialize_direction(p.RefDirection)
        return result
    except Exception:
        return None


def _serialize_axis2_placement_2d(p: Any) -> Optional[Dict]:
    if p is None:
        return None
    try:
        result: Dict[str, Any] = {"type": p.is_a()}
        result["location"] = _serialize_cartesian_point(p.Location)
        if hasattr(p, "RefDirection"):
            result["ref_direction"] = _serialize_direction(p.RefDirection)
        return result
    except Exception:
        return None


def _serialize_placement(p: Any) -> Optional[Dict]:
    if p is None:
        return None
    try:
        type_name = p.is_a()
        if type_name == "IfcAxis2Placement3D":
            return _serialize_axis2_placement_3d(p)
        elif type_name == "IfcAxis2Placement2D":
            return _serialize_axis2_placement_2d(p)
        return {"type": type_name}
    except Exception:
        return None


# ── Curves ───────────────────────────────────────────────────────────

def _serialize_curve(curve: Any, depth: int = 0) -> Optional[Dict]:
    if curve is None or depth > MAX_RECURSION_DEPTH:
        return None
    try:
        t = curve.is_a()
        result: Dict[str, Any] = {"type": t}

        if t == "IfcPolyline":
            result["points"] = [
                _serialize_cartesian_point(p) for p in curve.Points
            ]
        elif t == "IfcCircle":
            result["radius"] = _round(curve.Radius)
            result["position"] = _serialize_placement(curve.Position)
        elif t == "IfcEllipse":
            result["semi_axis1"] = _round(curve.SemiAxis1)
            result["semi_axis2"] = _round(curve.SemiAxis2)
            result["position"] = _serialize_placement(curve.Position)
        elif t == "IfcTrimmedCurve":
            result["basis_curve"] = _serialize_curve(curve.BasisCurve, depth + 1)
            result["sense_agreement"] = curve.SenseAgreement
            result["master_representation"] = str(curve.MasterRepresentation)
            # Trim parameters
            trim1 = []
            for tv in curve.Trim1:
                if hasattr(tv, "is_a") and tv.is_a("IfcCartesianPoint"):
                    trim1.append({"point": _serialize_cartesian_point(tv)})
                else:
                    trim1.append({"param": float(tv.wrappedValue) if hasattr(tv, "wrappedValue") else float(tv)})
            result["trim1"] = trim1
            trim2 = []
            for tv in curve.Trim2:
                if hasattr(tv, "is_a") and tv.is_a("IfcCartesianPoint"):
                    trim2.append({"point": _serialize_cartesian_point(tv)})
                else:
                    trim2.append({"param": float(tv.wrappedValue) if hasattr(tv, "wrappedValue") else float(tv)})
            result["trim2"] = trim2
        elif t == "IfcCompositeCurve":
            segments = []
            for seg in curve.Segments:
                seg_data: Dict[str, Any] = {"type": seg.is_a()}
                seg_data["same_sense"] = seg.SameSense
                seg_data["parent_curve"] = _serialize_curve(seg.ParentCurve, depth + 1)
                segments.append(seg_data)
            result["segments"] = segments
        elif t == "IfcLine":
            result["point"] = _serialize_cartesian_point(curve.Pnt)
            result["direction"] = _serialize_direction(curve.Dir.Orientation if hasattr(curve.Dir, "Orientation") else curve.Dir)
            if hasattr(curve.Dir, "Magnitude"):
                result["magnitude"] = _round(curve.Dir.Magnitude)
        elif t == "IfcIndexedPolyCurve":
            if hasattr(curve, "Points") and curve.Points:
                pts_obj = curve.Points
                if hasattr(pts_obj, "CoordList"):
                    result["points"] = [[_round(c) for c in coord] for coord in pts_obj.CoordList]
            if hasattr(curve, "Segments") and curve.Segments:
                segs = []
                for seg in curve.Segments:
                    if hasattr(seg, "is_a"):
                        segs.append({"type": seg.is_a(), "indices": list(seg.wrappedValue) if hasattr(seg, "wrappedValue") else list(seg)})
                    else:
                        segs.append(list(seg))
                result["segments"] = segs
        elif t.startswith("IfcBSplineCurve"):
            result["degree"] = curve.Degree
            result["control_points"] = [_serialize_cartesian_point(p) for p in curve.ControlPointsList]
            if hasattr(curve, "KnotMultiplicities") and curve.KnotMultiplicities:
                result["knot_multiplicities"] = list(curve.KnotMultiplicities)
            if hasattr(curve, "Knots") and curve.Knots:
                result["knots"] = [_round(k) for k in curve.Knots]
            if hasattr(curve, "WeightsData") and curve.WeightsData:
                result["weights"] = [_round(w) for w in curve.WeightsData]
        else:
            result["unsupported_curve"] = True

        return result
    except Exception:
        return {"type": curve.is_a() if hasattr(curve, "is_a") else "Unknown", "error": True}


# ── Surfaces ─────────────────────────────────────────────────────────

def _serialize_surface(surface: Any, depth: int = 0) -> Optional[Dict]:
    if surface is None or depth > MAX_RECURSION_DEPTH:
        return None
    try:
        t = surface.is_a()
        result: Dict[str, Any] = {"type": t}

        if t == "IfcPlane":
            result["position"] = _serialize_axis2_placement_3d(surface.Position)
        elif t == "IfcCylindricalSurface":
            result["position"] = _serialize_axis2_placement_3d(surface.Position)
            result["radius"] = _round(surface.Radius)
        elif t == "IfcConicalSurface":
            result["position"] = _serialize_axis2_placement_3d(surface.Position)
            result["radius"] = _round(surface.Radius)
            result["semi_angle"] = _round(surface.SemiAngle)
        elif t == "IfcSphericalSurface":
            result["position"] = _serialize_axis2_placement_3d(surface.Position)
            result["radius"] = _round(surface.Radius)
        elif t == "IfcToroidalSurface":
            result["position"] = _serialize_axis2_placement_3d(surface.Position)
            result["major_radius"] = _round(surface.MajorRadius)
            result["minor_radius"] = _round(surface.MinorRadius)
        elif t == "IfcSurfaceOfLinearExtrusion":
            result["swept_curve"] = _serialize_curve(surface.SweptCurve, depth + 1)
            result["extrusion_axis"] = _serialize_direction(surface.ExtrudedDirection)
            result["depth"] = _round(surface.Depth) if hasattr(surface, "Depth") else None
        elif t == "IfcSurfaceOfRevolution":
            result["swept_curve"] = _serialize_curve(surface.SweptCurve, depth + 1)
            result["axis_position"] = _serialize_axis2_placement_3d(surface.AxisPosition) if hasattr(surface, "AxisPosition") else None
        elif t.startswith("IfcBSplineSurface"):
            result["u_degree"] = surface.UDegree
            result["v_degree"] = surface.VDegree
            # Control points grid
            ctrl_pts = []
            for row in surface.ControlPointsList:
                ctrl_pts.append([_serialize_cartesian_point(p) for p in row])
            result["control_points"] = ctrl_pts
            if hasattr(surface, "UKnots") and surface.UKnots:
                result["u_knots"] = [_round(k) for k in surface.UKnots]
            if hasattr(surface, "VKnots") and surface.VKnots:
                result["v_knots"] = [_round(k) for k in surface.VKnots]
            if hasattr(surface, "UMultiplicities") and surface.UMultiplicities:
                result["u_multiplicities"] = list(surface.UMultiplicities)
            if hasattr(surface, "VMultiplicities") and surface.VMultiplicities:
                result["v_multiplicities"] = list(surface.VMultiplicities)
            if hasattr(surface, "WeightsData") and surface.WeightsData:
                weights = []
                for row in surface.WeightsData:
                    weights.append([_round(w) for w in row])
                result["weights"] = weights
        else:
            result["unsupported_surface"] = True

        return result
    except Exception:
        return {"type": surface.is_a() if hasattr(surface, "is_a") else "Unknown", "error": True}


# ── Profiles ─────────────────────────────────────────────────────────

def _serialize_profile(profile: Any, depth: int = 0) -> Optional[Dict]:
    if profile is None or depth > MAX_RECURSION_DEPTH:
        return None
    try:
        t = profile.is_a()
        result: Dict[str, Any] = {"type": t}

        if hasattr(profile, "ProfileName") and profile.ProfileName:
            result["profile_name"] = profile.ProfileName
        if hasattr(profile, "ProfileType") and profile.ProfileType:
            result["profile_type"] = str(profile.ProfileType)

        if t == "IfcRectangleProfileDef" or t == "IfcRectangleHollowProfileDef":
            result["x_dim"] = _round(profile.XDim)
            result["y_dim"] = _round(profile.YDim)
            if hasattr(profile, "Position") and profile.Position:
                result["position"] = _serialize_placement(profile.Position)
            if t == "IfcRectangleHollowProfileDef":
                result["wall_thickness"] = _round(profile.WallThickness)
                if hasattr(profile, "InnerFilletRadius") and profile.InnerFilletRadius:
                    result["inner_fillet_radius"] = _round(profile.InnerFilletRadius)
                if hasattr(profile, "OuterFilletRadius") and profile.OuterFilletRadius:
                    result["outer_fillet_radius"] = _round(profile.OuterFilletRadius)
        elif t == "IfcCircleProfileDef" or t == "IfcCircleHollowProfileDef":
            result["radius"] = _round(profile.Radius)
            if hasattr(profile, "Position") and profile.Position:
                result["position"] = _serialize_placement(profile.Position)
            if t == "IfcCircleHollowProfileDef":
                result["wall_thickness"] = _round(profile.WallThickness)
        elif t == "IfcIShapeProfileDef" or t == "IfcAsymmetricIShapeProfileDef":
            result["overall_width"] = _round(profile.OverallWidth)
            result["overall_depth"] = _round(profile.OverallDepth)
            result["web_thickness"] = _round(profile.WebThickness)
            result["flange_thickness"] = _round(profile.FlangeThickness)
            if hasattr(profile, "FilletRadius") and profile.FilletRadius:
                result["fillet_radius"] = _round(profile.FilletRadius)
            if hasattr(profile, "Position") and profile.Position:
                result["position"] = _serialize_placement(profile.Position)
        elif t == "IfcLShapeProfileDef":
            result["depth"] = _round(profile.Depth)
            result["width"] = _round(profile.Width)
            result["thickness"] = _round(profile.Thickness)
            if hasattr(profile, "FilletRadius") and profile.FilletRadius:
                result["fillet_radius"] = _round(profile.FilletRadius)
            if hasattr(profile, "Position") and profile.Position:
                result["position"] = _serialize_placement(profile.Position)
        elif t == "IfcTShapeProfileDef":
            result["depth"] = _round(profile.Depth)
            result["flange_width"] = _round(profile.FlangeWidth)
            result["web_thickness"] = _round(profile.WebThickness)
            result["flange_thickness"] = _round(profile.FlangeThickness)
            if hasattr(profile, "FilletRadius") and profile.FilletRadius:
                result["fillet_radius"] = _round(profile.FilletRadius)
            if hasattr(profile, "Position") and profile.Position:
                result["position"] = _serialize_placement(profile.Position)
        elif t == "IfcUShapeProfileDef":
            result["depth"] = _round(profile.Depth)
            result["flange_width"] = _round(profile.FlangeWidth)
            result["web_thickness"] = _round(profile.WebThickness)
            result["flange_thickness"] = _round(profile.FlangeThickness)
            if hasattr(profile, "Position") and profile.Position:
                result["position"] = _serialize_placement(profile.Position)
        elif t == "IfcCShapeProfileDef":
            result["depth"] = _round(profile.Depth)
            result["width"] = _round(profile.Width)
            result["wall_thickness"] = _round(profile.WallThickness)
            result["girth"] = _round(profile.Girth)
            if hasattr(profile, "Position") and profile.Position:
                result["position"] = _serialize_placement(profile.Position)
        elif t == "IfcZShapeProfileDef":
            result["depth"] = _round(profile.Depth)
            result["flange_width"] = _round(profile.FlangeWidth)
            result["web_thickness"] = _round(profile.WebThickness)
            result["flange_thickness"] = _round(profile.FlangeThickness)
            if hasattr(profile, "Position") and profile.Position:
                result["position"] = _serialize_placement(profile.Position)
        elif t == "IfcEllipseProfileDef":
            result["semi_axis1"] = _round(profile.SemiAxis1)
            result["semi_axis2"] = _round(profile.SemiAxis2)
            if hasattr(profile, "Position") and profile.Position:
                result["position"] = _serialize_placement(profile.Position)
        elif t == "IfcTrapeziumProfileDef":
            result["bottom_x_dim"] = _round(profile.BottomXDim)
            result["top_x_dim"] = _round(profile.TopXDim)
            result["y_dim"] = _round(profile.YDim)
            result["top_x_offset"] = _round(profile.TopXOffset)
            if hasattr(profile, "Position") and profile.Position:
                result["position"] = _serialize_placement(profile.Position)
        elif t == "IfcArbitraryClosedProfileDef" or t == "IfcArbitraryProfileDefWithVoids":
            result["outer_curve"] = _serialize_curve(profile.OuterCurve, depth + 1)
            if t == "IfcArbitraryProfileDefWithVoids" and hasattr(profile, "InnerCurves") and profile.InnerCurves:
                result["inner_curves"] = [
                    _serialize_curve(c, depth + 1) for c in profile.InnerCurves
                ]
        elif t == "IfcArbitraryOpenProfileDef":
            result["curve"] = _serialize_curve(profile.Curve, depth + 1)
        elif t == "IfcCompositeProfileDef":
            result["profiles"] = [
                _serialize_profile(p, depth + 1) for p in profile.Profiles
            ]
        elif t == "IfcDerivedProfileDef":
            result["parent_profile"] = _serialize_profile(profile.ParentProfile, depth + 1)
            if hasattr(profile, "Operator") and profile.Operator:
                result["operator"] = _serialize_cartesian_transform_operator(profile.Operator)
        elif t == "IfcMirroredProfileDef":
            result["parent_profile"] = _serialize_profile(profile.ParentProfile, depth + 1)
        else:
            result["unsupported_profile"] = True

        return result
    except Exception:
        return {"type": profile.is_a() if hasattr(profile, "is_a") else "Unknown", "error": True}


def _serialize_cartesian_transform_operator(op: Any) -> Optional[Dict]:
    if op is None:
        return None
    try:
        result: Dict[str, Any] = {"type": op.is_a()}
        if hasattr(op, "LocalOrigin") and op.LocalOrigin:
            result["local_origin"] = _serialize_cartesian_point(op.LocalOrigin)
        if hasattr(op, "Axis1") and op.Axis1:
            result["axis1"] = _serialize_direction(op.Axis1)
        if hasattr(op, "Axis2") and op.Axis2:
            result["axis2"] = _serialize_direction(op.Axis2)
        if hasattr(op, "Axis3") and op.Axis3:
            result["axis3"] = _serialize_direction(op.Axis3)
        if hasattr(op, "Scale") and op.Scale is not None:
            result["scale"] = _round(op.Scale)
        if hasattr(op, "Scale2") and op.Scale2 is not None:
            result["scale2"] = _round(op.Scale2)
        if hasattr(op, "Scale3") and op.Scale3 is not None:
            result["scale3"] = _round(op.Scale3)
        return result
    except Exception:
        return None


# ── Geometry Item Serializers ────────────────────────────────────────

def _serialize_extruded_area_solid(item: Any, depth: int) -> Dict:
    result: Dict[str, Any] = {"type": "IfcExtrudedAreaSolid"}
    result["profile"] = _serialize_profile(item.SweptArea, depth + 1)
    result["depth"] = _round(item.Depth)
    result["direction"] = _serialize_direction(item.ExtrudedDirection)
    if hasattr(item, "Position") and item.Position:
        result["position"] = _serialize_placement(item.Position)
    return result


def _serialize_revolved_area_solid(item: Any, depth: int) -> Dict:
    result: Dict[str, Any] = {"type": "IfcRevolvedAreaSolid"}
    result["profile"] = _serialize_profile(item.SweptArea, depth + 1)
    result["angle"] = _round(item.Angle)
    if hasattr(item, "Axis") and item.Axis:
        result["axis"] = _serialize_axis2_placement_3d(item.Axis) if hasattr(item.Axis, "Location") else _serialize_direction(item.Axis)
    if hasattr(item, "Position") and item.Position:
        result["position"] = _serialize_placement(item.Position)
    return result


def _serialize_boolean_result(item: Any, depth: int) -> Dict:
    result: Dict[str, Any] = {"type": item.is_a()}
    result["operator"] = str(item.Operator)
    result["first_operand"] = _serialize_geometry_item(item.FirstOperand, depth + 1)
    result["second_operand"] = _serialize_geometry_item(item.SecondOperand, depth + 1)
    return result


def _serialize_half_space_solid(item: Any, depth: int) -> Dict:
    result: Dict[str, Any] = {"type": item.is_a()}
    result["agreement_flag"] = item.AgreementFlag
    if hasattr(item, "BaseSurface") and item.BaseSurface:
        result["base_surface"] = _serialize_surface(item.BaseSurface, depth + 1)
    return result


def _serialize_polygonal_bounded_half_space(item: Any, depth: int) -> Dict:
    result = _serialize_half_space_solid(item, depth)
    result["type"] = "IfcPolygonalBoundedHalfSpace"
    if hasattr(item, "Position") and item.Position:
        result["position"] = _serialize_axis2_placement_3d(item.Position)
    if hasattr(item, "PolygonalBoundary") and item.PolygonalBoundary:
        result["polygonal_boundary"] = _serialize_curve(item.PolygonalBoundary, depth + 1)
    return result


def _serialize_swept_disk_solid(item: Any, depth: int) -> Dict:
    result: Dict[str, Any] = {"type": "IfcSweptDiskSolid"}
    result["directrix"] = _serialize_curve(item.Directrix, depth + 1)
    result["radius"] = _round(item.Radius)
    if hasattr(item, "InnerRadius") and item.InnerRadius is not None:
        result["inner_radius"] = _round(item.InnerRadius)
    if hasattr(item, "StartParam") and item.StartParam is not None:
        result["start_param"] = _round(item.StartParam)
    if hasattr(item, "EndParam") and item.EndParam is not None:
        result["end_param"] = _round(item.EndParam)
    return result


def _serialize_surface_curve_swept(item: Any, depth: int) -> Dict:
    result: Dict[str, Any] = {"type": "IfcSurfaceCurveSweptAreaSolid"}
    result["profile"] = _serialize_profile(item.SweptArea, depth + 1)
    result["directrix"] = _serialize_curve(item.Directrix, depth + 1)
    if hasattr(item, "ReferenceSurface") and item.ReferenceSurface:
        result["reference_surface"] = _serialize_surface(item.ReferenceSurface, depth + 1)
    if hasattr(item, "Position") and item.Position:
        result["position"] = _serialize_placement(item.Position)
    if hasattr(item, "StartParam") and item.StartParam is not None:
        result["start_param"] = _round(item.StartParam)
    if hasattr(item, "EndParam") and item.EndParam is not None:
        result["end_param"] = _round(item.EndParam)
    return result


def _serialize_csg_solid(item: Any, depth: int) -> Dict:
    result: Dict[str, Any] = {"type": "IfcCsgSolid"}
    if hasattr(item, "TreeRootExpression") and item.TreeRootExpression:
        result["tree_root"] = _serialize_geometry_item(item.TreeRootExpression, depth + 1)
    return result


def _serialize_advanced_brep(item: Any, depth: int) -> Dict:
    result: Dict[str, Any] = {"type": item.is_a()}
    faces = []
    if hasattr(item, "Outer") and item.Outer:
        shell = item.Outer
        if hasattr(shell, "CfsFaces"):
            for face in shell.CfsFaces:
                face_data: Dict[str, Any] = {"type": face.is_a()}
                if hasattr(face, "FaceSurface") and face.FaceSurface:
                    face_data["surface"] = _serialize_surface(face.FaceSurface, depth + 1)
                if hasattr(face, "SameSense"):
                    face_data["same_sense"] = face.SameSense
                bounds = []
                if hasattr(face, "Bounds"):
                    for bound in face.Bounds:
                        bound_data: Dict[str, Any] = {"type": bound.is_a()}
                        bound_data["orientation"] = bound.Orientation
                        if hasattr(bound, "Bound") and bound.Bound:
                            loop = bound.Bound
                            loop_data: Dict[str, Any] = {"type": loop.is_a()}
                            if hasattr(loop, "EdgeList"):
                                edges = []
                                for edge in loop.EdgeList:
                                    edge_data: Dict[str, Any] = {"type": edge.is_a()}
                                    edge_data["orientation"] = edge.Orientation if hasattr(edge, "Orientation") else None
                                    if hasattr(edge, "EdgeElement"):
                                        ee = edge.EdgeElement
                                        ee_data: Dict[str, Any] = {"type": ee.is_a()}
                                        if hasattr(ee, "EdgeGeometry") and ee.EdgeGeometry:
                                            ee_data["curve"] = _serialize_curve(ee.EdgeGeometry, depth + 1)
                                        if hasattr(ee, "SameSense"):
                                            ee_data["same_sense"] = ee.SameSense
                                        if hasattr(ee, "EdgeStart") and ee.EdgeStart:
                                            vp = ee.EdgeStart
                                            if hasattr(vp, "VertexGeometry"):
                                                ee_data["start"] = _serialize_cartesian_point(vp.VertexGeometry)
                                        if hasattr(ee, "EdgeEnd") and ee.EdgeEnd:
                                            vp = ee.EdgeEnd
                                            if hasattr(vp, "VertexGeometry"):
                                                ee_data["end"] = _serialize_cartesian_point(vp.VertexGeometry)
                                        edge_data["edge_element"] = ee_data
                                    edges.append(edge_data)
                                loop_data["edges"] = edges
                            bound_data["loop"] = loop_data
                        bounds.append(bound_data)
                face_data["bounds"] = bounds
                faces.append(face_data)
    result["faces"] = faces

    # IfcAdvancedBrepWithVoids
    if hasattr(item, "Voids") and item.Voids:
        voids = []
        for void_shell in item.Voids:
            void_faces = []
            if hasattr(void_shell, "CfsFaces"):
                for face in void_shell.CfsFaces:
                    void_faces.append({"type": face.is_a()})
            voids.append({"face_count": len(void_faces)})
        result["voids"] = voids

    return result


def _serialize_mapped_item(item: Any, depth: int) -> Dict:
    result: Dict[str, Any] = {"type": "IfcMappedItem"}

    source = item.MappingSource
    if source:
        result["mapping_source_id"] = source.id()
        # Inline the source representation
        if hasattr(source, "MappedRepresentation") and source.MappedRepresentation:
            mapped_rep = source.MappedRepresentation
            source_data: Dict[str, Any] = {}
            if hasattr(mapped_rep, "RepresentationType"):
                source_data["representation_type"] = mapped_rep.RepresentationType
            if hasattr(mapped_rep, "Items") and mapped_rep.Items:
                source_data["items"] = [
                    _serialize_geometry_item(sub_item, depth + 1)
                    for sub_item in mapped_rep.Items
                ]
            result["mapping_source"] = source_data
        # MappingOrigin (source coordinate system)
        if hasattr(source, "MappingOrigin") and source.MappingOrigin:
            result["mapping_origin"] = _serialize_placement(source.MappingOrigin)

    target = item.MappingTarget
    if target:
        result["mapping_target"] = _serialize_cartesian_transform_operator(target)

    return result


def _serialize_geometry_item(item: Any, depth: int = 0) -> Optional[Dict]:
    """Dispatch to the appropriate serializer based on IFC type."""
    if item is None or depth > MAX_RECURSION_DEPTH:
        return None

    try:
        t = item.is_a()

        if t == "IfcExtrudedAreaSolid":
            return _serialize_extruded_area_solid(item, depth)
        elif t == "IfcExtrudedAreaSolidTapered":
            result = _serialize_extruded_area_solid(item, depth)
            result["type"] = "IfcExtrudedAreaSolidTapered"
            if hasattr(item, "EndSweptArea") and item.EndSweptArea:
                result["end_profile"] = _serialize_profile(item.EndSweptArea, depth + 1)
            return result
        elif t == "IfcRevolvedAreaSolid" or t == "IfcRevolvedAreaSolidTapered":
            return _serialize_revolved_area_solid(item, depth)
        elif t in ("IfcBooleanClippingResult", "IfcBooleanResult"):
            return _serialize_boolean_result(item, depth)
        elif t == "IfcHalfSpaceSolid":
            return _serialize_half_space_solid(item, depth)
        elif t == "IfcPolygonalBoundedHalfSpace":
            return _serialize_polygonal_bounded_half_space(item, depth)
        elif t == "IfcSweptDiskSolid" or t == "IfcSweptDiskSolidPolygonal":
            return _serialize_swept_disk_solid(item, depth)
        elif t == "IfcSurfaceCurveSweptAreaSolid":
            return _serialize_surface_curve_swept(item, depth)
        elif t == "IfcCsgSolid":
            return _serialize_csg_solid(item, depth)
        elif t in ("IfcAdvancedBrep", "IfcAdvancedBrepWithVoids"):
            return _serialize_advanced_brep(item, depth)
        elif t == "IfcMappedItem":
            return _serialize_mapped_item(item, depth)
        elif t == "IfcCsgPrimitive3D" or t.startswith("IfcBlock") or t.startswith("IfcRightCircularCylinder") or t.startswith("IfcRightCircularCone") or t.startswith("IfcSphere") or t.startswith("IfcRectangularPyramid"):
            result: Dict[str, Any] = {"type": t}
            if hasattr(item, "Position") and item.Position:
                result["position"] = _serialize_axis2_placement_3d(item.Position)
            # Collect numeric attributes
            for attr_name in ("XLength", "YLength", "ZLength", "Height", "Radius", "BottomRadius"):
                if hasattr(item, attr_name):
                    val = getattr(item, attr_name)
                    if val is not None:
                        result[attr_name.lower()] = _round(val)
            return result
        elif t in ("IfcFacetedBrep", "IfcFacetedBrepWithVoids",
                    "IfcFaceBasedSurfaceModel", "IfcShellBasedSurfaceModel",
                    "IfcTessellatedFaceSet", "IfcTriangulatedFaceSet",
                    "IfcPolygonalFaceSet", "IfcTessellatedItem"):
            # Non-parametric — geometry lives in OBJ mesh
            return None
        else:
            # Fallback for unknown types
            return {"type": t, "unsupported": True}

    except Exception as e:
        try:
            return {"type": item.is_a(), "error": str(e)}
        except Exception:
            return {"type": "Unknown", "error": str(e)}


# ── Representation helpers ───────────────────────────────────────────

def _get_body_representations(element: Any) -> List[Any]:
    """Get the Body IfcShapeRepresentation(s) from an element."""
    result = []
    try:
        rep = element.Representation
        if rep is None:
            return result
        for sub_rep in rep.Representations:
            rep_id = getattr(sub_rep, "RepresentationIdentifier", None)
            if rep_id in ("Body", "Body-FallBack", "Facetation"):
                result.append(sub_rep)
    except Exception:
        pass
    return result


_METHOD_MAP = {
    "SweptSolid": "extrusion",
    "Clipping": "boolean",
    "Brep": "faceted_brep",
    "AdvancedBrep": "advanced_brep",
    "AdvancedSweptSolid": "swept_curve",
    "CSG": "csg",
    "SurfaceModel": "faceted_brep",
    "Tessellation": "faceted_brep",
    "MappedRepresentation": "mapped",
    "BooleanClipping": "boolean",
}


def _classify_method(rep_type: Optional[str], items: Any) -> str:
    """Classify the geometry method from RepresentationType and items."""
    if rep_type and rep_type in _METHOD_MAP:
        return _METHOD_MAP[rep_type]

    # Fallback: inspect items directly
    if items:
        for item in items:
            try:
                t = item.is_a()
                if t == "IfcExtrudedAreaSolid":
                    return "extrusion"
                elif t in ("IfcBooleanClippingResult", "IfcBooleanResult"):
                    return "boolean"
                elif t in ("IfcAdvancedBrep", "IfcAdvancedBrepWithVoids"):
                    return "advanced_brep"
                elif t == "IfcMappedItem":
                    return "mapped"
                elif t == "IfcRevolvedAreaSolid":
                    return "revolution"
                elif t in ("IfcSweptDiskSolid", "IfcSweptDiskSolidPolygonal"):
                    return "swept_disk"
                elif t == "IfcSurfaceCurveSweptAreaSolid":
                    return "swept_curve"
                elif t == "IfcCsgSolid":
                    return "csg"
                elif t in ("IfcFacetedBrep", "IfcFacetedBrepWithVoids",
                           "IfcFaceBasedSurfaceModel", "IfcShellBasedSurfaceModel",
                           "IfcTessellatedFaceSet", "IfcTriangulatedFaceSet",
                           "IfcPolygonalFaceSet"):
                    return "faceted_brep"
            except Exception:
                continue
    return "unknown"


def _is_parametric(method: str) -> bool:
    return method not in NON_PARAMETRIC_METHODS and method != "unknown"


# ── Instancing / dedup ───────────────────────────────────────────────

def _split_for_instancing(method: str, tree: Any) -> Tuple[Any, Optional[Dict], str]:
    """
    Split a geometry tree into definition and instance-specific parts.

    Returns:
        definition: geometry data shared across instances (stored in library)
        instance_params: per-instance data (position/transform), or None
        dedup_key: string for deduplication lookup
    """
    if tree is None:
        return None, None, "null"

    if isinstance(tree, list):
        # Multiple items — hash full content, no split
        h = hashlib.md5(json.dumps(tree, sort_keys=True).encode()).hexdigest()
        return tree, None, f"{method}_{h}"

    if method == "mapped":
        # Definition = source geometry; Instance = mapping transform
        definition = {}
        instance_params = {}
        for k in ("type", "mapping_source_id", "mapping_source", "mapping_origin"):
            if k in tree:
                definition[k] = tree[k]
        if "mapping_target" in tree:
            instance_params["mapping_target"] = tree["mapping_target"]
        dedup_key = f"mapped_{tree.get('mapping_source_id', 'unknown')}"
        return definition, instance_params or None, dedup_key

    elif method in ("extrusion", "revolution", "swept_curve"):
        # Definition = shape (profile + params); Instance = position
        definition = {k: v for k, v in tree.items() if k != "position"}
        instance_params = {"position": tree["position"]} if tree.get("position") else None
        h = hashlib.md5(json.dumps(definition, sort_keys=True).encode()).hexdigest()
        return definition, instance_params, f"{method}_{h}"

    else:
        # boolean, csg, advanced_brep, swept_disk, unknown — hash full tree
        h = hashlib.md5(json.dumps(tree, sort_keys=True).encode()).hexdigest()
        return tree, None, f"{method}_{h}"


# ── Pre-classification ───────────────────────────────────────────────

def pre_classify_geometry(elements: List[Any]) -> Tuple[Set[str], List[Any]]:
    """
    Quick pass to classify elements as parametric or non-parametric.
    Only inspects IFC schema (RepresentationType), no tessellation.

    Returns:
        parametric_guids: GlobalIds with parametric body representations
        non_parametric_elements: Elements needing tessellation for OBJ
    """
    parametric_guids: Set[str] = set()
    non_parametric_elements: List[Any] = []

    for elem in elements:
        gid = getattr(elem, "GlobalId", None)
        if not gid:
            continue

        body_reps = _get_body_representations(elem)
        if not body_reps:
            continue

        body_rep = body_reps[0]
        rep_type = getattr(body_rep, "RepresentationType", None)
        items = list(body_rep.Items) if hasattr(body_rep, "Items") else []

        if not items:
            continue

        method = _classify_method(rep_type, items)

        if _is_parametric(method):
            parametric_guids.add(gid)
        else:
            non_parametric_elements.append(elem)

    logger.info(
        f"[PRE-CLASSIFY] {len(parametric_guids)} parametric, "
        f"{len(non_parametric_elements)} non-parametric"
    )
    return parametric_guids, non_parametric_elements


# ── Main entry point ────────────────────────────────────────────────

def extract_parametric_geometry(
    elements: List[Any],
    guids_with_geometry: Set[str],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Extract parametric geometry with instancing/deduplication.

    Returns:
        library_df:  Unique geometry definitions (geometry_library.csv)
            Columns: definition_id, method, representation_type, geometry_tree, instance_count
        instance_df: Per-element instances (geometry_instance.csv)
            Columns: GlobalId, ifc_type, method, definition_id, instance_params
    """
    library: Dict[str, Dict] = {}  # dedup_key -> library entry
    instances: List[Dict[str, Any]] = []
    next_def_id = 1
    stats = {"total": 0, "parametric": 0, "non_parametric": 0, "definitions": 0, "errors": 0}

    for i, elem in enumerate(elements):
        if (i + 1) % LOG_PROGRESS_INTERVAL == 0:
            logger.info(f"[PARAMETRIC] Processing element {i + 1}/{len(elements)}...")

        try:
            gid = getattr(elem, "GlobalId", None)
            if not gid or gid not in guids_with_geometry:
                continue

            ifc_type = elem.is_a()
            body_reps = _get_body_representations(elem)
            if not body_reps:
                continue

            stats["total"] += 1

            body_rep = body_reps[0]
            rep_type = getattr(body_rep, "RepresentationType", None)
            items = list(body_rep.Items) if hasattr(body_rep, "Items") else []
            method = _classify_method(rep_type, items)

            # Non-parametric (faceted_brep): no library entry
            if not _is_parametric(method):
                stats["non_parametric"] += 1
                instances.append({
                    "GlobalId": gid,
                    "ifc_type": ifc_type,
                    "method": method,
                    "definition_id": None,
                    "instance_params": None,
                })
                continue

            # Serialize geometry tree
            tree_items = []
            for item in items:
                serialized = _serialize_geometry_item(item, depth=0)
                if serialized is not None:
                    tree_items.append(serialized)

            if not tree_items:
                stats["non_parametric"] += 1
                instances.append({
                    "GlobalId": gid,
                    "ifc_type": ifc_type,
                    "method": method,
                    "definition_id": None,
                    "instance_params": None,
                })
                continue

            tree = tree_items[0] if len(tree_items) == 1 else tree_items

            # Split into definition + instance, get dedup key
            definition, inst_params, dedup_key = _split_for_instancing(method, tree)

            if dedup_key not in library:
                def_id = next_def_id
                next_def_id += 1
                library[dedup_key] = {
                    "definition_id": def_id,
                    "method": method,
                    "representation_type": rep_type or "",
                    "geometry_tree": json.dumps(definition, ensure_ascii=False),
                    "instance_count": 0,
                }
            library[dedup_key]["instance_count"] += 1
            stats["parametric"] += 1

            instances.append({
                "GlobalId": gid,
                "ifc_type": ifc_type,
                "method": method,
                "definition_id": library[dedup_key]["definition_id"],
                "instance_params": json.dumps(inst_params, ensure_ascii=False) if inst_params else None,
            })

        except Exception as e:
            stats["errors"] += 1
            gid = getattr(elem, "GlobalId", "??")
            logger.debug(f"[PARAMETRIC] Error on {gid}: {e}")

    stats["definitions"] = len(library)
    logger.info(
        f"[PARAMETRIC] Complete: {stats['total']} elements, "
        f"{stats['parametric']} parametric ({stats['definitions']} unique definitions), "
        f"{stats['non_parametric']} non-parametric, {stats['errors']} errors"
    )

    library_df = pd.DataFrame(
        list(library.values()),
        columns=["definition_id", "method", "representation_type", "geometry_tree", "instance_count"],
    )
    instance_df = pd.DataFrame(
        instances,
        columns=["GlobalId", "ifc_type", "method", "definition_id", "instance_params"],
    )
    return library_df, instance_df
