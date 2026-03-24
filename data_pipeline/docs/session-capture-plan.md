# Session Capture Plan V2

## Purpose

This document defines the resolved session object that sits between:

- the shared V2 topic contract
- live hardware discovery
- operator intent
- published-profile compatibility

It exists so raw session setup is no longer confused with published dataset schema.

See also:

- [../V2_SPEC.md](../V2_SPEC.md)
- [topic-contract.md](./topic-contract.md)


## Design Objects

### Shared Contract

Defines the lab-wide meaning layer:

- canonical role vocabulary
- canonical raw topic names
- timestamp semantics
- dataset-facing semantic conventions

### Session Capture Plan

Defines the resolved truth for one live session:

- discovered devices
- enabled devices
- resolved canonical roles
- resolved selected raw topics
- applied local overlays
- published-profile compatibility

### Published Profile

Defines a fixed shared dataset schema for conversion:

- required canonical raw topics
- optional canonical raw topics
- raw-to-published mapping
- alignment rules

### Local Overlay

Defines optional machine- or operator-local defaults and facts:

- serial-to-role defaults
- enabled-by-default flags
- display labels
- launch defaults
- calibration references
- optional geometry data
- other rig facts that do not redefine shared semantics


## Canonical Role Vocabulary

Suggested first V2 vocabulary:

- arms
  - `lightning`
  - `thunder`
- wrist cameras
  - `lightning_wrist_1`
  - `thunder_wrist_1`
- scene cameras
  - `scene_1`
  - `scene_2`
  - `scene_3`
- tactile sensors
  - `lightning_finger_left`
  - `lightning_finger_right`
  - `thunder_finger_left`
  - `thunder_finger_right`

Rules:

- canonical role names are lab-controlled
- operators do not invent canonical names at runtime
- local display labels may differ, but canonical role names must stay stable


## Role To Topic Mapping

The session capture plan resolves canonical roles into canonical raw topics defined by [topic-contract.md](./topic-contract.md).

Examples:

- `lightning_wrist_1` maps to:
  - `/spark/cameras/lightning/wrist_1/color/image_raw`
  - `/spark/cameras/lightning/wrist_1/depth/image_rect_raw`
- `scene_1` maps to:
  - `/spark/cameras/world/scene_1/color/image_raw`
  - `/spark/cameras/world/scene_1/depth/image_rect_raw`
- `lightning_finger_left` maps to:
  - `/spark/tactile/lightning/finger_left/color/image_raw`
  - `/spark/tactile/lightning/finger_left/depth/image_raw`
  - `/spark/tactile/lightning/finger_left/marker_offset`

The session plan does not invent ad hoc topic names. It only resolves canonical role names into the canonical V2 surface.


## Session Workflow

The intended workflow is:

1. discover live devices
2. load optional local overlays
3. suggest canonical role assignments from remembered mappings
4. let the operator confirm or correct those assignments once
5. enable or disable devices for this session
6. resolve the final selected raw topics for this session
7. record multiple episodes under that session plan

The operator should not redo this role-confirmation flow for every episode unless the rig changed.


## What The Operator Chooses

The operator may choose:

- which discovered devices are enabled
- whether suggested role assignments are correct
- whether optional devices are recorded
- which published profile to target later

The operator must not choose:

- new canonical role names
- alternate topic naming schemes
- timestamp semantics
- dataset field semantics


## Session Capture Plan Shape

The exact storage format can be JSON or YAML, but the resolved object should look like this:

```yaml
schema_version: 2
contract_version: v2
session_id: session-20260323-101500

active_arms:
  - lightning
  - thunder

local_overlays:
  - path: data_pipeline/configs/session.local.yaml
    exists: true
    kind: local_defaults

discovered_devices:
  - device_id: arm/lightning
    kind: ur_arm
    enabled: true
    suggested_role: lightning
    resolved_role: lightning

  - device_id: arm/thunder
    kind: ur_arm
    enabled: true
    suggested_role: thunder
    resolved_role: thunder

  - device_id: realsense/130322273305
    kind: realsense
    model: Intel RealSense D405
    serial_number: "130322273305"
    enabled: true
    suggested_role: lightning_wrist_1
    resolved_role: lightning_wrist_1

  - device_id: realsense/213622251272
    kind: realsense
    model: Intel RealSense D455
    serial_number: "213622251272"
    enabled: true
    suggested_role: scene_1
    resolved_role: scene_1

  - device_id: realsense/f1380660
    kind: realsense
    model: Intel RealSense L515
    serial_number: "f1380660"
    enabled: true
    suggested_role: scene_2
    resolved_role: scene_2

  - device_id: gelsight/28D8PXEC
    kind: gelsight
    model: GelSight Mini
    serial_number: "28D8PXEC"
    enabled: true
    suggested_role: lightning_finger_left
    resolved_role: lightning_finger_left

selected_topics:
  - /spark/session/teleop_active
  - /spark/lightning/robot/joint_state
  - /spark/lightning/robot/eef_pose
  - /spark/lightning/robot/tcp_wrench
  - /spark/lightning/robot/gripper_state
  - /spark/lightning/teleop/cmd_joint_state
  - /spark/lightning/teleop/cmd_gripper_state
  - /spark/thunder/robot/joint_state
  - /spark/thunder/robot/eef_pose
  - /spark/thunder/robot/tcp_wrench
  - /spark/thunder/robot/gripper_state
  - /spark/thunder/teleop/cmd_joint_state
  - /spark/thunder/teleop/cmd_gripper_state
  - /spark/cameras/lightning/wrist_1/color/image_raw
  - /spark/cameras/lightning/wrist_1/depth/image_rect_raw
  - /spark/cameras/world/scene_1/color/image_raw
  - /spark/cameras/world/scene_1/depth/image_rect_raw
  - /spark/cameras/world/scene_2/color/image_raw
  - /spark/cameras/world/scene_2/depth/image_rect_raw
  - /spark/tactile/lightning/finger_left/color/image_raw
  - /spark/tactile/lightning/finger_left/depth/image_raw
  - /spark/tactile/lightning/finger_left/marker_offset

selected_extra_topics: []

profile_compatibility:
  publishable_profiles:
    - name: lightning_multiview_v2
      compatible: true
  incompatible_profiles:
    - name: bimanual_dual_wrist_v2
      compatible: false
      reasons:
        - missing required role thunder_wrist_1
```


## Episode Snapshot Rule

Each episode manifest should snapshot the relevant resolved session information:

- active arms
- applied local overlays
- resolved devices and roles
- selected topics
- target-profile compatibility state at record time

The operator does the resolution once per session, but every episode remains self-describing.


## Local Overlay Example

```yaml
devices:
  realsense/130322273305:
    role: lightning_wrist_1
    enabled_by_default: true
    display_label: Lightning wrist D405
    metadata:
      calibration_ref: calib://realsense/lightning_wrist_1/v2

  realsense/213622251272:
    role: scene_1
    enabled_by_default: true

  realsense/f1380660:
    role: scene_2
    enabled_by_default: false

  gelsight/28D8PXEC:
    role: lightning_finger_left
    enabled_by_default: true
    metadata:
      calibration_ref: calib://gelsight/lightning_finger_left/v1

ui:
  viewer_base_url: http://10.33.55.65:3000
```

The overlay may add local defaults and facts. It must not redefine canonical role names or canonical topic names.


## Non-Goals

The session capture plan must not become:

- a second published-profile schema file
- a place to preserve V1 aliases
- a place for operator-defined topic naming
- a replacement for explicit geometry data when geometry matters


## Migration Rule

For V2 implementation:

- session-plan resolution must target canonical V2 topic names directly
- do not preserve the old `wrist`, `scene`, `left`, `right` raw topic surface as a compatibility layer
- if a bridge, launcher, UI, manifest builder, or profile disagrees with the V2 topic contract, the contract wins
