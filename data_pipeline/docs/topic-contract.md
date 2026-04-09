# Topic Contract And Timing

## Purpose

This document defines the canonical raw ROS topic contract for the current data
pipeline.

It is authoritative for:

- topic names
- message types
- timestamp meanings
- semantic conventions

It is meant to document the current contract, not every alternate naming scheme
someone might find elsewhere.


## Why This Contract Exists

The pipeline is easier to evolve when one raw topic surface is treated as the
stable contract and everything else is treated as either:

- an upstream producer detail
- a compatibility detail
- or a local bridge input

The design rule is:

- `/spark/...` is the canonical raw surface
- producer-specific names are not the contract

That keeps recording, manifests, conversion, calibration, and review aligned to
one naming system instead of accumulating more alias layers.


## Timestamp Vocabulary

The timestamp meanings are:

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


## Canonical Topics

| Topic Pattern | Message Type | Semantic Type | Timestamp Meaning | Usage |
|---|---|---|---|---|
| `/spark/{arm}/robot/joint_state` | `sensor_msgs/msg/JointState` | measured state | `control_tick_time_v1` | published source |
| `/spark/{arm}/robot/eef_pose` | `geometry_msgs/msg/PoseStamped` | measured state | `control_tick_time_v1` | published source |
| `/spark/{arm}/robot/tcp_wrench` | `geometry_msgs/msg/WrenchStamped` | measured state | `control_tick_time_v1` | published source |
| `/spark/{arm}/robot/gripper_state` | `sensor_msgs/msg/JointState` | measured state | `control_tick_time_v1` | published source |
| `/spark/{arm}/teleop/cmd_joint_state` | `sensor_msgs/msg/JointState` | command | `command_issue_time_v1` | published source |
| `/spark/{arm}/teleop/cmd_gripper_state` | `sensor_msgs/msg/JointState` | command | `command_issue_time_v1` | published source |
| `/spark/session/teleop_active` | `std_msgs/msg/Bool` | teleop activity | host receive/publish time of the shared pedal activity packet | raw-only conversion aid |
| `/spark/cameras/{attachment}/{camera_slot}/color/image_raw` | `sensor_msgs/msg/Image` | raw sensor | `host_capture_time_v1` immediately after `wait_for_frames()` returns | raw/published depending on profile |
| `/spark/cameras/{attachment}/{camera_slot}/depth/image_rect_raw` | `sensor_msgs/msg/Image` | raw sensor | `host_capture_time_v1` immediately after `wait_for_frames()` returns | raw-only or published-depth depending on profile |
| `/spark/tactile/{arm}/{finger_slot}/color/image_raw` | `sensor_msgs/msg/Image` | raw sensor | `host_capture_time_v1` immediately after `get_image()` returns | raw/published depending on profile |


## Observed Rates On The Current Rig

Recent Lightning single-arm bags recorded on `2026-04-06` on this rig
showed these typical observed rates:

| Topic Family | Typical Observed Rate |
|---|---:|
| world RGB / depth | ~30 Hz |
| `/spark/session/teleop_active` | ~30 Hz |
| robot measured state topics | ~114-150 Hz |
| teleop command topics | ~8-17 Hz during active demos |

This is here as a practical reference for this rig, especially when
debugging throughput or checking whether a new recording looks obviously wrong.


## Examples

Examples of valid raw topics:

- `/spark/lightning/robot/joint_state`
- `/spark/thunder/teleop/cmd_gripper_state`
- `/spark/session/teleop_active`
- `/spark/cameras/lightning/wrist_1/color/image_raw`
- `/spark/cameras/world/scene_1/color/image_raw`
- `/spark/cameras/world/scene_2/depth/image_rect_raw`
- `/spark/tactile/lightning/finger_left/color/image_raw`


## Non-Canonical Names

The following are not part of the canonical raw contract:

- `/spark/cameras/wrist/...`
- `/spark/cameras/scene/...`
- `/spark/tactile/left/...`
- `/spark/tactile/right/...`
- `/Spark_enable/lightning`

Why this matters:

- extra aliases create a second naming vocabulary
- the manifest, session model, and published schema then drift apart
- future changes become harder than they need to be


## Semantic Conventions

### Gripper state and command

Both stable gripper topics use:

- `0.0 = fully open`
- `1.0 = fully closed`

For measured state, normalize from the calibrated Robotiq open/closed range when available.

### Session activity

`/spark/session/teleop_active` is not a published action.

It exists only so conversion can remove intentional pedal-off spans instead of misclassifying them as stale action gaps.

It is now part of the required raw contract for supported episodes, not an
optional hint.

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

No new topic is ready unless its:

- topic pattern
- message type
- timestamp meaning
- semantic convention

can be stated in one sentence each using this document.
