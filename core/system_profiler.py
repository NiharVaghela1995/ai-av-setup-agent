"""
core/system_profiler.py — OS detection, targeted system scan, virtual env guard.
"""
from __future__ import annotations
import json, os, platform, re, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.models import CFG, ENV_SNAP
from core.ui import _c, _sep, _hdr, gate, AgentError

# ── shared runner ─────────────────────────────────────────────────────────────
def _run(cmd: str, capture=True) -> Tuple[str, str, int]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=capture,
                           text=True, timeout=300)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "Timed out", 1
    except Exception as e:
        return "", str(e), 1

NAME_MAP = {
    "opencv-python":"cv2","opencv-python-headless":"cv2","pillow":"PIL",
    "scikit-learn":"sklearn","pyyaml":"yaml","nuscenes-devkit":"nuscenes",
    "python-dateutil":"dateutil","mmcv-full":"mmcv",
}

# ══════════════════════════════════════════════════════════════════════════════
# OS DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def detect_os() -> dict:
    sys_ = platform.system().lower()
    if "linux" in sys_:
        out, _, _ = _run("lsb_release -si 2>/dev/null")
        is_ubuntu = "ubuntu" in out.lower()
        return dict(type="ubuntu" if is_ubuntu else "linux",
                    raw=platform.platform(), pkg="apt",
                    sep="/", evar="$", shell="bash",
                    python=sys.executable, home=str(Path.home()))
    elif "windows" in sys_:
        return dict(type="windows", raw=platform.platform(),
                    pkg="winget", sep="\\", evar="%", shell="powershell",
                    python=sys.executable, home=str(Path.home()))
    elif "darwin" in sys_:
        brew = shutil.which("brew") or "/opt/homebrew/bin/brew"
        ver, _, _ = _run("sw_vers -productVersion 2>/dev/null")
        return dict(type="mac", raw=platform.platform(),
                    pkg="brew", sep="/", evar="$", shell="zsh",
                    python=sys.executable, home=str(Path.home()),
                    brew_path=brew, mac_ver=ver)
    return dict(type="linux", raw=platform.platform(),
                pkg="apt", sep="/", evar="$", shell="bash",
                python=sys.executable, home=str(Path.home()))

# ══════════════════════════════════════════════════════════════════════════════
# TARGETED SYSTEM SCAN
# ══════════════════════════════════════════════════════════════════════════════

def targeted_scan(needed: dict, os_info: dict) -> dict:
    _hdr("System scan — targeted to project requirements")
    state: Dict = {
        "os":            os_info,
        "python_ver":    platform.python_version(),
        "python_prefix": sys.prefix,
        "conda_envs":    [],
        "active_env":    os.environ.get("CONDA_DEFAULT_ENV",""),
        "cuda_ver":      "not found",
        "gpu":           "none",
        "gpu_vram_gb":   0,
        "ros_distro":    os.environ.get("ROS_DISTRO","not found"),
        "disk_free_gb":  0,
        "packages":      {},
        "in_venv":       bool(os.environ.get("VIRTUAL_ENV","")),
    }

    # Conda env list
    out, _, rc = _run("conda env list --json 2>/dev/null")
    if rc == 0:
        try:
            d = json.loads(out)
            state["conda_envs"] = [Path(e).name for e in d.get("envs",[])]
        except Exception:
            pass

    # GPU / CUDA — only when relevant
    needs_cuda = any(re.search(r"torch|cuda|open3d|carla|tensorrt",
                               " ".join(needed.get("pip",[])).lower()))
    if needs_cuda or needed.get("rosdep"):
        out, _, rc = _run(
            "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null"
        )
        if rc == 0 and out:
            parts = out.splitlines()[0].split(",")
            state["gpu"] = parts[0].strip()
            try:
                # memory.total is "8192 MiB" → int GB
                vram_str = parts[1].strip().split()[0]
                state["gpu_vram_gb"] = int(vram_str) // 1024
            except Exception:
                pass
        out2, _, _ = _run("nvcc --version 2>/dev/null")
        m = re.search(r"release (\S+),", out2)
        if m: state["cuda_ver"] = m.group(1)

    # Disk
    if os_info["type"] != "windows":
        out, _, _ = _run("df -BG / 2>/dev/null | awk 'NR==2{print $4}'")
        try: state["disk_free_gb"] = int(out.replace("G","").strip())
        except ValueError: pass

    # Package scan
    print(f"  Checking {len(needed.get('pip',[]))} packages…")
    for spec in needed.get("pip",[]):
        base = re.split(r"[><=!]", spec)[0].strip().lower()
        imp  = NAME_MAP.get(base, base.replace("-","_"))
        out, _, rc = _run(
            f'{sys.executable} -c '
            f'"import {imp}; v=getattr({imp},chr(95)*2+chr(118)+chr(101)+chr(114)+chr(115)+chr(105)+chr(111)+chr(110)+chr(95)*2,chr(111)+chr(107)); print(v)"'
            f' 2>/dev/null'
        )
        state["packages"][base] = out if rc == 0 else "MISSING"

    # Print
    installed = {k:v for k,v in state["packages"].items() if v != "MISSING"}
    missing   = [k for k,v in state["packages"].items() if v == "MISSING"]
    print(f"  Python {state['python_ver']}  env: {state['active_env'] or '(none)'}")
    print(f"  GPU: {state['gpu']}  CUDA: {state['cuda_ver']}  VRAM: {state['gpu_vram_gb']}GB")
    print(f"  Disk free: {state['disk_free_gb']} GB  ROS: {state['ros_distro']}")
    print(f"  {_c('g','✓')} Installed: {len(installed)}  {_c('r','✗')} Missing: {len(missing)}")
    if missing:
        print(f"    Missing: {', '.join(missing[:12])}{'…' if len(missing)>12 else ''}")

    # Save snapshot
    snap = (f"# System Snapshot — {datetime.now().isoformat()}\n\n"
            f"OS: {os_info['raw']}\nPython: {state['python_ver']}\n"
            f"GPU: {state['gpu']}  CUDA: {state['cuda_ver']}\n"
            f"Disk free: {state['disk_free_gb']} GB  ROS: {state['ros_distro']}\n\n"
            "## Packages\n" +
            "".join(f"  {'✓' if v!='MISSING' else '✗'}  {k:<35} {v}\n"
                    for k,v in state["packages"].items()))
    ENV_SNAP.parent.mkdir(parents=True, exist_ok=True)
    ENV_SNAP.write_text(snap, encoding="utf-8")
    return state

# ══════════════════════════════════════════════════════════════════════════════
# VIRTUAL ENV GUARD
# ══════════════════════════════════════════════════════════════════════════════

def check_virtual_env(state: dict, needed: dict, env_override: str = None
                      ) -> Tuple[bool, Optional[str]]:
    """
    Returns (safe_to_proceed, env_name).
    Blocks global installs unless ALLOW_GLOBAL_INSTALL is set.
    Creates env automatically if AUTO_CREATE_ENV is on.
    """
    active_env = state.get("active_env","")
    in_conda   = bool(active_env and active_env not in ("","base"))
    in_venv    = bool(os.environ.get("VIRTUAL_ENV",""))
    in_any     = in_conda or in_venv

    if in_any:
        label = active_env if in_conda else os.environ.get("VIRTUAL_ENV","venv")
        print(_c("g", f"  ✓  Active env: {_c('bold', label)}"))
        return True, (active_env if in_conda else None)

    # No env detected
    _sep("═")
    print(_c("r", """
  ⚠  WARNING: No virtual environment active
  ═══════════════════════════════════════════
  Installing globally can:
    • Break other Python projects
    • Conflict with system Python
    • Make setup non-reproducible
    • Corrupt your base conda env
"""))

    if env_override:
        print(f"  Using specified env: {env_override}")
        return _create_env(env_override, needed)

    if CFG.AUTO_CREATE_ENV:
        pv = needed.get("min_python") or "3.10"
        ts = datetime.now().strftime("%m%d_%H%M")
        name = f"av_auto_{ts}"
        print(_c("y", f"  AUTO_CREATE_ENV ON → will create: {_c('bold',name)} (Python {pv})"))
        c = gate("Create and use this environment?", risk=Risk.LOW)
        if c == "y":
            return _create_env(name, needed)
        else:
            custom = input("  Enter existing env name (or Enter to abort): ").strip()
            if custom: return True, custom
            print(_c("r","  Aborting — no virtual environment.")); raise SystemExit(1)

    if CFG.ALLOW_GLOBAL_INSTALL:
        print(_c("y","  ALLOW_GLOBAL_INSTALL set — proceeding globally (not recommended)."))
        return True, None

    print(_c("r","  Cannot install globally. Use --allow-global or enable AUTO_CREATE_ENV."))
    raise SystemExit(1)

def _create_env(name: str, needed: dict) -> Tuple[bool, Optional[str]]:
    pv = needed.get("min_python") or "3.10"
    print(f"  Creating conda env '{name}' (Python {pv})…")
    out, err, rc = _run(f"conda create -n {name} python={pv} pip -y")
    if rc == 0:
        print(_c("g", f"  ✓  Created: {name}"))
        return True, name
    raise AgentError(f"Failed to create conda env '{name}': {err[:200]}",
                     fix_hint="Check conda is installed and Python version is available.")
