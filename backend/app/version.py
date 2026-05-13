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
            
    return "0.2.3.1"

VERSION = get_version()
