"""
core/ui.py — Terminal output: colours, separators, gates, banners, loud-failure wrapper.
No business logic. No imports from other core modules except models for type hints.
"""
from __future__ import annotations
import sys, textwrap, traceback
from typing import Callable, Optional, Tuple

# Import only what's needed from models (no circular risk — models has no ui import at top level)
from core.models import Risk, RestartType, Confidence, CFG

CONFIRM_PHRASE = "I UNDERSTAND THE RISK"

# ── Colour ────────────────────────────────────────────────────────────────────

def _c(k: str, t: str) -> str:
    m = {"r":"\033[91m","g":"\033[92m","y":"\033[93m","b":"\033[94m",
         "c":"\033[96m","bold":"\033[1m","dim":"\033[2m","ul":"\033[4m",
         "reset":"\033[0m"}
    return f"{m.get(k,'')}{t}{m['reset']}"

def _sep(ch: str = "─", w: int = 70):
    print(_c("dim", ch * w))

def _hdr(t: str):
    _sep("═"); print(_c("bold", f"  {t}")); _sep("═")

def _wrap(text: str, width: int = 62, indent: str = "      ") -> str:
    return f"\n{indent}".join(textwrap.wrap(text, width))

# ── Banners ───────────────────────────────────────────────────────────────────

BANNER = """
╔══════════════════════════════════════════════════════════════════════╗
║  AV Setup Agent v5  ·  modular · SAFE by default · production-grade  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

def safe_banner():
    print(_c("y", """
  ┌──────────────────────────────────────────────────────┐
  │  SAFE MODE  ·  read-only analysis  ·  no execution   │
  │  Run with --execute to apply changes                  │
  └──────────────────────────────────────────────────────┘"""))

def execute_banner():
    print(_c("g", """
  ┌──────────────────────────────────────────────────────┐
  │  EXECUTE MODE  ·  changes will be applied             │
  └──────────────────────────────────────────────────────┘"""))

# ── Interaction gates ─────────────────────────────────────────────────────────

def gate(prompt: str,
         risk: Risk = Risk.LOW,
         restart: RestartType = RestartType.NONE,
         allow_edit: bool = False) -> str:
    rb   = f"  {restart.badge()}" if restart != RestartType.NONE else ""
    opts = "[y] yes  [n] skip  [q] abort"
    if allow_edit: opts += "  [e] edit"
    ans = input(f"\n  {_c(risk.col,'▶')} {prompt}{rb}  ({opts}): ").strip().lower() or "y"
    if ans == "q":
        print(_c("r", "\n  Aborted.")); sys.exit(0)
    return ans

def high_risk_gate(title: str, what: str, where: str,
                   impacts: list, risks: list, rollback: str = "") -> bool:
    """
    Prints full HIGH-risk explanation and requires exact typed phrase.
    In SAFE_MODE always returns False.
    Returns True only if user typed the confirmation phrase.
    """
    if CFG.SAFE_MODE:
        print(_c("dim", "  [SAFE MODE] HIGH risk step shown only — not executed."))
        return False

    _sep("═")
    print(_c("r", f"\n  ⚠  HIGH RISK STEP: {title}\n  {'═'*50}\n"))
    print(f"  {_c('ul','What:')}\n    {_wrap(what)}")
    print(f"\n  {_c('ul','Where:')}\n    {where}")
    print(f"\n  {_c('ul','Impacts:')}")
    for imp in impacts: print(f"    {_c('y','⊙')} {imp}")
    print(f"\n  {_c('ul','Risks:')}")
    for r in risks: print(f"    {_c('r','⚠')} {r}")
    if rollback:
        print(f"\n  {_c('ul','Rollback:')}\n    {rollback}")
    print()
    print(_c("y", f"  Requires typed confirmation:  {CONFIRM_PHRASE}"))
    print(_c("dim","  Press Enter to skip."))
    typed = input("  > ").strip()
    if typed == CONFIRM_PHRASE:
        print(_c("g","  Confirmed. Proceeding…")); return True
    print(_c("y","  Skipped (phrase did not match).")); return False

# ── Loud failure wrapper ──────────────────────────────────────────────────────

class AgentError(Exception):
    def __init__(self, message: str, fix_hint: str = "", can_skip: bool = True):
        super().__init__(message)
        self.fix_hint = fix_hint
        self.can_skip = can_skip

class UnsupportedConfig(Exception):
    def __init__(self, reason: str, alternatives: list):
        super().__init__(reason)
        self.alternatives = alternatives

def loud(fn: Callable, phase_name: str, can_skip: bool = True) -> Tuple:
    try:
        return fn(), True
    except AgentError as e:
        _sep("═")
        print(_c("r", f"\n  ✗  {phase_name}: {e}"))
        if e.fix_hint: print(_c("y", f"  Fix: {e.fix_hint}"))
        if can_skip:   print(_c("dim","  Continuing…"))
        _sep("═")
        return None, False
    except KeyboardInterrupt:
        print(_c("r","\n  Interrupted.")); sys.exit(0)
    except Exception as e:
        _sep("═")
        print(_c("r", f"\n  Unexpected error in {phase_name}:"))
        tb = traceback.format_exc().strip().splitlines()
        for line in tb[-5:]: print(_c("dim", "  " + line))
        print(_c("y", f"\n  Please report: {type(e).__name__}: {e}"))
        if can_skip:
            ans = input("  [c] continue  [q] quit: ").strip().lower()
            if ans != "c": sys.exit(1)
        return None, False

def print_refusal(e: UnsupportedConfig):
    _sep("═")
    print(_c("r", f"""
  ╔══════════════════════════════════════════════════════╗
  ║  STOP: Unsupported Configuration                    ║
  ╚══════════════════════════════════════════════════════╝

  {e}
"""))
    print(_c("y","  Alternatives:"))
    for i, alt in enumerate(e.alternatives, 1):
        print(f"    {i}. {alt}")
    print()
    print(_c("dim","  Agent will not generate commands for this configuration."))
    print(_c("dim","  Resolve the issue above, then re-run the agent."))
    _sep("═")

def print_result(ok: bool, out: str):
    if ok:
        print(_c("g","  ✓  Done."))
        if out.strip():
            tail = "\n".join(out.strip().splitlines()[-4:])
            print(_c("dim", textwrap.indent(tail, "    ")))
    else:
        print(_c("r","  ✗  Failed."))
        if out.strip():
            tail = "\n".join(out.strip().splitlines()[-6:])
            print(_c("dim", textwrap.indent(tail, "    ")))
