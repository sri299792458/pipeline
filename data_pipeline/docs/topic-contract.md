# Topic Contract

## Purpose

This document defines the ROS topic contract expected by the V1 data pipeline.

The contract is written in terms of a **stable V1 topic surface**. Current legacy SPARK topics are listed separately where relevant so we can bridge from the existing runtime without confusing "what exists today" with "what the pipeline depends on long term."


## Timestamp Vocabulary

The following timestamp meanings are allowed in V1:

- `host_capture_time_v1`
  - Host ROS time assigned immediately after a sensor sample is acquired by the process.
- `control_tick_time_v1`
  - Host ROS time assigned once for a single robot/control update tick and reused for all state values from that tick.
- `command_issue_time_v1`
  - Host ROS time at which a command is issued toward the robot or gripper.

The following meanings are explicitly **not** the V1 canonical clock:

- raw device hardware time as the primary dataset alignment clock
- host publish time after heavy reconstruction or post-processing
- recorder assembly time after multiple modalities have already been read


## Stable V1 Topics

For arm-scoped robot topics, `{arm}` means one of:

- `lightning`
- `thunder`

| Topic | Message Type | Semantic Type | Timestamp Meaning | Expected Rate | V1 Role |
|---|---|---|---|---:|---|
| `/spark/cameras/wrist/color/image_raw` | `sensor_msgs/msg/Image` | raw sensor | `host_capture_time_v1` immediately after `wait_for_frames()` | 20-30 Hz | published |
| `/spark/cameras/wrist/depth/image_rect_raw` | `sensor_msgs/msg/Image` | raw sensor | `host_capture_time_v1` immediately after `wait_for_frames()` | 20-30 Hz | raw-only |
| `/spark/cameras/scene/color/image_raw` | `sensor_msgs/msg/Image` | raw sensor | `host_capture_time_v1` immediately after `wait_for_frames()` | 20-30 Hz | published |
| `/spark/cameras/scene/depth/image_rect_raw` | `sensor_msgs/msg/Image` | raw sensor | `host_capture_time_v1` immediately after `wait_for_frames()` | 20-30 Hz | raw-only |
| `/spark/tactile/left/color/image_raw` | `sensor_msgs/msg/Image` | raw sensor | `host_capture_time_v1` immediately after `get_image()` returns | 15-30 Hz | published when present |
| `/spark/tactile/left/depth/image_raw` | `sensor_msgs/msg/Image` | derived sensor | same stamp as the source tactile RGB frame | 15-30 Hz | raw-only |
| `/spark/tactile/left/marker_offset` | `sensor_msgs/msg/PointCloud2` | derived sensor | same stamp as the source tactile RGB frame | 15-30 Hz | raw-only |
| `/spark/tactile/right/color/image_raw` | `sensor_msgs/msg/Image` | raw sensor | `host_capture_time_v1` immediately after `get_image()` returns | 15-30 Hz | published when present |
| `/spark/tactile/right/depth/image_raw` | `sensor_msgs/msg/Image` | derived sensor | same stamp as the source tactile RGB frame | 15-30 Hz | raw-only |
| `/spark/tactile/right/marker_offset` | `sensor_msgs/msg/PointCloud2` | derived sensor | same stamp as the source tactile RGB frame | 15-30 Hz | raw-only |
| `/spark/{arm}/robot/joint_state` | `sensor_msgs/msg/JointState` | measured state | `control_tick_time_v1` | 50-200 Hz | published source |
| `/spark/{arm}/robot/eef_pose` | `geometry_msgs/msg/PoseStamped` | measured state | `control_tick_time_v1` | 50-200 Hz | published source |
| `/spark/{arm}/robot/tcp_wrench` | `geometry_msgs/msg/WrenchStamped` | measured state | `control_tick_time_v1` | 50-200 Hz | published source |
| `/spark/{arm}/robot/gripper_state` | `sensor_msgs/msg/JointState` | measured state | `control_tick_time_v1` | 20-100 Hz | published source |
| `/spark/{arm}/teleop/cmd_joint_state` | `sensor_msgs/msg/JointState` | command | `command_issue_time_v1` | 20-200 Hz | published source |
| `/spark/{arm}/teleop/cmd_gripper_state` | `sensor_msgs/msg/JointState` | command | `command_issue_time_v1` | 20-200 Hz | published source |


## Why These Types

The topic contract prefers stamped standard ROS message types wherever possible.

### Why cameras use `sensor_msgs/msg/Image`

This is the standard message type expected by almost every ROS imaging tool and conversion library. It also carries a `Header`, which gives us the place to define timestamp semantics explicitly.

### Why joint state uses `sensor_msgs/msg/JointState`

This gives us a standard stamped container for joint position, velocity, and effort-like values. It is a better long-term contract than an unstamped `Float32MultiArray`.

### Why gripper state and command also use `sensor_msgs/msg/JointState`

There is no standard stamped scalar message in core ROS 2. Reusing `JointState` lets us keep the gripper in the same timestamped ecosystem while still being explicit about the semantic meaning.

Suggested convention:

- state: `name = ["gripper"]`, `position = [measured_position]`
- command: `name = ["gripper_cmd"]`, `position = [commanded_position]`

### Why wrench uses `geometry_msgs/msg/WrenchStamped`

This is the natural stamped message for force and torque. It avoids inventing another array schema.

### Why pose uses `geometry_msgs/msg/PoseStamped`

This makes the end-effector pose an explicit stamped state rather than another untyped float array.


## Current Legacy SPARK Topics

The existing runtime currently publishes or can be made to publish the following topics:

| Legacy Topic | Current Type | Current Status | Stable V1 Equivalent |
|---|---|---|---|
| `/lightning_q` | `std_msgs/msg/Float32MultiArray` | exists in `main`, unstamped | `/spark/lightning/robot/joint_state` |
| `/lightning_cartesian_eef` | `std_msgs/msg/Float32MultiArray` | exists in `main`, unstamped | `/spark/lightning/robot/eef_pose` |
| `/lightning_ft` | `std_msgs/msg/Float32MultiArray` | exists in `main`, unstamped | `/spark/lightning/robot/tcp_wrench` |
| `/lightning_raw_ft_raw` | `std_msgs/msg/Float32MultiArray` | exists in `main`, unstamped | optional raw debug topic |
| `/lightning_gripper` | `std_msgs/msg/Int32` | exists in current hardware-tuned runtime, unstamped | `/spark/lightning/robot/gripper_state` |
| `/lightning_enable` | `std_msgs/msg/Bool` | exists in `main`, unstamped | optional raw debug topic |
| `/lightning_safety_mode` | `std_msgs/msg/Int32` | exists in `main`, unstamped | optional raw debug topic |
| `/lightning_force_offset` | `std_msgs/msg/Float32MultiArray` | exists in `main`, unstamped | optional raw debug topic |
| `/lightning_spark_command_angles` | `std_msgs/msg/Float32MultiArray` | exists in current hardware-tuned runtime, unstamped | `/spark/lightning/teleop/cmd_joint_state` |
| `/lightning_spark_command_gripper` | `std_msgs/msg/Float32` | exists in current hardware-tuned runtime, unstamped | `/spark/lightning/teleop/cmd_gripper_state` |
| `/thunder_q` | `std_msgs/msg/Float32MultiArray` | exists in `main`, unstamped | `/spark/thunder/robot/joint_state` |
| `/thunder_cartesian_eef` | `std_msgs/msg/Float32MultiArray` | exists in `main`, unstamped | `/spark/thunder/robot/eef_pose` |
| `/thunder_ft` | `std_msgs/msg/Float32MultiArray` | exists in `main`, unstamped | `/spark/thunder/robot/tcp_wrench` |
| `/thunder_raw_ft_raw` | `std_msgs/msg/Float32MultiArray` | exists in `main`, unstamped | optional raw debug topic |
| `/thunder_gripper` | `std_msgs/msg/Int32` | exists in current hardware-tuned runtime, unstamped | `/spark/thunder/robot/gripper_state` |
| `/thunder_enable` | `std_msgs/msg/Bool` | exists in `main`, unstamped | optional raw debug topic |
| `/thunder_safety_mode` | `std_msgs/msg/Int32` | exists in `main`, unstamped | optional raw debug topic |
| `/thunder_force_offset` | `std_msgs/msg/Float32MultiArray` | exists in `main`, unstamped | optional raw debug topic |
| `/thunder_spark_command_angles` | `std_msgs/msg/Float32MultiArray` | exists in current hardware-tuned runtime, unstamped | `/spark/thunder/teleop/cmd_joint_state` |
| `/thunder_spark_command_gripper` | `std_msgs/msg/Float32` | exists in current hardware-tuned runtime, unstamped | `/spark/thunder/teleop/cmd_gripper_state` |


## Bridge Rule

The V1 recorder and converter should consume the **stable V1 topics**, not the legacy ones.

This means we will need a small bridge or publisher upgrade in the runtime that:

- republishes current legacy robot topics into stamped standard message types
- ports the Spark command topics from the `data_collection` branch into `main`
- assigns timestamps with the meanings declared in this document

For robot and teleop topics, the bridge must preserve arm identity explicitly in the topic path. V1 should not collapse both arms into one ambiguous robot topic namespace.

The pipeline itself should not depend on legacy unstamped topic semantics.


## Camera Notes

### RealSense

For V1, the topic stamp should mean:

"host ROS time immediately after the process receives the frame batch from `wait_for_frames()`"

It should not mean:

- RealSense hardware clock time
- post-resize or post-encoding time
- recorder assembly time

If the process also wants to retain RealSense device timestamps for diagnostics, those can be carried in metadata or in a side channel, but the `Image.header.stamp` used for dataset alignment should still be the V1 host capture stamp.

### GelSight

For V1, the topic stamp should mean:

"host ROS time immediately after `get_image()` returns"

It should not mean:

- post-depth-reconstruction time
- post-marker-processing time
- post-point-cloud-generation time

Any derived GelSight topic must reuse the RGB frame's stamp from the same cycle.


## Robot Notes

### Measured state topics

Measured robot topics from one control loop iteration should reuse the same `control_tick_time_v1` stamp when possible.

This does not require a fused message. It only requires that the producer stamp related robot-side state consistently.

This rule applies per arm. `lightning` and `thunder` may share a control loop, but the stable topic contract still keeps their state streams separate.

### Command topics

Command topics must represent the time the command is issued, not the time the actuator later reaches the target state.

That distinction matters because command and achieved state are not the same thing and should not be made to look simultaneous.


## Required V1 Documentation Rule

No topic is considered "ready for V1" unless its timestamp meaning can be described in one sentence using the vocabulary above.
