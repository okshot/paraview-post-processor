"""PyGMT-based plotting for ASPECT post-processing outputs.

Public API
----------
plot(csv_path, meta, config, overrides)
    Read a CSV extracted by ``extractor.py`` and create a publication-quality
    figure using PyGMT (map view for depth slices, Cartesian cross-section
    for latitude / longitude slices).
"""

import numpy as np
import json
from pathlib import Path

try:
    import pygmt
    HAS_PYGMT = True
except ImportError:
    HAS_PYGMT = False

from scipy.interpolate import griddata as _griddata
import xarray as xr


# =====================================================================
# CSV reader
# =====================================================================

def _read_csv(csv_path):
    """Read a ParaView-style CSV and return ``{column_name: array}``."""
    with open(csv_path) as fh:
        raw_header = fh.readline().strip()

    col_names = [c.strip().strip('"') for c in raw_header.split(',')]
    data = np.loadtxt(csv_path, delimiter=',', skiprows=1)

    if data.size == 0:
        raise ValueError(f"No data in {csv_path}")
    if data.ndim == 1:
        data = data.reshape(1, -1)

    return {name: data[:, i] for i, name in enumerate(col_names)}


# =====================================================================
# Public entry point
# =====================================================================

def plot(csv_path, meta, config, overrides=None):
    """Create a plot from a previously-extracted CSV.

    Parameters
    ----------
    csv_path : str
        Path to the CSV file (ParaView format).
    meta : dict
        Metadata dictionary (loaded from the JSON sidecar).
    config : dict
        Application config (from ``config.load_config``).
    overrides : dict, optional
        Per-call overrides for cmap, vmin, vmax, log_scale, symmetric,
        coastlines, title, output_png, csv_path.

    Returns
    -------
    str
        Path to the saved PNG image.
    """
    if not HAS_PYGMT:
        raise RuntimeError("PyGMT is not installed — cannot plot.")

    overrides = overrides or {}

    # Load data ──────────────────────────────────────────────────────
    cols = _read_csv(csv_path)

    variable = meta.get('variable', '')
    values = cols[variable]
    lon = cols['Points:0']
    lat = cols['Points:1']
    depth = cols.get('Points:2', np.zeros_like(lon))

    # Arrow data (if present in metadata)
    arrows_meta = meta.get('arrows')
    arrow_data = None
    if arrows_meta:
        ae = cols.get(arrows_meta.get('east_component', ''))
        an = cols.get(arrows_meta.get('north_component', ''))
        ar = cols.get(arrows_meta.get('radial_component', ''))
        if ae is not None and an is not None:
            arrow_data = (ae, an, ar)
            
    # Contour data (if present in metadata)
    contour_var = meta.get('contour_var')
    contour_data = None
    if contour_var:
        contour_vals = cols.get(contour_var)
        if contour_vals is not None:
            contour_data = (contour_var, contour_vals)

    # Route to the appropriate plotting function ─────────────────────
    slice_type = meta.get('slice_type', 'slice')
    direction = meta.get('slice_direction', 'Depth')

    if slice_type == 'depth_averaged' or direction == 'Depth':
        # Fallback for old map arrow_data which didn't have ar
        map_arrow = (arrow_data[0], arrow_data[1]) if arrow_data else None
        return _plot_map(lon, lat, values, variable, meta, config, overrides,
                         arrow_data=map_arrow, contour_data=contour_data)
    elif direction == 'Latitude':
        return _plot_cross_section(
            lon, depth, values,
            'Longitude (°)', 'Depth (km)',
            variable, meta, config, overrides,
            arrow_data=arrow_data, direction_type='Latitude',
            contour_data=contour_data
        )
    elif direction == 'Longitude':
        return _plot_cross_section(
            lat, depth, values,
            'Latitude (°)', 'Depth (km)',
            variable, meta, config, overrides,
            arrow_data=arrow_data, direction_type='Longitude',
            contour_data=contour_data
        )
    else:
        raise ValueError(f"Unknown slice direction: {direction}")


# =====================================================================
# Map view  (depth slices & depth-averaged maps)
# =====================================================================

def _plot_map(lon, lat, values, variable, meta, config, overrides,
              arrow_data=None, contour_data=None):
    """Create a map-view plot (depth slices or depth-averaged)."""
    import config as cfg  # local import to avoid circular at module level

    cmap = overrides.get('cmap', cfg.get_colormap(variable, config))
    log_scale = overrides.get('log_scale', cfg.is_log_scale(variable, config))
    symmetric = overrides.get('symmetric', cfg.is_symmetric(variable, config))
    coastlines = overrides.get('coastlines',
                               config.get('plotting', {}).get('coastlines', True))
    dpi = config.get('plotting', {}).get('figure_dpi', 300)
    vmin = overrides.get('vmin')
    vmax = overrides.get('vmax')

    # Process values
    plot_values = values.copy()
    if log_scale:
        plot_values = np.log10(np.maximum(plot_values, 1e-30))

    if symmetric and vmin is None and vmax is None:
        absmax = float(np.nanmax(np.abs(plot_values)))
        vmin, vmax = -absmax, absmax

    if vmin is None:
        vmin = float(np.nanmin(plot_values))
    if vmax is None:
        vmax = float(np.nanmax(plot_values))

    # Region with small padding
    pad = 0.1
    region = [
        float(np.min(lon)) - pad,
        float(np.max(lon)) + pad,
        float(np.min(lat)) - pad,
        float(np.max(lat)) + pad,
    ]

    resolution = config.get('general', {}).get('grid_resolution_deg', 0.25)

    # Interpolate scattered data → regular grid
    grid_lon = np.arange(region[0], region[1] + resolution, resolution)
    grid_lat = np.arange(region[2], region[3] + resolution, resolution)
    glon_2d, glat_2d = np.meshgrid(grid_lon, grid_lat)

    try:
        grid_values = _griddata((lon, lat), plot_values, (glon_2d, glat_2d), method='cubic')
        if np.any(np.isnan(grid_values)):
            lin_vals = _griddata((lon, lat), plot_values, (glon_2d, glat_2d), method='linear')
            grid_values = np.where(np.isnan(grid_values), lin_vals, grid_values)
    except Exception:
        grid_values = _griddata((lon, lat), plot_values, (glon_2d, glat_2d), method='linear')

    grid = xr.DataArray(
        grid_values, dims=['lat', 'lon'],
        coords={'lat': grid_lat, 'lon': grid_lon},
    )

    # Projection ───────────────────────────────────────────────────────
    proj_type = config.get('general', {}).get('map_projection', 'mercator')
    if proj_type == 'conic':
        lon0 = float(lon.min() + lon.max()) / 2
        lat0 = float(lat.min() + lat.max()) / 2
        lat1 = float(lat.min() + (lat.max() - lat.min()) * 0.25)
        lat2 = float(lat.min() + (lat.max() - lat.min()) * 0.75)
        proj = f"B{lon0}/{lat0}/{lat1}/{lat2}/15c"
    else:
        proj = "M15c"

    # Plot ───────────────────────────────────────────────────────────
    fig = pygmt.Figure()
    
    # Elegant plot aesthetics
    pygmt.config(
        FONT_ANNOT_PRIMARY='10p,Helvetica,black',
        FONT_LABEL='12p,Helvetica-Bold,black',
        MAP_FRAME_TYPE='plain',
        MAP_FRAME_PEN='1p,black',
        MAP_TICK_LENGTH_PRIMARY='0.15c'
    )

    pygmt.makecpt(cmap=cmap, series=[vmin, vmax], continuous=True)

    fig.grdimage(grid, projection=proj, frame=True, interpolation='c')

    if coastlines:
        fig.coast(shorelines='0.5p,black', borders='1/0.3p,gray50')

    # ── Contours ─────────────────────────────────────────────────────
    if contour_data is not None:
        c_var, c_vals = contour_data
        c_grid_values = _griddata((lon, lat), c_vals, (glon_2d, glat_2d), method='linear')
        c_grid = xr.DataArray(c_grid_values, dims=['lat', 'lon'], coords={'lat': grid_lat, 'lon': grid_lon})
        
        c_min, c_max = np.nanmin(c_vals), np.nanmax(c_vals)
        c_int = max((c_max - c_min) / 6.0, 1e-6)
        magnitude = 10**np.floor(np.log10(c_int))
        c_int = round(c_int / magnitude) * magnitude
        
        fig.grdcontour(c_grid, levels=c_int, annotation=c_int*2, pen="0.6p,black,-")

    # Arrow overlay
    if arrow_data is not None:
        # Note: _overlay_arrows might need to be updated as well if it uses old linear arrow logic.
        _overlay_arrows(fig, lon, lat, arrow_data[0], arrow_data[1], config)

    # Colorbar — with units
    unit = cfg.get_unit(variable)
    if log_scale:
        label = f'log10({variable}) [{unit}]' if unit else f'log10({variable})'
    else:
        label = f'{variable} [{unit}]' if unit else variable

    fig.colorbar(
        position='JBC+w10c/0.3c+h+o0/1.2c',
        frame=[f'af+l{label}']
    )

    # Title
    title = overrides.get('title', '')
    if not title:
        title = _auto_title(variable, meta)

    if title:
        fig.basemap(frame=[f'WSen+t{title}'])

    # Save
    output_png = _resolve_output_png(overrides)
    fig.savefig(output_png, dpi=dpi)
    return output_png


# =====================================================================
# Arrow overlay
# =====================================================================

def _overlay_arrows(fig, lon, lat, v_east, v_north, config):
    """Overlay velocity arrows on an existing PyGMT map figure.

    Subsamples the vector field to a coarser regular grid so arrows
    are legible and don't overlap.
    """
    spacing = config.get('general', {}).get('arrow_spacing_deg', 2.0)

    # Build coarser grid for arrows
    grid_lon = np.arange(float(np.min(lon)) + spacing / 2,
                         float(np.max(lon)), spacing)
    grid_lat = np.arange(float(np.min(lat)) + spacing / 2,
                         float(np.max(lat)), spacing)

    if len(grid_lon) < 2 or len(grid_lat) < 2:
        return

    glon, glat = np.meshgrid(grid_lon, grid_lat)

    ge = _griddata((lon, lat), v_east, (glon, glat), method='linear')
    gn = _griddata((lon, lat), v_north, (glon, glat), method='linear')

    # Flatten and remove NaN
    mask = ~(np.isnan(ge) | np.isnan(gn))
    lons = glon[mask]
    lats = glat[mask]
    ve = ge[mask]
    vn = gn[mask]

    if len(lons) == 0:
        return

    # Compute azimuth (degrees from North, clockwise, GMT convention for -SV)
    azimuth = np.degrees(np.arctan2(ve, vn))
    magnitude = np.sqrt(ve ** 2 + vn ** 2)

    # Scale lengths
    max_mag = float(np.nanmax(magnitude))
    max_arrow_cm = 0.5
    if max_mag <= 0:
        return
    
    # Constant length so direction is visible everywhere regardless of magnitude
    length = np.full_like(magnitude, 0.3)

    # Keep all arrows
    keep = length > 0.0

    if not np.any(keep):
        return

    fig.plot(
        x=lons[keep],
        y=lats[keep],
        direction=[azimuth[keep], length[keep]],
        style='V0.12c+e+a40+n0.25c', # V is for azimuth geographic arrows
        pen='0.5p,white',
        fill='black',
    )


# =====================================================================
# Cross-section  (latitude or longitude slices)
# =====================================================================

def _plot_cross_section(x, depth_m, values, x_label, y_label,
                        variable, meta, config, overrides,
                        arrow_data=None, direction_type=None, contour_data=None):
    """Create a Cartesian cross-section (depth vs lon/lat)."""
    import config as cfg

    cmap = overrides.get('cmap', cfg.get_colormap(variable, config))
    log_scale = overrides.get('log_scale', cfg.is_log_scale(variable, config))
    symmetric = overrides.get('symmetric', cfg.is_symmetric(variable, config))
    dpi = config.get('plotting', {}).get('figure_dpi', 300)
    vmin = overrides.get('vmin')
    vmax = overrides.get('vmax')

    # Convert depth metres → km for display
    depth_km = depth_m / 1000.0

    # Process values
    plot_values = values.copy()
    if log_scale:
        plot_values = np.log10(np.maximum(plot_values, 1e-30))

    if symmetric and vmin is None and vmax is None:
        absmax = float(np.nanmax(np.abs(plot_values)))
        vmin, vmax = -absmax, absmax

    if vmin is None:
        vmin = float(np.nanmin(plot_values))
    if vmax is None:
        vmax = float(np.nanmax(plot_values))

    resolution = config.get('general', {}).get('grid_resolution_deg', 0.25)
    # Ensure reasonable resolutions
    x_range = float(np.max(x) - np.min(x))
    y_range = float(np.max(depth_km) - np.min(depth_km))
    
    # Adaptive grid resolution for smoother images
    n_x = max(150, int(x_range / resolution))
    n_y = max(100, int(y_range / (resolution * 50.0))) # depth is in km, x in deg (1 deg ~ 111km)
    
    grid_x = np.linspace(np.min(x), np.max(x), n_x)
    grid_y = np.linspace(np.min(depth_km), np.max(depth_km), n_y)
    gx_2d, gy_2d = np.meshgrid(grid_x, grid_y)

    # Use cubic interpolation for smoother continuous fields, fallback to linear
    try:
        grid_values = _griddata((x, depth_km), plot_values, (gx_2d, gy_2d), method='cubic')
        # cubic can produce NaNs at boundaries, fill with linear
        if np.any(np.isnan(grid_values)):
            lin_vals = _griddata((x, depth_km), plot_values, (gx_2d, gy_2d), method='linear')
            grid_values = np.where(np.isnan(grid_values), lin_vals, grid_values)
    except Exception:
        grid_values = _griddata((x, depth_km), plot_values, (gx_2d, gy_2d), method='linear')

    grid = xr.DataArray(
        grid_values, dims=['y', 'x'],
        coords={'y': grid_y, 'x': grid_x},
    )

    # Aspect ratio
    width_cm = 15.0
    height_cm = 7.5 # Lock to a highly aesthetic 2:1 landscape rectangle

    region = [
        float(np.min(x)), float(np.max(x)),
        float(np.min(depth_km)), float(np.max(depth_km)),
    ]

    # Plot ───────────────────────────────────────────────────────────
    fig = pygmt.Figure()
    
    # Elegant plot aesthetics
    pygmt.config(
        FONT_ANNOT_PRIMARY='10p,Helvetica,black',
        FONT_LABEL='12p,Helvetica-Bold,black',
        MAP_FRAME_TYPE='plain',
        MAP_FRAME_PEN='1p,black',
        MAP_TICK_LENGTH_PRIMARY='0.15c'
    )

    pygmt.makecpt(cmap=cmap, series=[vmin, vmax], continuous=True)

    # Use interpolation='c' (bicubic) for smooth rendering in PyGMT
    fig.grdimage(
        grid,
        projection=f'X{width_cm:.1f}c/-{height_cm:.1f}c',
        region=region,
        interpolation='c',
        frame=[
            f'xaf+l{x_label}',
            f'yaf+l{y_label}',
            'WSen',
        ],
    )
    
    # ── Contours ─────────────────────────────────────────────────────
    if contour_data is not None:
        c_var, c_vals = contour_data
        c_grid_values = _griddata((x, depth_km), c_vals, (gx_2d, gy_2d), method='linear')
        c_grid = xr.DataArray(c_grid_values, dims=['y', 'x'], coords={'y': grid_y, 'x': grid_x})
        
        # Calculate intelligent contour intervals to prevent dense lines
        c_min, c_max = np.nanmin(c_vals), np.nanmax(c_vals)
        c_int = max((c_max - c_min) / 6.0, 1e-6)
        magnitude = 10**np.floor(np.log10(c_int))
        c_int = round(c_int / magnitude) * magnitude
        
        fig.grdcontour(c_grid, levels=c_int, annotation=c_int*2, pen="0.6p,black,-")
    
    # ── Arrows ───────────────────────────────────────────────────────
    if arrow_data is not None and arrow_data[2] is not None:
        ae, an, ar = arrow_data
        
        if direction_type == 'Latitude':
            v_horiz = ae
        else:
            v_horiz = an
            
        v_vert = ar
        
        # Create a coarse grid specifically for beautiful, evenly-spaced arrows
        n_arrows_x = config.get('general', {}).get('cross_section_arrows_x', 40)
        n_arrows_y = config.get('general', {}).get('cross_section_arrows_y', 16)
        
        ax_1d = np.linspace(np.min(x), np.max(x), n_arrows_x)
        ay_1d = np.linspace(np.min(depth_km), np.max(depth_km), n_arrows_y)
        ax_2d, ay_2d = np.meshgrid(ax_1d, ay_1d)
        
        # Interpolate vector components onto coarse grid
        hs = _griddata((x, depth_km), v_horiz, (ax_2d, ay_2d), method='linear').flatten()
        vs = _griddata((x, depth_km), v_vert, (ax_2d, ay_2d), method='linear').flatten()
        xs = ax_2d.flatten()
        ys = ay_2d.flatten()
        
        # Filter out NaNs (outside data domain)
        valid = ~(np.isnan(hs) | np.isnan(vs))
        xs = xs[valid]
        ys = ys[valid]
        hs = hs[valid]
        vs = vs[valid]
        
        # Calculate magnitudes and angles in data space
        magnitude = np.sqrt(hs**2 + vs**2)
        
        dx_page = (hs / x_range) * width_cm
        dy_page = (vs / y_range) * height_cm
        angle = np.degrees(np.arctan2(dy_page, dx_page))
        
        max_mag = float(np.nanmax(magnitude))
        max_arrow_cm = 0.5 # Sleek small arrows
        
        if max_mag > 0:
            # Constant length so direction is visible everywhere regardless of magnitude
            length = np.full_like(magnitude, 0.3)
            keep = length > 0.0
            
            if np.any(keep):
                # Elegant arrows
                fig.plot(
                    x=xs[keep], y=ys[keep],
                    direction=[angle[keep], length[keep]],
                    style='v0.12c+ea+a40+n0.25c',
                    pen='0.5p,white', fill='black'
                )

    # Colorbar — with units
    unit = cfg.get_unit(variable)
    if log_scale:
        label = f'log10({variable}) [{unit}]' if unit else f'log10({variable})'
    else:
        label = f'{variable} [{unit}]' if unit else variable

    fig.colorbar(
        position='JBC+w10c/0.3c+h+o0/1.2c',
        frame=[f'af+l{label}']
    )

    title = overrides.get('title', '')
    if not title:
        title = _auto_title(variable, meta)

    output_png = _resolve_output_png(overrides)
    fig.savefig(output_png, dpi=dpi)
    return output_png


# =====================================================================
# Helpers
# =====================================================================

def _auto_title(variable, meta):
    """Generate a sensible default title from metadata."""
    slice_type = meta.get('slice_type', 'slice')
    direction = meta.get('slice_direction', '')
    slice_val = meta.get('slice_value', 0)
    ts_yr = meta.get('timestep_years', 0)

    if slice_type == 'depth_averaged':
        d_min = meta.get('depth_min', 0)
        d_max = meta.get('depth_max', 0)
        return (f'{variable}  avg {d_min / 1000:.0f}–{d_max / 1000:.0f} km'
                f'  (t = {ts_yr:,.0f} yr)')

    if direction == 'Depth':
        return f'{variable}  at {slice_val / 1000:.0f} km depth  (t = {ts_yr:,.0f} yr)'

    return f'{variable}  at {direction} = {slice_val:.1f}°  (t = {ts_yr:,.0f} yr)'


def _resolve_output_png(overrides):
    """Determine the output PNG path from overrides."""
    output_png = overrides.get('output_png', '')
    if not output_png:
        csv_path = overrides.get('csv_path', '')
        if csv_path:
            output_png = str(csv_path).replace('.csv', '.png')
        else:
            output_png = 'plot.png'
    return output_png
