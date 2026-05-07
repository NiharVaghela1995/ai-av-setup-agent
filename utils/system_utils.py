"""
utils/system_utils.py — Shared system utility helpers.
Used by core modules for common shell operations.
"""
from __future__ import annotations
import subprocess
from typing import Tuple


def run_cmd(cmd: str, timeout: int = 300) -> Tuple[str, str, int]:
    """Run a shell command. Returns (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True,
            text=True, timeout=timeout
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", f"Command timed out after {timeout}s", 1
    except Exception as e:
        return "", str(e), 1


def command_exists(cmd: str) -> bool:
    """Check if a command is available on PATH."""
    import shutil
    return shutil.which(cmd) is not None


def get_disk_free_gb(path: str = "/") -> int:
    """Return free disk space in GB for the given path."""
    import shutil
    try:
        usage = shutil.disk_usage(path)
        return int(usage.free / (1024 ** 3))
    except Exception:
        return 0
