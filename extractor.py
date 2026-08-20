#!/usr/bin/env pvpython
"""
ASPECT solution data extractor — runs under pvpython.

This script is called as a subprocess by ``main.py``.  It should never be
run interactively; all parameters come from command-line arguments.

Modes
-----
info    Print metadata (variables, timesteps, bounds) as JSON to stdout.
slice   Extract a 2-D cross-section at a constant value of Depth / Latitude /
        Longitude and write a CSV + metadata JSON.
volume  Extract all points within a depth range (for depth-averaging) and
        write a CSV + metadata JSON.
"""

import argparse
import json
import sys

# ── Coordinate-transform script executed inside ParaView's
#    ProgrammableFilter.  The ``{earth_radius}`` placeholder is filled in
#    at runtime via ``str.format()``.
TRANSFORM_SCRIPT = """\
import numpy as np, vtk
from vtk.util.numpy_support import numpy_to_vtk

output.ShallowCopy(self.GetInputDataObject(0, 0))

EARTH_RADIUS = {earth_radius}

def transform_block(b):
    if not b or b.GetNumberOfPoints() == 0:
        return

    p = np.array([b.GetPoint(i) for i in range(b.GetNumberOfPoints())])
    r = np.linalg.norm(p, axis=1)

    lon = np.degrees(np.arctan2(p[:, 1], p[:, 0]))
    lat = np.degrees(np.arcsin(np.clip(p[:, 2] / r, -1, 1)))
    dep = EARTH_RADIUS - r

    # Add geographic coordinate arrays
    for name, arr in zip(["Longitude", "Latitude", "Depth"], [lon, lat, dep]):
        va = numpy_to_vtk(arr.astype(np.float64), deep=True)
        va.SetName(name)
        b.GetPointData().AddArray(va)

    # ── Rotate ALL vector arrays from Cartesian to geographic ──
    lr, ar = np.radians(lon), np.radians(lat)
    sl, cl = np.sin(lr), np.cos(lr)
    sa, ca = np.sin(ar), np.cos(ar)

    vec_names = []
    for i in range(b.GetPointData().GetNumberOfArrays()):
        arr = b.GetPointData().GetArray(i)
        if arr is not None and arr.GetNumberOfComponents() == 3:
            vec_names.append(arr.GetName())

    for vname in vec_names:
        arr = b.GetPointData().GetArray(vname)
        n = arr.GetNumberOfTuples()
        v = np.array([arr.GetTuple3(j) for j in range(n)])

        v_east   = -sl * v[:, 0] + cl * v[:, 1]
        v_north  = -sa * cl * v[:, 0] - sa * sl * v[:, 1] + ca * v[:, 2]
        v_radial =  ca * cl * v[:, 0] + ca * sl * v[:, 1] + sa * v[:, 2]
        v_mag    = np.sqrt(v_east**2 + v_north**2 + v_radial**2)

        for name, arr_data in zip(
            [vname + "_east", vname + "_north", vname + "_radial", vname + "_magnitude"],
            [v_east, v_north, v_radial, v_mag],
        ):
            va = numpy_to_vtk(arr_data.astype(np.float64), deep=True)
            va.SetName(name)
            b.GetPointData().AddArray(va)

    # Replace point positions with geographic coordinates
    new_p = np.c_[lon, lat, dep]
    pts = vtk.vtkPoints()
    pts.SetData(numpy_to_vtk(new_p.astype(np.float64), deep=True))
    b.SetPoints(pts)


if output.IsA("vtkMultiBlockDataSet"):
    it = output.NewIterator()
    while not it.IsDoneWithTraversal():
        transform_block(it.GetCurrentDataObject())
        it.GoToNextItem()
else:
    transform_block(output)
"""


# =====================================================================
# Mode implementations
# =====================================================================

def run_info(args):
    """Print metadata about the solution as JSON to stdout."""
    from paraview.simple import (
        PVDReader, ProgrammableFilter, Delete,
    )
    import paraview.simple
    paraview.simple._DisableFirstRenderCameraReset()

    reader = PVDReader(FileName=args.input)
    timesteps = list(reader.TimestepValues)

    # Fetch variable info from the first timestep
    if timesteps:
        reader.UpdatePipeline(timesteps[0])
    else:
        reader.UpdatePipeline()

    point_info = reader.GetDataInformation().GetPointDataInformation()

    variables = []
    vector_variables = []
    for i in range(point_info.GetNumberOfArrays()):
        arr_info = point_info.GetArrayInformation(i)
        name = arr_info.GetName()
        n_comp = arr_info.GetNumberOfComponents()
        variables.append(name)
        if n_comp >= 3:
            vector_variables.append(name)

    # Apply coordinate transform to discover geographic bounds
    prog = ProgrammableFilter(Input=reader)
    prog.Script = TRANSFORM_SCRIPT.format(earth_radius=args.earth_radius)
    prog.UpdatePipeline()

    bounds = prog.GetDataInformation().GetBounds()
    # After transform: bounds = (lon_min, lon_max, lat_min, lat_max, dep_min, dep_max)

    result = {
        'timesteps': [
            {'index': i, 'time_years': float(t)}
            for i, t in enumerate(timesteps)
        ],
        'variables': variables,
        'vector_variables': vector_variables,
        'bounds': {
            'lon': [float(bounds[0]), float(bounds[1])],
            'lat': [float(bounds[2]), float(bounds[3])],
            'depth_km': [float(bounds[4]) / 1000.0, float(bounds[5]) / 1000.0],
        },
    }

    Delete(prog)
    Delete(reader)

    print(json.dumps(result))


def run_slice(args):
    """Extract a 2-D contour slice and save as CSV."""
    from paraview.simple import (
        PVDReader, ProgrammableFilter, Contour, SaveData, Delete,
    )
    import paraview.simple
    paraview.simple._DisableFirstRenderCameraReset()

    reader = PVDReader(FileName=args.input)
    timesteps = list(reader.TimestepValues)

    ts_idx = args.timestep if args.timestep is not None else max(0, len(timesteps) - 1)
    if timesteps:
        reader.UpdatePipeline(timesteps[ts_idx])

    prog = ProgrammableFilter(Input=reader)
    prog.Script = TRANSFORM_SCRIPT.format(earth_radius=args.earth_radius)
    prog.UpdatePipeline()

    contour = Contour(Input=prog)
    contour.ContourBy = ['POINTS', args.direction]
    contour.Isosurfaces = [args.value]
    contour.UpdatePipeline()

    var_list = [v.strip() for v in args.variable.split(',')]

    SaveData(
        args.output, proxy=contour,
        ChooseArraysToWrite=1,
        PointDataArrays=var_list,
    )

    # Write metadata sidecar
    meta = {
        'variable': var_list[0],
        'all_variables': var_list,
        'slice_type': 'slice',
        'slice_direction': args.direction,
        'slice_value': args.value,
        'timestep_index': ts_idx,
        'timestep_years': float(timesteps[ts_idx]) if timesteps else 0.0,
        'input_path': args.input,
    }
    meta_path = args.output.replace('.csv', '.json')
    with open(meta_path, 'w') as fh:
        json.dump(meta, fh, indent=2)

    Delete(contour)
    Delete(prog)
    Delete(reader)

    print(json.dumps({'status': 'ok', 'output': args.output, 'metadata': meta_path}))


def run_volume(args):
    """Extract all points within a depth range and save as CSV."""
    from paraview.simple import (
        PVDReader, ProgrammableFilter, Threshold, SaveData, Delete,
    )
    import paraview.simple
    paraview.simple._DisableFirstRenderCameraReset()

    reader = PVDReader(FileName=args.input)
    timesteps = list(reader.TimestepValues)

    ts_idx = args.timestep if args.timestep is not None else max(0, len(timesteps) - 1)
    if timesteps:
        reader.UpdatePipeline(timesteps[ts_idx])

    prog = ProgrammableFilter(Input=reader)
    prog.Script = TRANSFORM_SCRIPT.format(earth_radius=args.earth_radius)
    prog.UpdatePipeline()

    threshold = Threshold(Input=prog)
    threshold.Scalars = ['POINTS', 'Depth']
    threshold.LowerThreshold = args.depth_min
    threshold.UpperThreshold = args.depth_max
    threshold.UpdatePipeline()

    var_list = [v.strip() for v in args.variable.split(',')]

    SaveData(
        args.output, proxy=threshold,
        ChooseArraysToWrite=1,
        PointDataArrays=var_list,
    )

    # Write metadata sidecar
    meta = {
        'variable': var_list[0],
        'all_variables': var_list,
        'slice_type': 'depth_averaged',
        'depth_min': args.depth_min,
        'depth_max': args.depth_max,
        'timestep_index': ts_idx,
        'timestep_years': float(timesteps[ts_idx]) if timesteps else 0.0,
        'input_path': args.input,
    }
    meta_path = args.output.replace('.csv', '.json')
    with open(meta_path, 'w') as fh:
        json.dump(meta, fh, indent=2)

    Delete(threshold)
    Delete(prog)
    Delete(reader)

    print(json.dumps({'status': 'ok', 'output': args.output, 'metadata': meta_path}))


# =====================================================================
# CLI
# =====================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='ASPECT data extractor (pvpython)',
    )
    parser.add_argument('--mode', choices=['info', 'slice', 'volume'], required=True)
    parser.add_argument('--input', required=True, help='Path to solution.pvd')
    parser.add_argument('--direction', help='Slice direction: Depth, Latitude, or Longitude')
    parser.add_argument('--value', type=float, help='Contour value (m for depth, ° for lat/lon)')
    parser.add_argument('--variable', help='Variable name to extract')
    parser.add_argument('--timestep', type=int, default=None, help='Timestep index')
    parser.add_argument('--depth-min', type=float, help='Minimum depth in metres (volume mode)')
    parser.add_argument('--depth-max', type=float, help='Maximum depth in metres (volume mode)')
    parser.add_argument('--output', help='Output CSV file path')
    parser.add_argument('--earth-radius', type=float, default=6371000,
                        help='Earth radius in metres (default: 6371000)')

    args = parser.parse_args()

    try:
        if args.mode == 'info':
            run_info(args)
        elif args.mode == 'slice':
            run_slice(args)
        elif args.mode == 'volume':
            run_volume(args)
    except Exception as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}), file=sys.stderr)
        sys.exit(1)
