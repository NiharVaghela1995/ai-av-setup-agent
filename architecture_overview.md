# Architecture Overview

## High-Level Pipeline

```
Source Input (GitHub URL / local path / task description)
        │
        ▼
Step 0: Requirement Parsing          [core/parser.py]
        │  - extract pip/apt/rosdep deps
        │  - detect domain (CARLA/ROS2/Autoware/nuScenes)
        │  - assign confidence (HIGH/MEDIUM/LOW)
        ▼
Step 1: Targeted System Scan         [core/system_profiler.py]
        │  - OS / CUDA / Python / conda / ROS / disk / GPU
        │  - only checks what requirements actually need
        ▼
        [REFUSAL CHECK]              [core/planner.py]
        │  - unsupported configs refused here
        │  - ROS on Windows → STOP
        │  - CUDA needed + no GPU → STOP
        │  - CARLA on macOS → STOP
        ▼
Step 2: Gap Analysis + Strategy      [core/planner.py]
        │  - diff needed vs installed
        │  - detect version conflicts
        │  - decide: new isolated env vs install-in-place
        ▼
Step 3: File Map                     [core/planner.py]
        │  - locate datasets (nuScenes, KITTI, CARLA, etc.)
        │  - map expected paths → actual paths
        │  - write file_manifest.json
        ▼
Step 4: Build Change Plans           [core/planner.py]
        │  - conda env creation plan
        │  - apt / brew system lib plan
        │  - pip install plans (bucketed by restart tier)
        │  - rosdep plan (Linux only)
        │  - every step: what / where / how / impacts / risks
        │  - every step: confidence badge + restart type
        ▼
        ┌─────────────────────────────────┐
        │  SAFE MODE (default)            │
        │  Dry-run preview printed        │
        │  safe_mode_plan.md written      │
        │  Ask: switch to execute?        │
        └─────────────────────────────────┘
                        │ (if --execute or user switches)
                        ▼
Step 5: Guarded Execution            [core/executor.py]
        │  - per-plan approval
        │  - per-step approval
        │  - per-sub-command approval
        │  - HIGH risk → typed confirmation required
        │  - LOW confidence → extra warning
        │  - on failure → classify error → suggest fix
        │  - dynamic re-plan after each successful step
        │  - pause at restart boundaries
        ▼
Step 6: Scaffold Notebook            [core/executor.py]
        │  - copy source notebook
        │  - rewrite hardcoded paths
        │  - inject env check cell
        │  - inject context markdown header
        ▼
Step 7: Execute Notebook             [core/executor.py]
        │  - nbclient cell-by-cell
        │  - capture stdout/stderr per cell
        │  - classify errors → suggest fixes
        │  - apply fixes on approval
        ▼
Output Artifacts                     [core/logger.py]
        - ready_<timestamp>.ipynb
        - safe_mode_plan.md
        - dry_run_preview.md
        - errors_summary.md
        - unified_errors.md
        - change_log.md
        - requirements-lock.txt
        - env_snapshot.txt
        - file_manifest.json
```

---

## Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `core/models.py` | All shared data types, enums, config flags. No imports from other core modules. |
| `core/ui.py` | Terminal output only. Colours, separators, gates, banners, loud-failure wrapper. |
| `core/parser.py` | Parse requirements from any source. Domain detection. AV-specific profiles. |
| `core/system_profiler.py` | OS detection, targeted system scan, virtual env guard. |
| `core/planner.py` | Gap analysis, version strategy, refusal checks, plan building, dynamic re-planning. |
| `core/executor.py` | Execute plans, handle restarts, scaffold notebook, run cells. |
| `core/logger.py` | Write all log files, error summary, dry-run preview. |
| `core/error_handler.py` | Classify errors, generate fix suggestions with confidence. |
| `main.py` | CLI entry point only. Wires modules together. No business logic. |

---

## Design Principles

### Safety First
- SAFE mode is the default — user must explicitly opt in to execution
- HIGH risk steps require `I UNDERSTAND THE RISK` typed exactly
- Unsupported configurations refused with clear alternatives
- Global installs blocked unless explicitly allowed

### Confidence Transparency
- Every requirement, dependency, and fix carries a confidence score
- LOW confidence items shown with warnings, never auto-executed
- Source of every requirement tracked (requirements.txt / import scan / guess)

### Restart Awareness
- Every step classified: `none` / `kernel` / `session` / `reboot`
- Steps grouped by restart tier to minimise total restart count
- Agent pauses at blocking restarts, saves resume state, continues on signal

### Structured Failure
- Every error classified into: missing_dep / version_mismatch / cuda_gpu / os_compat
- Probable cause + fix + confidence attached to every error
- All errors written to unified log and structured summary

---

## Execution Modes

### SAFE MODE (default)
- Runs Steps 0–4 (parse → scan → refusal → gap → file map → plan)
- Prints full dry-run preview
- Writes `safe_mode_plan.md` and `dry_run_preview.md`
- Does NOT execute any commands
- Asks if user wants to switch to execute mode

### EXECUTE MODE (`--execute`)
- Runs full pipeline Steps 0–7
- Per-step approval at every stage
- HIGH risk steps require typed confirmation
- Dynamic re-planning after each step

---

## Risk Levels

| Level | Meaning | Gate |
|-------|---------|------|
| INFO | Read-only, no side effects | None |
| LOW | Easily reversible, isolated | `[y/n]` |
| MEDIUM | Reversible with effort | `[y/n]` |
| HIGH | System-wide, hard to reverse | Type `I UNDERSTAND THE RISK` |

---

## Restart Types

| Type | Trigger | Agent behaviour |
|------|---------|----------------|
| NONE | pip install of minor package | Continue immediately |
| KERNEL | torch, carla, open3d install | Pause, instruct kernel restart, wait |
| SESSION | ROS, conda env creation | Save state, exit, resume in new terminal |
| REBOOT | CUDA driver, kernel module | Save state, exit, resume after reboot |
