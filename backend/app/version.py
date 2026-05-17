from pathlib import Path

def get_version() -> str:
    """Reads the version from the root VERSION file, checking multiple locations."""
    # Possible locations for VERSION file
    paths = [
        Path(__file__).parent.parent.parent / "VERSION",  # Local: backend/app/version.py -> root/VERSION
        Path(__file__).parent.parent / "VERSION",         # Docker: /app/app/version.py -> /app/VERSION
        Path("/app/VERSION"),                             # Absolute Docker path
        Path("VERSION")                                   # Current working directory
    ]
    
    for version_file in paths:
        try:
            if version_file.exists():
                return version_file.read_text().strip()
        except Exception:
            continue
            
    return "0.2.5"

VERSION = get_version()

def normalize_version(version: str | None) -> str | None:
    """Normalize version string by removing 'v' prefix and stripping whitespace."""
    if not version:
        return None
    version_str = str(version).strip().lower()
    if version_str.startswith('v'):
        version_str = version_str[1:]
    return version_str
