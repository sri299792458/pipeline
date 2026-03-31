# Python Environment Setup

This page explains the local Python environment used by the current pipeline.

The important idea is that we do **not** use one interpreter for everything.

Current split:

- system ROS Python:
  - `/usr/bin/python3`
- shared local project environment:
  - `.venv`

## Why There Are Two Python Paths

The pipeline uses:

- ROS 2 Jazzy packages installed for system Python
- a shared local `.venv` for project dependencies that are not provided by the
  ROS install

That means:

- some scripts are intentionally run with `/usr/bin/python3`
- other tools are intentionally run from `.venv`

This is not accidental. It is the current supported setup.

## What `.venv` Is Used For

The shared `.venv` is the main local project environment for:

- offline bag conversion and LeRobot export
- Teleop GUI/runtime dependencies such as `ur_rtde`
- SPARK serial runtime dependency `pyserial`
- the Qt operator console dependency `PySide6`
- local validation and calibration tools that run from `.venv`

The bootstrap script is:

- `./data_pipeline/setup_shared_venv.sh`

Despite the historical name, it now prepares the shared local `.venv` used by
more than just the converter.

## What System ROS Python Is Still Used For

System ROS Python remains the main path for:

- raw recording entrypoints launched as `/usr/bin/python3`
- the GelSight bridge
- the RealSense capture bridge
- the pinned local `librealsense v2.54.2` runtime build

The most important consequence is:

- the RealSense capture path does **not** use `.venv` as its primary runtime
- it uses `/usr/bin/python3` plus the local pinned `v2.54.2` build wired in by
  `setup_realsense_contract_runtime.sh`

## Create The Shared `.venv`

From the main repo root:

```bash
source /opt/ros/jazzy/setup.bash
./data_pipeline/setup_shared_venv.sh
source .venv/bin/activate
```

What that script currently installs:

- [requirements-converter.txt](../requirements-converter.txt)
- [requirements-teleop.txt](../requirements-teleop.txt)
- `torch==2.6.0`
- `torchvision==0.21.0`
- editable `lerobot` from the sibling workspace checkout

## Install The Qt Operator Console Dependency

If the user wants the Qt operator console, install:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
pip install -r data_pipeline/requirements-operator-console.txt
```

That currently adds:

- `PySide6`

## Why ROS Still Needs To Be Sourced

Even inside `.venv`, the ROS environment must still be sourced before running
tools that depend on ROS Python modules such as:

- `rclpy`
- `rosbag2_py`

So for `.venv` tools that touch ROS, use:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
```

not just:

```bash
source .venv/bin/activate
```

## Practical Checks

After setup, these commands should succeed:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python - <<'PY'
import lerobot
import torch
import rtde_control
import rtde_receive
import serial
print("shared .venv imports look good")
PY
```

If the Qt operator console dependency was installed, this should also work:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python - <<'PY'
import PySide6
print("PySide6 import OK")
PY
```

## Current Limitations

This shared `.venv` intentionally does **not** yet encode every optional input
device dependency.

Examples that are still outside the core setup path:

- `pyspacemouse`
- VR/OpenVR-specific Python dependencies

Those should be documented separately once their setup path is tightened.

## Next Step

After the Python environment is ready, move on to:

- [hardware-bringup.md](./hardware-bringup.md)
