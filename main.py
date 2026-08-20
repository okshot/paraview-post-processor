#!/usr/bin/env python3
"""
Interactive ASPECT Post-Processor — main entry point.

Run with::

    python3 post-process/main.py
"""

import sys
import os
import json
import subprocess
from pathlib import Path

# Ensure local modules (menu, config, plotter) are importable regardless of
# the working directory from which this script is invoked.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

import menu
import config as cfg
import plotter

EXTRACTOR = os.path.join(_SCRIPT_DIR, 'extractor.py')

# Variables that should never appear in the user-facing selection list.
_SKIP_VARS = frozenset({
    'Longitude', 'Latitude', 'Depth',
    'velocity_east', 'velocity_north', 'velocity_radial', 'velocity_magnitude',
    'depth', 'TIME',
})


# =====================================================================
# Entry point
# =====================================================================

def main():
    menu.banner()

    # Load (or create) configuration
    conf = cfg.load_config()

    # First-run setup: ask for pvpython path
    if not conf['general'].get('pvpython_path'):
        conf = cfg.first_run_setup(conf)

    # Ask for input file
    input_path = _get_input_path(conf)
    if not input_path:
        return

    # Fetch metadata via pvpython
    metadata = _load_metadata(input_path, conf)
    if not metadata:
        return

    menu.info(f"Loaded: {input_path}")
    menu.display_metadata(metadata)

    # Session state
    current_timestep = max(0, len(metadata.get('timesteps', [])) - 1)

    # ── Main loop ──────────────────────────────────────────────────
    while True:
        ts_list = metadata.get('timesteps', [])
        if ts_list and current_timestep < len(ts_list):
            ts_info = ts_list[current_timestep]
            ts_label = f"t={current_timestep} ({ts_info['time_years']:,.0f} yrs)"
        else:
            ts_label = "N/A"

        idx, _ = menu.prompt_choice("Main Menu", [
            "Cross-section slice  (2D map / cross-section)",
            "Depth-averaged map   (average between two depths)",
            "Re-plot from saved CSV",
            f"Change timestep      [current: {ts_label}]",
            "Switch to different run",
            "Edit defaults",
        ], allow_back=False, allow_quit=True)

        if idx == -2:
            print("\n  Goodbye!\n")
            break
        elif idx == 0:
            _do_slice(input_path, metadata, current_timestep, conf)
        elif idx == 1:
            _do_depth_average(input_path, metadata, current_timestep, conf)
        elif idx == 2:
            _do_replot(input_path, conf)
        elif idx == 3:
            current_timestep = _change_timestep(metadata, current_timestep)
        elif idx == 4:
            new_path = _get_input_path(conf)
            if new_path:
                new_meta = _load_metadata(new_path, conf)
                if new_meta:
                    input_path = new_path
                    metadata = new_meta
                    menu.info(f"Loaded: {input_path}")
                    menu.display_metadata(metadata)
                    current_timestep = max(0, len(metadata.get('timesteps', [])) - 1)
        elif idx == 5:
            _edit_defaults(conf)


# =====================================================================
# File loading helpers
# =====================================================================

def _get_input_path(conf):
    """Prompt for and validate the path to a solution.pvd file."""
    last = conf['general'].get('last_input_path', '')

    menu.header("Input File")
    if last:
        print(f"  Last used: {last}")

    raw = menu.prompt("Path to solution.pvd or output directory",
                      last if last else None)
    if not raw:
        return None

    path = Path(raw).expanduser().resolve()

    # If the user pointed at a directory, look for solution.pvd inside
    if path.is_dir():
        pvd = path / 'solution.pvd'
        if pvd.exists():
            path = pvd
        else:
            menu.error(f"No solution.pvd found in {path}")
            return None

    if not path.exists():
        menu.error(f"File not found: {path}")
        return None

    # Persist for next session
    conf['general']['last_input_path'] = str(path)
    cfg.save_config(conf)

    return str(path)


def _load_metadata(input_path, conf):
    cache_path = str(input_path).replace('.pvd', '_metadata.json')
    if os.path.exists(cache_path):
        print("\n  Loading cached metadata...", end='', flush=True)
        try:
            with open(cache_path, 'r') as f:
                meta = json.load(f)
            print(" done")
            return meta
        except Exception:
            print(" failed (will re-extract)")

    pvpython = conf['general']['pvpython_path']
    print("\n  Loading metadata via pvpython...", end='', flush=True)

    try:
        result = subprocess.run(
            [pvpython, EXTRACTOR,
             '--mode', 'info',
             '--input', input_path,
             '--earth-radius', str(conf['general']['earth_radius_m'])],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        print()
        menu.error("pvpython timed out (120 s)")
        return None
    except FileNotFoundError:
        print()
        menu.error(f"pvpython not found at: {pvpython}")
        menu.warn("Run the tool again or edit defaults.toml to fix the path.")
        return None

    if result.returncode != 0:
        print()
        menu.error(f"pvpython error:\n{result.stderr[:500]}")
        return None

    print(" done")

    try:
        meta = json.loads(result.stdout)
        with open(cache_path, 'w') as f:
            json.dump(meta, f, indent=2)
        return meta
    except json.JSONDecodeError:
        menu.error(f"Failed to parse pvpython output:\n{result.stdout[:300]}")
        return None


# =====================================================================
# Variable list builder
# =====================================================================

def _build_variable_list(metadata):
    """Return a user-facing list of extractable variable names.

    Raw vector arrays (e.g. ``velocity``) are expanded into their scalar
    components (magnitude, east, north, radial).  Other vector arrays get
    a ``{name}_magnitude`` entry.
    """
    vector_vars = set(metadata.get('vector_variables', []))
    variables = []
    for v in metadata.get('variables', []):
        if v in _SKIP_VARS:
            continue
        if v in vector_vars:
            if v == 'velocity':
                variables.extend([
                    'velocity_magnitude',
                    'velocity_east',
                    'velocity_north',
                    'velocity_radial',
                ])
            else:
                # Offer magnitude for other vector arrays
                variables.append(f'{v}_magnitude')
            continue
        variables.append(v)
    return variables


# =====================================================================
# Plot-options prompt
# =====================================================================

def _get_plot_options(variable, direction, conf):
    """Interactively ask for colormap, value range, log-scale, etc."""
    menu.header("Plot Options")

    default_cmap = cfg.get_colormap(variable, conf)
    default_log = cfg.is_log_scale(variable, conf)
    default_sym = cfg.is_symmetric(variable, conf)
    default_coast = conf.get('plotting', {}).get('coastlines', True)

    cmap = menu.prompt("Colormap", default_cmap)
    vmin, vmax = menu.prompt_two_floats("Value range (min max)", "auto")
    log_scale = menu.prompt_bool("Log scale?", default_log)
    symmetric = menu.prompt_bool("Symmetric colorbar?", default_sym)

    overrides = {
        'cmap': cmap,
        'log_scale': log_scale,
        'symmetric': symmetric,
    }
    if vmin is not None:
        overrides['vmin'] = vmin
    if vmax is not None:
        overrides['vmax'] = vmax

    # Coastlines make sense only for map views
    if direction in ('Depth', None):
        overrides['coastlines'] = menu.prompt_bool("Coastlines?", default_coast)

    return overrides


# =====================================================================
# Menu action: cross-section slice
# =====================================================================

def _do_slice(input_path, metadata, timestep, conf):
    """Interactively extract and (optionally) plot a 2-D slice."""

    # 1. Direction
    idx, _ = menu.prompt_choice("Slice Direction", [
        "Depth slice       → map view  (lon × lat)",
        "Latitude slice    → cross-section (lon × depth)",
        "Longitude slice   → cross-section (lat × depth)",
    ])
    if idx == -1:
        return

    direction = ['Depth', 'Latitude', 'Longitude'][idx]

    # 2. Slice value
    bounds = metadata.get('bounds', {})
    if direction == 'Depth':
        dep = bounds.get('depth_km', [0, 660])
        val_km = menu.prompt_float(
            f"Depth (km) [{dep[0]:.0f} – {dep[1]:.0f}]", default=100)
        if val_km is None:
            return
        value = val_km * 1000.0
        value_display = f"{val_km:.0f}km"
    elif direction == 'Latitude':
        lat = bounds.get('lat', [0, 90])
        val = menu.prompt_float(
            f"Latitude (°) [{lat[0]:.1f} – {lat[1]:.1f}]",
            default=round((lat[0] + lat[1]) / 2, 1))
        if val is None:
            return
        value = val
        value_display = f"{val:.1f}deg"
    else:  # Longitude
        lon = bounds.get('lon', [0, 180])
        val = menu.prompt_float(
            f"Longitude (°) [{lon[0]:.1f} – {lon[1]:.1f}]",
            default=round((lon[0] + lon[1]) / 2, 1))
        if val is None:
            return
        value = val
        value_display = f"{val:.1f}deg"

    # 3. Variable
    variables = _build_variable_list(metadata)
    var_idx, var_name = menu.prompt_choice("Variable", variables)
    if var_idx == -1:
        return

    # 3b. Arrow overlay (available for all slice types now)
    want_arrows = False
    arrow_var = None
    vector_vars = metadata.get('vector_variables', [])
    if vector_vars:
        if menu.prompt_bool("Overlay vector arrows?", default=False):
            if len(vector_vars) == 1:
                arrow_var = vector_vars[0]
            else:
                idx, choice = menu.prompt_choice("Select vector for arrows", vector_vars)
                if idx != -1:
                    arrow_var = choice
            
            if arrow_var:
                want_arrows = True

    # 3c. Contour overlay
    want_contours = False
    contour_var = None
    # Let user pick from all variables (excluding the primary one if they want to be silly, but usually they pick something else)
    all_vars = [v for v in metadata.get('variables', []) if v != var_name and v not in vector_vars]
    if all_vars:
        if menu.prompt_bool("Overlay contour lines of a secondary variable?", default=False):
            idx, choice = menu.prompt_choice("Select variable for contours", all_vars)
            if idx != -1:
                contour_var = choice
                want_contours = True

    # 4. Plot options
    plot_opts = _get_plot_options(var_name, direction, conf)

    # 5. Build output paths
    input_dir = str(Path(input_path).parent)
    output_dir = os.path.join(input_dir, conf['general']['output_subdir'])
    os.makedirs(output_dir, exist_ok=True)

    filename = f"{var_name}_{direction.lower()}_{value_display}_t{timestep}"
    csv_path = os.path.join(output_dir, f"{filename}.csv")

    # 6. Build the variable list for extraction
    extract_vars = [var_name]
    if want_arrows:
        extract_vars.extend([f'{arrow_var}_east', f'{arrow_var}_north', f'{arrow_var}_radial'])
    if want_contours:
        extract_vars.append(contour_var)

    # 7. Extract via pvpython
    pvpython = conf['general']['pvpython_path']
    print(f"\n  Extracting variables at {direction} = {value_display}...",
          end='', flush=True)

    cmd = [
        pvpython, EXTRACTOR,
        '--mode', 'slice',
        '--input', input_path,
        '--direction', direction,
        '--value', str(value),
        '--variable', ','.join(extract_vars),
        '--timestep', str(timestep),
        '--output', csv_path,
        '--earth-radius', str(conf['general']['earth_radius_m']),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        print()
        menu.error("Extraction timed out (300 s)")
        return

    if result.returncode != 0:
        print()
        menu.error(f"Extraction failed:\n{result.stderr[:500]}")
        return

    print(" done")
    menu.info(f"CSV  → {csv_path}")

    # 7b. Write arrow and contour info into metadata sidecar if applicable
    meta_path = csv_path.replace('.csv', '.json')
    try:
        with open(meta_path) as fh:
            meta = json.load(fh)
        if want_arrows:
            meta['arrows'] = {
                'east_component': f'{arrow_var}_east',
                'north_component': f'{arrow_var}_north',
                'radial_component': f'{arrow_var}_radial',
            }
        if want_contours:
            meta['contour_var'] = contour_var
            
        with open(meta_path, 'w') as fh:
            json.dump(meta, fh, indent=2)
    except Exception:
        pass

    # 8. Plot
    if menu.prompt_bool("Plot now?"):
        _run_plotter(csv_path, var_name, conf, plot_opts)

    menu.wait_for_enter()


# =====================================================================
# Menu action: depth-averaged map
# =====================================================================

def _do_depth_average(input_path, metadata, timestep, conf):
    """Extract a depth range, average, and (optionally) plot."""

    bounds = metadata.get('bounds', {})
    dep = bounds.get('depth_km', [0, 660])

    menu.header("Depth-Averaged Map")
    print(f"  Depth range available: {dep[0]:.0f} – {dep[1]:.0f} km")

    d_min, d_max = menu.prompt_two_floats(
        "Depth range (km) — min max", f"{dep[0]:.0f} {dep[1]:.0f}")
    if d_min is None or d_max is None:
        return
    if d_min >= d_max:
        menu.error("Min depth must be less than max depth")
        return

    # Variable
    variables = _build_variable_list(metadata)
    var_idx, var_name = menu.prompt_choice("Variable", variables)
    if var_idx == -1:
        return

    log_avg = False
    if var_name in ('viscosity',):
        log_avg = menu.prompt_bool(
            "Use log-average (geometric mean)?", default=True)

    # Plot options
    plot_opts = _get_plot_options(var_name, 'Depth', conf)
    
    # Arrow overlay
    want_arrows = False
    arrow_var = None
    vector_vars = metadata.get('vector_variables', [])
    if vector_vars:
        if menu.prompt_bool("Overlay depth-averaged vector arrows?", default=False):
            if len(vector_vars) == 1:
                arrow_var = vector_vars[0]
            else:
                idx, choice = menu.prompt_choice("Select vector for arrows", vector_vars)
                if idx != -1:
                    arrow_var = choice
            if arrow_var:
                want_arrows = True

    # Contour overlay
    want_contours = False
    contour_var = None
    all_vars = [v for v in metadata.get('variables', []) if v != var_name and v not in vector_vars]
    if all_vars:
        if menu.prompt_bool("Overlay depth-averaged contour lines?", default=False):
            idx, choice = menu.prompt_choice("Select variable for contours", all_vars)
            if idx != -1:
                contour_var = choice
                want_contours = True

    # Build extract vars
    extract_vars = [var_name]
    if want_arrows:
        extract_vars.extend([f'{arrow_var}_east', f'{arrow_var}_north', f'{arrow_var}_radial'])
    if want_contours:
        extract_vars.append(contour_var)

    # Output paths
    input_dir = str(Path(input_path).parent)
    output_dir = os.path.join(input_dir, conf['general']['output_subdir'])
    os.makedirs(output_dir, exist_ok=True)

    filename = f"{var_name}_avg_{d_min:.0f}-{d_max:.0f}km_t{timestep}"
    vol_csv = os.path.join(output_dir, f"{filename}_raw.csv")
    avg_csv = os.path.join(output_dir, f"{filename}.csv")

    # Extract volume
    pvpython = conf['general']['pvpython_path']
    print(f"\n  Extracting {var_name} in {d_min:.0f}–{d_max:.0f} km...",
          end='', flush=True)

    cmd = [
        pvpython, EXTRACTOR,
        '--mode', 'volume',
        '--input', input_path,
        '--depth-min', str(d_min * 1000.0),
        '--depth-max', str(d_max * 1000.0),
        '--variable', ','.join(extract_vars),
        '--timestep', str(timestep),
        '--output', vol_csv,
        '--earth-radius', str(conf['general']['earth_radius_m']),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        print()
        menu.error("Extraction timed out (600 s)")
        return

    if result.returncode != 0:
        print()
        menu.error(f"Extraction failed:\n{result.stderr[:500]}")
        return

    print(" done")

    # Average onto a regular grid
    print("  Averaging onto grid...", end='', flush=True)

    import numpy as np
    from scipy.stats import binned_statistic_2d

    # Read header to know column indices
    with open(vol_csv, 'r') as f:
        header = f.readline().strip().split(',')
        # Remove quotes
        header = [h.strip('"') for h in header]
        
    data = np.loadtxt(vol_csv, delimiter=',', skiprows=1)
    if data.size == 0:
        print()
        menu.error("No data points in the specified depth range")
        return

    # Find coordinate columns
    try:
        lon_idx = header.index("Points:0")
        lat_idx = header.index("Points:1")
    except ValueError:
        print()
        menu.error("Could not find coordinate columns in extraction.")
        return

    lon = data[:, lon_idx]
    lat = data[:, lat_idx]

    resolution = conf['general']['grid_resolution_deg']
    lon_edges = np.arange(np.floor(lon.min()),
                          np.ceil(lon.max()) + resolution, resolution)
    lat_edges = np.arange(np.floor(lat.min()),
                          np.ceil(lat.max()) + resolution, resolution)

    lon_centers = (lon_edges[:-1] + lon_edges[1:]) / 2.0
    lat_centers = (lat_edges[:-1] + lat_edges[1:]) / 2.0
    glon, glat = np.meshgrid(lon_centers, lat_centers)
    
    # We will compute the average for every data variable (everything not named "Points:*")
    var_indices = [i for i, h in enumerate(header) if not h.startswith("Points:")]
    
    averaged_data = {}
    valid_mask = None
    
    for v_idx in var_indices:
        v_name = header[v_idx]
        v_data = data[:, v_idx]
        
        # Apply log if requested for main variable
        is_log = log_avg and v_name == var_name
        work = np.log10(np.maximum(v_data, 1e-30)) if is_log else v_data

        stat, _, _, _ = binned_statistic_2d(
            lon, lat, work, statistic='mean',
            bins=[lon_edges, lat_edges],
        )
        
        stat = stat.T
        if is_log:
            stat = 10.0 ** stat
            
        averaged_data[v_name] = stat
        if valid_mask is None:
            valid_mask = ~np.isnan(stat)

    with open(avg_csv, 'w') as fh:
        # Write headers
        out_vars = [header[i] for i in var_indices]
        headers_str = ",".join([f'"{v}"' for v in out_vars])
        fh.write(f'{headers_str},"Points:0","Points:1","Points:2"\n')
        
        # Write data
        for i in range(len(glon[valid_mask])):
            lo = glon[valid_mask][i]
            la = glat[valid_mask][i]
            
            row = []
            for v_name in out_vars:
                row.append(str(averaged_data[v_name][valid_mask][i]))
            
            row_str = ",".join(row)
            fh.write(f'{row_str},{lo},{la},0\n')

    print(" done")
    menu.info(f"CSV  → {avg_csv}")

    # Write metadata sidecar
    ts_list = metadata.get('timesteps', [])
    meta = {
        'variable': var_name,
        'slice_type': 'depth_averaged',
        'slice_direction': 'Depth',
        'depth_min': d_min * 1000.0,
        'depth_max': d_max * 1000.0,
        'timestep_index': timestep,
        'timestep_years': ts_list[timestep]['time_years'] if ts_list else 0.0,
    }
    
    if want_arrows:
        meta['arrows'] = {
            'east_component': f'{arrow_var}_east',
            'north_component': f'{arrow_var}_north',
            'radial_component': f'{arrow_var}_radial',
        }
    if want_contours:
        meta['contour_var'] = contour_var

    meta_path = avg_csv.replace('.csv', '.json')
    with open(meta_path, 'w') as fh:
        json.dump(meta, fh, indent=2)

    # Plot
    if menu.prompt_bool("Plot now?"):
        _run_plotter(avg_csv, var_name, conf, plot_opts)

    # Clean up
    if os.path.exists(vol_csv) and menu.prompt_bool(
            "Delete raw volume CSV? (can be large)", default=True):
        os.remove(vol_csv)
        raw_json = vol_csv.replace('.csv', '.json')
        if os.path.exists(raw_json):
            os.remove(raw_json)
        menu.info("Cleaned up raw files")

    menu.wait_for_enter()


# =====================================================================
# Menu action: re-plot from saved CSV
# =====================================================================

def _do_replot(input_path, conf):
    """Re-plot a previously extracted CSV with new options."""
    input_dir = str(Path(input_path).parent)
    output_dir = os.path.join(input_dir, conf['general']['output_subdir'])

    if not os.path.isdir(output_dir):
        menu.error(f"No slices directory found: {output_dir}")
        return

    # List CSVs (skip raw volume files)
    csv_files = sorted([
        f for f in os.listdir(output_dir)
        if f.endswith('.csv') and not f.endswith('_raw.csv')
    ])

    if not csv_files:
        menu.error("No saved CSVs found")
        return

    idx, csv_name = menu.prompt_choice("Select CSV to re-plot", csv_files)
    if idx == -1:
        return

    csv_path = os.path.join(output_dir, csv_name)
    meta_path = csv_path.replace('.csv', '.json')

    # Load metadata
    try:
        with open(meta_path) as fh:
            meta = json.load(fh)
    except FileNotFoundError:
        menu.warn("No metadata JSON found — using defaults")
        meta = {
            'variable': csv_name.split('_')[0],
            'slice_type': 'slice',
            'slice_direction': 'Depth',
        }

    variable = meta.get('variable', '')
    direction = meta.get('slice_direction', 'Depth')

    # Plot options
    plot_opts = _get_plot_options(variable, direction, conf)

    # Generate a new filename so we don't overwrite previous plots
    base = csv_name.replace('.csv', '')
    version = 2
    while True:
        png_name = f"{base}_v{version}.png"
        if not os.path.exists(os.path.join(output_dir, png_name)):
            break
        version += 1

    plot_opts['csv_path'] = csv_path
    plot_opts['output_png'] = os.path.join(output_dir, png_name)

    try:
        out = plotter.plot(csv_path, meta, conf, plot_opts)
        menu.info(f"Plot → {out}")
    except Exception as exc:
        menu.error(f"Plotting failed: {exc}")

    menu.wait_for_enter()


# =====================================================================
# Menu action: change timestep
# =====================================================================

def _change_timestep(metadata, current):
    """Let the user pick a timestep from the list."""
    ts_list = metadata.get('timesteps', [])
    if not ts_list:
        menu.error("No timesteps available")
        return current

    options = []
    for ts in ts_list:
        marker = "  ◄" if ts['index'] == current else ""
        options.append(f"t = {ts['index']:>3d}   ({ts['time_years']:>12,.0f} yrs){marker}")

    idx, _ = menu.prompt_choice("Select Timestep", options)
    if idx == -1:
        return current

    menu.info(f"Timestep set to {idx} ({ts_list[idx]['time_years']:,.0f} yrs)")
    return idx


# =====================================================================
# Menu action: edit defaults
# =====================================================================

def _edit_defaults(conf):
    """Interactively edit some key defaults."""
    menu.header("Edit Defaults")
    
    ans = menu.prompt("Default output subdirectory", conf['general']['output_subdir'])
    conf['general']['output_subdir'] = ans

    ans = menu.prompt("Grid resolution for interpolation (degrees)",
                      str(conf['general']['grid_resolution_deg']))
    if ans:
        try:
            conf['general']['grid_resolution_deg'] = float(ans)
        except ValueError:
            pass
            
    proj = conf.get('general', {}).get('map_projection', 'mercator')
    ans = menu.prompt("Map Projection (mercator or conic)", proj)
    if ans and ans.lower() in ('mercator', 'conic'):
        conf['general']['map_projection'] = ans.lower()

    cfg.save_config(conf)
    menu.info(f"Config saved to {cfg.CONFIG_PATH}")
    menu.wait_for_enter()


# =====================================================================
# Plotting helper
# =====================================================================

def _run_plotter(csv_path, variable, conf, plot_opts):
    """Load the JSON sidecar and call the plotter."""
    meta_path = csv_path.replace('.csv', '.json')
    try:
        with open(meta_path) as fh:
            meta = json.load(fh)
    except FileNotFoundError:
        meta = {'variable': variable, 'slice_type': 'slice',
                'slice_direction': 'Depth'}

    plot_opts['csv_path'] = csv_path
    if 'output_png' not in plot_opts:
        plot_opts['output_png'] = csv_path.replace('.csv', '.png')

    try:
        out = plotter.plot(csv_path, meta, conf, plot_opts)
        menu.info(f"Plot → {out}")
    except Exception as exc:
        menu.error(f"Plotting failed: {exc}")


# =====================================================================

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Interrupted. Goodbye!\n")
        sys.exit(0)
