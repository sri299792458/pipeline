# Workspace Setup

This page defines the exact repository layout a new lab member should create on a fresh machine.

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

## Current Code Assumptions

The pipeline currently assumes these sibling paths relative to `spark-data-collection/`:

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

- [system-setup.md](./system-setup.md)
- [viewer-setup.md](./viewer-setup.md) if the user needs local dataset viewing
- [python-env-setup.md](./python-env-setup.md)
- RealSense runtime setup
- hardware bring-up
