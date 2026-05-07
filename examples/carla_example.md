# CARLA Example Workflow

## Prerequisites
- Ubuntu 20.04 or 22.04
- NVIDIA GPU with 4+ GB VRAM (8 GB recommended)
- CARLA server binary downloaded from https://github.com/carla-simulator/carla/releases

## Step 1 — SAFE mode analysis

```bash
python main.py --safe --source path/to/carla_project
```

Expected output:
- Domain detected: CARLA
- GPU VRAM check
- Python version check (3.8 required)
- Warning: CARLA PythonAPI version must match server binary
- Warning: DISPLAY must be set for headless mode

## Step 2 — Review plan

Check `agent_output/safe_mode_plan.md` for:
- apt system libs (libpng, libjpeg, libtiff)
- pip install carla==<VERSION>
- PYTHONPATH setup instructions

## Step 3 — Create environment

```bash
conda create -n carla_env python=3.8
conda activate carla_env
```

## Step 4 — Execute

```bash
python main.py --execute --source path/to/carla_project --env carla_env
```

HIGH risk step (apt install) requires:
```
I UNDERSTAND THE RISK
```

## Step 5 — Set PYTHONPATH

```bash
export PYTHONPATH=$PYTHONPATH:/path/to/carla/PythonAPI/carla/dist/carla*.egg
```

Add to `~/.bashrc` for persistence.

## Step 6 — Verify

```bash
python -c "import carla; print(carla.__version__)"
```

## Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError: carla` | PYTHONPATH not set | Set PYTHONPATH to .egg file |
| Version mismatch | pip carla ≠ server binary | `pip install carla==<exact server version>` |
| DISPLAY error | No display set | `export DISPLAY=:0` or use VirtualGL |
| Low FPS | GPU memory | Reduce rendering quality in CARLA settings |
