# Data Pipeline V2 Spec

## Goal

V2 is the new canonical data-collection contract for `data_pipeline/`.

It keeps the same high-level pipeline shape:

- raw recording as one rosbag per episode
- one resolved `episode_manifest.json` per episode
- offline conversion into fixed-schema published datasets

But it changes the sensor/topic model decisively:

- V2 uses canonical sensor-key-based raw topic names
- session setup is separated from published-profile selection
- no V1 topic aliases or compatibility shims are part of the target design

Current implementation status:

- V2 is the authoritative target contract
- the runtime and conversion code are still mid-migration
- when code and spec disagree, future implementation should move toward V2 rather than preserving V1 aliases


## Authority

These files are the authoritative V2 contract:

- [V2_SPEC.md](./V2_SPEC.md)
- [docs/topic-contract.md](./docs/topic-contract.md)
- [docs/session-capture-plan.md](./docs/session-capture-plan.md)

The operator-console behavior spec is:

- [docs/operator-console-spec.md](./docs/operator-console-spec.md)

Historical V1 material is archive-only and must not be used to justify new fallback paths.


## Boundary

- `TeleopSoftware/` remains the runtime producer of robot and teleop data.
- `data_pipeline/` owns:
  - recording
  - manifests
  - session planning
  - conversion
  - validation
- new pipeline work must target the V2 topic contract directly
- do not add new V1 aliases such as:
  - `/spark/cameras/wrist/...`
  - `/spark/cameras/scene/...`
  - `/spark/tactile/left/...`
  - `/spark/tactile/right/...`


## Core Objects

### Shared contract

The shared contract defines:

- canonical topic names
- timestamp meanings
- canonical sensor keys
- dataset-facing field semantics

It is lab-wide and must not vary by operator.

### Sensors file

The sensors file is the one local rig file.

Its main job is:

- serial or device-path to canonical-sensor-key mapping

It may also hold optional local metadata such as calibration references.

Solved camera geometry lives separately in `calibration.local.json` and is snapshotted into raw manifests when present.

### Session profile

The session profile is created once at session start.

It defines:

- session metadata
- discovered devices chosen for recording
- canonical sensor keys confirmed for those devices
- resolved raw topics for that session

All episodes recorded in that session inherit the same session profile.

Operators may save session profiles locally for reuse across sessions.
These saved profiles are convenience artifacts, not shared-contract objects.


## Canonical Raw Topic Surface

V2 raw recording uses only the canonical sensor-key-based surface.

### Robot and command topics

- `/spark/{arm}/robot/joint_state`
- `/spark/{arm}/robot/eef_pose`
- `/spark/{arm}/robot/tcp_wrench`
- `/spark/{arm}/robot/gripper_state`
- `/spark/{arm}/teleop/cmd_joint_state`
- `/spark/{arm}/teleop/cmd_gripper_state`

Where `{arm}` is one of:

- `lightning`
- `thunder`

### Session activity topic

V2 uses one shared teleop-activity topic:

- `/spark/session/teleop_active`

This is a raw conversion aid, not the published action.

### Camera topics

V2 camera topics use:

- `/spark/cameras/{attachment}/{camera_slot}/color/image_raw`
- `/spark/cameras/{attachment}/{camera_slot}/depth/image_rect_raw`

Where:

- `{attachment}` is one of:
  - `lightning`
  - `thunder`
  - `world`
- `{camera_slot}` is a canonical slot name such as:
  - `wrist_1`
  - `scene_1`
  - `scene_2`
  - `scene_3`

Examples:

- `/spark/cameras/lightning/wrist_1/color/image_raw`
- `/spark/cameras/lightning/wrist_1/depth/image_rect_raw`
- `/spark/cameras/world/scene_1/color/image_raw`
- `/spark/cameras/world/scene_1/depth/image_rect_raw`

### Tactile topics

V2 tactile topics use:

- `/spark/tactile/{arm}/{finger_slot}/color/image_raw`

Where `{finger_slot}` is one of:

- `finger_left`
- `finger_right`

Examples:

- `/spark/tactile/lightning/finger_left/color/image_raw`


## Raw Recording Rules

- one demo = one raw episode = one rosbag
- the raw bag stores canonical V2 topics only
- one session may record multiple episodes under one resolved session plan
- pedal-off spans are represented by the session activity topic, not by fake action holds
- the raw layer remains the source of truth


## Episode Manifest

`episode_manifest.json` remains the single resolved per-episode snapshot.

Its top-level sections stay:

- `episode`
- `session`
- `profile`
- `capture`
- `sensors`
- `recorded_topics`
- `provenance`

The important V2 change is that `recorded_topics` and `sensors.devices` must reflect canonical V2 raw topics and canonical V2 sensor keys.


## Published Profiles

Published profiles in V2 must refer directly to canonical V2 raw topics.

That means:

- they map from sensor-key-based raw topics
- they do not use V1 shorthand camera/tactile names
- they do not define session bring-up

The active `multisensor_20hz*.yaml` files are now part of the V2 profile layer and must continue to point directly at canonical V2 raw topics.


## Timestamp Rule

V2 keeps the existing timestamp meanings unless a later spec changes them explicitly:

- `host_capture_time_v1`
- `control_tick_time_v1`
- `command_issue_time_v1`

The naming stays because the semantics are unchanged. V2 changes the topic/sensor-key model, not the clock meanings.


## Migration Rule

From this point on:

- V2 is the only target contract
- do not add dual V1/V2 code paths
- do not add legacy alias topics
- do not let the UI, session plan, profiles, and topic contract disagree about canonical names

If a new change does not satisfy the V2 topic contract directly, it is the wrong change.
