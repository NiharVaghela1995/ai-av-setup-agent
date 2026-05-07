#!/usr/bin/env python3
"""
main.py — AI-AV Setup Agent entry point.

Wires all core modules together. No business logic here.

Usage:
    python main.py --safe --source <url|path|description>   (default)
    python main.py --execute --source <...>
    python main.py --resume
    python main.py --source <...> --dry-run
    python main.py --source <...> --execute --env av_env
    python main.py --source <...> --execute --no-dynamic-planning
    python main.py --source <...> --execute --allow-global
    python main.py --source <...> --skip-phases 1,3
"""

import argparse, sys, textwrap
from pathlib import Path

# ── Core modules ──────────────────────────────────────────────────────────────
from core.models      import CFG, OUT
from core.ui          import BANNER, safe_banner, execute_banner, loud, print_refusal, _c, _sep
from core.logger      import init_logs, write_errors_summary, print_dry_run_preview, load_resume, save_resume
from core.parser      import parse_requirements, print_domain_warnings
from core.system_profiler import detect_os, targeted_scan, check_virtual_env
from core.planner     import check_unsupported, gap_and_strategy, file_map, build_plans
from core.executor    import execute_plans, scaffold_notebook, run_notebook
from core.ui          import UnsupportedConfig


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="AI-AV Setup Agent — safety-first AV/ML environment orchestration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Modes:
              --safe      (default) Analyse and plan only. Nothing is executed.
              --execute   Execute the plan after showing it.

            Examples:
              python main.py --safe --source https://github.com/user/repo
              python main.py --safe --source ./week3_perception.ipynb
              python main.py --execute --source ./notebook.ipynb --env av_week3
              python main.py --execute --source "nuScenes PointPillars setup"
              python main.py --resume
        """),
    )

    # Source
    parser.add_argument(
        "--source", metavar="SOURCE",
        help="GitHub URL, local file/directory path, or plain task description"
    )

    # Mode (mutually exclusive)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--safe", dest="safe_mode", action="store_true", default=True,
        help="SAFE MODE: analyse and plan only, no execution (default)"
    )
    mode.add_argument(
        "--execute", dest="safe_mode", action="store_false",
        help="EXECUTE MODE: apply changes after showing plan"
    )

    # Environment
    parser.add_argument(
        "--env", metavar="ENV_NAME",
        help="Target conda environment name (created if it does not exist)"
    )

    # Behaviour flags
    parser.add_argument("--resume",              action="store_true",
                        help="Resume after a system/kernel restart")
    parser.add_argument("--dry-run",             action="store_true",
                        help="Show full plan but execute nothing (implies --safe)")
    parser.add_argument("--no-dynamic-planning", action="store_true",
                        help="Disable re-scan and re-plan after each step")
    parser.add_argument("--allow-global",        action="store_true",
                        help="Allow installs outside a virtual environment (not recommended)")
    parser.add_argument("--skip-phases",         default="", metavar="PHASES",
                        help="Comma-separated phase numbers to skip, e.g. '1,3'")

    return parser


def main():
    parser = build_arg_parser()
    args   = parser.parse_args()

    # Apply config flags
    CFG.SAFE_MODE          = args.safe_mode or args.dry_run
    CFG.DYNAMIC_PLANNING   = not args.no_dynamic_planning
    CFG.ALLOW_GLOBAL_INSTALL = args.allow_global
    skip = {int(x) for x in args.skip_phases.split(",") if x.strip().isdigit()}

    # Banner
    print(BANNER)
    OUT.mkdir(parents=True, exist_ok=True)
    init_logs()

    if CFG.SAFE_MODE:
        safe_banner()
    else:
        execute_banner()

    # Resume state
    resume_state = load_resume() if args.resume else None
    if resume_state:
        print(_c("y", f"  Resuming from: {resume_state.get('saved_at','')}"))

    # Source
    source = args.source or (resume_state or {}).get("source", "")
    if not source:
        source = input("  Source (URL / path / description): ").strip()
    if not source:
        print(_c("r","  No source provided.")); sys.exit(1)

    # OS detection
    os_info = detect_os()
    print(f"  OS: {_c('c', os_info['type'])}  |  pkg manager: {os_info['pkg']}")
    if os_info["type"] == "windows":
        print(_c("y","  Note: ROS/rosdep plans will be refused on Windows (use WSL2)."))
    print()

    # ── Pipeline ──────────────────────────────────────────────────────────────
    needed   = {"pip":[],"apt":[],"rosdep":[],"manual":[],"source_files":[],"min_python":None}
    reqs     = []
    domains  = []
    sys_state = {}
    strat    = {"missing":[],"missing_with_conf":[],"conflicts":[],
                "needs_new_env":False,"env_name":None,"reason":""}
    manifest = {"datasets":{},"notebooks":[],"configs":{}}
    plans    = []

    # Phase 0: parse requirements
    if 0 not in skip:
        result, ok = loud(lambda: parse_requirements(source), "requirement parsing")
        if ok and result:
            needed, reqs, domains = result

    # Phase 1: system scan
    if 1 not in skip:
        result, ok = loud(lambda: targeted_scan(needed, os_info), "system scan")
        if ok and result:
            sys_state = result

    # Domain warnings (always shown, even in safe mode)
    if domains:
        loud(lambda: print_domain_warnings(domains, os_info, sys_state),
             "domain warnings")

    # Refusal check — before any plans built
    try:
        check_unsupported(needed, sys_state, os_info, domains)
    except UnsupportedConfig as e:
        print_refusal(e)
        sys.exit(1)

    # Phase 2: gap analysis + strategy
    if 2 not in skip:
        result, ok = loud(
            lambda: gap_and_strategy(needed, sys_state, reqs, args.env),
            "gap analysis"
        )
        if ok and result:
            strat = result

    # Phase 3: file map
    if 3 not in skip:
        result, ok = loud(lambda: file_map(source, sys_state), "file map")
        if ok and result:
            manifest = result

    # Phase 4: build plans
    if 4 not in skip:
        plans = build_plans(needed, sys_state, strat, os_info, reqs)

    # ── SAFE MODE output ──────────────────────────────────────────────────────
    if CFG.SAFE_MODE:
        if 5 not in skip and plans:
            switch = loud(
                lambda: print_dry_run_preview(plans, os_info["type"]),
                "dry-run preview"
            )
            if switch and switch[0]:  # user chose to switch to execute
                CFG.SAFE_MODE = False
                execute_banner()
            else:
                # Write error summary (none yet in safe mode, but creates the file)
                write_errors_summary()
                _sep("═")
                print(_c("bold","  Safe mode complete. No changes made.\n"))
                _print_artifacts(None)
                return

    # ── EXECUTE MODE ──────────────────────────────────────────────────────────
    if not CFG.SAFE_MODE:

        # Virtual env guard
        if 5 not in skip and plans:
            result, ok = loud(
                lambda: check_virtual_env(sys_state, needed, args.env),
                "virtual env guard"
            )
            if ok and result:
                _, resolved_env = result
                if resolved_env and resolved_env != strat.get("env_name"):
                    strat["env_name"] = resolved_env
                    strat["needs_new_env"] = False
                    plans = build_plans(needed, sys_state, strat, os_info, reqs)

        # Execute plans
        if 5 not in skip and plans:
            resume_from = (resume_state or {}).get("next_plan_idx", 0)
            loud(
                lambda: execute_plans(plans, os_info, strat, needed, reqs,
                                      resume_from, source),
                "plan execution"
            )

        # Scaffold notebook
        nb_path = None
        if 6 not in skip:
            result, ok = loud(
                lambda: scaffold_notebook(source, manifest, sys_state, strat, needed),
                "notebook scaffold"
            )
            if ok: nb_path = result

        # Run notebook
        if 7 not in skip and nb_path:
            loud(
                lambda: run_notebook(nb_path, os_info, strat),
                "notebook execution"
            )

        # Write error summary
        write_errors_summary()

        # Final summary
        _sep("═")
        print(_c("bold","  Agent complete.\n"))
        _print_artifacts(nb_path)


def _print_artifacts(nb_path):
    from core.models import (LOCK_F, CHANGE_LOG, UNIFIED_LOG,
                              ERRORS_SUMMARY, ENV_SNAP, MANIFEST_F,
                              PLAN_F, DRY_RUN_F)
    artifacts = []
    if nb_path and Path(nb_path).exists():
        artifacts.append((nb_path, "Ready notebook  ← open this"))
    artifacts += [
        (PLAN_F,         "Safe mode plan"),
        (DRY_RUN_F,      "Dry-run preview"),
        (ERRORS_SUMMARY, "Error summary (ERROR→CAUSE→FIX→CONF)"),
        (UNIFIED_LOG,    "Unified error log"),
        (CHANGE_LOG,     "Change log"),
        (LOCK_F,         "Requirements lock  ← commit to git"),
        (ENV_SNAP,       "System snapshot"),
        (MANIFEST_F,     "File manifest"),
    ]
    for path, label in artifacts:
        if Path(path).exists():
            sz = Path(path).stat().st_size
            print(f"  {_c('g','✓')}  {label:<45} {path}  ({sz}B)")
    _sep("═")
    if nb_path and Path(nb_path).exists():
        print(_c("bold", f"\n  Open: jupyter notebook {nb_path}\n"))


if __name__ == "__main__":
    main()
