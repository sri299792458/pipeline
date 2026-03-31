# Dataset Mapping

## Purpose

This document defines how raw episode bags are converted into the published V2 LeRobot dataset.

The raw bag preserves asynchronous truth.
The published dataset is a fixed-rate aligned view of that raw data.


## Published Profiles

V2 publishes three profile shapes at `20 Hz`:

- `multisensor_20hz`
  - current bimanual profile
- `multisensor_20hz_lightning`
  - Lightning-only profile
- `multisensor_20hz_thunder`
  - Thunder-only profile

Current implementation note:

- the shipped default config file is still the bimanual `multisensor_20hz.yaml`
- raw recording now resolves the matching profile from the detected active-arm set
- conversion now defaults to the manifest-selected profile when `--profile` is omitted

### Why

If GelSight is a first-class published modality, then 20 Hz is the most honest default common rate. A faster published rate would either duplicate tactile frames too aggressively or claim more temporal precision than the raw streams actually support.


## Raw vs Published

The raw bag may contain one active arm or two active arms.

That does not mean all raw episodes should be coerced into one published schema.

Rules:

- raw recording should preserve whichever `/spark/...` robot topics are actually present
- published conversion must choose a profile that matches the active embodiment
- do not zero-fill the inactive arm into the bimanual profile by default
- do not append episodes from different published profiles into the same `dataset_id`

### Why

The storage cost of zero-filling an inactive arm is small, but the semantic cost is not. It mixes single-arm and bimanual behavior into one schema and makes downstream training depend on implicit padding conventions instead of explicit embodiment choice.


## Profile Selection

For each raw episode:

1. Inspect which arm-specific state and command topic sets are actually present and usable.
2. Choose exactly one published profile:
   - if both `lightning` and `thunder` have valid state and action streams, use `multisensor_20hz`
   - if only `lightning` has a valid state and action stream, use `multisensor_20hz_lightning`
   - if only `thunder` has a valid state and action stream, use `multisensor_20hz_thunder`
3. Fail conversion if the arm presence is ambiguous or inconsistent.

Examples of inconsistent episodes that should fail:

- `lightning` state exists but `lightning` action does not
- `thunder` action exists but `thunder` state does not
- an arm comes and goes in a way that makes the published profile ambiguous for the episode


## Canonical Published Time Grid

For each raw episode:

1. Load all required published streams.
2. Compute:
   - `t_start = max(first timestamp of each required published stream)`
   - `t_end = min(last timestamp of each required published stream)`
3. Define:
   - `t_k = t_start + k / 20.0`
4. Keep frame indices while `t_k <= t_end`.

### Why

This creates one explicit frame timeline for the published episode. The timeline is no longer implicit in whichever modality happened to be processed first. This is the cleanest form for LeRobot and for downstream learning code.


## Published Observation Schema

V2 publishes:

- `observation.state`
- `action`
- `observation.images.wrist`
- `observation.images.scene`
- `observation.images.gelsight_left` when present
- `observation.images.gelsight_right` when present

### Why

This is the smallest multimodal schema that still captures the key training signal:

- robot state
- commanded action
- scene RGB
- wrist RGB
- tactile RGB

For the bimanual setup, `multisensor_20hz` uses a fixed arm order:

1. `lightning`
2. `thunder`

That ordering must not change across episodes.
This profile is explicitly bimanual.

Depth and other derived products remain available in the raw layer without burdening the first public dataset contract.

For the single-arm profiles:

- `multisensor_20hz_lightning` publishes only the Lightning low-dimensional state/action slice
- `multisensor_20hz_thunder` publishes only the Thunder low-dimensional state/action slice
- both keep the same image-field rules as the bimanual profile
- both keep the real arm-specific field names instead of renaming to generic placeholders


## Observation State Definition

The current bimanual `multisensor_20hz` profile uses this flat `observation.state` order:

### `lightning`

1. `lightning_joint_pos_1`
2. `lightning_joint_pos_2`
3. `lightning_joint_pos_3`
4. `lightning_joint_pos_4`
5. `lightning_joint_pos_5`
6. `lightning_joint_pos_6`
7. `lightning_eef_x`
8. `lightning_eef_y`
9. `lightning_eef_z`
10. `lightning_eef_rx`
11. `lightning_eef_ry`
12. `lightning_eef_rz`
13. `lightning_gripper_position`
14. `lightning_ft_fx`
15. `lightning_ft_fy`
16. `lightning_ft_fz`
17. `lightning_ft_tx`
18. `lightning_ft_ty`
19. `lightning_ft_tz`

### `thunder`

20. `thunder_joint_pos_1`
21. `thunder_joint_pos_2`
22. `thunder_joint_pos_3`
23. `thunder_joint_pos_4`
24. `thunder_joint_pos_5`
25. `thunder_joint_pos_6`
26. `thunder_eef_x`
27. `thunder_eef_y`
28. `thunder_eef_z`
29. `thunder_eef_rx`
30. `thunder_eef_ry`
31. `thunder_eef_rz`
32. `thunder_gripper_position`
33. `thunder_ft_fx`
34. `thunder_ft_fy`
35. `thunder_ft_fz`
36. `thunder_ft_tx`
37. `thunder_ft_ty`
38. `thunder_ft_tz`

### Why

This keeps all robot-side low-dimensional state in one compact feature, which is the easiest shape for LeRobot-style datasets and policy code. It also avoids prematurely creating many custom low-dimensional namespaces.

For both arms:

- `*_gripper_position` is normalized measured opening on `0..1`
- `0.0 = fully open`
- `1.0 = fully closed`


## Action Definition

The current bimanual `multisensor_20hz` profile uses this flat `action` order:

### `lightning`

1. `lightning_cmd_joint_1`
2. `lightning_cmd_joint_2`
3. `lightning_cmd_joint_3`
4. `lightning_cmd_joint_4`
5. `lightning_cmd_joint_5`
6. `lightning_cmd_joint_6`
7. `lightning_cmd_gripper`

### `thunder`

8. `thunder_cmd_joint_1`
9. `thunder_cmd_joint_2`
10. `thunder_cmd_joint_3`
11. `thunder_cmd_joint_4`
12. `thunder_cmd_joint_5`
13. `thunder_cmd_joint_6`
14. `thunder_cmd_gripper`

### Why

The V2 action is the command sent by the teleoperation/runtime stack. This is more stable and more semantically honest than silently replacing action with a derived delta later in the pipeline.

For both arms:

- `*_cmd_gripper` is commanded gripper opening on `0..1`
- `0.0 = fully open`
- `1.0 = fully closed`

For the single-arm profiles, use the corresponding per-arm slice only.


## Per-Topic Alignment Rules

### Robot state

Sources:

- `/spark/lightning/robot/joint_state`
- `/spark/lightning/robot/eef_pose`
- `/spark/lightning/robot/tcp_wrench`
- `/spark/lightning/robot/gripper_state`
- `/spark/thunder/robot/joint_state`
- `/spark/thunder/robot/eef_pose`
- `/spark/thunder/robot/tcp_wrench`
- `/spark/thunder/robot/gripper_state`

Alignment rule:

- choose the latest sample with timestamp `<= t_k`

Validity threshold:

- max age 50 ms

### Why

Robot state is causal and should not look into the future relative to the published frame time. Latest-before is the correct rule for a state signal that is being sampled onto a coarser grid.


### Action

Sources:

- `/spark/lightning/teleop/cmd_joint_state`
- `/spark/lightning/teleop/cmd_gripper_state`
- `/spark/thunder/teleop/cmd_joint_state`
- `/spark/thunder/teleop/cmd_gripper_state`

Alignment rule:

- choose the latest sample with timestamp `<= t_k`

Validity threshold:

- max age 50 ms

### Why

Action is also causal. A nearest-future command would make the published sample look as though the system already knew a command that had not yet been issued.

### Teleop activity mask

Raw source:

- `/spark/session/teleop_active`

Alignment rule:

- treat the Boolean value as a zero-order-held teleop-activity signal until the next sample
- keep published frames only while the held value is `true`

### Why

The action topics encode what command was issued, not whether the operator intended teleoperation to be active continuously. When the foot pedal is intentionally released in the middle of a raw episode, those pedal-off spans should be removed from the published demonstration rather than counted as stale-action failures.


### Wrist and scene RGB

Sources:

- `/spark/cameras/lightning/wrist_1/color/image_raw`
- `/spark/cameras/world/scene_1/color/image_raw`

Alignment rule:

- choose the nearest sample to `t_k`

Validity threshold:

- max skew 25 ms

### Why

Image streams are observations, not control signals. Nearest is the correct rule for selecting the frame that best represents the scene around the target time.


### GelSight RGB

Sources:

- `/spark/tactile/lightning/finger_left/color/image_raw`
- `/spark/tactile/lightning/finger_right/color/image_raw`

Alignment rule:

- choose the nearest sample to `t_k`

Validity threshold:

- max skew 25 ms

### Why

GelSight RGB is treated like a tactile image stream. Nearest-to-grid keeps the published episode visually coherent without pretending tactile updates happen exactly on the grid.


## Missing Data Policy

If a required modality is outside its validity threshold:

- if the failure occurs only at the episode tail, truncate the episode at the last valid frame
- otherwise fail conversion for that episode

Exception:

- frames masked out by the teleop-activity signal are not treated as failures
- they are removed from the published timeline before action-age validity is applied

### Why

Silent filling of large gaps hides real collection problems and makes the dataset look healthier than it is. Tail truncation is acceptable because it only shortens the usable interval. Mid-episode failures should be made explicit.


## Raw-Only Modalities

The following topics remain raw-only in V2:

- `/spark/cameras/lightning/wrist_1/depth/image_rect_raw`
- `/spark/cameras/world/scene_1/depth/image_rect_raw`
- `/spark/tactile/lightning/finger_left/depth/image_raw`
- `/spark/tactile/lightning/finger_right/depth/image_raw`
- `/spark/tactile/lightning/finger_left/marker_offset`
- `/spark/tactile/lightning/finger_right/marker_offset`
- `/spark/session/teleop_active`
- optional point cloud or debugging topics

### Why

These topics are valuable to preserve, but they complicate the first published dataset contract without being necessary for the first training and visualization workflows.


## Multi-Sensor Rules

V2 supports:

- multiple RealSense sensors
- multiple GelSight sensors

The published profile only includes the sensors explicitly declared in the mapping config.

The raw manifest should still preserve every recorded sensor as a sensor instance with:

- `sensor_key`
- `serial_number`

### Why

Support for multiple sensors comes from the raw-first design, not from trying to cram every modality into one live fused message. The mapping profile keeps the published contract small while still allowing the raw bag to preserve richer sessions.


## Conversion Outputs

For each raw episode, conversion produces:

- one published episode in the shared LeRobot dataset
- episode-level diagnostics

Diagnostics should include:

- usable interval
- number of published frames
- per-modality alignment error summary
- count of invalid or dropped frames

### Why

A successful conversion should mean more than "the script finished." We need enough diagnostics to judge whether the episode quality is acceptable.
