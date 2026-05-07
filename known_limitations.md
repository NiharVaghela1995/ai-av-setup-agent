# Known Limitations

## Current Constraints

### CUDA and GPU
- CUDA compatibility resolution is heuristic-based — the agent checks version numbers
  but cannot fully resolve complex driver / toolkit / PyTorch three-way compatibility
- CUDA driver installation is refused (marked HIGH risk) — requires manual handling
- No support for multi-GPU configurations

### Build Systems
- Complex C++ build systems (custom CARLA builds, Autoware from source) require
  manual setup beyond what the agent handles
- CMake, colcon, and catkin builds are not automated — the agent flags them but
  does not execute them

### ROS / Autoware
- ROS 2 on Windows is refused — use WSL2 or Linux
- ROS 2 on macOS is refused — use Docker
- rosdep installs are system-wide and difficult to roll back automatically
- Autoware workspace builds are not automated

### Dependency Resolution
- Flat pip list resolution only — no full dependency graph awareness
- Transitive conflicts (A requires X==1.0, B requires X==2.0) may not be
  caught until pip install fails
- Dynamic re-planning is partial — it re-scans after each step but does not
  do full graph re-resolution

### Rollback
- Automatic rollback is implemented for pip (via pip freeze snapshot) but
  is not fully tested for all failure scenarios
- apt / rosdep installs have no automatic rollback — package names must be
  read from terminal output and removed manually

### Notebook Execution
- Cell execution timeout is fixed at 180 seconds — long-running cells
  (model training, large data loading) may time out
- Cells with interactive widgets or display outputs may not render correctly
  in headless execution

### Windows
- Most functionality works on Windows, but ROS and rosdep are refused
- Some path handling edge cases on Windows have not been fully tested
- conda run prefix may behave differently in PowerShell vs CMD

### Confidence Scoring
- LOW confidence items are guessed from keyword heuristics — treat these
  as suggestions only, not authoritative requirements

## Recommended Usage Patterns

- Always run SAFE mode first before any execution
- Use isolated conda environments — never install globally
- Review all HIGH risk steps carefully before typing confirmation
- Use Linux / Ubuntu for any ROS or CARLA workflows
- For Autoware, prefer the official Docker-based install
- Commit `requirements-lock.txt` to git after a successful setup
