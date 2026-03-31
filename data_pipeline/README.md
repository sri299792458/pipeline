# Data Pipeline

This directory contains the raw-capture and LeRobot conversion stack.

The current implementation contract lives in [V2_SPEC.md](./V2_SPEC.md). The old [V1_SPEC.md](./V1_SPEC.md) file is archive-only. The running implementation log lives in [notes/running-notes.md](./notes/running-notes.md).

V2 is the authoritative target contract. The codebase is still mid-migration toward it.

The raw bag storage decision lives in [docs/raw-storage.md](./docs/raw-storage.md).

The offline archive-bag design lives in [docs/archive-bag.md](./docs/archive-bag.md).

For the expected multi-repo workspace layout on a fresh machine, use [docs/workspace-setup.md](./docs/workspace-setup.md).

For the required Ubuntu and ROS Jazzy packages on a fresh machine, use [docs/system-setup.md](./docs/system-setup.md).

For a generic bring-up sequence, use [docs/hardware-bringup.md](./docs/hardware-bringup.md).

For the current exact Lightning-only command sequence on this machine, use [docs/current-lightning-gelsight-runbook.md](./docs/current-lightning-gelsight-runbook.md).

The current reference frontend is the Qt implementation:

```bash
source .venv/bin/activate
pip install -r data_pipeline/requirements-operator-console.txt
python data_pipeline/operator_console_qt.py
```

On Ubuntu/X11, the Qt frontend also needs the system package:

```bash
sudo apt-get install -y libxcb-cursor0
```

## Current Scope

The current V2-direction path is in place:

- stable `/spark/...` topic contract for robot, camera, tactile, and teleop-activity streams
- raw episode recording as one rosbag per demo
- raw-to-LeRobot conversion for the current bimanual `multisensor_20hz` profile
- dummy-data eval path
- direct `pyrealsense2` ROS2 publisher for RealSense RGB+D topics
- GelSight ROS2 bridge process for the declared tactile topics

The remaining work is live hardware validation with the actual full sensor set attached.


## Calibration

The pipeline now has a first-class camera calibration workflow for:

- wrist-camera hand-eye calibration
- static scene-camera extrinsics
- click-point validation

Use:

- [docs/calibration.md](./docs/calibration.md)

The local split is:

- `sensors.local.yaml`
  - device identity and canonical roles
- `calibration.local.json`
  - solved calibration results


## Embodiments

The accepted direction is:

- raw recording should work with `lightning` only, `thunder` only, or both arms
- published LeRobot datasets should stay embodiment-specific
- do not zero-fill a missing arm into the bimanual schema by default

So the intended published split is:

- `multisensor_20hz`
  - bimanual
- `multisensor_20hz_lightning`
  - Lightning-only
- `multisensor_20hz_thunder`
  - Thunder-only

Current implementation note:

- the shipped default config file remains the bimanual `multisensor_20hz.yaml`
- raw recording now requires explicit `--active-arms` and stamps the matching published profile into the manifest
- conversion defaults to the manifest-selected profile when `--profile` is omitted


## Runtime Split

Live ROS capture should use system ROS Jazzy and `/usr/bin/python3`. The RealSense launch wrapper now starts system Python with ROS sourced and injects the local `build/librealsense-v2.54.2/Release` runtime through `PYTHONPATH` and `LD_LIBRARY_PATH`.

Offline conversion and LeRobot export should use the local `.venv` created by:

```bash
./data_pipeline/setup_converter_env.sh
```


## One-Time Setup

### Offline converter environment

```bash
./data_pipeline/setup_converter_env.sh
source .venv/bin/activate
```

## Launching The Sensor Contract

The current intended RealSense path is the direct SDK bridge, backed by a local official `librealsense v2.54.2` build:

```bash
source /opt/ros/jazzy/setup.bash
./data_pipeline/setup_realsense_contract_runtime.sh
ros2 launch data_pipeline/launch/realsense_contract.launch.py \
  camera_specs:='lightning;wrist_1;<WRIST_SERIAL>;640,480,30;640,480,30|world;scene_1;<SCENE_SERIAL>;640,480,30;640,480,30'
```

That setup script builds the local `pyrealsense2` binding for system ROS Python, not for `.venv`.

This bridge stamps `Image.header.stamp` with host ROS time immediately after `wait_for_frames()` returns, which matches the V2 topic contract directly. Older bags that include official RealSense metadata topics are still supported by the converter.

See [docs/hardware-bringup.md](./docs/hardware-bringup.md) for the exact bring-up sequence.

To launch the GelSight contract publishers:

```bash
/usr/bin/python3 data_pipeline/gelsight_bridge.py --arm lightning --finger-slot finger_left --device-path /dev/v4l/by-id/<LEFT_GELSIGHT>
/usr/bin/python3 data_pipeline/gelsight_bridge.py --arm lightning --finger-slot finger_right --device-path /dev/v4l/by-id/<RIGHT_GELSIGHT>
```

Or with the existing launch wrapper:

```bash
ros2 launch data_pipeline/launch/gelsight_contract.launch.py \
  sensor_specs:='lightning;finger_left;/dev/v4l/by-id/<LEFT_GELSIGHT>|lightning;finger_right;/dev/v4l/by-id/<RIGHT_GELSIGHT>'
```

The arm-side `/spark/{arm}/...` robot topics still come from the Teleop runtime in [TeleopSoftware](../TeleopSoftware/).


## Recording One Episode

Dry-run the topic selection first:

```bash
/usr/bin/python3 data_pipeline/record_episode.py \
  --task-name pick_place \
  --language-instruction "pick up the object and place it in the target area" \
  --operator <operator_name> \
  --active-arms <lightning|thunder|lightning,thunder> \
  --sensors-file data_pipeline/configs/sensors.example.yaml \
  --dry-run
```

Record one episode:

```bash
/usr/bin/python3 data_pipeline/record_episode.py \
  --task-name pick_place \
  --language-instruction "pick up the object and place it in the target area" \
  --operator <operator_name> \
  --active-arms <lightning|thunder|lightning,thunder> \
  --sensors-file data_pipeline/configs/sensors.example.yaml
```

Each episode is written under `raw_episodes/<episode_id>/` with:

- `bag/`
- `episode_manifest.json`
- `notes.md`

If `data_pipeline/configs/calibration.local.json` exists, the recorder also snapshots the current solved calibration into the sensor entries of `episode_manifest.json`.

`episode_manifest.json` is now the single resolved per-episode snapshot. The reusable profile stays in YAML, and the manifest carries the resolved episode-specific sections:

- `episode`
- `session` when the run came from an operator-console session plan
- `profile`
- `capture`
- `sensors.devices`
- `recorded_topics`
- `provenance`

Raw bag storage now defaults to:

- `mcap`

Capture bags are now preserved as untrimmed plain MCAP artifacts. Head/tail
trim and lossless visual compression belong to the later offline archive step,
not to `record_episode.py`.

`--active-arms` is now explicit for recording runs. The recorder uses that value to select:

- `multisensor_20hz`
  - if both arms are active
- `multisensor_20hz_lightning`
  - if only Lightning is active
- `multisensor_20hz_thunder`
  - if only Thunder is active


## Offline Conversion

Convert one episode:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python data_pipeline/convert_episode_bag_to_lerobot.py \
  raw_episodes/<episode_id> \
  --published-dataset-id <published_dataset_folder_name> \
  --published-root published
```

If the selected profile declares `published_depth`, the converter also writes a lossless depth sidecar under:

- `published/<dataset_id>/depth/`
- `published/<dataset_id>/meta/depth_info.json`

## Offline Archive

Create a storage-optimized archive bag from one preserved capture bag:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python data_pipeline/archive_episode.py raw_episodes/<episode_id>
```

The archive step:

- keeps the source capture bag unchanged
- computes head/tail trim offline
- writes lossless image-transport topics:
  - RGB/tactile as `/compressed` with PNG
  - depth as `/compressedDepth` with PNG
- writes the final archive bag as MCAP with zstd chunk compression
- records provenance in `raw_episodes/<episode_id>/archive/archive_manifest.json`

## Standing Eval

Run the no-hardware eval path:

```bash
source .venv/bin/activate
python data_pipeline/validate_eval_set.py \
  --work-root /tmp/pipeline_eval \
  --clean
```

Once a real raw episode exists, include it:

```bash
python data_pipeline/validate_eval_set.py \
  --work-root /tmp/pipeline_eval \
  --real-episode raw_episodes/<episode_id> \
  --require-real \
  --clean
```


## Sensor Metadata Overrides

`record_episode.py` can merge operator-supplied sensor metadata into the manifest with `--sensors-file`.

Start from [configs/sensors.example.yaml](./configs/sensors.example.yaml) and replace the placeholder values with the real inventory values for the capture rig.

The important rule is:

- raw manifests should preserve unambiguous sensor identity
- published dataset field names can be remapped later

So the override file should record not just serials, but also:

- a stable `sensor_id`
- `attached_to` (`lightning`, `thunder`, or `world`)
- `mount_site`
- `calibration_ref`

That keeps the raw episodes convertible even if the naming convention changes later.
