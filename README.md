# AI-Assisted AV/ML Environment Setup Agent

A safety-first orchestration assistant designed to reduce setup friction in
complex Autonomous Driving and Machine Learning workflows.

The tool analyses repositories, compares requirements against the local system,
generates guarded execution plans, and assists with environment setup using a
structured approval-based workflow.

---

## Motivation

Built after spending 1.5 months debugging CUDA, mmcv, spconv, and 
nuScenes dependency conflicts across 5 compute environments — local 
Ubuntu laptop, Google Colab, Kaggle, RRZE FAU Compute Cloud, and 
RunPod. The tool emerged from a real problem: every hour spent on 
environment setup was an hour not spent on algorithms and research.

---

## Features

- Repository requirement analysis
- System profiling
- Environment isolation enforcement
- SAFE MODE (read-only analysis, default)
- Step-by-step guarded execution
- Confidence scoring (HIGH / MEDIUM / LOW)
- Risk-aware command approval
- Unified notebook + terminal error reporting
- Dynamic re-planning after each step
- Refusal logic for unsupported configurations
- Restart orchestration (kernel / session / reboot)
- Structured error intelligence with `errors_summary.md`
- OS-aware commands (Ubuntu / macOS / Windows)
- Domain-specific rules (CARLA, ROS 2, Autoware, nuScenes)

---

## Safety Philosophy

This project follows a safety-first design philosophy:

- SAFE mode enabled by default — nothing is executed without explicit opt-in
- HIGH risk operations require typed confirmation: `I UNDERSTAND THE RISK`
- Unsupported configurations are refused instead of guessed
- Global environment modifications are blocked unless explicitly allowed
- Environment isolation is strongly enforced

---

## Disclaimer

This tool is **NOT** a fully autonomous environment repair system.

It uses heuristic analysis and guarded automation to reduce setup friction,
but manual verification may still be required for:

- CUDA / toolchain issues
- custom C++ builds
- unsupported repositories
- highly specialised environments
- incomplete project metadata

---

## Installation

### Prerequisites

**Required**
- Python 3.10+
- Git
- Conda (recommended) or venv

**Recommended**
- Ubuntu 22.04 / Linux
- NVIDIA GPU for AV workflows

### 1. Clone repository

```bash
git clone https://github.com/NiharVaghela1995/ai-av-setup-agent.git
cd ai-av-setup-agent
```

### 2. Create environment

**Conda (recommended)**
```bash
conda create -n avagent python=3.10
conda activate avagent
```

**OR venv**
```bash
python -m venv avagent
source avagent/bin/activate        # Linux / macOS
avagent\Scripts\activate           # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## Usage

### Step 1 — SAFE MODE (always start here)

```bash
python main.py --safe --source path/to/repo_or_notebook
```

This will:
- analyse the repository or notebook
- scan your system
- generate a full execution plan
- **NOT modify anything**

### Step 2 — Review the plan

Read the output carefully. Check:
- `agent_output/safe_mode_plan.md`
- `agent_output/dry_run_preview.md`

Pay special attention to HIGH risk steps and LOW confidence items.

### Step 3 — Execute (only after review)

```bash
python main.py --execute --source path/to/repo_or_notebook
```

### Resume after a restart

```bash
python main.py --resume
```

### Other flags

```bash
--env av_env          # specify target conda env
--dry-run             # show plan without executing (implies --safe)
--no-dynamic-planning # disable re-scan after each step
--allow-global        # allow install outside env (not recommended)
--skip-phases 1,3     # skip specific pipeline phases
```

---

## Example Workflows

**CARLA repository**
```bash
python main.py --safe --source path/to/carla_repo
```

**Notebook-based coursework**
```bash
python main.py --safe --source notebooks/week3_perception.ipynb
```

**GitHub repo**
```bash
python main.py --safe --source https://github.com/user/av-repo
```

**Execute approved plan**
```bash
python main.py --execute --source path/to/project --env av_env
```

---

## Output Artifacts

All outputs written to `agent_output/`:

| File | Description |
|------|-------------|
| `safe_mode_plan.md` | Full plan in SAFE mode |
| `dry_run_preview.md` | Step-by-step preview with impacts |
| `errors_summary.md` | Structured error report (ERROR → CAUSE → FIX → CONFIDENCE) |
| `unified_errors.md` | Combined terminal + notebook error stream |
| `change_log.md` | Every action taken |
| `requirements-lock.txt` | Pinned versions after install — commit this |
| `env_snapshot.txt` | System state at scan time |
| `file_manifest.json` | Dataset paths and file locations |

---

## Project Structure

```
ai-av-setup-agent/
├── main.py                  ← entry point
├── requirements.txt
├── README.md
├── LICENSE
├── CHANGELOG.md
├── known_limitations.md
├── architecture_overview.md
│
├── core/
│   ├── models.py            ← data types, enums, config
│   ├── ui.py                ← terminal output, gates, banners
│   ├── parser.py            ← requirement parsing, domain detection
│   ├── system_profiler.py   ← OS detection, system scan, env guard
│   ├── planner.py           ← gap analysis, plan building, refusal
│   ├── executor.py          ← execution engine, notebook runner
│   ├── logger.py            ← logging, error summary, dry-run preview
│   └── error_handler.py     ← error classification, fix suggestions
│
├── utils/
│   ├── system_utils.py
│   ├── env_utils.py
│   └── display_utils.py
│
├── examples/
│   ├── carla_example.md
│   ├── ros_example.md
│   └── notebook_example.md
│
├── logs/
├── reports/
└── backups/
```

---

## Known Limitations

See [`known_limitations.md`](known_limitations.md) for full details.

---

## License

MIT License — see [`LICENSE`](LICENSE)
