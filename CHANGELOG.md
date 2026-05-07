# Changelog

All notable changes to this project are documented here.

---

## v1.0.0 — 2026

### Added

**Core pipeline**
- Requirements-first parsing (repo scanned before system touched)
- Targeted system scan (only checks what requirements actually need)
- Gap analysis with version conflict detection
- OS-aware command generation (Ubuntu / macOS / Windows)

**Safety system**
- SAFE MODE enabled by default — read-only analysis, zero execution
- HIGH risk steps blocked until user types `I UNDERSTAND THE RISK`
- Refusal logic for unsupported configurations (never generates fake commands)
- Virtual environment guard — blocks global installs by default
- AUTO_CREATE_ENV — creates isolated conda env automatically when needed

**Execution engine**
- Step-by-step guarded execution with per-sub-command approval gates
- Dynamic re-planning — re-scans system after each successful step
- Restart orchestration — pause + resume across kernel / session / reboot
- Resume state saved to `agent_output/resume_state.json`

**Confidence scoring**
- HIGH / MEDIUM / LOW confidence on every requirement, dependency, and fix
- LOW confidence items blocked from auto-execution
- Confidence badges shown in all plan output

**Error intelligence**
- Unified error stream — terminal + notebook cell errors in one log
- Structured error classification: missing dep / version mismatch / CUDA / OS
- `errors_summary.md` in ERROR → CAUSE → FIX → CONFIDENCE format
- Fix suggestions with confidence scores

**Domain-specific rules**
- CARLA: Python version check, GPU/VRAM requirement, OS guard, Unreal deps
- ROS 2: Linux enforcement, rosdep check, env sourcing verification
- Autoware: ROS 2 + CUDA + colcon checks
- nuScenes: dataset download guidance

**Logging and reporting**
- `change_log.md` — every action taken
- `errors_summary.md` — classified errors
- `dry_run_preview.md` — full step preview before execution
- `requirements-lock.txt` — pinned versions after install
- `env_snapshot.txt` — system state at scan time
- `file_manifest.json` — dataset and file locations

**Modular architecture**
- `core/models.py` — data types, enums, config
- `core/ui.py` — terminal output, gates, banners
- `core/parser.py` — requirement parsing, domain detection
- `core/system_profiler.py` — OS detection, system scan, env guard
- `core/planner.py` — gap analysis, plan building, refusal checks
- `core/executor.py` — execution engine, notebook runner
- `core/logger.py` — logging, error summary, dry-run preview
- `core/error_handler.py` — error classification, fix suggestions

---

## Planned

- Dependency graph resolution (beyond flat requirements lists)
- Smarter rollback and environment snapshotting
- Docker integration for fully isolated runs
- Better CUDA compatibility matrix
- GUI dashboard
- Multi-repository workspace support
