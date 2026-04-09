# Current Lightning + GelSight Runbook

This is the exact command sequence currently validated on this machine for:

- `lightning` only
- RealSense wrist + scene cameras
- one GelSight on the Lightning gripper
- raw bag recording
- LeRobot conversion
- LeRobot browser visualizer

It is intentionally concrete, not general.


## Current Hardware Assumptions

- Lightning arm is powered and reachable.
- Foot pedal is wired through the Lightning Spark path.
- Current active RealSense pair:
  - wrist: D405 `130322273305`
  - scene: D455 `213622251272`
- Current GelSight:
  - serial: `28D8PXEC`
  - device path:
    - `/dev/v4l/by-id/usb-Arducam_Technology_Co.__Ltd._GelSight_Mini_R0B_28D8-PXEC_28D8PXEC-video-index0`

Current published dataset identifiers for this embodiment:

- `dataset_id=spark_multisensor_lightning_tactile_v1`
- `profile=multisensor_20hz`
- `active_arms=lightning`


## 0. Shell Shortcut

The shell alias `spark` is expected to:

- `cd /home/srinivas/Desktop/pipeline`
- `cd ~/spark-workspace/spark-data-collection`
- source `/opt/ros/jazzy/setup.bash`
- activate `.venv`

If needed:

```bash
source ~/.bashrc
spark
```


## 1. Start SPARK Devices

Terminal 1:

```bash
spark
python TeleopSoftware/launch_devs.py
```


## 2. Start Teleop GUI / Robot Runtime

Terminal 2:

```bash
spark
python TeleopSoftware/launch.py
```

Notes:

- keep the foot pedal unpressed until you are ready to execute the demo
- if needed, enable remote control on the robot


## 3. Start RealSense Contract Publishers

Terminal 3:

```bash
spark
ros2 launch data_pipeline/launch/realsense_contract.launch.py \
  camera_specs:='lightning;wrist_1;130322273305;640,480,30;640,480,30|world;scene_1;213622251272;640,480,30;640,480,30'
```

Note:

- the launch wrapper now runs the RealSense bridge under system ROS Python and the local `build/librealsense-v2.54.2/Release` runtime; it does not rely on `.venv` for camera capture


## 4. Start GelSight Contract Publisher

Terminal 4:

```bash
spark
ros2 launch data_pipeline/launch/gelsight_contract.launch.py \
  sensor_specs:='lightning;finger_left;/dev/v4l/by-id/usb-Arducam_Technology_Co.__Ltd._GelSight_Mini_R0B_28D8-PXEC_28D8PXEC-video-index0'
```


## 5. Preflight Topic Checks

Terminal 5:

```bash
spark
ros2 topic hz /spark/lightning/robot/joint_state
ros2 topic hz /spark/session/teleop_active
ros2 topic hz /spark/cameras/lightning/wrist_1/color/image_raw
ros2 topic hz /spark/cameras/world/scene_1/color/image_raw
ros2 topic hz /spark/tactile/lightning/finger_left/color/image_raw
```

Expected:

- Lightning robot state is live
- teleop activity is live
- wrist and scene RGB are live
- GelSight left RGB is live


## 6. Recorder Dry-Run

Terminal 6:

```bash
spark
/usr/bin/python3 data_pipeline/record_episode.py \
  --task-name pick_place \
  --language-instruction "pick up the object and place it in the target area" \
  --operator srinivas \
  --active-arms lightning \
  --sensors-file data_pipeline/configs/sensors.local.yaml \
  --dry-run
```

Expected:

- `active_arms=lightning`
- `profile_name=multisensor_20hz`
- no `Missing required topics` error


## 7. Real Recording

Once the dry-run passes, start the real recorder.

Terminal 6:

```bash
spark
/usr/bin/python3 data_pipeline/record_episode.py \
  --task-name pick_place \
  --language-instruction "pick up the object and place it in the target area" \
  --operator srinivas \
  --active-arms lightning \
  --sensors-file data_pipeline/configs/sensors.local.yaml
```

Then:

1. leave the recorder running
2. click `Run Spark`
3. use the foot pedal
4. perform the demo
5. stop the recorder with `Ctrl-C`


## 8. Convert The New Raw Episode

Find the newest episode id:

```bash
cd ~/spark-workspace/spark-data-collection
ls -td raw_episodes/* | head -n 3
```

Convert:

```bash
source /opt/ros/jazzy/setup.bash
source ~/spark-workspace/spark-data-collection/.venv/bin/activate
python ~/spark-workspace/spark-data-collection/data_pipeline/convert_episode_bag_to_lerobot.py \
  ~/spark-workspace/spark-data-collection/raw_episodes/<episode_id> \
  --published-dataset-id spark_multisensor_lightning_tactile_v1 \
  --published-root ~/spark-workspace/spark-data-collection/published
```


## 9. Inspect The Converted Dataset In The Browser Viewer

The current local viewer setup uses the official `lerobot-dataset-visualizer` checkout.

If the server is not already running:

```bash
cd ~/spark-workspace/lerobot-dataset-visualizer
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy -u NO_PROXY -u no_proxy \
NEXT_PUBLIC_DATASET_URL=http://localhost:3000/datasets \
DATASET_URL=http://localhost:3000/datasets \
REPO_ID=local/spark_multisensor_lightning_tactile_v1 \
EPISODES=0 \
~/.bun/bin/bun run build
```

```bash
cd ~/spark-workspace/lerobot-dataset-visualizer
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy -u NO_PROXY -u no_proxy \
NEXT_PUBLIC_DATASET_URL=http://localhost:3000/datasets \
DATASET_URL=http://localhost:3000/datasets \
REPO_ID=local/spark_multisensor_lightning_tactile_v1 \
EPISODES=0 \
~/.bun/bin/bun start
```

Open:

- `http://10.33.55.65:3000/local/spark_multisensor_lightning_tactile_v1/episode_0`

Important:

- use `10.33.55.65`, not `localhost`, in this IDE/browser environment
- the browser viewer fix for local datasets lives in the nested `lerobot-dataset-visualizer` repo


## Current Known Caveats

- The first real recorded episode had a bad Lightning gripper calibration and should not be treated as the final reference episode for gripper behavior.
- The current RealSense scene camera in this validated runbook is the D455, not the L515.
- Only one GelSight is currently wired into this validated runbook.
- Optional viewer requests for:
  - `sarm_progress.parquet`
  - `srm_progress.parquet`
  may return `404`; this is harmless for the current dataset.
