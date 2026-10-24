#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build Dify plugin package (.difypkg) with a strict file whitelist.

Usage:
    python build_package.py [plugin_dir] [output_name]

Default output: <name>-<manifest version>.difypkg
"""

import hashlib
import sys
import zipfile
from pathlib import Path

import yaml

INCLUDE_FILES = (
    "manifest.yaml",
    "main.py",
    "requirements.txt",
    "README.md",
    "PRIVACY.md",
    "LICENSE",
)

INCLUDE_DIRS = (
    "_assets",
    "provider",
    "tools",
    "endpoints",
    "readme",
)

FORBIDDEN_SUFFIXES = (".pyc", ".pyo", ".difypkg", ".log", ".env")
FORBIDDEN_NAMES = {".env", ".env.example", ".DS_Store", "Thumbs.db", ".gitignore", ".difyignore"}


def calculate_sha256(file_path: Path) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def collect_files(plugin_path: Path):
    for name in INCLUDE_FILES:
        path = plugin_path / name
        if not path.is_file():
            raise FileNotFoundError(f"required file missing: {name}")
        yield name, path

    for directory in INCLUDE_DIRS:
        base = plugin_path / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if path.name in FORBIDDEN_NAMES or path.name.endswith(FORBIDDEN_SUFFIXES):
                continue
            if "__pycache__" in path.parts:
                continue
            yield str(path.relative_to(plugin_path)).replace("\\", "/"), path


def create_difypkg(plugin_dir: str, output_name: str = None) -> bool:
    plugin_path = Path(plugin_dir).resolve()
    if not plugin_path.exists():
        print(f"Error: directory not found: {plugin_dir}")
        return False

    manifest_path = plugin_path / "manifest.yaml"
    if not manifest_path.exists():
        print(f"Error: manifest.yaml not found in {plugin_path}")
        return False

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    version = manifest.get("version", "0.0.0")
    name = manifest.get("name", "plugin")

    if output_name is None:
        output_name = f"{name}-{version}.difypkg"
    output_path = plugin_path / output_name

    print(f"Building package from: {plugin_path}")
    print(f"Output: {output_path}")

    try:
        files_added = []
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_path, file_path in collect_files(plugin_path):
                entry = zipfile.ZipInfo(rel_path, date_time=(1980, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o644 << 16
                zf.writestr(entry, file_path.read_bytes())
                files_added.append(rel_path)
                print(f"  + {rel_path}")

        sha256 = calculate_sha256(output_path)
        print(f"\nFiles added: {len(files_added)}")
        print(f"Package created: {output_path}")
        print(f"Size: {output_path.stat().st_size:,} bytes")
        print(f"SHA256: {sha256}")
        return True
    except Exception as e:
        print(f"Error creating package: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    plugin_dir = str(Path(__file__).parent.resolve())
    output_name = None
    if len(sys.argv) > 1:
        plugin_dir = str(Path(sys.argv[1]).resolve())
    if len(sys.argv) > 2:
        output_name = sys.argv[2]

    if create_difypkg(plugin_dir, output_name):
        print("\nDone! Upload the .difypkg to Dify: Settings -> Plugins -> Install Plugin -> Upload")
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
