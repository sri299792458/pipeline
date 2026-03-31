# ROS And System Setup

This page defines the Ubuntu and ROS packages a new lab member should install
before creating the Python environment or bringing up hardware.

The current target platform is:

- Ubuntu with ROS 2 Jazzy installed under `/opt/ros/jazzy`

This page does not replace the official ROS installation instructions. It
assumes ROS Jazzy itself is already installed and that this command works:

```bash
source /opt/ros/jazzy/setup.bash
ros2 --help
```

If that command fails, install ROS 2 Jazzy first and then return here.

## Core Ubuntu Packages

Install the base system packages used by the current pipeline:

```bash
sudo apt-get update
sudo apt-get install -y \
  git \
  curl \
  build-essential \
  cmake \
  pkg-config \
  python3-dev \
  python3-pip \
  python3-venv \
  v4l-utils \
  libxcb-cursor0
```

What these are for:

- `build-essential`, `cmake`, `pkg-config`
  - needed for the local pinned `librealsense v2.54.2` build
- `python3-dev`, `python3-pip`, `python3-venv`
  - needed for the local `.venv` and Python package installs
- `v4l-utils`
  - provides `v4l2-ctl` for GelSight and camera inspection
- `libxcb-cursor0`
  - required for the Qt operator console on Ubuntu/X11

## ROS Jazzy Packages Required By This Repo

Install the ROS packages the current pipeline depends on directly:

```bash
sudo apt-get install -y \
  ros-jazzy-cv-bridge \
  ros-jazzy-image-transport-plugins \
  ros-jazzy-rosbag2-storage-mcap
```

What these are for:

- `ros-jazzy-cv-bridge`
  - used by the GelSight bridge and some Teleop camera utilities
- `ros-jazzy-image-transport-plugins`
  - required for offline archive bag generation and verification
  - provides the `compressed` and `compressedDepth` transports
- `ros-jazzy-rosbag2-storage-mcap`
  - required because raw capture bags default to `mcap`

## What We Are Not Using As The Main Path

Do not treat these as the main runtime contract for this pipeline:

- the ROS `realsense2_camera` wrapper
- a random system `librealsense` version

The current RealSense path is:

- upstream source checkout at `../librealsense`
- local pinned build/runtime at `v2.54.2`
- launched through `data_pipeline/setup_realsense_contract_runtime.sh`

So the important contract is:

- the system provides ROS Jazzy
- the repo builds its own pinned RealSense runtime

## Optional Viewer Packages

If the user also wants to run the dataset viewer locally, install:

```bash
sudo apt-get install -y nodejs npm
```

The current viewer launch path also expects:

- `bun` at `~/.bun/bin/bun`

That is part of the viewer workflow, not the core recording pipeline.

## Practical Check

After finishing this page, these commands should work:

```bash
source /opt/ros/jazzy/setup.bash
ros2 --help
v4l2-ctl --help
```

And this package lookup should succeed:

```bash
apt-cache show ros-jazzy-cv-bridge
apt-cache show ros-jazzy-image-transport-plugins
apt-cache show ros-jazzy-rosbag2-storage-mcap
```

## Next Step

After system setup is done, move on to:

- [workspace-setup.md](./workspace-setup.md) if the workspace does not exist yet
- local Python environment setup
- RealSense runtime setup
