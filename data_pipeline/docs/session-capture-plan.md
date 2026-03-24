# Session Capture Plan

## Purpose

This document separates four things that are currently too entangled in the V1 stack:

- shared contract
- session capture plan
- published profile
- optional local YAML overlays

The goal is to keep shared dataset meaning stable without forcing raw session bring-up to look like a fixed published schema.


## Current Problem

Today, the system is too rigid because the same profile layer is doing multiple jobs at once:

- deciding what raw topics are recorded
- implying which physical sensors exist
- implying which semantic camera roles exist
- defining the fixed published LeRobot schema

That works for the current narrow setup of:

- one Lightning wrist camera
- one scene camera
- optional left GelSight

It does not scale cleanly to:

- two UR arms
- zero, one, or two wrist cameras
- two or three scene cameras
- four GelSight sensors
- geometry-sensitive downstream policies


## Design Objects

### 1. Shared Contract

The shared contract is the lab-wide meaning layer.

It defines:

- stable topic semantics
- timestamp semantics
- canonical role vocabulary
- published dataset field semantics

Examples:

- what `/spark/{arm}/robot/gripper_state` means
- what `control_tick_time_v1` means
- what `scene_0` means
- what `lightning_finger_left` means

The shared contract must not vary by operator.


### 2. Session Capture Plan

The session capture plan is the resolved runtime truth for one live session.

It should describe:

- which devices were discovered
- which devices were enabled for this session
- which canonical role each enabled device was assigned
- which topics were resolved for recording
- which optional local YAML files were applied
- which published profiles this session can satisfy

The session capture plan is session-level, not episode-level.

Each recorded episode should snapshot the relevant resolved session information into `episode_manifest.json`.


### 3. Published Profile

A published profile is a fixed shared dataset schema.

It defines:

- required semantic roles
- optional semantic roles
- raw-to-published mapping
- alignment rules
- published feature names

A published profile is used for conversion and dataset appending.

It should not be the thing that decides which devices must exist before a raw session can start.


### 4. Optional Local YAML Overlay

A local YAML overlay is an operator- or machine-local defaults file.

It may provide:

- serial-to-role defaults
- display labels
- enabled-by-default flags
- launch defaults
- viewer/UI defaults
- mount metadata
- calibration references
- optional geometry data or geometry file references
- other rig-specific facts that do not redefine shared semantics

It must not redefine shared semantics.

It is a convenience layer, not the shared contract.


## Canonical Role Model

Canonical roles should be stable, shared, and independent of the current device serial numbers.

Suggested first vocabulary:

- arms
  - `lightning`
  - `thunder`
- wrist cameras
  - `lightning_wrist_0`
  - `thunder_wrist_0`
- scene cameras
  - `scene_0`
  - `scene_1`
  - `scene_2`
- tactile sensors
  - `lightning_finger_left`
  - `lightning_finger_right`
  - `thunder_finger_left`
  - `thunder_finger_right`

Rules:

- canonical role names are lab-controlled
- operators do not invent canonical names at runtime
- optional display labels may differ locally, but dataset-facing names must remain canonical


## Why Roles And Geometry Must Be Separate

Role identity is not the same thing as geometry.

For example:

- `scene_1` tells us which semantic camera slot this is
- it does not tell us where the camera is relative to the robot base or world frame

That distinction matters because:

- image-only policies may only need the role and image stream
- point-cloud or geometry-sensitive policies may also need camera intrinsics and extrinsics

Therefore:

- canonical role naming must stay stable
- optional geometry may be attached separately via local YAML


## Session Workflow

The intended session workflow is:

1. start session
2. discover live devices
3. load optional local YAML overlays
4. suggest canonical role assignments from remembered serial-to-role mappings
5. let the operator confirm or correct assignments once
6. resolve the final topic list for this session
7. record multiple episodes under that session plan

The operator should not repeat this role-confirmation workflow for every episode unless the rig changed.


## What The Operator Chooses

The operator should be choosing intent, not redefining shared meaning.

The operator may choose:

- which discovered devices are enabled for this session
- whether the suggested canonical role assignments are correct
- whether to include optional devices in raw recording
- which published profile to target later

The operator should not be choosing:

- new canonical role names
- topic timestamp semantics
- dataset field semantics


## Session Capture Plan Shape

The exact file format can be JSON or YAML, but the resolved object should look like this:

```yaml
schema_version: 1
session_id: session-20260323-101500
contract_version: v1

local_overlays:
  - path: data_pipeline/configs/session.local.yaml

discovered_devices:
  - device_id: realsense/130322273305
    kind: realsense
    model: Intel RealSense D405
    serial_number: "130322273305"
    enabled: true
    suggested_role: lightning_wrist_0
    resolved_role: lightning_wrist_0
  - device_id: realsense/213622251272
    kind: realsense
    model: Intel RealSense D455
    serial_number: "213622251272"
    enabled: true
    suggested_role: scene_0
    resolved_role: scene_0
  - device_id: realsense/f1380660
    kind: realsense
    model: Intel RealSense L515
    serial_number: "f1380660"
    enabled: true
    suggested_role: scene_1
    resolved_role: scene_1
  - device_id: gelsight/28D8PXEC
    kind: gelsight
    model: GelSight Mini
    serial_number: "28D8PXEC"
    enabled: true
    suggested_role: lightning_finger_left
    resolved_role: lightning_finger_left

selected_topics:
  - /spark/cameras/lightning/wrist_0/color/image_raw
  - /spark/cameras/lightning/wrist_0/depth/image_rect_raw
  - /spark/cameras/world/scene_0/color/image_raw
  - /spark/cameras/world/scene_0/depth/image_rect_raw
  - /spark/cameras/world/scene_1/color/image_raw
  - /spark/cameras/world/scene_1/depth/image_rect_raw
  - /spark/tactile/lightning/finger_left/color/image_raw
  - /spark/lightning/robot/joint_state
  - /spark/lightning/teleop/cmd_joint_state
  - /spark/thunder/robot/joint_state
  - /spark/thunder/teleop/cmd_joint_state

profile_compatibility:
  publishable_profiles:
    - lightning_minimal_v1
    - lightning_multiview_v1
  incompatible_profiles:
    - name: bimanual_dual_wrist_v1
      missing_roles:
        - thunder_wrist_0
```


## Optional Local YAML Overlay Shape

The local overlay should be broad enough to hold local defaults and rig-specific facts,
while staying out of shared semantics.

Example:

```yaml
schema_version: 1

devices:
  realsense/130322273305:
    role: lightning_wrist_0
    enabled_by_default: true
    display_label: Lightning wrist D405
    launch:
      color_profile: 640,480,30
      depth_profile: 640,480,30
    metadata:
      calibration_ref: calib://realsense/lightning_wrist_0/v2
  realsense/213622251272:
    role: scene_0
    enabled_by_default: true
    display_label: Primary overhead D455
  realsense/f1380660:
    role: scene_1
    enabled_by_default: false
    display_label: Side L515
  gelsight/28D8PXEC:
    role: lightning_finger_left
    display_label: Lightning left GelSight
    metadata:
      gel_type: marker
      calibration_ref: calib://gelsight/lightning_finger_left/v1

ui:
  viewer_base_url: http://10.33.55.65:3000
```

If geometry is needed, the same local YAML may also embed a transform directly or attach a separate geometry file reference:

```yaml
devices:
  realsense/213622251272:
    role: scene_0
    geometry:
      file: data_pipeline/calibration/scene_0.yaml
```

This keeps geometry optional without making geometry the only reason the overlay exists.


## Episode Manifest Rule

Each episode should remain self-describing.

That means the episode manifest should snapshot, at minimum:

- the enabled devices used for that episode
- their resolved canonical roles
- the optional local overlay paths used for the session
- the resolved topic list actually recorded

This avoids making old episodes depend on later edits to a local YAML file.


## Published Profile Rule

Published profiles remain necessary because a shared LeRobot dataset needs a fixed feature schema.

However:

- raw session bring-up must not be blocked just because no published profile was chosen yet
- conversion must check whether the recorded session/episode satisfies the requested published profile

So the correct order is:

- discover and record first
- publish against a fixed profile later

not:

- force every raw session to conform to one small set of predefined published profiles before recording


## Non-Goals

This design does not require:

- one new YAML file per run
- operator-defined canonical role names
- per-episode re-selection of every device role
- geometry for image-only runs
- forcing every raw recording to be immediately publishable


## Immediate Direction

The next implementation steps should be:

1. keep the shared topic/timestamp contract
2. stop treating the current `multisensor_20hz*.yaml` files as session-definition files
3. introduce an explicit session capture-plan object in the operator console/backend
4. let optional local YAML overlays provide serial-to-role defaults and other local rig/session defaults
5. keep published profiles for conversion-time schema checks

This is the smallest architecture change that removes the current rigidity without throwing away the existing V1 pipeline rules.

## First Implementation Slice

The first implemented slice is intentionally narrow:

- the operator console still uses the current fixed fields for:
  - `wrist_serial_no`
  - `scene_serial_no`
  - left/right GelSight enable and path
- a new explicit session capture-plan object is now built from those current inputs
- the operator console persists that plan under `.operator_console/capture_plans/`
- recorded episodes may snapshot that resolved plan under an optional top-level `session` section in `episode_manifest.json`

This does not fully realize runtime device discovery or flexible role assignment yet.

Its purpose is to create the missing explicit boundary so future work can replace the current rigid UI and config assumptions without again entangling session state with published profile YAMLs.

## Second Implementation Slice

The second implemented slice makes the session capture plan operational instead of purely descriptive:

- `record_episode.py` now records the session plan's `selected_topics` when `--session-plan-file ...` is provided
- `selected_extra_topics` are preserved from the session plan instead of being recomputed from the CLI
- the recorder still validates that the resolved published profile is compatible before recording
- session plans now carry:
  - `default_published_profile`
  - `discovered_devices`
  - `selected_topics`
  - `selected_extra_topics`
  - real `profile_compatibility` against all known published profiles

This is still transitional because device discovery and role assignment are not yet dynamic in the UI.

But it completes the important backend separation:

- the session plan now chooses what raw topics are recorded
- published profiles now act as compatibility/schema checks instead of being the sole thing that determines the raw topic set

## First UI Slice

The first UI slice does not attempt full runtime discovery yet.

Instead, it makes the current session-plan layer visible and honest in the operator console:

- the console now shows a `Session Plan` panel
- the panel renders either:
  - the active session plan, if a session has already been started
  - or a live form preview of the session plan derived from the current inputs
- the panel exposes:
  - default published profile
  - selected topic count
  - publishable and blocked published profiles
  - applied local overlays
  - resolved devices
  - selected topics

The same slice also brings the current form closer to the real backend config by exposing:

- `Enable RealSense`
- `Record Left GelSight`
- `Record Right GelSight`
- both left and right GelSight device paths

This is still transitional because the operator is not yet editing a true discovered-device table.

But it removes the previous opacity: the form is no longer just a bag of serial fields, and the operator can now see what session plan the backend will actually use before starting the session.

## Second UI Slice

The second UI slice makes the current session plan editable through an explicit device list.

- the operator console now uses a `Session Devices` table instead of dedicated:
  - wrist serial
  - scene serial
  - left GelSight path
  - right GelSight path
- presets populate device rows
- the Qt config derives the current legacy launch fields from that device list

This slice also fixed an important model issue in the session-plan backend:

- `selected_topics` is no longer built by blindly taking every topic referenced by the default published profile
- instead, the session plan filters sensor topics based on the enabled device roles in the session device list

That means:

- a session with no enabled GelSight devices no longer selects tactile topics
- a session with one enabled left GelSight selects left tactile topics but not right tactile topics
- a session with no enabled scene-role camera will show the profile as incompatible instead of silently carrying scene topics anyway

This is still not full hardware discovery.

But it is the first UI/backend form where:

- the operator edits an explicit device list
- the backend uses that same device list to build the session plan
- the session plan chooses the raw sensor topics that will be recorded

## Third UI Slice

The third UI slice introduces actual runtime discovery.

- RealSense discovery uses `pyrealsense2` from `.venv` when available
- GelSight discovery uses `/dev/v4l/by-id/*-video-index0`
- discovered devices are matched back through the local sensor overlay when possible so canonical roles can be suggested from lab defaults instead of guessed blindly

The operator console now uses discovery in two places:

- preset load prefers discovered devices over preset-baked serial/path values when hardware is present
- the `Session Devices` table has a `Discover Devices` button to refresh the device list

This means the current console no longer depends purely on stale preset values to know which RealSense cameras are available on the host.

The current limitations are still explicit:

- GelSight discovery is only as good as the current `/dev/v4l/by-id` names and overlay serials
- extra discovered RealSense devices without overlay matches still get heuristic role suggestions
- there is still no live preview attached to discovery

But the important boundary is now in place:

- the session device table can be populated from actual available hardware
- overlay metadata supplies stable lab meaning where possible
- the session plan and raw topic selection can now follow actual discovered devices instead of just preset literals
