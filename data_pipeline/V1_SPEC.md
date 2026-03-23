# Data Pipeline V1 Spec

## 1. Goal

Build a clean data collection and conversion pipeline inside `data_pipeline/`.

V1 is for:

- recording demos
- preserving raw ROS data
- converting demos into published LeRobot datasets with fixed per-dataset schemas

V1 is not for:

- live policy inference
- controller logic
- runtime latency compensation
- audio/contact microphones
- multi-episode segmentation inside one bag


## 2. Boundary

- `TeleopSoftware/` remains the legacy topic producer.
- `data_pipeline/` owns recording, metadata, conversion, and validation.
- New pipeline code should depend on ROS topics, config files, and its own metadata.
- New pipeline code should not depend on legacy teleop internals as a library.


## 3. Runtime Base

- Use the `main` branch runtime as the starting point.
- Port any missing command topics we need from `data_collection`.
- Do not reuse `data_collection.py`.

### Why

`main` is the cleaner runtime base. `data_collection.py` is the part we are replacing.


## 4. Environment

- Use system ROS 2 Jazzy for live topic production and bag recording.
- Conda or other Python environments are fine for offline conversion, inspection, and training.
- Live ROS capture must not depend on Conda activation.


## 5. Recording Unit

- one demo = one rosbag = one raw episode

This means:

- bag start = episode start
- bag stop = episode end
- no in-bag episode boundary logic in V1


## 6. Directory Layout

V1 work lives under `data_pipeline/`.

Expected files:

- `data_pipeline/V1_SPEC.md`
- `data_pipeline/docs/topic-contract.md`
- `data_pipeline/docs/dataset-mapping.md`
- `data_pipeline/docs/session-capture-plan.md`
- `data_pipeline/configs/multisensor_20hz.yaml`
- `data_pipeline/record_episode.py`
- `data_pipeline/convert_episode_bag_to_lerobot.py`
- `data_pipeline/generate_dummy_episode.py`

Longer-term architecture direction is defined in [docs/session-capture-plan.md](./docs/session-capture-plan.md).

That document separates:

- shared contract
- session capture plan
- published profile
- optional local YAML overlays

The current implementation does not fully realize that separation yet, but future changes should move in that direction rather than deepening the current rigid session model.


## 7. Raw Output

Each episode is stored as:

```text
raw_episodes/
  episode-YYYYMMDD-HHMMSS/
    bag/
    episode_manifest.json
    notes.md
```

`episode_manifest.json` should be the single resolved per-episode snapshot.

It should use these top-level sections:

- `manifest_schema_version`
- `episode`
- `session` (optional)
- `profile`
- `capture`
- `sensors`
- `recorded_topics`
- `provenance`

Minimum expectations for each section:

- `episode`
  - `episode_id`
  - `dataset_id`
  - `task_name`
  - `language_instruction` (optional, recommended for language-conditioned training)
  - `robot_id`
  - `active_arms`
  - `operator`
- `profile`
  - `name`
  - `version`
  - `path`
  - `clock_policy`
- `session`
  - `session_id`
  - `active_arms`
  - `local_overlays`
  - `resolved_devices`
  - `planned_topics`
  - `profile_compatibility`
- `capture`
  - `start_time_ns`
  - `end_time_ns`
  - `storage`
    - `bag_storage_id`
    - `bag_storage_preset_profile`
  - `record_exit_code`
  - `raw_trim`
- `sensors`
  - `inventory_version`
  - `devices`
- `recorded_topics`
  - one resolved entry per topic actually recorded in the bag
- `provenance`
  - `git_commit`

Each entry under `sensors.devices` should stay minimal and include only:

- `sensor_id`
- `modality`
- `attached_to`
- `mount_site`
- `topic_names`
- `serial_number`
- `model`
- `calibration_ref`

For RealSense cameras, serial number is required.

For tactile sensors, the raw manifest may also include a small provenance extension when available at capture time:

- `device_path` or `device_index`
- `frame_id`
- `encoding`
- `fps`
- `capture_width`
- `capture_height`
- `output_width`
- `output_height`
- `preprocessing`
  - `pipeline`
  - `border_fraction`
  - `crop_applied`

This tactile extension is intentionally narrow:

- keep the source tactile image as the canonical raw signal
- record only the preprocessing needed to understand that signal later
- do not require derived depth, marker offsets, slip fields, or vague placeholder calibration labels with no backing artifact

`sensor_id` is the raw-layer stable identifier. Published dataset field names may change later, but `sensor_id` and the attachment fields should make it possible to remap old raw episodes without ambiguity.

If `language_instruction` is present, the converter should use it as the published task string. Otherwise it should fall back to `task_name`.

Raw bag storage defaults are defined in [docs/raw-storage.md](./docs/raw-storage.md):

- record raw bags as `mcap`
- use `zstd_fast`
- keep the raw layer lossless

Published depth storage is defined separately in [docs/depth-storage.md](./docs/depth-storage.md):

- keep published RGB in the normal LeRobot path
- publish RealSense depth as a lossless sidecar
- do not force depth into the current RGB video feature path

Published conversion also relies on a raw teleop-activity signal defined in [docs/topic-contract.md](./docs/topic-contract.md):

- record `/Spark_enable/lightning` for new raw episodes
- use it only as a conversion-time activity mask
- do not treat it as the published action
- do not split one raw episode into multiple published episodes because of pedal-off pauses


## 8. Raw Layer Rule

The raw layer is the source of truth.

That means:

- record stamped raw topics
- preserve native per-topic rates
- do not force all topics to one live fused stream
- do not overwrite raw timing semantics during recording


## 9. Topic Contract

Every topic we may care about later must satisfy both:

- it is recorded raw in the bag
- its timestamp meaning is documented in `topic-contract.md`

Each topic entry must document:

- topic name
- message type
- producer node
- semantic type: sensor, state, command, derived, debug
- timestamp meaning
- expected rate
- required or optional
- raw-only or published

The stable V1 topic surface should be under `/spark/...`.
Legacy `/lightning_*` topics are bridge inputs, not the long-term contract.


## 10. Robot Topics

V1 does not require a mandatory fused robot topic.

Primary rule:

- preserve stamped raw robot state topics
- preserve stamped raw robot command topics

An optional convenience topic like `/spark/robot_frame` can be added later, but it is not required for V1.


## 11. Arm Presence

The hardware setup is bimanual, but an individual raw episode may be:

- `lightning` only
- `thunder` only
- `lightning` + `thunder`

V1 raw recording must therefore:

- tolerate one active arm or two active arms
- preserve whichever stamped robot topics are actually present
- record the active-arm set as episode metadata

V1 published conversion must not zero-fill an inactive arm just to force all episodes into one dataset schema.

Instead:

- the current `multisensor_20hz` profile is the bimanual published profile
- single-arm published profiles should be separate profiles:
  - `multisensor_20hz_lightning`
  - `multisensor_20hz_thunder`
- a given `dataset_id` must contain episodes from exactly one published profile

If both arms are published into `observation.state` or `action`, the mapping profile must define a fixed arm order.


## 12. Timestamp Policy

V1 uses one canonical policy:

- `clock_policy = host_capture_time_v1`

Meaning:

- RealSense topics are stamped with host ROS time immediately after frame acquisition
- GelSight topics are stamped with host ROS time immediately after raw image acquisition
- robot measured state topics are stamped at the update tick they represent
- robot command topics are stamped when the command is issued

If a device exposes richer hardware timestamps, those may be recorded as extra metadata or diagnostics, but they are not the canonical alignment clock in V1.


## 13. Device Rules

### RealSense

- record RGB
- record depth
- stamp immediately after frame acquisition
- log sensor serial number in metadata

### GelSight

- record tactile RGB
- if depth, marker offsets, or point clouds already exist, they may also be recorded raw
- stamp immediately after raw image acquisition
- reconstruction latency must not define the canonical timestamp

### Robot

- record measured state topics
- record command topics
- keep state and command as distinct semantic classes


## 14. Published Dataset

V1 publishes a small family of aligned LeRobot profiles, all at `20 Hz`:

- `mapping_profile = multisensor_20hz`
  - current bimanual profile
- `mapping_profile = multisensor_20hz_lightning`
  - planned Lightning-only profile
- `mapping_profile = multisensor_20hz_thunder`
  - planned Thunder-only profile

Current implementation note:

- the shipped default config file is still `multisensor_20hz.yaml`
- raw recording now resolves the matching profile from the detected active-arm set
- conversion now defaults to the manifest-selected profile when `--profile` is omitted

Rules:

- do not append episodes from different published profiles into the same `dataset_id`
- raw bags may be recorded first and routed to the matching published profile later
- published profile choice is an embodiment decision, not a storage optimization trick

Why `20 Hz`:

- it matches the slower tactile-first multimodal setup better than pretending the dataset is 30 Hz


## 15. Published Schema

Keep the V1 published schema small:

- `observation.state`
- `action`
- `observation.images.wrist`
- `observation.images.scene`
- `observation.images.gelsight_left`
- `observation.images.gelsight_right`

Only include the GelSight image streams that actually exist in the recording setup.

For arm state/action fields:

- the bimanual `multisensor_20hz` profile contains both `lightning` and `thunder` slices in a fixed order
- the single-arm profiles contain only the active arm slice
- single-arm profiles should keep the real arm identity in field names rather than renaming to a generic `arm_*`
- do not zero-fill an inactive arm into the bimanual schema by default

Recommended `observation.state` contents:

- joint positions
- end-effector pose
- gripper position normalized to `0..1` with `0=open`, `1=closed`
- force-torque values

Recommended `action` contents:

- teleop/runtime command sent to the robot
- commanded gripper value on the same `0..1` scale with `0=open`, `1=closed`


## 16. Raw-Only vs Published

Record in raw by default:

- RealSense RGB
- RealSense depth
- GelSight RGB
- robot state topics
- robot command topics

Keep raw-only in V1:

- RealSense depth
- GelSight reconstructed depth
- GelSight point clouds
- GelSight marker offsets
- debug topics

Publish in V1:

- RealSense RGB
- GelSight RGB
- robot state mapped into `observation.state`
- command mapped into `action`


## 17. Alignment Rules

For each episode:

1. Determine the usable interval:
   - `t_start = max(first timestamp of each required published modality)`
   - `t_end = min(last timestamp of each required published modality)`
2. Define the frame grid:
   - `t_k = t_start + k / 20.0`
3. Align each modality onto that grid:
   - robot state: latest sample with timestamp `<= t_k`
   - action: latest sample with timestamp `<= t_k`
   - RGB cameras: nearest sample to `t_k`
   - GelSight RGB: nearest sample to `t_k`

Default thresholds:

- robot state max age: `50 ms`
- action max age: `50 ms`
- camera max skew: `25 ms`
- GelSight max skew: `25 ms`

If a required modality is missing within threshold:

- trim the episode tail if the failure is only at the end
- otherwise fail conversion for that episode


## 18. Diagnostics

Each conversion run must save machine-readable artifacts, not just terminal output.

At minimum:

- `diagnostics.json`
- effective mapping profile snapshot
- conversion summary: `pass`, `fail`, or `truncated_tail`

Diagnostics should include at least:

- per-topic observed rate
- inter-arrival statistics
- max skew per modality
- invalid or skipped frame count
- episode duration
- published frame count


## 19. Minimal Eval Path

V1 should keep a very small standing eval set:

- at least one dummy episode
- at least one real episode

Every meaningful converter or contract change should be checked against that set.

Keep this simple. V1 does not need a large eval framework.


## 20. Success Criteria

V1 is successful when:

- one demo can be recorded as one raw rosbag episode
- episode metadata is complete and includes sensor identity
- raw topics preserve native timing and timestamp semantics
- raw episodes can be converted into one valid LeRobot dataset
- the published dataset loads without ROS dependencies
- multiple RealSense and GelSight sensors can coexist under the same timestamp policy
- converter output includes diagnostics


## 21. Implementation Order

Build in this order:

1. finalize the `/spark/...` topic contract
2. bridge legacy runtime topics into that contract where needed
3. implement `record_episode.py`
4. implement `generate_dummy_episode.py`
5. implement `convert_episode_bag_to_lerobot.py`
6. validate on dummy data
7. validate on one real recorded episode


## 22. Short Version

V1 is intentionally simple:

- one demo per bag
- raw bag is truth
- one honest published profile at 20 Hz
- one shared host-capture timestamp policy
- small published schema
- depth and derived tactile stay raw-only
- sensor identity is logged
- diagnostics are saved
