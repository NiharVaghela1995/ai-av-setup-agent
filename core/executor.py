"""
core/executor.py — Execution engine, notebook scaffold, cell-by-cell notebook runner.
"""
from __future__ import annotations
import os, re, subprocess, sys, textwrap
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from core.models import (
    ChangePlan, Confidence, RestartType, Risk, CFG,
    OUT, LOCK_F,
)
from core.ui import (
    _c, _sep, _hdr, gate, high_risk_gate, print_result, AgentError,
    CONFIRM_PHRASE,
)
from core.logger import log_change, log_error, save_resume, write_lock_file
from core.error_handler import classify_error, print_error_triage

# ── optional notebook deps ────────────────────────────────────────────────────
try:
    import nbformat as _nbformat
    HAS_NB = True
except ImportError:
    _nbformat = None
    HAS_NB = False

try:
    import nbclient as _nbclient
    HAS_NBC = True
except ImportError:
    _nbclient = None
    HAS_NBC = False

NAME_MAP = {
    "opencv-python":"cv2","pillow":"PIL","scikit-learn":"sklearn",
    "pyyaml":"yaml","nuscenes-devkit":"nuscenes",
}

def _run(cmd: str) -> Tuple[str,str,int]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "Timed out", 1
    except Exception as e:
        return "", str(e), 1

def _exec(cmd: str, fn: Optional[Callable]) -> Tuple[bool, str]:
    if fn:
        try: return True, str(fn() or "")
        except Exception as e: return False, str(e)
    if cmd and cmd != "[python]":
        out, err, rc = _run(cmd)
        return rc == 0, (out + "\n" + err).strip()
    return True, ""

# ══════════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def execute_plans(plans: List[ChangePlan], os_info: dict,
                  strat: dict, needed: dict, reqs: list,
                  resume_from: int = 0, source: str = ""):
    os_type = os_info["type"]

    active = [p for p in plans
              if not p.os_guard or p.os_guard == "any"
              or os_type in p.os_guard
              or (p.os_guard == "linux" and os_type in ("ubuntu","linux"))]

    print(f"\n  {len(active)} active plans.")
    _sep()
    last_restart = RestartType.NONE

    for pi, plan in enumerate(active):
        if pi < resume_from:
            print(_c("dim",f"  Skipping plan {pi+1} (already done).")); continue

        print(f"\n  {_c('bold',f'Plan {pi+1}/{len(active)}:')} {plan.title}  "
              f"{plan.overall_risk.badge()}  {plan.confidence.badge()}")
        _sep("·")

        # LOW confidence plan warning
        if plan.confidence == Confidence.LOW:
            print(_c("y","\n  ⚠  LOW CONFIDENCE PLAN — derived from heuristics."))
            if gate("Execute this low-confidence plan?", risk=Risk.MEDIUM) != "y":
                print(_c("dim","  Plan skipped.")); continue

        for si, step in enumerate(plan.steps):
            print(f"\n  {_c('bold',f'Step {si+1}/{len(plan.steps)}:')} {step.title}  "
                  f"{step.risk.badge()}  {step.restart.badge()}  {step.confidence.badge()}")

            subs = step.all_subcmds()
            cmd  = step.cmd_for(os_type)

            # HIGH RISK: requires typed confirmation
            if step.risk == Risk.HIGH or step.requires_typed_confirm:
                ok = high_risk_gate(
                    title=step.title, what=step.what, where=step.where,
                    impacts=step.impacts, risks=step.risks, rollback=step.rollback
                )
                if not ok:
                    print(_c("dim","  HIGH risk step skipped.")); continue
                # execute directly after typed confirm
                success, out = _exec(cmd, step.fn)
                log_change(f"P{pi+1}S{si+1}(HIGH): {step.title}",
                           f"$ {cmd}\nOK:{success}\n{out[:400]}")
                if not success:
                    err = classify_error(out, source=f"plan{pi+1}_step{si+1}")
                    log_error(err); print_error_triage(err)
                print_result(success, out)

            elif len(subs) > 1:
                # Multiple sub-commands — gate per sub-command
                choice = gate("Approve step? (will gate per sub-command)",
                              risk=step.risk, restart=step.restart)
                if choice == "n":
                    print(_c("dim","  Step skipped.")); continue

                for sci, sc in enumerate(subs):
                    sc_cmd = sc.cmd_for(os_type)
                    print(f"\n    {_c('bold',f'{sci+1}/{len(subs)}:')} {sc.label}  "
                          f"{sc.risk.badge()}  {sc.confidence.badge()}")
                    print(f"    {_c('c','$ '+sc_cmd)}")

                    if sc.confidence == Confidence.LOW:
                        print(_c("y","    ⚠ LOW confidence — verify manually."))
                    c2 = gate("Execute sub-command?", risk=sc.risk,
                              restart=sc.restart, allow_edit=True)
                    if c2 == "n":
                        print(_c("dim","    Skipped.")); continue
                    if c2 == "e":
                        sc_cmd = input(f"    Edit [{sc_cmd}]: ").strip() or sc_cmd

                    ok, out = _exec(sc_cmd, sc.fn)
                    log_change(f"P{pi+1}S{si+1}sc{sci+1}", f"$ {sc_cmd}\n{out[:400]}")
                    if not ok:
                        err = classify_error(out, f"plan{pi+1}_step{si+1}_sc{sci+1}")
                        log_error(err); print_error_triage(err)
                        if sc.rollback:
                            if gate("Rollback?", risk=Risk.MEDIUM) == "y":
                                _exec(sc.rollback, None)
                    print_result(ok, out)
                    _handle_restart(sc.restart, last_restart, strat, pi, source)
                    if sc.restart != RestartType.NONE: last_restart = sc.restart
                continue  # skip bottom-of-step logic

            else:
                # Single command step
                if cmd: print(f"  {_c('c','$ '+cmd)}")
                if step.confidence == Confidence.LOW:
                    print(_c("y","  ⚠ LOW confidence — verify manually."))
                c = gate("Execute?", risk=step.risk, restart=step.restart,
                         allow_edit=bool(cmd))
                if c == "n":
                    print(_c("dim","  Skipped.")); continue
                if c == "e" and cmd:
                    cmd = input(f"  Edit [{cmd}]: ").strip() or cmd

                success, out = _exec(cmd, step.fn)
                log_change(f"P{pi+1}S{si+1}: {step.title}",
                           f"$ {cmd}\nOK:{success}\n{out[:400]}")
                if not success:
                    err = classify_error(out, f"plan{pi+1}_step{si+1}")
                    log_error(err); print_error_triage(err)
                    if step.rollback:
                        if gate("Rollback?", risk=Risk.MEDIUM) == "y":
                            _exec(step.rollback, None)
                print_result(success, out)

            _handle_restart(step.restart, last_restart, strat, pi, source)
            if step.restart != RestartType.NONE: last_restart = step.restart

            # Dynamic re-planning
            if CFG.DYNAMIC_PLANNING and step.phase_tag != "":
                from core.planner import dynamic_replan
                remaining = active[pi+1:]
                updated   = dynamic_replan(needed, strat, os_info, reqs, remaining)
                if len(updated) != len(remaining):
                    active[pi+1:] = updated

    write_lock_file(sys.executable)

def _handle_restart(rt: RestartType, last: RestartType,
                    strat: dict, pi: int, source: str):
    if rt == RestartType.NONE or rt == last: return
    _sep("═")
    print(_c("y",f"\n  ⟳  ACTION REQUIRED: {rt.desc}\n"))
    if rt == RestartType.REBOOT:
        print("  Full system reboot required. After rebooting:")
        print(_c("c",f"    python main.py --resume --source {source}"))
        save_resume({"next_plan_idx":pi,"source":source})
        input("  Press Enter to exit, then reboot…"); sys.exit(0)
    elif rt == RestartType.SESSION:
        print("  New terminal session required.")
        if strat.get("needs_new_env") and strat.get("env_name"):
            print(f"  conda activate {strat['env_name']}")
        print(f"  python main.py --resume --source {source}")
        save_resume({"next_plan_idx":pi,"source":source})
        input("  Press Enter to exit…"); sys.exit(0)
    elif rt == RestartType.KERNEL:
        print("  Jupyter kernel restart required.")
        print("  Kernel → Restart Kernel  (0, 0 in Jupyter)")
        input("  Press Enter when kernel is restarted…")
        _sep("═")

# ══════════════════════════════════════════════════════════════════════════════
# NOTEBOOK SCAFFOLD
# ══════════════════════════════════════════════════════════════════════════════

def scaffold_notebook(source: str, manifest: dict, state: dict,
                      strat: dict, needed: dict) -> Optional[Path]:
    _hdr("Step 6 · Scaffold notebook")
    if not HAS_NB:
        raise AgentError("nbformat not installed","pip install nbformat nbclient")

    src = Path(source)
    ts  = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = OUT / f"ready_{ts}.ipynb"

    if src.exists() and source.endswith(".ipynb"):
        try:
            nb = _nbformat.read(str(src), as_version=4)
        except Exception as e:
            raise AgentError(f"Cannot read notebook: {e}")
    else:
        nb = _nbformat.v4.new_notebook(); nb.cells = []

    # Path rewrites
    count = 0
    for ds_name, ds_path in manifest.get("datasets",{}).items():
        for pat in [f"./data/{ds_name.lower()}", f"data/{ds_name.lower()}"]:
            for cell in nb.cells:
                if cell.cell_type == "code" and pat in cell.source:
                    cell.source = cell.source.replace(pat, ds_path)
                    count += 1

    # Environment check cell
    env_name = strat.get("env_name") or state.get("active_env","")
    pkgs = [re.split(r"[><=!]",p)[0].strip() for p in needed.get("pip",[])[:12]]
    check = (
        "# AV Agent: environment check\n"
        "import sys, importlib\n"
        f"print(f'Python: {{sys.version.split()[0]}}  env: {env_name}')\n"
        f"_pkgs = {repr(pkgs)}\n"
        "_nm = {'opencv-python':'cv2','pillow':'PIL','scikit-learn':'sklearn'}\n"
        "for _p in _pkgs:\n"
        "    _i = _nm.get(_p.lower(), _p.replace('-','_'))\n"
        "    try:\n"
        "        _m=importlib.import_module(_i); "
        "print(f'  ✓  {_p}: {getattr(_m,\"__version__\",\"ok\")}')\n"
        "    except ImportError: print(f'  ✗  {_p}: MISSING')\n"
    )
    nb.cells.insert(0, _nbformat.v4.new_code_cell(check))
    nb.cells.insert(0, _nbformat.v4.new_markdown_cell(
        f"# AV Agent Ready — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"**Source:** `{source}`  ·  **Python:** `{state.get('python_ver','?')}`  ·  "
        f"**Env:** `{env_name}`\n\n"
        f"Path rewrites applied: {count}"
    ))

    c = gate("Write scaffolded notebook?", risk=Risk.LOW)
    if c == "n": return None

    _nbformat.write(nb, str(out_path))
    print(_c("g", f"  ✓  {out_path}"))
    return out_path

# ══════════════════════════════════════════════════════════════════════════════
# NOTEBOOK CELL EXECUTOR
# ══════════════════════════════════════════════════════════════════════════════

def run_notebook(nb_path: Path, os_info: dict, strat: dict):
    if not nb_path or not nb_path.exists(): return
    if not HAS_NB or not HAS_NBC:
        raise AgentError("nbformat and nbclient required",
                         "pip install nbformat nbclient")

    _hdr("Step 7 · Execute notebook cell-by-cell")
    nb = _nbformat.read(str(nb_path), as_version=4)
    code_cells = [(i,c) for i,c in enumerate(nb.cells) if c.cell_type=="code"]
    print(f"  {len(code_cells)} code cells.")

    for pos, (real_idx, cell) in enumerate(code_cells):
        preview = cell.source[:65].replace("\n"," ↵ ")
        print(f"\n  Cell {pos+1}: {_c('dim', preview)}")
        if gate("Execute?", risk=Risk.LOW) != "y": continue

        client = _nbclient.NotebookClient(nb, timeout=180, kernel_name="python3")
        try:
            client.km, client.kc = client.start_new_kernel()
            client.execute_cell(cell, real_idx)
            print(_c("g","  ✓"))
        except _nbclient.exceptions.CellExecutionError as exc:
            raw = str(exc)
            err = classify_error(raw, source=nb_path.name, cell_idx=pos)
            log_error(err)
            print_error_triage(err)

            # Apply fix if confidence allows
            fix = err.suggested_fix
            if fix.command and fix.auto_ok:
                if gate(f"Apply fix: {fix.description}?",
                        risk=fix.risk) == "y":
                    _exec(fix.command, None)
            elif fix.command:
                print(_c("y",f"  LOW confidence fix — apply manually: {fix.command}"))
        except Exception as exc:
            raw = str(exc)
            err = classify_error(raw, source=nb_path.name, cell_idx=pos)
            log_error(err); print_error_triage(err)
        finally:
            try: client.shutdown_kernel()
            except Exception: pass

    _nbformat.write(nb, str(nb_path))
