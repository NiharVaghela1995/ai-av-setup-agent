"""
core/parser.py — Requirement parsing, domain detection, AV-specific rules.

Domain detection step: scans source for CARLA/ROS/Autoware/nuScenes indicators
and attaches a DomainProfile with special checks, warnings, and requirements.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.models import (
    Confidence, Domain, DomainProfile, Requirement, CFG
)
from core.ui import _c, _sep, _hdr, AgentError

# ── Optional deps ─────────────────────────────────────────────────────────────
try:
    import requests as _requests
    HAS_REQ = True
except ImportError:
    _requests = None
    HAS_REQ = False

try:
    import nbformat as _nbformat
    HAS_NB = True
except ImportError:
    _nbformat = None
    HAS_NB = False

# ── Constants ─────────────────────────────────────────────────────────────────
STDLIB = {
    "os","sys","re","json","math","time","datetime","pathlib","collections",
    "itertools","functools","typing","abc","io","subprocess","shutil","copy",
    "random","string","struct","threading","multiprocessing","logging","warnings",
    "unittest","csv","hashlib","inspect","contextlib","dataclasses","enum",
    "traceback","gc","weakref","operator","array","bisect","heapq","queue",
    "socket","http","urllib","email","html","xml","configparser","argparse",
    "platform","signal","ctypes","tempfile","glob","fnmatch","stat","errno",
}

KEYWORD_DEPS: Dict[str, List[str]] = {
    "carla":     ["carla","pygame","numpy","opencv-python"],
    "nuscenes":  ["nuscenes-devkit","numpy","matplotlib","Pillow","pyquaternion"],
    "kitti":     ["pykitti","numpy","opencv-python","matplotlib"],
    "argoverse": ["av2","numpy","scipy","pandas"],
    "open3d":    ["open3d","numpy"],
    "mmdet3d":   ["torch","mmcv-full","mmdet","mmdet3d"],
    "torch":     ["torch","torchvision","torchaudio"],
    "scenic":    ["scenic"],
    "autoware":  [],
    "ros":       [],
    "waymo":     ["waymo-open-dataset-tf-2-11-0"],
}

# ══════════════════════════════════════════════════════════════════════════════
# DOMAIN DETECTION + AV-SPECIFIC PROFILES
# ══════════════════════════════════════════════════════════════════════════════

# Domain indicators: keyword → Domain enum
DOMAIN_INDICATORS: Dict[str, Domain] = {
    "carla":              Domain.CARLA,
    "CarlaUE4":           Domain.CARLA,
    "carla.Client":       Domain.CARLA,
    "rospy":              Domain.ROS2,
    "rclpy":              Domain.ROS2,
    "ament":              Domain.ROS2,
    "package.xml":        Domain.ROS2,
    "autoware":           Domain.AUTOWARE,
    "nuscenes":           Domain.NUSCENES,
    "mmdet3d":            Domain.MMDET3D,
    "scenic":             Domain.SCENIC,
    "torch":              Domain.PYTORCH,
}

def _carla_profile() -> DomainProfile:
    return DomainProfile(
        domain          = Domain.CARLA,
        required_python = "3.8",       # CARLA 0.9.14 officially supports 3.8
        required_os     = ["ubuntu","linux"],
        gpu_required    = True,
        min_vram_gb     = 4,
        required_env_vars = [],
        pre_checks      = [
            "Check CARLA server is not already running: ps aux | grep CarlaUE4",
            "Verify Unreal Engine 4.26 libs: ls /opt/carla-simulator/",
            "CARLA Python API must match server version exactly",
        ],
        warnings        = [
            "CARLA is NOT supported on macOS or Windows (server-side)",
            "CARLA requires 4+ GB GPU VRAM — 8 GB recommended",
            "CARLA PythonAPI version MUST match CarlaUE4 binary version",
            "Unreal Engine requires ~20 GB disk for full build",
            "DISPLAY variable must be set or VirtualGL used for headless mode",
        ],
        install_notes   = (
            "CARLA install: https://carla.readthedocs.io/en/latest/start_quickstart/\n"
            "  1. Download prebuilt: https://github.com/carla-simulator/carla/releases\n"
            "  2. pip install carla==<VERSION> (must match server binary)\n"
            "  3. export PYTHONPATH=$PYTHONPATH:<CARLA_ROOT>/PythonAPI/carla/dist/carla*.egg"
        ),
    )

def _ros2_profile() -> DomainProfile:
    return DomainProfile(
        domain          = Domain.ROS2,
        required_python = "3.10",      # ROS 2 Humble on Ubuntu 22.04
        required_os     = ["ubuntu","linux"],
        gpu_required    = False,
        required_env_vars = ["ROS_DISTRO","AMENT_PREFIX_PATH","ROS_PYTHON_VERSION"],
        pre_checks      = [
            "Verify ROS 2 source: source /opt/ros/$ROS_DISTRO/setup.bash",
            "Check rosdep installed: rosdep --version",
            "Verify colcon installed: colcon --version",
            "Check workspace sourced: echo $AMENT_PREFIX_PATH",
        ],
        warnings        = [
            "ROS 2 is NOT supported on Windows natively — use WSL2 or Linux",
            "ROS 2 on macOS has very limited support — use Docker",
            "rosdep installs system-wide packages (sudo required)",
            "Mixing ROS 1 and ROS 2 environments causes sourcing conflicts",
            "Always source the workspace AFTER activating conda env",
            "Python packages installed via rosdep are system-wide, not in conda",
        ],
        install_notes   = (
            "ROS 2 Humble install: https://docs.ros.org/en/humble/Installation.html\n"
            "  1. sudo apt install ros-humble-desktop\n"
            "  2. source /opt/ros/humble/setup.bash\n"
            "  3. rosdep install --from-paths src --ignore-src -r -y"
        ),
    )

def _autoware_profile() -> DomainProfile:
    return DomainProfile(
        domain          = Domain.AUTOWARE,
        required_python = "3.10",
        required_os     = ["ubuntu","linux"],
        gpu_required    = True,
        min_vram_gb     = 8,
        required_env_vars = ["ROS_DISTRO","AUTOWARE_HOME"],
        pre_checks      = [
            "Check ROS 2 Humble installed: ros2 --version",
            "Check CUDA 11.x or 12.x: nvcc --version",
            "Check colcon: colcon --version",
            "Verify rosdep: rosdep --version",
        ],
        warnings        = [
            "Autoware.Universe requires ROS 2 Humble on Ubuntu 22.04",
            "Requires 8+ GB GPU VRAM for full sensor stack",
            "Build takes 60–90 minutes on first compile",
            "Must source workspace: source install/setup.bash",
            "Use Docker if on non-Ubuntu system: https://autowarefoundation.github.io/autoware-documentation/",
        ],
        install_notes   = (
            "Autoware install: https://autowarefoundation.github.io/autoware-documentation/\n"
            "  Recommended: Docker-based install\n"
            "  docker pull ghcr.io/autowarefoundation/autoware:latest-prebuilt"
        ),
    )

def _nuscenes_profile() -> DomainProfile:
    return DomainProfile(
        domain          = Domain.NUSCENES,
        required_python = "3.8",
        required_os     = [],     # cross-platform
        gpu_required    = False,
        pre_checks      = [
            "Register at nuscenes.org to get download access",
            "Download mini split for testing: ~15 GB",
        ],
        warnings        = [
            "Full nuScenes dataset is ~300 GB — use mini split for development",
            "Set NUSCENES_DATAROOT or update paths in notebook after download",
        ],
        install_notes   = "pip install nuscenes-devkit\nData: https://www.nuscenes.org/download",
    )

DOMAIN_PROFILES: Dict[Domain, DomainProfile] = {
    Domain.CARLA:    _carla_profile(),
    Domain.ROS2:     _ros2_profile(),
    Domain.AUTOWARE: _autoware_profile(),
    Domain.NUSCENES: _nuscenes_profile(),
}

def detect_domains(source: str, source_files: List[Tuple[str,str]]) -> List[DomainProfile]:
    """
    Scan source text and file contents for domain indicators.
    Returns list of active DomainProfiles ordered by specificity.
    """
    combined = source.lower()
    for fname, content in source_files:
        combined += f"\n{fname}\n{content.lower()}"

    detected: List[Domain] = []
    for indicator, domain in DOMAIN_INDICATORS.items():
        if indicator.lower() in combined and domain not in detected:
            detected.append(domain)

    # Autoware implies ROS2
    if Domain.AUTOWARE in detected and Domain.ROS2 not in detected:
        detected.insert(detected.index(Domain.AUTOWARE)+1, Domain.ROS2)

    profiles = [DOMAIN_PROFILES[d] for d in detected if d in DOMAIN_PROFILES]
    return profiles

def print_domain_warnings(profiles: List[DomainProfile], os_info: dict, state: dict):
    """Print domain-specific warnings and pre-checks before plan generation."""
    if not profiles:
        return
    _hdr("Domain detection — AV-specific rules")
    for profile in profiles:
        print(f"\n  {_c('bold', profile.domain.value.upper())} domain detected")
        _sep("·")

        # OS check
        if profile.required_os and os_info["type"] not in profile.required_os:
            print(_c("r", f"  ⛔  {profile.domain.value.upper()} requires OS: "
                          f"{', '.join(profile.required_os)}. "
                          f"Detected: {os_info['type']}"))
            print(_c("y","     This will trigger a refusal — see alternatives below."))

        # Python version check
        if profile.required_python:
            cur = platform.python_version()
            req = profile.required_python
            cur_major_minor = tuple(int(x) for x in cur.split(".")[:2])
            req_major_minor = tuple(int(x) for x in req.split(".")[:2])
            if cur_major_minor < req_major_minor:
                print(_c("y", f"  ⚠  Python {req}+ required, {cur} detected."))
                print(f"     Recommended: conda create -n av_env python={req}")

        # GPU check
        if profile.gpu_required:
            gpu = state.get("gpu","none")
            vram = state.get("gpu_vram_gb",0)
            if gpu == "none":
                print(_c("r", f"  ⛔  GPU required for {profile.domain.value.upper()} but none detected."))
            elif profile.min_vram_gb and vram < profile.min_vram_gb:
                print(_c("y", f"  ⚠  {vram}GB VRAM detected, {profile.min_vram_gb}GB+ recommended."))
            else:
                print(_c("g", f"  ✓  GPU: {gpu} ({vram}GB VRAM)"))

        # Env vars check
        if profile.required_env_vars:
            import os as _os
            missing_vars = [v for v in profile.required_env_vars
                            if not _os.environ.get(v)]
            if missing_vars:
                print(_c("y", f"  ⚠  Missing env vars: {', '.join(missing_vars)}"))
                print(f"     Add to ~/.bashrc: source /opt/ros/$ROS_DISTRO/setup.bash")

        # Pre-checks
        if profile.pre_checks:
            print(f"\n  {_c('ul','Pre-checks:')}")
            for chk in profile.pre_checks:
                print(f"    {_c('c','→')} {chk}")

        # Warnings
        if profile.warnings:
            print(f"\n  {_c('ul','Warnings:')}")
            for w in profile.warnings:
                print(f"    {_c('y','⚠')} {w}")

        # Install notes
        if profile.install_notes:
            print(f"\n  {_c('ul','Install notes:')}")
            for line in profile.install_notes.splitlines():
                print(f"    {line}")

    print()


# ══════════════════════════════════════════════════════════════════════════════
# REQUIREMENT PARSING
# ══════════════════════════════════════════════════════════════════════════════

def parse_requirements(source: str) -> Tuple[dict, List[Requirement], List[DomainProfile]]:
    """
    Parse requirements from any source.
    Returns (raw_needed_dict, requirements_list, domain_profiles).
    """
    _hdr("Step 0 · Parse requirements (before scanning your system)")
    requirements: List[Requirement] = []
    raw: dict = {
        "pip": [], "apt": [], "rosdep": [], "manual": [],
        "source_files": [], "min_python": None,
    }

    def _add(spec: str, src: str):
        spec = spec.strip()
        if not spec or spec.startswith("#") or spec.startswith("-r"):
            return
        base = re.split(r"[><=!]", spec)[0].strip().lower()
        if not any(r.base == base for r in requirements):
            req = Requirement(spec=spec, base=base, source=src)
            requirements.append(req)
            raw["pip"].append(spec)

    def _scan_imports(code: str, label: str):
        imports = re.findall(r"^\s*(?:import|from)\s+([\w]+)", code, re.MULTILINE)
        for imp in set(imports) - STDLIB:
            _add(imp, f"import scan: {label}")

    src = Path(source)
    is_url = source.startswith("http")
    is_nb  = src.exists() and source.endswith(".ipynb")
    is_py  = src.exists() and source.endswith(".py")
    is_dir = src.is_dir()

    if is_url and "github.com" in source:
        if not HAS_REQ:
            raise AgentError("requests not installed", "pip install requests")
        raw_base = source.replace("github.com","raw.githubusercontent.com").rstrip("/")
        fetched_any = False
        for branch in ["main","master","develop"]:
            for fname in ["requirements.txt","requirements-dev.txt",
                          "pyproject.toml","package.xml"]:
                try:
                    r = _requests.get(f"{raw_base}/{branch}/{fname}", timeout=8)
                    if r.status_code == 200:
                        raw["source_files"].append((fname, r.text))
                        fetched_any = True
                        print(f"  {_c('g','✓')} {fname}  ({branch})")
                        if "requirements" in fname:
                            for line in r.text.splitlines():
                                _add(line, fname)
                        elif fname == "package.xml":
                            raw["rosdep"].append("package.xml")
                except Exception:
                    pass
        if not fetched_any:
            raise AgentError(f"No files fetched from {source}",
                             "Check URL is correct and repo is public.")

    elif is_nb:
        if not HAS_NB:
            raise AgentError("nbformat not installed","pip install nbformat")
        try:
            nb = _nbformat.read(str(src), as_version=4)
            code = "\n".join(c.source for c in nb.cells if c.cell_type=="code")
            _scan_imports(code, src.name)
            raw["source_files"].append((src.name, code[:4000]))
            print(f"  {_c('g','✓')} Scanned: {src.name} ({len(nb.cells)} cells)")
        except Exception as e:
            raise AgentError(f"Cannot read notebook: {e}",
                             f"python -m json.tool {src}")

    elif is_py:
        content = src.read_text(errors="replace")
        _scan_imports(content, src.name)
        raw["source_files"].append((src.name, content[:4000]))
        print(f"  {_c('g','✓')} Scanned: {src.name}")

    elif is_dir:
        for rf in src.rglob("requirements*.txt"):
            for line in rf.read_text(errors="replace").splitlines():
                _add(line.strip(), str(rf))
        for pxml in src.rglob("package.xml"):
            raw["rosdep"].append(str(pxml))
        if HAS_NB:
            for nbf in src.rglob("*.ipynb"):
                try:
                    nb = _nbformat.read(str(nbf), as_version=4)
                    code = "\n".join(c.source for c in nb.cells if c.cell_type=="code")
                    _scan_imports(code, nbf.name)
                    raw["source_files"].append((nbf.name, code[:2000]))
                except Exception:
                    pass

    else:
        # Plain text — keyword heuristic
        lower = source.lower()
        for kw, pkgs in KEYWORD_DEPS.items():
            if kw in lower:
                for p in pkgs:
                    _add(p, f"keyword guess: '{kw}'")
                if kw in ("ros","autoware"):
                    raw["rosdep"].append(kw)

    # Print with confidence badges
    print(f"\n  {_c('bold','Requirements with confidence:')}")
    by_conf: Dict[Confidence, List[Requirement]] = {
        Confidence.HIGH:[], Confidence.MEDIUM:[], Confidence.LOW:[]
    }
    for r in requirements:
        by_conf[r.confidence].append(r)

    for conf, reqs in by_conf.items():
        if reqs:
            print(f"  {conf.badge()} ({len(reqs)}): "
                  f"{', '.join(r.spec for r in reqs[:8])}{'…' if len(reqs)>8 else ''}")

    low = len(by_conf[Confidence.LOW])
    if low:
        print(_c("y",f"\n  ⚠  {low} LOW-confidence item(s) — verify manually."))

    # Domain detection
    domains = detect_domains(source, raw["source_files"])
    if domains:
        print(f"\n  {_c('bold','Domains detected:')} "
              f"{', '.join(p.domain.value for p in domains)}")

    return raw, requirements, domains


import platform  # needed for python_version check inside print_domain_warnings
