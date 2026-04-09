# Data Pipeline

This directory contains the raw-capture and LeRobot conversion stack.

For the curated docs entrypoint, start with [docs/setup.md](./docs/setup.md).

For the design section, start with [docs/design-choices.md](./docs/design-choices.md).

For the operations section, start with [docs/operations-and-debugging.md](./docs/operations-and-debugging.md).

To preview the MkDocs site locally:

```bash
pip install -r requirements-docs.txt
mkdocs serve
```

The default setup path for a collection-only user on the existing collection machine is:

1. [lab-machine-quick-start.md](./docs/lab-machine-quick-start.md)
2. [hardware-bringup.md](./docs/hardware-bringup.md)
3. [first-raw-demo.md](./docs/first-raw-demo.md)
4. [first-published-conversion.md](./docs/first-published-conversion.md)
5. [first-viewer-review.md](./docs/first-viewer-review.md)

If you are using your own Linux account on the same machine, start with:

- [personal-account-setup.md](./docs/personal-account-setup.md)

Supporting setup pages are:

- [personal-account-setup.md](./docs/personal-account-setup.md)
- [workspace-setup.md](./docs/workspace-setup.md)
- [python-env-setup.md](./docs/python-env-setup.md)
- [viewer-setup.md](./docs/viewer-setup.md)
- [system-setup.md](./docs/system-setup.md)

Curated design pages are:

- [design-choices.md](./docs/design-choices.md)
- [system-boundaries.md](./docs/system-boundaries.md)
- [artifact-model.md](./docs/artifact-model.md)
- [episode-manifest-design.md](./docs/episode-manifest-design.md)
- [environment-and-workspace-model.md](./docs/environment-and-workspace-model.md)
- [calibration-design.md](./docs/calibration-design.md)
- [operator-console-design.md](./docs/operator-console-design.md)
- [viewer-integration.md](./docs/viewer-integration.md)
- [sensor-runtime-design.md](./docs/sensor-runtime-design.md)
- [archive-and-compression-strategy.md](./docs/archive-and-compression-strategy.md)
- [topic-contract.md](./docs/topic-contract.md)
- [session-capture-plan.md](./docs/session-capture-plan.md)
- [dataset-mapping.md](./docs/dataset-mapping.md)
- [calibration.md](./docs/calibration.md)

Curated operations and debugging pages are:

- [operations-and-debugging.md](./docs/operations-and-debugging.md)
- [usb-port-and-controller-mapping.md](./docs/usb-port-and-controller-mapping.md)

Internal implementation references still live here:

- [V2_SPEC.md](./V2_SPEC.md)
- [V1_SPEC.md](./V1_SPEC.md) archived
- [notes/running-notes.md](./notes/running-notes.md)
- [docs/internal/raw-storage.md](./docs/internal/raw-storage.md)
- [docs/internal/archive-bag.md](./docs/internal/archive-bag.md)
- [docs/internal/depth-storage.md](./docs/internal/depth-storage.md)
- [docs/internal/operator-console-spec.md](./docs/internal/operator-console-spec.md)
- [docs/internal/raiden-reference-analysis.md](./docs/internal/raiden-reference-analysis.md)
- [docs/internal/teleop-runtime-refactor-spec.md](./docs/internal/teleop-runtime-refactor-spec.md)
- [docs/internal/current-lightning-gelsight-runbook.md](./docs/internal/current-lightning-gelsight-runbook.md)
- [docs/internal/replay.md](./docs/internal/replay.md)

The current reference frontend is the Qt implementation:

```bash
source /opt/ros/jazzy/setup.bash
./data_pipeline/setup_shared_venv.sh
source .venv/bin/activate
python data_pipeline/operator_console_qt.py
```

On Ubuntu/X11, the Qt frontend also needs the system package:

```bash
sudo apt-get install -y libxcb-cursor0
```

## Current Scope

The current system provides:

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

- a user-selected sensors file
  - usually created from [`configs/sensors.example.yaml`](./configs/sensors.example.yaml)
  - device identity and canonical sensor keys
- `calibration.local.json`
  - solved calibration results


## Embodiments

The accepted direction is:

- raw recording should work with `lightning` only, `thunder` only, or both arms
- published LeRobot datasets should stay embodiment-specific
- do not zero-fill a missing arm into a bimanual schema by default
- do not mix different active-arm or sensor layouts into the same `dataset_id`

The pipeline uses one checked-in conversion policy:

- `multisensor_20hz`
  - generic 20 Hz conversion policy

Current implementation note:

- raw recording requires explicit `--active-arms`
- the recorder uses the generic `multisensor_20hz.yaml` policy and derives the effective topic set from:
  - the requested active arms
  - the enabled session sensors
- conversion uses the same generic policy and derives the effective published schema from:
  - the manifest active-arm set
  - the `sensor_key` values under `sensors.devices`
- `dataset_id` remains the place where you keep embodiment-specific or rig-specific published datasets separate


## Runtime Split

Live ROS capture should use system ROS Jazzy and `/usr/bin/python3`. The RealSense launch wrapper now starts system Python with ROS sourced and injects the local `build/librealsense-v2.54.2/Release` runtime through `PYTHONPATH` and `LD_LIBRARY_PATH`.

Offline conversion and LeRobot export should use the local `.venv` created by:

```bash
./data_pipeline/setup_shared_venv.sh
```


## One-Time Setup

### Offline converter environment

```bash
./data_pipeline/setup_shared_venv.sh
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

This bridge stamps `Image.header.stamp` with host ROS time immediately after
`wait_for_frames()` returns, which matches the current topic contract directly.

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

For RealSense sensors, the manifest also snapshots per-episode camera metadata when the bridge exposes it:

- `device_type`
- `firmware_version`
- stream profiles
- stream intrinsics
- `depth_scale_meters_per_unit`

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
  - as the generic conversion policy

The actual recorded topic set is derived from:

- the requested active arms
- the enabled session sensors


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

The published dataset also keeps a per-episode source snapshot under:

- `published/<dataset_id>/meta/spark_source/<episode_id>/episode_manifest.json`
- `published/<dataset_id>/meta/spark_source/<episode_id>/notes.md`

`meta/depth_info.json` is only the dataset-level index for the depth sidecar layout. The copied source manifest remains the canonical place for per-sensor metadata such as RealSense intrinsics and `depth_scale_meters_per_unit`.

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

- the canonical sensor key as the YAML key

That keeps the raw episodes convertible without inventing a second naming layer on top of the topic contract.
