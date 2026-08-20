"""CLI menu helpers and ANSI formatting for the ASPECT post-processing tool."""

import sys


class Style:
    """ANSI escape codes for terminal styling."""
    BOLD = '\033[1m'
    DIM = '\033[2m'
    GREEN = '\033[92m'
    CYAN = '\033[96m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    MAGENTA = '\033[95m'
    BLUE = '\033[94m'
    RESET = '\033[0m'


def banner():
    """Print the application banner."""
    print(f"""
{Style.BOLD}{Style.CYAN}╔══════════════════════════════════════╗
║     ASPECT Post-Processor v1.0       ║
╚══════════════════════════════════════╝{Style.RESET}
""")


def info(msg):
    """Print a success/info message."""
    print(f"  {Style.GREEN}✓{Style.RESET} {msg}")


def warn(msg):
    """Print a warning message."""
    print(f"  {Style.YELLOW}⚠{Style.RESET} {msg}")


def error(msg):
    """Print an error message."""
    print(f"  {Style.RED}✗{Style.RESET} {msg}")


def header(title):
    """Print a section header."""
    print(f"\n{Style.BOLD}{Style.CYAN}── {title} ──{Style.RESET}")


def section(title):
    """Print a major section divider."""
    print(f"\n{Style.BOLD}═══ {title} ═══{Style.RESET}")


def prompt(msg, default=None):
    """Prompt for text input with optional default value.

    Returns the entered text, or default if the user presses Enter.
    Returns None only if default is None and user enters nothing.
    """
    if default is not None:
        suffix = f" [{Style.DIM}{default}{Style.RESET}]: "
    else:
        suffix = ": "
    try:
        value = input(f"  {msg}{suffix}").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return value if value else (str(default) if default is not None else None)


def prompt_choice(title, options, allow_back=True, allow_quit=False):
    """Display a numbered menu and return (index, option_text).

    Returns ``(-1, None)`` when the user selects *back* and
    ``(-2, None)`` when the user selects *quit*.
    """
    header(title)
    for i, opt in enumerate(options, 1):
        print(f"  {Style.BOLD}[{i}]{Style.RESET} {opt}")
    if allow_back:
        print(f"  {Style.DIM}[b] Back{Style.RESET}")
    if allow_quit:
        print(f"  {Style.DIM}[q] Quit{Style.RESET}")

    while True:
        raw = input(f"\n  {Style.CYAN}>{Style.RESET} ").strip().lower()
        if allow_back and raw == 'b':
            return (-1, None)
        if allow_quit and raw == 'q':
            return (-2, None)
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return (idx, options[idx])
        except ValueError:
            pass
        error(f"Please enter a number from 1 to {len(options)}")


def prompt_float(msg, default=None):
    """Prompt for a float value with optional default."""
    while True:
        raw = prompt(msg, default)
        if raw is None:
            return default
        try:
            return float(raw)
        except (ValueError, TypeError):
            error("Please enter a valid number")


def prompt_bool(msg, default=True):
    """Prompt for a yes/no answer."""
    hint = "Y/n" if default else "y/N"
    raw = prompt(msg, hint)
    if raw is None or raw in ('Y/n', 'y/N'):
        return default
    return raw.lower() in ('y', 'yes', '1', 'true')


def prompt_two_floats(msg, default_str="auto"):
    """Prompt for two space-separated floats (e.g. min and max).

    Returns ``(None, None)`` when the user enters 'auto' or nothing.
    """
    while True:
        raw = prompt(msg, default_str)
        if raw is None or raw.lower() == 'auto':
            return None, None
        parts = raw.split()
        if len(parts) != 2:
            error("Enter two values separated by a space (e.g. 100 200)")
            continue
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            error("Please enter valid numbers")


def display_metadata(meta):
    """Display loaded file metadata in a readable format."""
    ts = meta.get('timesteps', [])
    variables = meta.get('variables', [])
    vectors = meta.get('vector_variables', [])
    bounds = meta.get('bounds', {})

    n_ts = len(ts)
    t_min = ts[0]['time_years'] if ts else 0
    t_max = ts[-1]['time_years'] if ts else 0

    lon = bounds.get('lon', [0, 0])
    lat = bounds.get('lat', [0, 0])
    dep = bounds.get('depth_km', [0, 0])

    scalar_vars = [v for v in variables if v not in vectors]
    var_str = ', '.join(scalar_vars)

    print()
    print(f"  {Style.BOLD}Timesteps{Style.RESET}  : {n_ts} ({t_min:,.0f} → {t_max:,.0f} yrs)")
    print(f"  {Style.BOLD}Scalars{Style.RESET}    : {var_str}")
    if vectors:
        print(f"  {Style.BOLD}Vectors{Style.RESET}    : {', '.join(vectors)}")
    print(f"  {Style.BOLD}Longitude{Style.RESET}  : {lon[0]:.1f}° – {lon[1]:.1f}°")
    print(f"  {Style.BOLD}Latitude{Style.RESET}   : {lat[0]:.1f}° – {lat[1]:.1f}°")
    print(f"  {Style.BOLD}Depth{Style.RESET}      : {dep[0]:.0f} – {dep[1]:.0f} km")
    print()


def wait_for_enter(msg="Press Enter to continue..."):
    """Wait for the user to press Enter before continuing."""
    try:
        input(f"\n  {Style.DIM}{msg}{Style.RESET}")
    except (EOFError, KeyboardInterrupt):
        pass
