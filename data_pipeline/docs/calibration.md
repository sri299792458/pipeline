# Calibration

This is the V2 camera-calibration workflow for the pipeline.

The calibration system has two parts:

- `data_pipeline/configs/sensors.local.yaml`
  - local rig identity and canonical role mapping
- `data_pipeline/configs/calibration.local.json`
  - solved camera intrinsics and extrinsics / hand-eye results

The sensors file tells the pipeline which physical device is which role.
The calibration results file tells the pipeline where that camera is.


## Current Assumptions

- RealSense cameras are calibrated with a ChArUco board.
- Wrist-camera hand-eye calibration uses UR `getActualTCPPose()`.
- During wrist calibration, the active UR TCP must be the tool flange.
- Static scene cameras are solved automatically in the reference wrist arm base frame from shared board observations.


## Files

Default local files:

- `data_pipeline/configs/sensors.local.yaml`
- `data_pipeline/configs/calibration_poses.local.json`
- `data_pipeline/configs/calibration.local.json`


## 1. Fill In The Sensors File

Start from:

```bash
cp data_pipeline/configs/sensors.example.yaml data_pipeline/configs/sensors.local.yaml
```

Fill in the real serial numbers and role metadata for the cameras you want to calibrate.


## 2. Record Wrist Calibration Poses

Record a set of diverse robot poses while the board is visible to:

- the wrist camera that will anchor the calibration frame
- any static scene camera you want to calibrate in that same reference frame

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python data_pipeline/record_calibration_poses.py --active-arms lightning
```

Controls:

- `r`
  - record current pose
- `d`
  - delete last pose
- `l`
  - list poses
- `q`
  - save and quit

This writes:

- `data_pipeline/configs/calibration_poses.local.json`


## 3. Run Calibration

Calibrate all roles found in the sensors file:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python data_pipeline/calibrate_rig.py \
  --sensors-file data_pipeline/configs/sensors.local.yaml
```

To calibrate only selected camera roles:

```bash
python data_pipeline/calibrate_rig.py \
  --sensors-file data_pipeline/configs/sensors.local.yaml \
  --camera-role lightning_wrist_1 \
  --camera-role scene_1
```

Notes:

- if any selected role is a wrist camera, `calibrate_rig.py` requires `calibration_poses.local.json`
- if any selected role is a static scene camera, the runner also needs a wrist camera reference:
  - if a wrist role is already selected, it uses that
  - otherwise it auto-picks a configured wrist role from the sensors file
  - if both `lightning_wrist_1` and `thunder_wrist_1` are available and no explicit `--reference-wrist-role` is given, the default is `lightning_wrist_1`
    - mnemonic: lightning travels before thunder
- the runner reads factory intrinsics from the RealSense SDK and solves:
  - wrist cameras as hand-eye calibration
  - scene cameras automatically from the wrist-calibrated board observations
- scene-camera extrinsics are expressed in the selected reference wrist arm base frame, for example:
  - `lightning_base`
  - `thunder_base`

This writes:

- `data_pipeline/configs/calibration.local.json`


## 4. Validate With Click-Point Inspection

Static scene camera example:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python data_pipeline/validate_calibration_click.py \
  --camera-role scene_1
```

Wrist camera example:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python data_pipeline/validate_calibration_click.py \
  --camera-role lightning_wrist_1
```

Click a pixel in the RGB image window. The tool prints:

- depth
- camera-frame point
- calibrated reference-frame point
- current TCP pose for wrist cameras


## 5. Recording Integration

`record_episode.py` automatically snapshots the current calibration results into `episode_manifest.json` when:

- `data_pipeline/configs/calibration.local.json` exists
- or `--calibration-file` is provided explicitly

That snapshot is stored per sensor under:

- `sensors.devices[].calibration_snapshot`

and the manifest also records:

- `sensors.sensors_file`
- `sensors.calibration_results_file`

So raw episodes stay self-describing even if local calibration files change later.
