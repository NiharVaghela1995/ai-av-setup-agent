"""
core/logger.py — Logging, error summary report (errors_summary.md),
                 dry-run preview, change log, unified error stream.
"""
from __future__ import annotations
import json, textwrap
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.models import (
    CapturedError, ChangePlan, ErrorClass, Confidence, Risk, RestartType,
    CFG, OUT, CHANGE_LOG, UNIFIED_LOG, ERRORS_SUMMARY, DRY_RUN_F, LOCK_F
)
from core.ui import _c, _sep, _hdr, _wrap

# ── Internal error registry (accumulated during run) ─────────────────────────
_errors: List[CapturedError] = []

def init_logs():
    OUT.mkdir(parents=True, exist_ok=True)
    _write(CHANGE_LOG,  f"# Change Log — {datetime.now().isoformat()}\n")
    _write(UNIFIED_LOG, f"# Unified Error Log — {datetime.now().isoformat()}\n")
    _write(ERRORS_SUMMARY, f"# Errors Summary — {datetime.now().isoformat()}\n\n"
                           "> Format: ERROR → CAUSE → FIX → CONFIDENCE\n\n")

def _write(p: Path, txt: str, mode: str = "w"):
    p.parent.mkdir(parents=True, exist_ok=True)
    if mode == "w": p.write_text(txt, encoding="utf-8")
    else:
        with open(p, "a", encoding="utf-8") as f: f.write(txt)

def log_change(section: str, content: str):
    ts = datetime.now().strftime("%H:%M:%S")
    _write(CHANGE_LOG, f"\n## [{ts}] {section}\n{content}\n", "a")

def log_error(err: CapturedError):
    """Register a classified error. Appends to unified log and error registry."""
    _errors.append(err)
    ts = datetime.now().strftime("%H:%M:%S")
    origin = f"cell {err.cell_idx+1}" if err.cell_idx is not None else err.source
    entry = (
        f"\n---\n"
        f"**[{ts}] {err.error_class.value}** · {origin}\n\n"
        f"**Raw message:**\n```\n{err.raw_message[:500]}\n```\n\n"
        f"**Probable cause:** {err.probable_cause}\n\n"
        f"**Suggested fix:** {err.suggested_fix.description}  "
        f"[CONF:{err.suggested_fix.confidence.label}]\n\n"
        f"---\n"
    )
    _write(UNIFIED_LOG, entry, "a")
    _write(CHANGE_LOG,  entry, "a")

def write_errors_summary():
    """
    Write structured errors_summary.md in the format:
    ERROR → CAUSE → FIX → CONFIDENCE
    """
    if not _errors:
        _write(ERRORS_SUMMARY, "# Errors Summary\n\nNo errors captured during this run.\n")
        return

    lines = [f"# Errors Summary\n\nGenerated: {datetime.now().isoformat()}\n",
             f"Total errors: {len(_errors)}\n",
             "\n---\n"]

    # Group by error class
    by_class: dict = {}
    for e in _errors:
        by_class.setdefault(e.error_class, []).append(e)

    for eclass, errs in by_class.items():
        lines.append(f"\n## {eclass.value.replace('_',' ').title()} ({len(errs)})\n")
        for i, e in enumerate(errs, 1):
            conf_label = e.confidence.label
            fix_label  = e.suggested_fix.description
            fix_conf   = e.suggested_fix.confidence.label
            lines.append(
                f"\n### Error {i}\n"
                f"\n| Field | Detail |\n|---|---|\n"
                f"| **ERROR** | `{e.raw_message[:120].strip()}` |\n"
                f"| **Source** | {e.source or 'unknown'} |\n"
                f"| **Class** | {eclass.value} |\n"
                f"| **CAUSE** | {e.probable_cause} |\n"
                f"| **FIX** | {fix_label} |\n"
                f"| **Fix command** | `{e.suggested_fix.command or 'manual'}` |\n"
                f"| **CONFIDENCE** | {conf_label} |\n"
                f"| **Fix confidence** | {fix_conf} |\n"
                f"| Timestamp | {e.timestamp} |\n"
            )
            if not e.suggested_fix.auto_ok:
                lines.append(
                    f"\n> ⚠ LOW confidence fix — do NOT auto-execute. "
                    f"Verify manually before applying.\n"
                )

    content = "\n".join(lines)
    _write(ERRORS_SUMMARY, content)

    # Also print a compact summary to terminal
    print(f"\n  {_c('bold','Error summary:')}")
    for eclass, errs in by_class.items():
        label = eclass.value.replace("_"," ").title()
        print(f"    {_c('r','✗')}  {label}: {len(errs)}")
    low_conf = sum(1 for e in _errors if e.confidence == Confidence.LOW)
    if low_conf:
        print(_c("y",f"    {low_conf} low-confidence fix(es) — manual review required"))
    print(_c("dim",f"    Full report → {ERRORS_SUMMARY}"))

# ══════════════════════════════════════════════════════════════════════════════
# DRY-RUN PREVIEW
# ══════════════════════════════════════════════════════════════════════════════

def print_dry_run_preview(plans: List[ChangePlan], os_type: str) -> bool:
    """
    Print a full dry-run preview of every step before asking for execution approval.
    Returns True if user approves execution, False otherwise.
    Writes dry_run_preview.md.
    """
    _hdr("Dry-run preview — full execution plan")

    active = [p for p in plans
              if not p.os_guard or p.os_guard == "any"
              or os_type in p.os_guard
              or (p.os_guard == "linux" and os_type in ("ubuntu","linux"))]

    total_steps = sum(len(p.steps) for p in active)
    all_restarts = sorted({
        s.restart.key for p in active for s in p.steps
        if s.restart != RestartType.NONE
    })
    high_risk = sum(1 for p in active for s in p.steps if s.risk == Risk.HIGH)

    print(f"""
  Plans:           {len(active)}
  Steps:           {total_steps}
  HIGH risk steps: {_c('r',str(high_risk))} {'← require typed confirmation' if high_risk else ''}
  Restarts needed: {_c('y', ', '.join(all_restarts)) if all_restarts else _c('g','none')}
  Mode:            {'DRY RUN — nothing executed yet' if CFG.SAFE_MODE else 'EXECUTE MODE — pending approval'}
""")

    md_lines = [
        f"# Dry-Run Preview\n\nGenerated: {datetime.now().isoformat()}\n",
        f"Plans: {len(active)}  ·  Steps: {total_steps}  ·  "
        f"High risk: {high_risk}  ·  Restarts: {', '.join(all_restarts) or 'none'}\n",
    ]

    for pi, plan in enumerate(active):
        print(f"\n  {'═'*66}")
        print(f"  {_c('bold',f'Plan {pi+1}:')} {plan.title}")
        print(f"  {plan.overall_risk.badge()}  {plan.confidence.badge()}")
        print(f"  Objective : {plan.objective}")
        print(f"  Why now   : {plan.why_now}")
        if plan.rollback_plan:
            print(f"  Rollback  : {_c('dim',plan.rollback_plan)}")

        md_lines.append(f"\n## Plan {pi+1}: {plan.title}\n")
        md_lines.append(f"- **Risk:** {plan.overall_risk.label}")
        md_lines.append(f"- **Confidence:** {plan.confidence.label}")
        md_lines.append(f"- **Objective:** {plan.objective}")
        md_lines.append(f"- **Rollback:** {plan.rollback_plan or 'none'}\n")

        for si, step in enumerate(plan.steps):
            cmd = step.cmd_for(os_type)
            print(f"\n    {_c('bold',f'Step {si+1}:')} {step.title}")
            print(f"    {step.risk.badge()}  {step.restart.badge()}  {step.confidence.badge()}")
            print(f"\n    {_c('ul','Command:')}")
            print(f"      {_c('c','$ '+cmd) if cmd else _c('dim','(python callable)')}")
            print(f"\n    {_c('ul','Expected outcome:')}")
            print(f"      {step.expected_outcome or '(not specified)'}")
            print(f"\n    {_c('ul','Files/dirs affected:')}")
            if step.files_affected:
                for f in step.files_affected: print(f"      {_c('y','→')} {f}")
            else:
                print(f"      {step.where}")
            print(f"\n    {_c('ul','Environment impact:')}")
            print(f"      {step.env_impact or step.how}")
            print(f"\n    {_c('ul','Restart requirement:')}")
            print(f"      {step.restart.badge()}  {step.restart.desc}")
            print(f"\n    {_c('ul','Risks:')}")
            for r in step.risks: print(f"      {_c('r','⚠')} {r}")
            if step.requires_typed_confirm:
                print(_c("r",f'      ► HIGH RISK: requires typed "{from_ui_confirm()}"'))
            if step.rollback:
                print(f"      {_c('g','↩')} Rollback: {step.rollback}")

            md_lines.append(f"\n### Step {si+1}: {step.title}\n")
            md_lines.append(f"| Field | Detail |")
            md_lines.append(f"|---|---|")
            md_lines.append(f"| Command | `{cmd}` |")
            md_lines.append(f"| Expected outcome | {step.expected_outcome or 'see impacts'} |")
            md_lines.append(f"| Files affected | {', '.join(step.files_affected) or step.where} |")
            md_lines.append(f"| Env impact | {step.env_impact or step.how} |")
            md_lines.append(f"| Restart | {step.restart.key} — {step.restart.desc} |")
            md_lines.append(f"| Risk | {step.risk.label} |")
            md_lines.append(f"| Confidence | {step.confidence.label} |")
            if step.rollback:
                md_lines.append(f"| Rollback | `{step.rollback}` |")
            md_lines.append("")

    _write(DRY_RUN_F, "\n".join(md_lines))
    print(f"\n  {_c('g','✓')} Dry-run preview saved → {DRY_RUN_F}")
    _sep("═")

    if CFG.SAFE_MODE:
        print(_c("bold","\n  SAFE MODE: No changes made.\n"))
        print("  To execute:")
        print(_c("c","    python main.py --source <...> --execute"))
        ans = input("\n  Switch to EXECUTE MODE now? (y/n): ").strip().lower()
        return ans == "y"
    else:
        ans = input("\n  Execute this plan? (y/n): ").strip().lower()
        return ans == "y"

def from_ui_confirm() -> str:
    from core.ui import CONFIRM_PHRASE
    return CONFIRM_PHRASE

def write_lock_file(python_exe: str):
    import subprocess
    r = subprocess.run(f"{python_exe} -m pip freeze",
                       shell=True, capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        _write(LOCK_F,
               f"# requirements-lock.txt\n# {datetime.now().isoformat()}\n\n{r.stdout.strip()}")

def save_resume(state: dict):
    state["saved_at"] = datetime.now().isoformat()
    _write(OUT / "resume_state.json", json.dumps(state, indent=2))

def load_resume() -> dict | None:
    p = OUT / "resume_state.json"
    if p.exists():
        try: return json.loads(p.read_text())
        except Exception: return None
    return None
