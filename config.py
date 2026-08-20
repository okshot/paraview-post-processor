"""Configuration management for the ASPECT post-processing tool.

Handles loading/saving of ``defaults.toml`` and provides helpers for
per-variable plotting defaults (colormaps, log scale, symmetric colorbar).
"""

from pathlib import Path

CONFIG_PATH = Path(__file__).parent / 'defaults.toml'

DEFAULT_CONFIG = {
    'general': {
        'pvpython_path': '',
        'earth_radius_m': 6371000.0,
        'output_subdir': 'slices',
        'grid_resolution_deg': 0.25,
        'arrow_spacing_deg': 2.0,
        'cross_section_arrows_x': 40,
        'cross_section_arrows_y': 16,
        'map_projection': 'mercator',
        'last_input_path': '',
    },
    'plotting': {
        'backend': 'pygmt',
        'figure_dpi': 300,
        'coastlines': False,
        'plate_boundaries': False,
    },
    'colormaps': {
        'T': 'inferno',
        'viscosity': 'viridis',
        'strain_rate': 'batlow',
        'density': 'buda',
        'velocity_magnitude': 'roma',
        'velocity_east': 'roma',
        'velocity_north': 'roma',
        'velocity_radial': 'roma',
        'shear_stress': 'lajolla',
        'dynamic_topography': 'roma',
        'p': 'oslo',
        'default': 'viridis',
    },
    'log_scale': {
        'viscosity': True,
        'strain_rate': True,
    },
    'symmetric_colorbar': {
        'dynamic_topography': True,
        'velocity_east': True,
        'velocity_north': True,
        'velocity_radial': True,
    },
}


# ---------------------------------------------------------------------------
# Loading / saving
# ---------------------------------------------------------------------------

def load_config():
    """Load config from ``defaults.toml``, merging with built-in defaults."""
    if not CONFIG_PATH.exists():
        return _copy_config(DEFAULT_CONFIG)

    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            # No TOML reader available — use defaults
            print("\n  [WARNING] Python 3.11+ or the 'tomli' package is required to read defaults.toml.")
            print("  [WARNING] Your configuration will not be saved between runs!")
            print("  [WARNING] Please run: pip install tomli\n")
            return _copy_config(DEFAULT_CONFIG)

    try:
        with open(CONFIG_PATH, 'rb') as f:
            user_config = tomllib.load(f)
    except Exception as e:
        print(f"\n  [WARNING] Failed to parse defaults.toml: {e}\n")
        return _copy_config(DEFAULT_CONFIG)

    return _deep_merge(DEFAULT_CONFIG, user_config)


def save_config(config):
    """Save *config* to ``defaults.toml``."""
    lines = [
        '# ASPECT Post-Processor — user defaults\n',
        '# Edit this file to change default settings.\n',
        '# Delete this file to reset to built-in defaults.\n',
    ]
    _write_toml_section(lines, config, prefix='')
    CONFIG_PATH.write_text(''.join(lines))


# ---------------------------------------------------------------------------
# Per-variable helpers
# ---------------------------------------------------------------------------

def get_colormap(variable, config):
    """Return the default colormap name for *variable*."""
    cmaps = config.get('colormaps', {})
    return cmaps.get(variable, cmaps.get('default', 'viridis'))


def is_log_scale(variable, config):
    """Return ``True`` if *variable* defaults to log-scale plotting."""
    return config.get('log_scale', {}).get(variable, False)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

UNITS = {
    'T': 'K',
    'p': 'Pa',
    'density': 'kg/m\u00b3',
    'density_field': 'kg/m\u00b3',
    'viscosity': 'Pa\u00b7s',
    'strain_rate': '1/s',
    'velocity_magnitude': 'm/yr',
    'velocity_east': 'm/yr',
    'velocity_north': 'm/yr',
    'velocity_radial': 'm/yr',
    'shear_stress_magnitude': 'Pa',
    'dynamic_topography': 'm',
    'thermal_expansivity': '1/K',
    'specific_heat': 'J/(kg\u00b7K)',
    'principal_stress_1': 'Pa',
    'principal_stress_2': 'Pa',
    'principal_stress_3': 'Pa',
    'maximum_horizontal_compressive_stress_magnitude': 'Pa',
}


def get_unit(variable):
    """Return the SI unit string for *variable*, or '' if unknown."""
    return UNITS.get(variable, '')


def is_symmetric(variable, config):
    """Return ``True`` if *variable* defaults to a symmetric colorbar."""
    return config.get('symmetric_colorbar', {}).get(variable, False)


# ---------------------------------------------------------------------------
# First-run setup
# ---------------------------------------------------------------------------

def first_run_setup(config):
    """Interactive first-run wizard — asks for pvpython path and saves config.

    Returns the (possibly updated) *config* dict.
    """
    import menu  # local import to avoid circular dependency at module level
    import shutil

    menu.header("First-Time Setup")
    print("  This tool requires pvpython (ParaView's Python interpreter)")
    print("  for extracting data from ASPECT output files.\n")

    # Try to auto-detect pvpython
    pvpython = shutil.which('pvpython')
    if not pvpython:
        for candidate in [
            '/opt/paraview-6.1.1/bin/pvpython',
            '/opt/paraview/bin/pvpython',
            '/usr/local/bin/pvpython',
            '/usr/bin/pvpython',
        ]:
            if Path(candidate).exists():
                pvpython = candidate
                break

    if pvpython:
        menu.info(f"Found pvpython: {pvpython}")
        if menu.prompt_bool("Use this path?"):
            config['general']['pvpython_path'] = pvpython
        else:
            path = menu.prompt("Enter full path to pvpython")
            if path:
                config['general']['pvpython_path'] = path
    else:
        menu.warn("Could not auto-detect pvpython")
        path = menu.prompt("Enter full path to pvpython")
        if path:
            config['general']['pvpython_path'] = path

    # Validate
    pvp = Path(config['general']['pvpython_path'])
    if pvp.exists() and pvp.is_file():
        menu.info("pvpython path verified")
    else:
        menu.error(f"Warning: '{config['general']['pvpython_path']}' not found")
        menu.warn("You can fix this later in defaults.toml")

    save_config(config)
    menu.info(f"Configuration saved to {CONFIG_PATH}")

    return config


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _copy_config(cfg):
    """Return a deep copy of *cfg* (dict of dicts)."""
    return {k: (dict(v) if isinstance(v, dict) else v) for k, v in cfg.items()}


def _deep_merge(base, override):
    """Deep-merge *override* into *base*, returning a new dict."""
    result = {}
    for key in set(list(base.keys()) + list(override.keys())):
        b_val = base.get(key)
        o_val = override.get(key)
        if isinstance(b_val, dict) and isinstance(o_val, dict):
            result[key] = _deep_merge(b_val, o_val)
        elif key in override:
            result[key] = o_val
        else:
            result[key] = b_val
    return result


def _write_toml_section(lines, data, prefix):
    """Recursively serialise *data* as TOML into *lines*."""
    # Simple key = value pairs first
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(f'{_toml_kv(key, value)}\n')

    # Nested [sections]
    for key, value in data.items():
        if isinstance(value, dict):
            section_name = f'{prefix}.{key}' if prefix else key
            lines.append(f'\n[{section_name}]\n')
            _write_toml_section(lines, value, section_name)


def _toml_kv(key, value):
    """Format a single TOML key = value pair."""
    if isinstance(value, bool):
        return f'{key} = {"true" if value else "false"}'
    if isinstance(value, str):
        return f'{key} = "{value}"'
    if isinstance(value, (int, float)):
        return f'{key} = {value}'
    return f'{key} = "{value}"'
