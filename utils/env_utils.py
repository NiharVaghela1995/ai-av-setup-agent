"""
utils/env_utils.py — Environment utility helpers.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Optional


def active_conda_env() -> Optional[str]:
    """Return the active conda environment name, or None."""
    env = os.environ.get("CONDA_DEFAULT_ENV", "")
    return env if env and env != "base" else None


def active_venv() -> Optional[str]:
    """Return the active venv path, or None."""
    return os.environ.get("VIRTUAL_ENV", None)


def in_any_virtual_env() -> bool:
    """Return True if running inside conda or venv."""
    return bool(active_conda_env() or active_venv())


def python_version_tuple() -> tuple:
    """Return (major, minor, patch) of current Python."""
    return sys.version_info[:3]


def python_version_str() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def site_packages_path() -> str:
    """Return path to current Python's site-packages."""
    import site
    paths = site.getsitepackages()
    return paths[0] if paths else sys.prefix + "/lib"
