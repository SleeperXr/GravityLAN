from pathlib import Path

def get_version() -> str:
    """Reads the version from the root VERSION file."""
    try:
        # Assuming we are in backend/app/version.py
        # Root is 3 levels up from here (app -> backend -> root)
        version_file = Path(__file__).parent.parent.parent / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip()
    except Exception:
        pass
    return "0.2.1-dev"

VERSION = get_version()
