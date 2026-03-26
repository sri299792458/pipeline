# Hardware Bring-Up

This is the step-by-step sequence for the first real capture run with the current V2 pipeline.

For the current known-good Lightning-only command sequence on this machine, use [current-lightning-gelsight-runbook.md](./current-lightning-gelsight-runbook.md).

Use separate terminals. For ROS-facing processes, prefer system ROS Jazzy and `/usr/bin/python3`, not Conda Python.


## Embodiment Decision

Before you record, decide which arms and sensors this session will use:

- `lightning` only
- `thunder` only
- `lightning` + `thunder`

Before you convert, choose the published dataset folder this session should append into.

Recommended published dataset naming:

- Lightning-only:
  - `spark_multisensor_lightning_v1`
- Lightning-only with published tactile:
  - `spark_multisensor_lightning_tactile_v1`
- Thunder-only:
  - `spark_multisensor_thunder_v1`
- Bimanual:
  - `spark_multisensor_bimanual_v1`

Why:

- raw bags may be recorded with one active arm or both
- published LeRobot datasets should stay profile-homogeneous
- single-arm and bimanual episodes should not be appended into the same published dataset
- episodes with different published image fields, such as tactile vs no tactile, should not be appended into the same `dataset_id`

Current implementation note:

- the shipped default config file `data_pipeline/configs/multisensor_20hz.yaml` is still the bimanual profile
- the recorder now requires explicit `--active-arms` and stamps the matching published profile into the raw manifest
- the converter now defaults to the manifest-selected profile when `--profile` is omitted


## 0. One-Time Setup

Run these once from the repository root:

```bash
source /opt/ros/jazzy/setup.bash
./data_pipeline/setup_converter_env.sh
./data_pipeline/setup_realsense_contract_runtime.sh
```


## 1. Discover Device IDs

### RealSense serial numbers

Then read the RealSense USB metadata directly:

```bash
for path in /sys/bus/usb/devices/*; do
  [ -f "$path/idVendor" ] || continue
  vendor=$(cat "$path/idVendor" 2>/dev/null)
  if [ "$vendor" = "8086" ]; then
    [ -f "$path/product" ] && echo "product=$(cat "$path/product")"
    [ -f "$path/serial" ] && echo "serial=$(cat "$path/serial")"
    echo "---"
  fi
done
```

Record the two serials you want to use as:

- `WRIST_SERIAL`
- `SCENE_SERIAL`

Note:

- the local `librealsense v2.54.2` runtime may report the L515 serial in shortened lowercase hex form such as `f1380660`
- the bridge now normalizes the raw USB serial and the runtime serial, so either `00000000F1380660` or `f1380660` is acceptable at launch

### GelSight device paths

List V4L camera symlinks and device names:

```bash
ls -l /dev/v4l/by-id
v4l2-ctl --list-devices
```

If two GelSight devices are attached, record the two paths you want to use as:

- `LEFT_GELSIGHT_DEV`
- `RIGHT_GELSIGHT_DEV`

If only one GelSight device is attached, record just one path and launch a single tactile bridge in step 6.

If the names are ambiguous, unplug one GelSight, list again, then plug it back in and repeat.


## 2. Fill In Sensor Metadata

Copy the example file and replace the placeholder serials/calibration refs:

```bash
cp data_pipeline/configs/sensors.example.yaml data_pipeline/configs/sensors.local.yaml
```

Edit `data_pipeline/configs/sensors.local.yaml` and fill in the real values you know.

Notes:

- RealSense serial numbers are also inferred from the running node parameters.
- GelSight serial numbers are not inferred automatically, so put the real values in this file if you have them.
- Fill in `sensor_id`, `attached_to`, and `mount_site` as well. Those fields are what make the raw episode remappable later if published naming changes.


## 2.5. Calibrate Cameras

If you want solved camera geometry in the raw manifests, run the calibration workflow before recording.

Use:

- [calibration.md](./calibration.md)

The important output files are:

- `data_pipeline/configs/world_board.local.json`
- `data_pipeline/configs/calibration_poses.local.json`
- `data_pipeline/configs/calibration.local.json`

`record_episode.py` will automatically snapshot `calibration.local.json` into each raw manifest when that file exists.


## 3. Start The Teleop Input Devices

If you are using SPARK, SpaceMouse, or VR inputs, start the legacy device launcher:

```bash
source /opt/ros/jazzy/setup.bash
.venv/bin/python TeleopSoftware/launch_devs.py
```

Leave this running.


## 4. Start The Teleop GUI / Robot Runtime

In a new terminal:

```bash
source /opt/ros/jazzy/setup.bash
.venv/bin/python TeleopSoftware/launch.py
```

Use the GUI to connect to the UR arms and bring the system into the control mode you want to record.

Notes:

- The current local Teleop bring-up path still uses `.venv` because that environment contains the Teleop Python dependencies such as `ur_rtde`.
- If the GUI logs `Please enable remote control on the robot!`, the dashboard connection succeeded but UR RTDE control was refused by the robot-side remote-control setting.

Expected robot topics come from this process:

- `/spark/lightning/robot/joint_state`
- `/spark/lightning/robot/eef_pose`
- `/spark/lightning/robot/tcp_wrench`
- `/spark/lightning/robot/gripper_state`
- `/spark/lightning/teleop/cmd_joint_state`
- `/spark/lightning/teleop/cmd_gripper_state`
- `/spark/thunder/robot/joint_state`
- `/spark/thunder/robot/eef_pose`
- `/spark/thunder/robot/tcp_wrench`
- `/spark/thunder/robot/gripper_state`
- `/spark/thunder/teleop/cmd_joint_state`
- `/spark/thunder/teleop/cmd_gripper_state`


## 5. Start The RealSense Contract Publishers

In a new terminal:

```bash
source /opt/ros/jazzy/setup.bash
ros2 launch data_pipeline/launch/realsense_contract.launch.py \
  camera_specs:='lightning;wrist_1;<WRIST_SERIAL>;640,480,30;640,480,30|world;scene_1;<SCENE_SERIAL>;640,480,30;640,480,30'
```

Replace the placeholders with the serials from step 1.

Expected topics:

- `/spark/cameras/lightning/wrist_1/color/image_raw`
- `/spark/cameras/lightning/wrist_1/depth/image_rect_raw`
- `/spark/cameras/world/scene_1/color/image_raw`
- `/spark/cameras/world/scene_1/depth/image_rect_raw`

This bridge uses `pyrealsense2` directly and stamps both color and depth images with host ROS time immediately after `wait_for_frames()` returns.
The setup script builds and validates the local official `librealsense v2.54.2` runtime for system ROS Python, which is currently required for stable L515 support on this host.


## 6. Start The GelSight Contract Publishers

If you are using two tactile sensors, start them in another terminal:

```bash
source /opt/ros/jazzy/setup.bash
ros2 launch data_pipeline/launch/gelsight_contract.launch.py \
  sensor_specs:='lightning;finger_left;<LEFT_GELSIGHT_DEV>|lightning;finger_right;<RIGHT_GELSIGHT_DEV>'
```

If you are using only one tactile sensor, launch only one side:

```bash
source /opt/ros/jazzy/setup.bash
ros2 launch data_pipeline/launch/gelsight_contract.launch.py \
  sensor_specs:='lightning;finger_left;<LEFT_GELSIGHT_DEV>'
```

Expected topics when both are present:

- `/spark/tactile/lightning/finger_left/color/image_raw`
- `/spark/tactile/lightning/finger_right/color/image_raw`

If only one side is present, you should see only the enabled topic. If tactile is not ready yet, skip this step. The profile allows optional tactile fields, but tactile and non-tactile episodes should still use separate published `dataset_id`s so the LeRobot feature schema stays homogeneous.


## 7. Preflight Check The Topic Surface

In a new terminal:

```bash
source /opt/ros/jazzy/setup.bash
ros2 topic list | rg '^/spark/'
```

Then spot-check a few topic rates:

```bash
ros2 topic hz /spark/cameras/lightning/wrist_1/color/image_raw
ros2 topic hz /spark/cameras/world/scene_1/color/image_raw
ros2 topic hz /spark/lightning/robot/joint_state
ros2 topic hz /spark/thunder/robot/joint_state
ros2 topic hz /spark/session/teleop_active
```

If tactile is enabled, also check:

```bash
ros2 topic hz /spark/tactile/lightning/finger_left/color/image_raw
ros2 topic hz /spark/tactile/lightning/finger_right/color/image_raw
```

Before recording, run the recorder dry-run:

```bash
source /opt/ros/jazzy/setup.bash
/usr/bin/python3 data_pipeline/record_episode.py \
  --task-name pick_place \
  --language-instruction "pick up the object and place it in the target area" \
  --operator <operator_name> \
  --active-arms <lightning|thunder|lightning,thunder> \
  --sensors-file data_pipeline/configs/sensors.local.yaml \
  --dry-run
```

This should print the selected topic list and should not fail with `Missing required topics`.

The dry-run output now also prints:

- `active_arms=...`
- `mapping_profile=...`
- `profile_path=...`
- `language_instruction=...`


## 8. Record One Short Real Episode

Do one short smoke-test recording before collecting anything longer:

```bash
source /opt/ros/jazzy/setup.bash
/usr/bin/python3 data_pipeline/record_episode.py \
  --task-name pick_place \
  --language-instruction "pick up the object and place it in the target area" \
  --operator <operator_name> \
  --active-arms <lightning|thunder|lightning,thunder> \
  --sensors-file data_pipeline/configs/sensors.local.yaml
```

Press `Ctrl+C` to stop after a short run.

The output episode directory will be:

```text
raw_episodes/<episode_id>/
```

with:

- `bag/`
- `episode_manifest.json`
- `notes.md`


## 9. Inspect The Raw Episode

Check the bag:

```bash
source /opt/ros/jazzy/setup.bash
ros2 bag info raw_episodes/<episode_id>/bag
```

Check the manifest:

```bash
sed -n '1,240p' raw_episodes/<episode_id>/episode_manifest.json
```

What to look for:

- both RealSense serials are present
- `recorded_topics` looks complete for the chosen profile
- `capture.record_exit_code` is `0`
- `capture.start_time_ns` and `capture.end_time_ns` are populated
- `sensors.devices` entries look reasonable


## 10. Convert The Episode To LeRobot

In a converter terminal:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python data_pipeline/convert_episode_bag_to_lerobot.py \
  raw_episodes/<episode_id> \
  --published-root published
```

Expected output includes:

- `status=pass` or `status=truncated_tail`
- `published_frames=<n>`
- `artifacts=published/<dataset_id>/meta/spark_conversion/<episode_id>`


## 11. Validate The Real Episode In The Standing Eval Path

```bash
source .venv/bin/activate
python data_pipeline/validate_eval_set.py \
  --work-root /tmp/pipeline_eval_real \
  --real-episode raw_episodes/<episode_id> \
  --require-real \
  --clean
```

This should leave a report at:

```text
/tmp/pipeline_eval_real/reports/evaluation_summary.json
```


## 12. If Something Fails

Use these checks first:

```bash
ros2 topic list | rg '^/spark/'
ros2 topic echo --once /spark/lightning/robot/joint_state
ros2 topic echo --once /spark/cameras/lightning/wrist_1/color/image_raw
ros2 topic echo --once /spark/cameras/world/scene_1/color/image_raw
ros2 param dump /spark/cameras/lightning/wrist_1
ros2 param dump /spark/cameras/world/scene_1
```

Common failure boundaries:

- missing required `/spark/...` topics means one of the runtime processes is not up
- RealSense failures with the official node usually mean:
  - the wrong serial number was used,
  - the upstream wrapper is not discovering that camera model on this host, or
  - the node is up but not publishing the expected image topics
- GelSight launch failures usually mean the wrong `/dev/v4l/by-id/...` path or camera access issues
- converter failures after a good bag usually point to timestamp/rate/alignment issues that should be investigated from the saved diagnostics
