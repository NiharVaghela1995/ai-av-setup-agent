"""
core/planner.py — Gap analysis, version strategy, OS-aware plan building,
                  refusal checks, dynamic re-planning.
"""
from __future__ import annotations
import re, sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.models import (
    ChangePlan, Confidence, Domain, DomainProfile, Requirement,
    RestartType, Risk, Step, SubCmd, CFG,
    OUT, MANIFEST_F,
)
from core.ui import _c, _sep, _hdr, gate, AgentError, UnsupportedConfig
from core.system_profiler import _run, NAME_MAP

# ── Restart rule table ────────────────────────────────────────────────────────
_RESTART_RULES: List[Tuple[str, RestartType]] = [
    (r"cuda|cudnn|nvidia|driver|kernel.module|dkms|udev", RestartType.REBOOT),
    (r"ros\b|ros2|ament|colcon|rosdep|rcl|rclpy",         RestartType.SESSION),
    (r"conda.create|conda.install",                        RestartType.SESSION),
    (r"torch|tensorflow|jax|onnx|open3d|carla",           RestartType.KERNEL),
    (r"nuscenes|pykitti|av2|scenic|mmdet|mmcv",           RestartType.KERNEL),
    (r".*",                                                RestartType.NONE),
]

def classify_restart(pkg: str) -> RestartType:
    for pat, rt in _RESTART_RULES:
        if re.search(pat, pkg.lower()):
            return rt
    return RestartType.NONE

# ══════════════════════════════════════════════════════════════════════════════
# REFUSAL CHECKS
# ══════════════════════════════════════════════════════════════════════════════

def check_unsupported(needed: dict, state: dict, os_info: dict,
                      domains: List[DomainProfile]):
    """Raises UnsupportedConfig for fundamentally broken combinations."""
    os_type  = os_info["type"]
    pip_str  = " ".join(needed.get("pip",[])).lower()
    has_ros  = bool(needed.get("rosdep")) or Domain.ROS2 in [d.domain for d in domains]
    has_cuda = bool(re.search(r"torch|cuda|tensorrt|cupy", pip_str))
    gpu      = state.get("gpu","none")
    cuda_ver = state.get("cuda_ver","")

    # ROS on Windows
    if has_ros and os_type == "windows":
        raise UnsupportedConfig(
            "ROS 2 / rosdep cannot be natively installed on Windows.",
            alternatives=[
                "WSL2 (recommended): https://learn.microsoft.com/en-us/windows/wsl/install",
                "Docker: docker pull osrf/ros:humble-desktop",
                "Dual-boot Ubuntu 22.04 LTS",
            ]
        )

    # ROS on macOS
    if has_ros and os_type == "mac":
        raise UnsupportedConfig(
            "ROS 2 on macOS has very limited, unstable support.",
            alternatives=[
                "Docker (recommended): docker pull osrf/ros:humble-desktop",
                "Linux VM via UTM: https://mac.getutm.app",
            ]
        )

    # CUDA required, no GPU
    if has_cuda and (not gpu or gpu == "none"):
        raise UnsupportedConfig(
            "Project requires CUDA/GPU but no NVIDIA GPU was detected.",
            alternatives=[
                "Use device='cpu' for learning/testing",
                "Google Colab (free GPU): https://colab.research.google.com",
                "Kaggle Notebooks: https://www.kaggle.com/code",
                "Rent cloud GPU: Lambda Labs / RunPod / Vast.ai",
            ]
        )

    # CUDA version too old
    if has_cuda and cuda_ver and cuda_ver not in ("not found",""):
        try:
            major = int(cuda_ver.split(".")[0])
            if major < 11:
                raise UnsupportedConfig(
                    f"CUDA {cuda_ver} detected. PyTorch requires CUDA 11.x or 12.x.",
                    alternatives=[
                        "Update NVIDIA drivers: https://www.nvidia.com/drivers",
                        "Install CUDA 11.8: https://developer.nvidia.com/cuda-11-8-0-download-archive",
                        "CPU-only PyTorch: pip install torch --index-url https://download.pytorch.org/whl/cpu",
                    ]
                )
        except (ValueError, IndexError):
            pass

    # CARLA on macOS / Windows
    if Domain.CARLA in [d.domain for d in domains]:
        if os_type in ("windows","mac"):
            raise UnsupportedConfig(
                f"CARLA simulator server is not supported on {os_type}.",
                alternatives=[
                    "Use Ubuntu 20.04 or 22.04",
                    "Docker on Linux: https://carla.readthedocs.io/en/latest/build_docker/",
                    "Cloud VM with Ubuntu + NVIDIA GPU",
                ]
            )
        vram = state.get("gpu_vram_gb",0)
        if gpu == "none":
            raise UnsupportedConfig(
                "CARLA requires an NVIDIA GPU but none was detected.",
                alternatives=[
                    "Use a cloud VM with GPU",
                    "Use carla-headless Docker for CI without GPU",
                ]
            )
        if vram < 4:
            print(_c("y",f"  ⚠  CARLA warning: {vram}GB VRAM detected, 4GB+ required, 8GB recommended."))

# ══════════════════════════════════════════════════════════════════════════════
# GAP ANALYSIS + VERSION STRATEGY
# ══════════════════════════════════════════════════════════════════════════════

def gap_and_strategy(needed: dict, state: dict, reqs: List[Requirement],
                     env_override: Optional[str] = None) -> dict:
    _hdr("Gap analysis + version strategy")

    missing = [p for p in needed.get("pip",[])
               if state.get("packages",{}).get(
                   re.split(r"[><=!]",p)[0].strip().lower(),"MISSING")=="MISSING"]

    conflicts = []
    for spec in needed.get("pip",[]):
        base = re.split(r"[><=!]",spec)[0].strip().lower()
        inst = state.get("packages",{}).get(base,"MISSING")
        if inst == "MISSING": continue
        if "==" in spec:
            req_ver = spec.split("==")[1].strip()
            if inst not in ("ok","?") and inst != req_ver:
                conflicts.append(dict(pkg=base, required=req_ver, installed=inst))

    has_pins  = sum(1 for p in needed.get("pip",[]) if "==" in p)
    needs_new = bool(conflicts) or (has_pins >= 3 and len(missing) > 2) or bool(env_override)

    # Attach confidence
    missing_with_conf = []
    for pkg in missing:
        base = re.split(r"[><=!]",pkg)[0].strip().lower()
        req  = next((r for r in reqs if r.base == base), None)
        conf = req.confidence if req else Confidence.LOW
        missing_with_conf.append((pkg, conf))

    res_conf = (Confidence.HIGH   if not conflicts and has_pins >= 1 else
                Confidence.MEDIUM if not conflicts else Confidence.LOW)

    strat = {
        "missing":            missing,
        "missing_with_conf":  missing_with_conf,
        "conflicts":          conflicts,
        "needs_new_env":      needs_new,
        "env_name":           env_override,
        "reason":             "",
        "resolution_confidence": res_conf,
    }

    if needs_new and not strat["env_name"]:
        from datetime import datetime
        strat["env_name"] = f"av_{datetime.now().strftime('%m%d')}"

    if conflicts:
        print(_c("y",f"\n  {len(conflicts)} version conflict(s):"))
        for c in conflicts:
            print(f"    {_c('r','✗')} {c['pkg']}: need {c['required']}, have {c['installed']}")

    print(f"  Dependency resolution: {res_conf.badge()}  {res_conf.desc}")

    if needs_new:
        strat["reason"] = f"Conflicts/pins → new env '{strat['env_name']}'"
        print(_c("y",f"  Strategy: NEW ENV '{strat['env_name']}'"))
    else:
        strat["reason"] = "No conflicts → install in current env"
        print(_c("g",f"  Strategy: CURRENT ENV ({state.get('active_env','base')})"))

    if not CFG.SAFE_MODE:
        c = gate("Accept strategy?", risk=Risk.MEDIUM if needs_new else Risk.LOW)
        if c == "n":
            flip = input("  [new] / [current]: ").strip().lower()
            if "new" in flip:
                strat["needs_new_env"] = True
                name = input(f"  Env name [{strat['env_name']}]: ").strip()
                if name: strat["env_name"] = name
            else:
                strat["needs_new_env"] = False
                strat["env_name"] = None

    return strat

# ══════════════════════════════════════════════════════════════════════════════
# FILE MAP
# ══════════════════════════════════════════════════════════════════════════════

DATASET_HINTS = {
    "nuScenes":   ["v1.0-mini","v1.0-trainval","nuscenes"],
    "KITTI":      ["velodyne","image_2","label_2","kitti"],
    "Argoverse2": ["argoverse2","sensor","lidar"],
    "Waymo":      ["segment-","tfrecords","waymo"],
    "CARLA":      ["CarlaUE4","PythonAPI","carla"],
    "Autoware":   ["autoware","autoware_data"],
}

def file_map(source: str, state: dict) -> dict:
    manifest: dict = {
        "scanned_at": __import__('datetime').datetime.now().isoformat(),
        "source": source, "datasets": {}, "notebooks": [], "configs": {},
    }
    for root in [Path.home(), Path("/mnt"), Path.home()/"data",
                 Path.home()/"datasets"]:
        if not root.exists(): continue
        for ds_name, hints in DATASET_HINTS.items():
            if ds_name in manifest["datasets"]: continue
            for hint in hints:
                for depth in [hint, f"*/{hint}", f"*/*/{hint}"]:
                    try:
                        matches = list(root.glob(depth))
                        if matches:
                            manifest["datasets"][ds_name] = str(matches[0])
                            break
                    except Exception:
                        pass

    src = Path(source)
    scan_root = src if src.is_dir() else (src.parent if src.exists() else Path("."))
    manifest["notebooks"] = [str(nb) for nb in scan_root.rglob("*.ipynb")]

    import json
    MANIFEST_F.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_F.write_text(json.dumps(manifest, indent=2))
    print(f"  Datasets: {list(manifest['datasets'].keys()) or 'none'}")
    print(f"  Notebooks: {len(manifest['notebooks'])}")
    return manifest

# ══════════════════════════════════════════════════════════════════════════════
# PLAN BUILDING
# ══════════════════════════════════════════════════════════════════════════════

def build_plans(needed: dict, state: dict, strat: dict,
                os_info: dict, reqs: List[Requirement]) -> List[ChangePlan]:
    plans: List[ChangePlan] = []
    os_type  = os_info["type"]
    env_name = strat.get("env_name","")
    pip_pfx  = f"conda run -n {env_name} " if strat.get("needs_new_env") and env_name else ""

    conda_base, _, _ = _run("conda info --base 2>/dev/null")
    env_path = (f"{conda_base}/envs/{env_name}" if conda_base
                else f"~/miniconda3/envs/{env_name}")

    # ── Plan A: Create conda env ──────────────────────────────────────────────
    if strat.get("needs_new_env") and env_name:
        pv = needed.get("min_python") or "3.10"
        plans.append(ChangePlan(
            title=f"Create isolated env '{env_name}'",
            objective="Isolate project deps to prevent conflicts",
            why_now=strat.get("reason",""),
            overall_risk=Risk.LOW,
            rollback_plan=f"conda env remove -n {env_name} -y",
            phase_tag="env",
            confidence=Confidence.HIGH,
            steps=[Step(
                title=f"conda create '{env_name}'",
                what=f"New Python {pv} env at {env_path}. Base env untouched.",
                where=env_path, how="conda create",
                impacts=[f"~200 MB at {env_path}","Base env untouched"],
                risks=["Needs ~200MB disk",f"Python {pv} must be in channels"],
                cmd_linux=f"conda create -n {env_name} python={pv} pip -y",
                cmd_win=f"conda create -n {env_name} python={pv} pip -y",
                cmd_mac=f"conda create -n {env_name} python={pv} pip -y",
                risk=Risk.LOW, restart=RestartType.SESSION,
                rollback=f"conda env remove -n {env_name} -y",
                confidence=Confidence.HIGH,
                expected_outcome=f"New conda env '{env_name}' created and ready",
                files_affected=[env_path],
                env_impact=f"New isolated environment — all installs go here",
            )],
        ))

    # ── Plan B: apt (Ubuntu/Linux) ────────────────────────────────────────────
    if os_type in ("ubuntu","linux"):
        apt_map = {
            "open3d":  ["libgl1-mesa-glx","libgomp1"],
            "cv2":     ["libglib2.0-0","libsm6","libxrender1","libxext6"],
            "carla":   ["libpng16-16","libjpeg8","libtiff5"],
            "pyaudio": ["portaudio19-dev"],
            "shapely": ["libgeos-dev"],
        }
        apt_needed = list(dict.fromkeys(
            lib for p in needed.get("pip",[])
            for lib in apt_map.get(re.split(r"[><=!]",p)[0].strip().lower().replace("-","_"), [])
        ))
        if apt_needed:
            plans.append(ChangePlan(
                title="Install system C libraries via apt",
                objective="Satisfy C lib deps for pip packages",
                why_now="Must precede pip installs that link against these.",
                overall_risk=Risk.HIGH,
                rollback_plan=f"sudo apt-get remove {' '.join(apt_needed)}",
                phase_tag="apt", os_guard="linux",
                confidence=Confidence.HIGH,
                steps=[
                    Step(title="apt-get update",
                         what="Refresh apt index — no packages installed yet.",
                         where="/var/lib/apt/lists/", how="apt-get update",
                         impacts=["Index refresh (~50MB bandwidth)"],
                         risks=["Requires internet"],
                         cmd_linux="sudo apt-get update -qq",
                         risk=Risk.INFO, restart=RestartType.NONE,
                         expected_outcome="Package index up to date",
                         files_affected=["/var/lib/apt/lists/"],
                         env_impact="Read-only — no packages changed",
                         confidence=Confidence.HIGH),
                    Step(title=f"apt install {len(apt_needed)} library(ies)",
                         what=f"System-wide C libraries: {', '.join(apt_needed)}.",
                         where="/usr/lib/  /usr/share/",
                         how="sudo apt-get install",
                         impacts=["System-wide — all users","May upgrade existing libs"],
                         risks=["Requires sudo","Hard to reverse fully",
                                "System-wide, not isolated"],
                         cmd_linux=f"sudo apt-get install -y {' '.join(apt_needed)}",
                         risk=Risk.HIGH, restart=RestartType.NONE,
                         rollback=f"sudo apt-get remove {' '.join(apt_needed)}",
                         requires_typed_confirm=True,
                         expected_outcome=f"{', '.join(apt_needed)} available system-wide",
                         files_affected=["/usr/lib/","/usr/share/"],
                         env_impact="System-wide install — affects all users",
                         confidence=Confidence.HIGH),
                ],
            ))

    # ── Plan B (macOS): brew ──────────────────────────────────────────────────
    elif os_type == "mac":
        brew_map = {"open3d":["libomp"],"cv2":["pkg-config"],
                    "pyaudio":["portaudio"],"shapely":["geos"]}
        brew_needed = list(dict.fromkeys(
            lib for p in needed.get("pip",[])
            for lib in brew_map.get(re.split(r"[><=!]",p)[0].strip().lower().replace("-","_"),[])
        ))
        if brew_needed:
            brew = os_info.get("brew_path","brew")
            plans.append(ChangePlan(
                title="Install system libs via Homebrew",
                objective="C libraries for pip packages on macOS",
                why_now="Required before dependent pip installs.",
                overall_risk=Risk.LOW, phase_tag="brew", os_guard="mac",
                confidence=Confidence.HIGH,
                steps=[Step(
                    title=f"brew install {' '.join(brew_needed)}",
                    what=f"Homebrew install: {', '.join(brew_needed)}.",
                    where="/opt/homebrew/ or /usr/local/", how="brew install",
                    impacts=["Homebrew prefix modified"],
                    risks=["Homebrew must be installed","M1/M2: /opt/homebrew"],
                    cmd_mac=f"{brew} install {' '.join(brew_needed)}",
                    risk=Risk.LOW, restart=RestartType.NONE,
                    rollback=f"{brew} uninstall {' '.join(brew_needed)}",
                    expected_outcome=f"Homebrew packages available",
                    files_affected=["/opt/homebrew/"],
                    env_impact="Homebrew prefix updated",
                    confidence=Confidence.HIGH,
                )],
            ))

    # ── Plan C: pip (bucketed by restart tier) ────────────────────────────────
    missing_with_conf = strat.get("missing_with_conf",[])
    buckets: Dict[str, list] = {"none":[],"kernel":[],"session":[],"reboot":[]}
    for pkg, conf in missing_with_conf:
        buckets[classify_restart(pkg).key].append((pkg, conf))

    for tier_key in ["none","kernel","session","reboot"]:
        tier = buckets[tier_key]
        if not tier: continue
        rt = next(r for r in RestartType if r.key == tier_key)

        plan_conf = (Confidence.HIGH
                     if all(c == Confidence.HIGH for _,c in tier) else
                     Confidence.MEDIUM if all(c != Confidence.LOW for _,c in tier)
                     else Confidence.LOW)

        plans.append(ChangePlan(
            title=f"pip install — {tier_key} tier ({len(tier)} pkgs)",
            objective=f"Install: {', '.join(p for p,_ in tier[:5])}{'…' if len(tier)>5 else ''}",
            why_now=f"Grouped by post-install action: {rt.desc}",
            overall_risk=Risk.MEDIUM,
            rollback_plan="pip install $(cat /tmp/av_pip_before.txt) --force-reinstall",
            phase_tag=f"pip_{tier_key}",
            confidence=plan_conf,
            steps=[
                Step(title="Snapshot packages for rollback",
                     what="pip freeze before changes.",
                     where="/tmp/av_pip_before.txt", how="pip freeze > file",
                     impacts=["Write-only, no packages changed"],risks=["None"],
                     cmd_linux=f"{pip_pfx}pip freeze > /tmp/av_pip_before.txt",
                     cmd_win="pip freeze > %TEMP%\\av_pip_before.txt",
                     cmd_mac=f"{pip_pfx}pip freeze > /tmp/av_pip_before.txt",
                     risk=Risk.INFO, restart=RestartType.NONE, confidence=Confidence.HIGH,
                     expected_outcome="Rollback snapshot saved",
                     files_affected=["/tmp/av_pip_before.txt"],
                     env_impact="Read-only"),
                Step(
                    title=f"pip install {len(tier)} package(s)",
                    what=f"Install: {', '.join(p for p,_ in tier)}.",
                    where=(f"conda env: {env_name}" if strat.get("needs_new_env")
                           else f"prefix: {state.get('python_prefix','')}"),
                    how="pip install — resolves deps, writes to site-packages",
                    impacts=["site-packages/ modified",
                             "May upgrade/downgrade existing packages",
                             f"After: {rt.desc}"],
                    risks=["Conflicting pins may break existing packages",
                           "Large pkgs (torch, open3d) can be 2–6 GB",
                           "Requires internet"],
                    subcmds=[
                        SubCmd(
                            label=f"pip install {pkg}",
                            cmd_linux=f"{pip_pfx}pip install {pkg}",
                            cmd_win=f"pip install {pkg}",
                            cmd_mac=f"{pip_pfx}pip install {pkg}",
                            risk=Risk.MEDIUM,
                            restart=classify_restart(pkg),
                            rollback=f"pip uninstall {re.split(r'[><=!]',pkg)[0]} -y",
                            confidence=conf,
                        )
                        for pkg, conf in tier
                    ],
                    risk=Risk.MEDIUM, restart=rt,
                    rollback="pip install $(cat /tmp/av_pip_before.txt) --force-reinstall",
                    confidence=plan_conf,
                    expected_outcome=f"{len(tier)} packages installed and importable",
                    files_affected=["site-packages/"],
                    env_impact=f"Python environment modified. {rt.desc}",
                ),
            ],
        ))

    # ── Plan D: rosdep (Linux only) ───────────────────────────────────────────
    if needed.get("rosdep") and os_type in ("ubuntu","linux"):
        pkg_xml = (needed["rosdep"][0]
                   if Path(str(needed["rosdep"][0])).exists() else "src")
        plans.append(ChangePlan(
            title="rosdep install (ROS dependencies)",
            objective="Install ROS system packages",
            why_now="package.xml or ROS imports detected.",
            overall_risk=Risk.HIGH,
            rollback_plan="Manual: sudo apt remove <packages from rosdep output>",
            phase_tag="rosdep", os_guard="linux", confidence=Confidence.HIGH,
            steps=[
                Step(title="rosdep update",
                     what="Refresh rosdep index.",
                     where="~/.ros/rosdep/", how="rosdep update",
                     impacts=["Cache updated"], risks=["Internet required"],
                     cmd_linux="rosdep update",
                     risk=Risk.INFO, restart=RestartType.NONE, confidence=Confidence.HIGH,
                     expected_outcome="rosdep index up to date",
                     files_affected=["~/.ros/rosdep/"],
                     env_impact="Cache only"),
                Step(title="rosdep install",
                     what="Resolve package.xml deps → apt install system-wide.",
                     where="/opt/ros/<distro>/  /usr/lib/",
                     how="rosdep → sudo apt-get install",
                     impacts=["System-wide apt installs","/opt/ros/ extended"],
                     risks=["Requires sudo","Hard to reverse",
                            f"ROS distro must match: {state.get('ros_distro','?')}"],
                     cmd_linux=f"rosdep install --from-paths {pkg_xml} --ignore-src -r -y",
                     risk=Risk.HIGH, restart=RestartType.SESSION,
                     rollback="sudo apt remove <check rosdep output>",
                     requires_typed_confirm=True, confidence=Confidence.HIGH,
                     expected_outcome="All ROS dependencies installed",
                     files_affected=["/opt/ros/","/usr/lib/"],
                     env_impact="System-wide — new session required after"),
            ],
        ))

    return plans

# ══════════════════════════════════════════════════════════════════════════════
# DYNAMIC RE-PLANNING
# ══════════════════════════════════════════════════════════════════════════════

def dynamic_replan(needed: dict, strat: dict, os_info: dict,
                   reqs: List[Requirement],
                   remaining: List[ChangePlan]) -> List[ChangePlan]:
    """Re-scan system and rebuild pip plans if gaps changed."""
    from core.system_profiler import targeted_scan
    print(_c("dim","  [Dynamic] Re-scanning after step…"))
    new_state = targeted_scan(needed, os_info)
    new_strat = gap_and_strategy(needed, new_state, reqs)

    old_missing = set(strat.get("missing",[]))
    new_missing = set(new_strat.get("missing",[]))
    resolved    = old_missing - new_missing
    appeared    = new_missing - old_missing

    if resolved: print(_c("g",f"  [Dynamic] Resolved: {', '.join(resolved)}"))
    if appeared:
        print(_c("y",f"  [Dynamic] New conflicts: {', '.join(appeared)}"))
        new_plans = build_plans(needed, new_state, new_strat, os_info, reqs)
        kept      = [p for p in remaining if not p.phase_tag.startswith("pip")]
        new_pip   = [p for p in new_plans  if p.phase_tag.startswith("pip")]
        updated   = kept + new_pip
        print(_c("y",f"  [Dynamic] Plan: {len(remaining)} → {len(updated)} plans"))
        return updated
    return remaining
