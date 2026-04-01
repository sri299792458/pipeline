# Topic Contract V2

## Purpose

This document defines the canonical raw ROS topic contract for the V2 data pipeline.

It is authoritative for:

- topic names
- message types
- timestamp meanings
- semantic conventions

It is not a migration guide for V1.


## Timestamp Vocabulary

V2 keeps the existing timestamp meanings because the clock semantics are unchanged:

- `host_capture_time_v1`
  - Host ROS time assigned immediately after a sensor sample is acquired by the producer.
- `control_tick_time_v1`
  - Host ROS time assigned once for one robot/control update tick and reused for related measured state values.
- `command_issue_time_v1`
  - Host ROS time at which a command is issued toward the robot or gripper.

The following are not canonical dataset-alignment times:

- raw hardware device clocks as the primary alignment clock
- post-processing or post-encoding time
- recorder assembly time after modalities have already been produced


## Naming Rules

### Arms

`{arm}` is one of:

- `lightning`
- `thunder`

### Camera attachment

`{attachment}` is one of:

- `lightning`
- `thunder`
- `world`

### Camera slot

`{camera_slot}` is a canonical semantic slot such as:

- `wrist_1`
- `scene_1`
- `scene_2`
- `scene_3`

The slot naming scheme is extensible. New slots should extend this grammar
mechanically, for example `scene_4`, rather than introducing an alias layer.

Camera slots are 1-based. This is intentional for user-facing consistency with joint numbering such as `joint_1 ... joint_6`.

### Finger slot

`{finger_slot}` is one of:

- `finger_left`
- `finger_right`


## Canonical V2 Topics

| Topic Pattern | Message Type | Semantic Type | Timestamp Meaning | Expected Rate | Usage |
|---|---|---|---|---:|---|
| `/spark/{arm}/robot/joint_state` | `sensor_msgs/msg/JointState` | measured state | `control_tick_time_v1` | 50-200 Hz | published source |
| `/spark/{arm}/robot/eef_pose` | `geometry_msgs/msg/PoseStamped` | measured state | `control_tick_time_v1` | 50-200 Hz | published source |
| `/spark/{arm}/robot/tcp_wrench` | `geometry_msgs/msg/WrenchStamped` | measured state | `control_tick_time_v1` | 50-200 Hz | published source |
| `/spark/{arm}/robot/gripper_state` | `sensor_msgs/msg/JointState` | measured state | `control_tick_time_v1` | 20-100 Hz | published source |
| `/spark/{arm}/teleop/cmd_joint_state` | `sensor_msgs/msg/JointState` | command | `command_issue_time_v1` | 20-200 Hz | published source |
| `/spark/{arm}/teleop/cmd_gripper_state` | `sensor_msgs/msg/JointState` | command | `command_issue_time_v1` | 20-200 Hz | published source |
| `/spark/session/teleop_active` | `std_msgs/msg/Bool` | teleop activity | host receive/publish time of the shared pedal activity packet | 20-200 Hz | raw-only conversion aid |
| `/spark/cameras/{attachment}/{camera_slot}/color/image_raw` | `sensor_msgs/msg/Image` | raw sensor | `host_capture_time_v1` immediately after `wait_for_frames()` returns | 20-30 Hz | raw/published depending on profile |
| `/spark/cameras/{attachment}/{camera_slot}/depth/image_rect_raw` | `sensor_msgs/msg/Image` | raw sensor | `host_capture_time_v1` immediately after `wait_for_frames()` returns | 20-30 Hz | raw-only or published-depth depending on profile |
| `/spark/tactile/{arm}/{finger_slot}/color/image_raw` | `sensor_msgs/msg/Image` | raw sensor | `host_capture_time_v1` immediately after `get_image()` returns | 15-30 Hz | raw/published depending on profile |
| `/spark/tactile/{arm}/{finger_slot}/depth/image_raw` | `sensor_msgs/msg/Image` | derived sensor | same stamp as the source tactile RGB frame | 15-30 Hz | raw-only unless a profile says otherwise |
| `/spark/tactile/{arm}/{finger_slot}/marker_offset` | `sensor_msgs/msg/PointCloud2` | derived sensor | same stamp as the source tactile RGB frame | 15-30 Hz | raw-only unless a profile says otherwise |


## Examples

Examples of valid V2 raw topics:

- `/spark/lightning/robot/joint_state`
- `/spark/thunder/teleop/cmd_gripper_state`
- `/spark/session/teleop_active`
- `/spark/cameras/lightning/wrist_1/color/image_raw`
- `/spark/cameras/world/scene_1/color/image_raw`
- `/spark/cameras/world/scene_2/depth/image_rect_raw`
- `/spark/tactile/lightning/finger_left/color/image_raw`
- `/spark/tactile/thunder/finger_right/marker_offset`


## Forbidden V1 Aliases

The following are not part of the V2 canonical raw contract:

- `/spark/cameras/wrist/...`
- `/spark/cameras/scene/...`
- `/spark/tactile/left/...`
- `/spark/tactile/right/...`
- `/Spark_enable/lightning`

They may exist in historical bags or old code, but they must not be extended or treated as the target contract.


## Semantic Conventions

### Gripper state and command

Both stable gripper topics use:

- `0.0 = fully open`
- `1.0 = fully closed`

For measured state, normalize from the calibrated Robotiq open/closed range when available.

### Session activity

`/spark/session/teleop_active` is not a published action.

It exists only so conversion can remove intentional pedal-off spans instead of misclassifying them as stale action gaps.

### Camera and tactile geometry

Topic names define semantic identity, not physical geometry.

Examples:

- `scene_1` identifies one scene-camera slot in the world attachment
- `lightning/wrist_1` identifies the wrist-camera slot attached to Lightning

Actual intrinsics and extrinsics, when available, belong in the local calibration results file and manifest snapshots, not in the topic name itself.


## Producer Expectations

### RealSense

For `/spark/cameras/{attachment}/{camera_slot}/...` topics:

- the stamp must be assigned immediately after `wait_for_frames()` returns
- color and depth from the same acquisition cycle should share the same semantic capture time

### GelSight

For `/spark/tactile/{arm}/{finger_slot}/...` topics:

- the RGB stamp must be assigned immediately after `get_image()` returns
- derived tactile topics must reuse the RGB frame stamp from the same cycle

### Robot and teleop topics

For `/spark/{arm}/robot/...` and `/spark/{arm}/teleop/...` topics:

- related measured robot-state topics from one control iteration should reuse one `control_tick_time_v1`
- command topics must reflect issue time, not achieved-state time


## Documentation Rule

No new topic is ready for V2 unless its:

- topic pattern
- message type
- timestamp meaning
- semantic convention

can be stated in one sentence each using this document.
