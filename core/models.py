"""
core/models.py — All shared data types, enums, and config.
Imported by every other module. No cross-module imports here.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ══════════════════════════════════════════════════════════════════════════════
# FEATURE CONFIG
# ══════════════════════════════════════════════════════════════════════════════

class Config:
    SAFE_MODE          : bool = True
    AUTO_CREATE_ENV    : bool = True
    DYNAMIC_PLANNING   : bool = True
    ALLOW_GLOBAL_INSTALL: bool = False

CFG = Config()

# ══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ══════════════════════════════════════════════════════════════════════════════

class RestartType(Enum):
    NONE    = ("none",    "g", "No restart needed")
    KERNEL  = ("kernel",  "y", "Jupyter kernel restart required")
    SESSION = ("session", "y", "New terminal session required (PATH changed)")
    REBOOT  = ("reboot",  "r", "Full system reboot required")

    def __init__(self, key, col, desc):
        self.key = key; self.col = col; self.desc = desc

    def badge(self) -> str:
        from core.ui import _c
        icons = {"none":"○","kernel":"⟳","session":"↺","reboot":"⏻"}
        return _c(self.col, f"[{icons[self.key]} {self.key.upper()}]")

class Risk(Enum):
    INFO   = ("c","INFO",   "Read-only, no side effects")
    LOW    = ("g","LOW",    "Easily reversible, isolated")
    MEDIUM = ("y","MEDIUM", "Reversible with effort")
    HIGH   = ("r","HIGH",   "System-wide, difficult to reverse — requires typed confirmation")

    def __init__(self, col, label, desc):
        self.col = col; self.label = label; self.desc = desc

    def badge(self) -> str:
        from core.ui import _c
        return _c(self.col, f"[{self.label}]")

class Confidence(Enum):
    HIGH   = ("g","HIGH",   "Exact match — requirements.txt or pinned version")
    MEDIUM = ("y","MEDIUM", "Inferred from imports or partial match")
    LOW    = ("r","LOW",    "Heuristic guess — manual verification recommended")

    def __init__(self, col, label, desc):
        self.col = col; self.label = label; self.desc = desc

    def badge(self) -> str:
        from core.ui import _c
        return _c(self.col, f"[CONF:{self.label}]")

    @property
    def auto_execute_ok(self) -> bool:
        return self in (Confidence.HIGH, Confidence.MEDIUM)

# ── Error classification (NEW) ────────────────────────────────────────────────

class ErrorClass(Enum):
    MISSING_DEP      = "missing_dependency"
    VERSION_MISMATCH = "version_mismatch"
    CUDA_GPU         = "cuda_gpu_issue"
    OS_COMPAT        = "os_incompatibility"
    MISSING_FILE     = "missing_file"
    API_CHANGE       = "api_change"
    UNKNOWN          = "unknown"

# ── Domain tags ───────────────────────────────────────────────────────────────

class Domain(Enum):
    GENERIC    = "generic"
    CARLA      = "carla"
    ROS2       = "ros2"
    AUTOWARE   = "autoware"
    NUSCENES   = "nuscenes"
    PYTORCH    = "pytorch"
    MMDET3D    = "mmdet3d"
    SCENIC     = "scenic"

# ══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Requirement:
    spec:       str
    base:       str
    source:     str
    confidence: Confidence = Confidence.HIGH

    def __post_init__(self):
        if "requirements" in self.source or "==" in self.spec:
            self.confidence = Confidence.HIGH
        elif "import" in self.source:
            self.confidence = Confidence.MEDIUM
        else:
            self.confidence = Confidence.LOW

@dataclass
class SubCmd:
    label:      str
    cmd_linux:  str = ""
    cmd_win:    str = ""
    cmd_mac:    str = ""
    risk:       Risk = Risk.LOW
    restart:    RestartType = RestartType.NONE
    rollback:   str = ""
    fn:         Optional[Callable] = None
    confidence: Confidence = Confidence.HIGH

    def cmd_for(self, os_type: str) -> str:
        if os_type == "windows": return self.cmd_win or self.cmd_linux
        if os_type == "mac":     return self.cmd_mac or self.cmd_linux
        return self.cmd_linux

@dataclass
class Step:
    title:      str
    what:       str
    where:      str
    how:        str
    impacts:    List[str]
    risks:      List[str]
    subcmds:    List[SubCmd]  = field(default_factory=list)
    risk:       Risk          = Risk.LOW
    restart:    RestartType   = RestartType.NONE
    rollback:   str           = ""
    cmd_linux:  str           = ""
    cmd_win:    str           = ""
    cmd_mac:    str           = ""
    fn:         Optional[Callable] = None
    confidence: Confidence    = Confidence.HIGH
    requires_typed_confirm: bool = False
    # dry-run metadata
    expected_outcome: str = ""
    files_affected:   List[str] = field(default_factory=list)
    env_impact:       str = ""

    def __post_init__(self):
        if self.risk == Risk.HIGH:
            self.requires_typed_confirm = True

    def cmd_for(self, os_type: str) -> str:
        if os_type == "windows": return self.cmd_win or self.cmd_linux
        if os_type == "mac":     return self.cmd_mac or self.cmd_linux
        return self.cmd_linux

    def all_subcmds(self) -> List[SubCmd]:
        if self.subcmds: return self.subcmds
        cmd = self.cmd_linux
        if "&&" in cmd:
            return [SubCmd(label=p.strip()[:60], cmd_linux=p.strip(),
                           risk=self.risk, restart=self.restart,
                           confidence=self.confidence)
                    for p in cmd.split("&&") if p.strip()]
        if cmd or self.fn:
            return [SubCmd(label=self.title,
                           cmd_linux=self.cmd_linux, cmd_win=self.cmd_win,
                           cmd_mac=self.cmd_mac, risk=self.risk,
                           restart=self.restart, rollback=self.rollback,
                           fn=self.fn, confidence=self.confidence)]
        return []

@dataclass
class ChangePlan:
    title:         str
    objective:     str
    why_now:       str
    steps:         List[Step]  = field(default_factory=list)
    overall_risk:  Risk        = Risk.LOW
    rollback_plan: str         = ""
    phase_tag:     str         = ""
    os_guard:      str         = ""
    confidence:    Confidence  = Confidence.HIGH
    domain:        Domain      = Domain.GENERIC

@dataclass
class FixSuggestion:
    description:    str
    command:        str
    confidence:     Confidence
    risk:           Risk = Risk.LOW
    auto_ok:        bool = True

    def __post_init__(self):
        self.auto_ok = self.confidence.auto_execute_ok

@dataclass
class CapturedError:
    """One error captured during execution, fully classified."""
    error_class:    ErrorClass
    raw_message:    str
    probable_cause: str
    suggested_fix:  FixSuggestion
    confidence:     Confidence
    source:         str       = ""   # plan/step label
    cell_idx:       Optional[int] = None
    timestamp:      str       = field(default_factory=lambda: datetime.now().isoformat())

@dataclass
class DomainProfile:
    """Rules and requirements for a specific AV domain."""
    domain:           Domain
    required_python:  Optional[str]    = None   # "3.8", "3.10", etc.
    required_os:      List[str]        = field(default_factory=list)
    gpu_required:     bool             = False
    min_vram_gb:      Optional[int]    = None
    required_env_vars: List[str]       = field(default_factory=list)
    pre_checks:       List[str]        = field(default_factory=list)
    warnings:         List[str]        = field(default_factory=list)
    install_notes:    str              = ""

# ══════════════════════════════════════════════════════════════════════════════
# OUTPUT PATHS (single source of truth)
# ══════════════════════════════════════════════════════════════════════════════

OUT          = Path("agent_output")
RESUME_F     = OUT / "resume_state.json"
LOCK_F       = OUT / "requirements-lock.txt"
CHANGE_LOG   = OUT / "change_log.md"
UNIFIED_LOG  = OUT / "unified_errors.md"
ERRORS_SUMMARY = OUT / "errors_summary.md"   # NEW
ENV_SNAP     = OUT / "env_snapshot.txt"
MANIFEST_F   = OUT / "file_manifest.json"
PLAN_F       = OUT / "safe_mode_plan.md"
DRY_RUN_F    = OUT / "dry_run_preview.md"    # NEW
