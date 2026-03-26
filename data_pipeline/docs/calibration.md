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
- Static scene cameras are solved directly in the `world` frame from a measured `T_world_board`.


## Files

Default local files:

- `data_pipeline/configs/sensors.local.yaml`
- `data_pipeline/configs/calibration_poses.local.json`
- `data_pipeline/configs/world_board.local.json`
- `data_pipeline/configs/calibration.local.json`


## 1. Fill In The Sensors File

Start from:

```bash
cp data_pipeline/configs/sensors.example.yaml data_pipeline/configs/sensors.local.yaml
```

Fill in the real serial numbers and role metadata for the cameras you want to calibrate.


## 2. Measure `T_world_board` For Static Scene Cameras

Use a rigid probe mounted at a known offset from the tool flange, touch the four board corners, and record the TCP poses.

Then compute the board transform:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python data_pipeline/compute_world_board.py \
  --top-left X Y Z RX RY RZ \
  --top-right X Y Z RX RY RZ \
  --bottom-right X Y Z RX RY RZ \
  --bottom-left X Y Z RX RY RZ \
  --flange-to-contact-m 0.0 0.0 0.162
```

This writes:

- `data_pipeline/configs/world_board.local.json`

Adjust `--flange-to-contact-m` if your contact point is not 162 mm along flange Z.


## 3. Record Wrist Calibration Poses

For wrist cameras, record a set of diverse robot poses while the board is visible.

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


## 4. Run Calibration

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
- if any selected role is a static scene camera, it requires `world_board.local.json`
- the runner reads factory intrinsics from the RealSense SDK and solves:
  - wrist cameras as hand-eye calibration
  - scene cameras as direct `T_world_camera`

This writes:

- `data_pipeline/configs/calibration.local.json`


## 5. Validate With Click-Point Inspection

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
- calibrated world-frame point
- current TCP pose for wrist cameras


## 6. Recording Integration

`record_episode.py` automatically snapshots the current calibration results into `episode_manifest.json` when:

- `data_pipeline/configs/calibration.local.json` exists
- or `--calibration-file` is provided explicitly

That snapshot is stored per sensor under:

- `sensors.devices[].calibration_snapshot`

and the manifest also records:

- `sensors.sensors_file`
- `sensors.calibration_results_file`

So raw episodes stay self-describing even if local calibration files change later.
