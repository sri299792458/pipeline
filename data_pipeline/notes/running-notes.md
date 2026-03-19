# Running Notes

## 2026-03-19

### Initial setup

- Initialized git at the repo root.
- Created working branch `codex/data-pipeline-v1`.
- Added `data_pipeline/` as the home for the new collection and conversion stack.
- Wrote the first version of the V1 architecture spec in [V1_SPEC.md](C:/Users/srini/Desktop/spark/SPARK-Remote-main/data_pipeline/V1_SPEC.md).
- Cleaned temporary external research clones from the top-level `spark/` workspace after the survey phase.

### What was intentionally not changed

- Did not modify `TeleopSoftware/` yet.
- Did not remove `Hardware/` or `TeleopSoftware/`, because they are still part of the legacy runtime boundary and may be needed as topic producers or reference implementations.
- Did not add implementation code yet; only architecture and workspace scaffolding were created.

### Temporary research clones removed

- `FACTR_Teleop`
- `FastUMI_Data`
- `FFTAI_teleoperation`
- `gello_software`
- `gelsight_mini_ros2_community`
- `gsmini_community`
- `gsrobotics_legacy`
- `gsrobotics_official`
- `lerobot_realsense_ros`
- `reactive_diffusion_policy`
- `universal_manipulation_interface`

### Current working assumptions

- `main` branch runtime remains the ROS topic producer.
- `data_pipeline/` will own raw episode recording, metadata, and conversion to a published LeRobot dataset.
- One demo will map to one rosbag and one raw episode folder.
- V1 canonical clock policy is `host_capture_time_v1`.
- V1 published profile target is `multisensor_20hz`.

### Immediate next implementation steps

- Write the topic contract with explicit timestamp semantics.
- Write the dataset mapping document for raw-to-published feature rules.
- Define the first `multisensor_20hz.yaml` profile.
- Implement episode recording and conversion against the declared contracts.

### Contract files added

- Added [topic-contract.md](C:/Users/srini/Desktop/spark/SPARK-Remote-main/data_pipeline/docs/topic-contract.md).
- Added [dataset-mapping.md](C:/Users/srini/Desktop/spark/SPARK-Remote-main/data_pipeline/docs/dataset-mapping.md).
- Added [multisensor_20hz.yaml](C:/Users/srini/Desktop/spark/SPARK-Remote-main/data_pipeline/configs/multisensor_20hz.yaml).

### What these files currently lock down

- Stable V1 topic surface uses stamped standard ROS message types under `/spark/...`.
- Legacy `/lightning_*` topics are documented only as bridge inputs, not as the long-term pipeline contract.
- Published V1 schema is limited to `observation.state`, `action`, and RGB image streams.
- RealSense depth and GelSight derived outputs remain raw-only in V1.
- Alignment rules are fixed-grid at 20 Hz with explicit latest-before and nearest policies.
- `episode_manifest.json` must carry per-sensor metadata, including RealSense serial numbers, model, fps, and calibration references when available.

### Second spec pass

- Tightened the spec around small-surface-area V1 scope: one raw path, one published profile, one narrow schema, one standing eval set.
- Reworded the runtime environment rule so Conda is allowed for offline work but not required for live ROS capture.
- Added a canonical-topic rule to reduce overlapping topic aliases in the stable `/spark/...` surface.
- Added explicit bimanual stability guidance: fixed arm ordering must come from the mapping profile.
- Added standing eval-set requirements and manual spot-check expectations to the success criteria.
- Required conversion artifacts like `diagnostics.json` and effective-profile snapshots for every run.
- Refined the eval section so V1 tracks graded quality metrics, not just binary converter success.

### Lean spec pass

- Replaced the longer architecture-style spec with a shorter implementation spec.
- Kept only decisions that directly affect v1 build order, topic semantics, metadata, alignment, and diagnostics.
- Preserved the core constraints: one demo per bag, host-capture timestamp policy, `multisensor_20hz`, raw-first design, and small published schema.

### Bimanual contract pass

- Updated the topic contract so robot and teleop topics are arm-scoped for both `lightning` and `thunder`.
- Updated the dataset mapping and `multisensor_20hz.yaml` so the published profile uses a fixed arm order: `lightning` then `thunder`.
- Made the first published profile explicitly bimanual rather than leaving the arm semantics implicit.

### GitHub prep pass

- Expanded `.gitignore` for Python, ROS/colcon, editor, and dataset artifacts so the repo is easier to move between Windows and Ubuntu.
- Updated the root `README.md` to point new work toward `data_pipeline/`.

### Cleanup pass

- Removed `data_pipeline/AGENTS.md` to keep the repository from spreading intent across too many files.
- Kept the source of truth concentrated in `V1_SPEC.md`, the contract docs, the mapping YAML, and `running-notes.md`.
