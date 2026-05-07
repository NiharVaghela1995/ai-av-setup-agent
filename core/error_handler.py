"""
core/error_handler.py — Error classification, cause analysis, fix suggestion.

Every captured error passes through here and comes out as a CapturedError with:
  - error_class (missing_dep, version_mismatch, cuda_gpu, os_compat, ...)
  - probable_cause (plain English)
  - suggested_fix (FixSuggestion with confidence)
  - overall confidence

The logger then writes these to errors_summary.md in ERROR → CAUSE → FIX → CONFIDENCE format.
"""
from __future__ import annotations
import re
from typing import Optional, Tuple

from core.models import (
    CapturedError, ErrorClass, FixSuggestion, Confidence, Risk
)
from core.ui import _c

# ── Pattern → (ErrorClass, cause_template, fix_fn) ───────────────────────────

def _fix_missing_import(match_val: str) -> FixSuggestion:
    pkg = match_val.replace(".", "-")
    # Special-case common import/package name mismatches
    name_map = {
        "cv2":   "opencv-python",
        "PIL":   "Pillow",
        "sklearn": "scikit-learn",
        "yaml":  "PyYAML",
        "nuscenes": "nuscenes-devkit",
    }
    pip_name = name_map.get(match_val, pkg)
    conf = Confidence.HIGH if match_val in name_map else Confidence.MEDIUM
    return FixSuggestion(
        description=f"pip install {pip_name}",
        command=f"pip install {pip_name}",
        confidence=conf,
        risk=Risk.LOW,
    )

def _fix_version_mismatch(match_val: str) -> FixSuggestion:
    return FixSuggestion(
        description=f"Upgrade or pin the package version. Check changelog for API changes.",
        command=f"pip install --upgrade {match_val}" if match_val else "",
        confidence=Confidence.MEDIUM,
        risk=Risk.MEDIUM,
    )

def _fix_cuda_oom() -> FixSuggestion:
    return FixSuggestion(
        description="Reduce batch size, or replace .cuda() → .cpu() in cell for testing.",
        command="",  # patch applied in notebook cell, not shell
        confidence=Confidence.HIGH,
        risk=Risk.MEDIUM,
    )

def _fix_cuda_error(match_val: str) -> FixSuggestion:
    return FixSuggestion(
        description="CUDA runtime error. Check nvidia-smi, driver version, and CUDA toolkit match.",
        command="nvidia-smi",
        confidence=Confidence.MEDIUM,
        risk=Risk.INFO,
    )

def _fix_missing_file(match_val: str) -> FixSuggestion:
    is_dataset = any(kw in match_val.lower()
                     for kw in ["data","nuscenes","kitti","waymo","carla","argoverse"])
    if is_dataset:
        return FixSuggestion(
            description=f"Dataset path not found: '{match_val}'. Update path in cell or download dataset.",
            command="",
            confidence=Confidence.LOW,   # agent can't know where dataset lives
            risk=Risk.LOW,
        )
    return FixSuggestion(
        description=f"File/directory not found: '{match_val}'. Check path or re-run file map phase.",
        command="",
        confidence=Confidence.LOW,
        risk=Risk.LOW,
    )

def _fix_api_change(match_val: str) -> FixSuggestion:
    return FixSuggestion(
        description=f"Attribute '{match_val}' removed or renamed. Check package changelog.",
        command="",
        confidence=Confidence.LOW,
        risk=Risk.LOW,
    )

def _fix_os_compat() -> FixSuggestion:
    return FixSuggestion(
        description="OS incompatibility. Check if package supports your platform.",
        command="",
        confidence=Confidence.MEDIUM,
        risk=Risk.INFO,
    )

# ── Main classifier ───────────────────────────────────────────────────────────

# Pattern, error_class, cause_template, fix_fn_name, match_group
_RULES = [
    # Missing imports
    (r"ModuleNotFoundError: No module named '(.+?)'",
     ErrorClass.MISSING_DEP,
     "Python cannot find module '{val}'. Package is not installed in the active environment.",
     _fix_missing_import),

    (r"ImportError: cannot import name '(.+?)' from '(.+?)'",
     ErrorClass.VERSION_MISMATCH,
     "Module '{val}' exists but the requested attribute/function was removed or renamed in the installed version.",
     lambda v: _fix_version_mismatch(v)),

    # File errors
    (r"FileNotFoundError.*?'(.+?)'",
     ErrorClass.MISSING_FILE,
     "File or directory '{val}' does not exist at the specified path.",
     _fix_missing_file),

    (r"No such file or directory.*?['\"](.+?)['\"]",
     ErrorClass.MISSING_FILE,
     "Path '{val}' does not exist. May be an incorrect dataset path or missing config file.",
     _fix_missing_file),

    # CUDA / GPU
    (r"CUDA out of memory",
     ErrorClass.CUDA_GPU,
     "GPU VRAM exhausted. Model or batch size exceeds available GPU memory.",
     lambda _: _fix_cuda_oom()),

    (r"out of memory",
     ErrorClass.CUDA_GPU,
     "Memory exhausted (CPU or GPU). Reduce batch size or model size.",
     lambda _: _fix_cuda_oom()),

    (r"RuntimeError: CUDA error[:\s]+(.+)",
     ErrorClass.CUDA_GPU,
     "CUDA runtime error: '{val}'. Usually a driver/toolkit version mismatch or hardware fault.",
     lambda v: _fix_cuda_error(v)),

    (r"CUDA driver version is insufficient",
     ErrorClass.CUDA_GPU,
     "Installed NVIDIA driver is too old for the CUDA toolkit version required by PyTorch.",
     lambda _: FixSuggestion(
         description="Update NVIDIA drivers: https://www.nvidia.com/drivers",
         command="",
         confidence=Confidence.HIGH,
         risk=Risk.HIGH,
     )),

    (r"AssertionError: Torch not compiled with CUDA",
     ErrorClass.CUDA_GPU,
     "The installed PyTorch build has no CUDA support (CPU-only build installed).",
     lambda _: FixSuggestion(
         description="Reinstall PyTorch with CUDA: https://pytorch.org/get-started/locally/",
         command="pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118",
         confidence=Confidence.HIGH,
         risk=Risk.MEDIUM,
     )),

    # Version mismatches
    (r"AttributeError:.+has no attribute '(.+?)'",
     ErrorClass.VERSION_MISMATCH,
     "Attribute '{val}' not found — the API changed between versions. "
     "Your code may target a different package version than what is installed.",
     _fix_api_change),

    (r"cannot import name '(.+?)'",
     ErrorClass.VERSION_MISMATCH,
     "'{val}' was removed or renamed in the installed version of the package.",
     lambda v: _fix_version_mismatch(v)),

    # OS / platform
    (r"OSError: \[Errno 8\]",
     ErrorClass.OS_COMPAT,
     "Exec format error — binary compiled for a different architecture (e.g. x86_64 vs ARM).",
     lambda _: _fix_os_compat()),

    (r"This package is not supported on Windows",
     ErrorClass.OS_COMPAT,
     "Package explicitly does not support Windows. Use WSL2 or Linux.",
     lambda _: _fix_os_compat()),
]

def classify_error(raw_message: str, source: str = "",
                   cell_idx: Optional[int] = None) -> CapturedError:
    """
    Classify a raw error string into a CapturedError with cause, fix, confidence.
    Always returns a CapturedError — falls back to UNKNOWN class if no rule matches.
    """
    for pattern, eclass, cause_tpl, fix_fn in _RULES:
        m = re.search(pattern, raw_message, re.IGNORECASE | re.DOTALL)
        if m:
            val = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else ""
            cause = cause_tpl.replace("{val}", val)
            fix   = fix_fn(val)
            return CapturedError(
                error_class    = eclass,
                raw_message    = raw_message.strip()[:600],
                probable_cause = cause,
                suggested_fix  = fix,
                confidence     = fix.confidence,
                source         = source,
                cell_idx       = cell_idx,
            )

    # Unknown error — LOW confidence
    return CapturedError(
        error_class    = ErrorClass.UNKNOWN,
        raw_message    = raw_message.strip()[:600],
        probable_cause = "Unrecognised error pattern. See raw message for details.",
        suggested_fix  = FixSuggestion(
            description = "Review raw error output manually.",
            command     = "",
            confidence  = Confidence.LOW,
            risk        = Risk.INFO,
        ),
        confidence     = Confidence.LOW,
        source         = source,
        cell_idx       = cell_idx,
    )

def print_error_triage(err: CapturedError):
    """Print a classified error to terminal in a clean, readable format."""
    print(_c("r", f"\n  ✗  {err.error_class.value.replace('_',' ').upper()}"))
    print(f"  Cause:      {err.probable_cause}")
    print(f"  Fix:        {err.suggested_fix.description}")
    print(f"  Confidence: {err.confidence.badge()}")
    if err.suggested_fix.command:
        print(f"  Command:    {_c('c', err.suggested_fix.command)}")
    if not err.suggested_fix.auto_ok:
        print(_c("y","  ⚠ LOW confidence — do not auto-execute. Verify manually first."))
