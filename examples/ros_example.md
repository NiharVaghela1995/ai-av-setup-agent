# ROS 2 Example Workflow

## Prerequisites
- Ubuntu 22.04 (required — ROS 2 Humble)
- ROS 2 Humble installed: https://docs.ros.org/en/humble/Installation.html
- rosdep installed and updated

## Step 1 — SAFE mode analysis

```bash
python main.py --safe --source path/to/ros2_workspace
```

Expected output:
- Domain detected: ROS2
- ROS distro check (must be humble)
- rosdep availability check
- Missing env vars: ROS_DISTRO, AMENT_PREFIX_PATH
- Warning: rosdep installs are system-wide

## Step 2 — Source ROS 2 before running

```bash
source /opt/ros/humble/setup.bash
python main.py --safe --source path/to/ros2_workspace
```

Always source ROS 2 before running the agent for ROS projects.

## Step 3 — Review plan

The plan will include:
- `rosdep update`
- `rosdep install --from-paths src --ignore-src -r -y`

Both `rosdep install` steps are HIGH risk (system-wide sudo).

## Step 4 — Execute

```bash
python main.py --execute --source path/to/ros2_workspace
```

rosdep install requires typed confirmation:
```
I UNDERSTAND THE RISK
```

## Step 5 — Build workspace

After rosdep install, build manually:
```bash
cd path/to/ros2_workspace
colcon build --symlink-install
source install/setup.bash
```

## Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `ROS_DISTRO not set` | Workspace not sourced | `source /opt/ros/humble/setup.bash` |
| `rosdep: command not found` | rosdep not installed | `sudo apt install python3-rosdep` |
| Python import errors after build | Workspace not sourced | `source install/setup.bash` |
| ROS on Windows refused | Not supported natively | Use WSL2 or Docker |

## Windows Users

ROS 2 on Windows is refused by the agent. Use one of:
- WSL2: https://learn.microsoft.com/en-us/windows/wsl/install
- Docker: `docker pull osrf/ros:humble-desktop`
