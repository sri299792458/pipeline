# ROS And System Setup

This page defines the Ubuntu and ROS packages an admin or maintainer should
install before provisioning the shared collection account or bringing up
hardware on a fresh machine.

This is an admin-only page.

Use it when:

- provisioning a fresh machine
- rebuilding the machine-level base install
- repairing missing system packages on the dedicated collection machine

For the normal user path on the already-prepared lab machine, do **not** start
here. Start with:

- [Lab Machine Quick Start](./lab-machine-quick-start.md)
- [Personal Account Setup](./personal-account-setup.md) if you are using your own account on the same machine

The current target platform is:

- Ubuntu Noble 24.04 with ROS 2 Jazzy installed under `/opt/ros/jazzy`

## Install ROS 2 Jazzy

Use the official Ubuntu deb installation path for ROS 2 Jazzy.

Reference:

- https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html

The pipeline expects the apt-installed ROS environment under:

- `/opt/ros/jazzy`

If ROS Jazzy is not installed yet, use the official repository setup and then
install the desktop variant:

```bash
sudo apt install software-properties-common
sudo add-apt-repository universe
sudo apt update && sudo apt install curl -y
export ROS_APT_SOURCE_VERSION=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | grep -F "tag_name" | awk -F'"' '{print $4}')
curl -L -o /tmp/ros2-apt-source.deb "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.$(. /etc/os-release && echo ${UBUNTU_CODENAME:-${VERSION_CODENAME}})_all.deb"
sudo dpkg -i /tmp/ros2-apt-source.deb
sudo apt update
sudo apt upgrade
sudo apt install ros-jazzy-desktop
```

After that, this command should work:

```bash
source /opt/ros/jazzy/setup.bash
ros2 --help
```

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

## Shared Collection Account Provisioning

If normal data collection happens through a shared Linux account such as:

- `shared_account`

that account should have device-access group membership before anyone tries to use the rig.

On this machine, the important groups are:

- `dialout`
  - required for SPARK serial devices under `/dev/ttyUSB*`
- `plugdev`
  - useful for camera and removable-device access on this machine
- `video`
  - useful for camera access on this machine

Provision the shared account with:

```bash
sudo usermod -aG dialout,plugdev,video shared_account
```

Then log out and log back in to that account before testing device access.

The point is:

- normal operators should not need `sudo`
- the shared collection account should already have the right device-group access

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

## Primary RealSense Runtime Contract

For the RealSense capture path, do not document or debug this pipeline as if it
primarily depends on:

- the ROS `realsense2_camera` wrapper
- a random system `librealsense` version

The current RealSense path is:

- upstream source checkout at `../librealsense`
- local pinned build/runtime at `v2.54.2`
- launched through `data_pipeline/setup_realsense_contract_runtime.sh`

So the important contract is:

- the system provides ROS Jazzy
- the repo builds its own pinned RealSense runtime

## Viewer Packages

The viewer is not required for raw recording, but it is a real part of the
normal local workflow. If the user wants local dataset inspection or `Open
Viewer` from the operator console, install:

```bash
sudo apt-get install -y nodejs npm
```

The current viewer setup path will install `bun` separately. See:

- [Viewer Setup](./viewer-setup.md)

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

- [Workspace Setup](./workspace-setup.md) if the workspace does not exist yet
- [Python Environment Setup](./python-env-setup.md)
- [Viewer Setup](./viewer-setup.md) if local dataset viewing is part of the shared-account workflow
- [Lab Machine Quick Start](./lab-machine-quick-start.md) once the shared account is provisioned
