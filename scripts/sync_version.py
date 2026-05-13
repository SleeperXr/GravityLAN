import json
import re
from pathlib import Path

def sync_version():
    root_dir = Path(__file__).parent.parent
    version_file = root_dir / "VERSION"
    if not version_file.exists():
        print("VERSION file not found!")
        return

    version = version_file.read_text().strip()
    print(f"Syncing version {version}...")

    # 1. Update frontend/package.json
    package_json_path = root_dir / "frontend" / "package.json"
    if package_json_path.exists():
        data = json.loads(package_json_path.read_text())
        if data.get("version") != version:
            data["version"] = version
            package_json_path.write_text(json.dumps(data, indent=2) + "\n")
            print(f"Updated {package_json_path.relative_to(root_dir)}")

    # 2. Update backend/pyproject.toml
    pyproject_toml_path = root_dir / "backend" / "pyproject.toml"
    if pyproject_toml_path.exists():
        content = pyproject_toml_path.read_text()
        new_content = re.sub(r'^version = ".*?"', f'version = "{version}"', content, flags=re.MULTILINE)
        if content != new_content:
            pyproject_toml_path.write_text(new_content)
            print(f"Updated {pyproject_toml_path.relative_to(root_dir)}")

    # 3. Update backend/app/main.py (just in case there's still a fallback)
    # Actually, we already updated it to use app.version.VERSION

    print("Sync complete.")

if __name__ == "__main__":
    sync_version()
