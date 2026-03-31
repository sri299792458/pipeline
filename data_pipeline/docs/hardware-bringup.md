# Hardware Bring-Up

This page is the normal bring-up flow for a new user on a fresh machine.

The goal is simple:

- get the hardware into a healthy operator-console state
- confirm the expected `/spark/...` topic surface exists
- stop before longer data collection work

For the current exact Lightning-only command sequence validated on this machine,
use [current-lightning-gelsight-runbook.md](./current-lightning-gelsight-runbook.md).
That page is intentionally concrete and machine-specific. This page is the
general bring-up contract.


## Before You Start

Finish these setup pages first:

- [workspace-setup.md](./workspace-setup.md)
- [system-setup.md](./system-setup.md)
- [python-env-setup.md](./python-env-setup.md)

Notes:

- this page assumes the shared `.venv` already exists
- this page assumes the pinned local `librealsense v2.54.2` runtime has already
  been prepared
- the viewer is **not** required for hardware bring-up


## 1. Physical Preflight

Before launching anything, check the rig physically:

- the UR arm or arms are powered and reachable on the network
- remote control is enabled on the robot before Teleop bring-up
- the SPARK input device is connected
- the foot pedal is connected and unpressed
- the RealSense cameras you want for this session are attached
- any GelSight devices you plan to record are attached

If you are using multiple RealSense cameras, keep them on the intended USB
controller layout. Do not assume that any two convenient ports are equivalent.


## 2. Prepare `sensors.local.yaml`

If you do not already have a local sensors file, create it:

```bash
cp data_pipeline/configs/sensors.example.yaml \
  data_pipeline/configs/sensors.local.yaml
```

Then edit:

- [sensors.local.yaml](/home/srinivas/Desktop/pipeline/data_pipeline/configs/sensors.local.yaml)

Fill in the metadata you already know:

- the sensor key itself as the YAML key
- `serial_number`
- `model`
- `calibration_ref`

Important:

- device discovery can help with live identifiers
- it does **not** replace the sensors file as the inventory record
- this file is the local hardware inventory and serial-to-sensor mapping

If this is a new camera setup or the rig has changed, plan to run:

- [calibration.md](./calibration.md)

before serious data collection.


## 3. Start The Operator Console

From the repository root:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python data_pipeline/operator_console_qt.py
```

This is the normal bring-up surface now. Do not start with a pile of manual
launch commands unless you are debugging.


## 4. Discover Devices

In the operator console:

1. confirm `Sensors File` points at `data_pipeline/configs/sensors.local.yaml`
2. set `Active Arms` for this session
3. click `Discover Devices`

The `Session Devices` table should populate with discovered hardware only.

Expected device kinds include:

- `realsense`
- `gelsight`

Use the table to decide which devices are part of this session:

- check `Record` for devices you want
- leave `Record` unchecked for devices you do not want
- assign the correct sensor key

Typical sensor keys are:

- RealSense:
  - `/spark/cameras/lightning/wrist_1`
  - `/spark/cameras/world/scene_1`
  - `/spark/cameras/world/scene_2`
- GelSight:
  - `/spark/tactile/lightning/finger_left`
  - `/spark/tactile/lightning/finger_right`
  - `/spark/tactile/thunder/finger_left`
  - `/spark/tactile/thunder/finger_right`

The operator should not need to type raw serial numbers or V4L paths into the
main workflow if discovery is working.


## 5. If Discovery Looks Wrong

If a device is missing or ambiguous, use these fallback probes in a separate
terminal.

### RealSense fallback

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

Notes:

- the local `librealsense v2.54.2` runtime may report the L515 serial in
  shortened lowercase hex form such as `f1380660`
- the bridge normalizes the raw USB serial and runtime serial, so either the
  full USB serial or the shortened runtime serial is acceptable

### GelSight fallback

```bash
ls -l /dev/v4l/by-id
v4l2-ctl --list-devices
```

If names are ambiguous, unplug one GelSight, list again, then plug it back in.

After you resolve the identifiers, return to the operator console and click
`Discover Devices` again.


## 6. Start The Session

Once the device table looks correct, click:

- `Start Session`

That starts the current managed bring-up stack:

- `SPARK Devices`
- `Teleop GUI`
- `RealSense`
- `GelSight` if one or more tactile devices are enabled

This is the intended default path. The backend is assembling the same launch
commands you would otherwise type manually:

- `TeleopSoftware/launch_devs.py`
- `TeleopSoftware/launch.py`
- `ros2 launch data_pipeline/launch/realsense_contract.launch.py ...`
- `ros2 launch data_pipeline/launch/gelsight_contract.launch.py ...`


## 7. Finish Robot Connection In The Teleop GUI

After `Start Session`, the Teleop GUI process should appear.

Use that GUI to:

- connect to the active UR arm or arms
- enable the robot-side control mode you intend to record
- verify the gripper path is alive

If the Teleop GUI shows `Please enable remote control on the robot!`, the
dashboard path succeeded but RTDE control was refused by the robot-side
remote-control setting. Enable remote control on the robot, then retry the
Teleop connection.


## 8. Check Health In The Operator Console

The health cards are the primary readiness check.

Healthy bring-up usually looks like:

- `SPARK Devices`: green
- `Teleop GUI`: green
- `RealSense`: green if enabled
- `GelSight`: green if enabled, otherwise off

Some useful interpretations:

- `SPARK Devices live but static`
  - the process is running, but no angle changes were observed yet
- `Teleop running; connect robot in Teleop GUI`
  - the Teleop process exists, but the expected robot topics are not live yet
- `RealSense disabled`
  - no RealSense devices are enabled in the session table
- `GelSight disabled`
  - no GelSight devices are enabled in the session table

At this stage, do **not** trust “the process started” as enough. The point of
the operator console is that readiness is measured from live topics.


## 9. Click `Validate`

After the health cards look right, click:

- `Validate`

The validation output should not complain about missing required topics.

For the enabled devices in this session, the expected topic surface should
include:

- `/spark/session/teleop_active`
- `/spark/<arm>/robot/joint_state`
- `/spark/<arm>/robot/eef_pose`
- `/spark/<arm>/robot/tcp_wrench`
- `/spark/<arm>/robot/gripper_state`
- `/spark/<arm>/teleop/cmd_joint_state`
- `/spark/<arm>/teleop/cmd_gripper_state`
- `/spark/cameras/<attachment>/<camera_slot>/color/image_raw`
- `/spark/cameras/<attachment>/<camera_slot>/depth/image_rect_raw`
- `/spark/tactile/<arm>/<finger_slot>/color/image_raw` when tactile is enabled


## 10. Optional Manual Topic Checks

If you want one more low-level check, use a ROS terminal:

```bash
source /opt/ros/jazzy/setup.bash
ros2 topic list | rg '^/spark/'
```

Then spot-check a few rates:

```bash
ros2 topic hz /spark/session/teleop_active
ros2 topic hz /spark/lightning/robot/joint_state
ros2 topic hz /spark/cameras/lightning/wrist_1/color/image_raw
ros2 topic hz /spark/cameras/world/scene_1/color/image_raw
```

If tactile is enabled, also check:

```bash
ros2 topic hz /spark/tactile/lightning/finger_left/color/image_raw
```

Use these manual probes as confirmation or debugging help, not as the main
operator workflow.


## What Success Looks Like

Hardware bring-up is complete when:

- the correct devices are discovered and assigned roles
- `Start Session` brings up the expected services
- the Teleop GUI is connected to the intended robot or robots
- the required health cards are green
- `Validate` passes without missing-topic errors

At that point, the rig is ready for a first smoke-test recording.

For the current known-good machine-specific record/convert/viewer sequence, use:

- [current-lightning-gelsight-runbook.md](./current-lightning-gelsight-runbook.md)
