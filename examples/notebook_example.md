# Notebook-Based Coursework Example

## Use Case
Running a perception exercise notebook (e.g. PointPillars on nuScenes) that
has dependency issues, hardcoded paths, and CUDA requirements.

## Step 1 — SAFE mode

```bash
python main.py --safe --source notebooks/week3_pointpillars.ipynb
```

The agent will:
- scan all import statements in the notebook
- detect nuScenes domain
- check if torch, open3d, nuscenes-devkit are installed
- check GPU and CUDA version
- detect hardcoded dataset paths
- generate a full plan

## Step 2 — Review plan output

```
agent_output/
  safe_mode_plan.md       ← read this
  dry_run_preview.md      ← step-by-step preview
  env_snapshot.txt        ← your system state
```

## Step 3 — Execute with isolated env

```bash
python main.py --execute \
  --source notebooks/week3_pointpillars.ipynb \
  --env av_week3
```

The agent will:
1. Create conda env `av_week3`
2. Install torch, nuscenes-devkit, open3d, etc.
3. Scaffold the notebook with corrected paths
4. Open `agent_output/ready_<timestamp>.ipynb`

## Step 4 — Open the ready notebook

```bash
jupyter notebook agent_output/ready_20260507_1430.ipynb
```

The notebook will have:
- A header cell with system info and dataset paths
- An environment check cell (run this first)
- All hardcoded paths rewritten to your system

## Step 5 — After a kernel restart

If torch or open3d was installed, the agent will prompt:
```
⟳ Jupyter kernel restart required.
Kernel → Restart Kernel (0, 0 in Jupyter)
Press Enter when kernel is restarted to continue…
```

Restart the kernel, then press Enter in the terminal.

## Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `MISSING` in env check cell | Package not imported correctly | Check import name vs pip name |
| `FileNotFoundError` for dataset | Path not updated | Update path in notebook cell |
| CUDA OOM | Batch size too large | Agent suggests cuda→cpu patch |
| `nuScenes: no data found` | Wrong dataroot | Set `NUSCENES_DATAROOT` env var |
