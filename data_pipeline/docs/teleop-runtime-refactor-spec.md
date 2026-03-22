# Teleop Runtime Refactor Spec

## 1. Goal

Refactor the legacy teleop runtime into a clearer internal architecture without changing operator-visible behavior.

This refactor is for:

- making the Spark and UR runtime systematic instead of launcher-driven
- separating device adapters from GUI code
- preserving the current ROS topic contract
- preserving the current tuned control quirks
- improving connection robustness, stale detection, and diagnostics

This refactor is not for:

- redesigning teleoperation behavior
- replacing the existing Tk Teleop GUI
- changing topic names
- changing the SPARK packet format
- changing UR command semantics
- reviving every legacy peripheral path in `TeleopSoftware/`


## 2. Problem

The current teleop runtime mixes several concerns in the same code paths:

- GUI layout and button callbacks
- Spark serial connection and packet parsing
- UR dashboard, RTDE control, RTDE state, and gripper setup
- mode switching
- teleop control logic
- ROS publishing
- peripheral support for SpaceMouse, VR, haptics, WebRTC, and legacy camera paths

That makes the code difficult to reason about and fragile to extend, even when the desired external behavior is already known.


## 3. Boundary

The refactor target is the core teleop runtime currently anchored by:

- [launch.py](/home/srinivas/Desktop/pipeline/TeleopSoftware/launch.py)
- [run.py](/home/srinivas/Desktop/pipeline/TeleopSoftware/launch_helpers/run.py)
- [tk_functions.py](/home/srinivas/Desktop/pipeline/TeleopSoftware/launch_helpers/tk_functions.py)
- [arms.py](/home/srinivas/Desktop/pipeline/TeleopSoftware/UR/arms.py)
- [SparkNode.py](/home/srinivas/Desktop/pipeline/TeleopSoftware/Spark/SparkNode.py)
- [launch_devs.py](/home/srinivas/Desktop/pipeline/TeleopSoftware/launch_devs.py)

The current `data_pipeline` integration depends on a narrow surface:

- `TeleopSoftware/launch.py` as the Teleop process entrypoint
- `/Spark_angle/<arm>`
- `/Spark_enable/<arm>`
- `/spark/<arm>/teleop/cmd_joint_state`
- `/spark/<arm>/teleop/cmd_gripper_state`

That dependency surface must remain stable through the refactor.


## 4. Scope

### 4.1 In scope

- Spark serial input and publishing
- UR dashboard connection
- UR RTDE control connection
- UR RTDE state connection
- Robotiq gripper connection
- teleop mode orchestration for the current Spark path
- ROS publishing for stable robot and teleop command topics
- the existing Tk GUI as an adapter on top of the runtime

### 4.2 Explicitly out of scope for phase 1

- SpaceMouse
- VR
- haptic gloves
- WebRTC
- legacy camera publishers under `TeleopSoftware/camera`
- broader cleanup of unrelated experimental control modes

These may remain as legacy adapters or be isolated later, but they must not drive the first architecture.


## 5. Core Rule

This is a behavior-preserving refactor.

The code may change structure, naming, and ownership boundaries, but it must preserve:

- topic names
- message types
- button meanings
- mode semantics
- arm ordering
- Spark-to-UR mapping behavior
- command timing assumptions used by the data pipeline

If a behavior is currently tuned and relied upon in hardware operation, the refactor must preserve it unless there is an explicit follow-up change with separate validation.


## 6. Frozen Behavioral Quirks

The following current behaviors are semantically important and must be treated as requirements, not cleanup opportunities.

### 6.1 Base-joint wrap reconciliation

On Spark mode entry, the code reconciles the base joint home offset by `±2π` when the delta crosses `π`.

Current source:

- [run.py](/home/srinivas/Desktop/pipeline/TeleopSoftware/launch_helpers/run.py#L129)

This behavior must be preserved exactly.

### 6.2 Arm-specific Spark gripper normalization

Lightning and Thunder use different Spark raw ranges for gripper mapping.

Current source:

- [run.py](/home/srinivas/Desktop/pipeline/TeleopSoftware/launch_helpers/run.py#L142)

This mapping must remain arm-specific unless deliberately recalibrated.

### 6.3 Rising-edge FT zero on enable

The force-torque sensor is zeroed on the transition from Spark disabled to enabled.

Current source:

- [run.py](/home/srinivas/Desktop/pipeline/TeleopSoftware/launch_helpers/run.py#L177)

This edge-triggered behavior must be preserved.

### 6.4 UR mode-transition guards

The UR wrapper currently stops the previous motion mode before entering a different one.

Current source:

- [arms.py](/home/srinivas/Desktop/pipeline/TeleopSoftware/UR/arms.py#L43)

This transition discipline must be preserved.

### 6.5 Stable stamped teleop command outputs

The current runtime publishes stamped teleop command topics used by the data pipeline.

Current source:

- [launch.py](/home/srinivas/Desktop/pipeline/TeleopSoftware/launch.py#L98)
- [run.py](/home/srinivas/Desktop/pipeline/TeleopSoftware/launch_helpers/run.py#L101)

These outputs must remain present and semantically equivalent.


## 7. Target Architecture

The target runtime should be split into explicit layers.

### 7.1 Config

Owns:

- arm names
- robot IPs
- gripper enable flags
- Spark serial device paths
- Spark offsets files
- arm-specific Spark profiles
- RTDE control settings

This layer must be explicit, typed, and not dependent on USB guessing as the primary contract.

### 7.2 Device adapters

Owns:

- Spark serial reader and parser
- Spark angle unwrapping
- UR dashboard adapter
- UR RTDE control adapter
- UR RTDE state adapter
- Robotiq gripper adapter

Each adapter should do one job and expose explicit errors and stale state.

### 7.3 Runtime / orchestrator

Owns:

- connection lifecycle
- mode transitions
- enable-edge behavior
- Spark-to-UR command mapping
- periodic publishing of stable robot state and teleop command topics

The orchestrator should contain the current teleop semantics, but not GUI widget code.

### 7.4 UI and ROS adapters

Owns:

- Tk widgets and button callbacks
- ROS subscriptions
- ROS publishers

These layers should call into the runtime instead of implementing device logic directly.


## 8. Allowed Improvements

The refactor may improve:

- explicit Spark serial configuration
- reconnect behavior
- startup sequencing
- stale-sample detection
- packet parse diagnostics
- device health metrics
- logging clarity
- testability of control logic

These improvements must not change teleop semantics by accident.


## 9. Non-Goals

- Do not rewrite the Teleop GUI in another toolkit.
- Do not merge Teleop GUI logic into `data_pipeline`.
- Do not make `data_pipeline` depend on Teleop internals as a library.
- Do not remove legacy peripheral code just because it is not in phase 1 scope.
- Do not promise protocol-level Spark packet-loss elimination without firmware/protocol changes.


## 10. Migration Strategy

This refactor must be incremental.

### 10.1 Step 1: specify contracts

Write down:

- the runtime config surface
- the device adapter boundaries
- the frozen behavior list
- the ROS compatibility surface

### 10.2 Step 2: extract adapters behind compatibility shims

Keep `launch.py` and the existing topic surface working while:

- Spark logic moves behind a dedicated adapter
- UR logic moves behind dedicated adapters
- GUI callbacks call the new runtime layer

### 10.3 Step 3: move orchestration logic

Move the Spark/UR control semantics out of GUI/helper glue and into an explicit runtime module.

### 10.4 Step 4: isolate legacy peripherals

Leave SpaceMouse, VR, haptics, WebRTC, and legacy camera paths outside the new core runtime, with legacy entrypoints if needed.


## 11. Validation

Every migration slice must be validated against current behavior.

Minimum parity checks:

- Teleop GUI still launches from `TeleopSoftware/launch.py`
- Spark topics still publish on:
  - `/Spark_angle/<arm>`
  - `/Spark_enable/<arm>`
- teleop command topics still publish on:
  - `/spark/<arm>/teleop/cmd_joint_state`
  - `/spark/<arm>/teleop/cmd_gripper_state`
- base-joint wrap behavior is unchanged on mode entry
- FT zero still occurs only on enable rising edge
- Lightning and Thunder gripper mappings are unchanged
- UR mode transitions still stop the previous mode before entering the next

Hardware validation matters more than unit tests for final acceptance.


## 12. Acceptance

The refactor is successful when:

- the core runtime is structurally separated into config, adapters, runtime, and UI/ROS glue
- the current Teleop GUI and `data_pipeline` continue to work without contract changes
- the tuned Spark and UR semantics are preserved
- the code path for Spark and UR bring-up is explicit and easier to reason about
- legacy peripheral code no longer dictates the design of the core runtime
