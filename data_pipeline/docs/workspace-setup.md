# Workspace Setup

This is a setup page for anyone who needs their own workspace layout.

Use it when you are:

- setting up your own Linux account on the existing collection machine
- rebuilding the shared account workspace
- provisioning the dedicated collection machine from scratch

Collection-only users on `shared_account` should start with:

- [Lab Machine Quick Start](./lab-machine-quick-start.md)

Lab members using their own account on the same machine should usually start
with:

- [Personal Account Setup](./personal-account-setup.md)

This page defines the exact repository layout the maintained workspace should use.

Use one shared workspace directory with these sibling checkouts:

```text
spark-workspace/
  spark-data-collection/
  lerobot/
  gsrobotics/
  lerobot-dataset-visualizer/
  librealsense/
```

This is the only supported layout we are documenting going forward.

We are not using:

- nested dependency repos inside `spark-data-collection/`
- git submodules
- lab-owned forks of `lerobot` or `gsrobotics` for now

## Repositories

Clone these exact repositories:

- `spark-data-collection`
  - `https://github.com/RPM-lab-UMN/spark-data-collection.git`
- `lerobot`
  - `https://github.com/huggingface/lerobot.git`
- `gsrobotics`
  - `https://github.com/gelsightinc/gsrobotics.git`
- `lerobot-dataset-visualizer`
  - `https://github.com/RPM-lab-UMN/lerobot-dataset-visualizer.git`
- `librealsense`
  - `https://github.com/IntelRealSense/librealsense.git`

## Clone Commands

```bash
mkdir -p ~/spark-workspace
cd ~/spark-workspace

git clone https://github.com/RPM-lab-UMN/spark-data-collection.git
git clone https://github.com/huggingface/lerobot.git
git clone https://github.com/gelsightinc/gsrobotics.git
git clone https://github.com/RPM-lab-UMN/lerobot-dataset-visualizer.git
git clone https://github.com/IntelRealSense/librealsense.git
```

After cloning, the main working repo is:

```bash
cd ~/spark-workspace/spark-data-collection
```

## Code Assumptions

The pipeline assumes these sibling paths relative to `spark-data-collection/`:

- `../lerobot`
- `../gsrobotics`
- `../lerobot-dataset-visualizer`
- `../librealsense`

That affects:

- converter environment setup
- GelSight bridge imports
- viewer launch from the operator console
- RealSense runtime setup

## RealSense Version Pin

The `librealsense` sibling checkout is the upstream source repository.

The runtime we actually build and use is still pinned to:

- `v2.54.2`

The RealSense setup script does not use an arbitrary SDK version. It creates and builds a pinned local worktree/runtime from the upstream sibling repo:

- source checkout:
  - `../librealsense`
- pinned worktree created under the main repo:
  - `librealsense-v2.54.2`
- local build output:
  - `build/librealsense-v2.54.2/Release`

So the operational requirement is:

- clone upstream `librealsense`
- build and run the pinned `v2.54.2` runtime through the pipeline setup script

## Viewer Remote Notes

The lab-maintained viewer checkout should use:

- `origin`
  - `RPM-lab-UMN/lerobot-dataset-visualizer`
- `upstream`
  - `huggingface/lerobot-dataset-visualizer`

If someone only needs to use the viewer, cloning the lab fork is enough. The `upstream` remote is only needed when maintaining the fork.

## Next Step

Once this workspace layout exists, move on to:

- [System Setup](./system-setup.md) if the machine itself is not prepared yet
- [Python Environment Setup](./python-env-setup.md)
- [Viewer Setup](./viewer-setup.md) if this account needs local dataset viewing
- [Personal Account Setup](./personal-account-setup.md) if you are following the personal-account path
- [Lab Machine Quick Start](./lab-machine-quick-start.md) once the shared account is provisioned
