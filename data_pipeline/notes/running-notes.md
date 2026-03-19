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

### Official upstream sources cloned

- Cloned `huggingface/lerobot` into the workspace so the converter can target the actual LeRobot dataset code instead of guessing its on-disk layout.
- Cloned `realsenseai/realsense-ros` and `IntelRealSense/librealsense` as the official RealSense ROS 2 wrapper and SDK sources.
- Cloned `gelsightinc/gsrobotics` as the official GelSight Mini driver/SDK reference.
- Added those checkouts to `.gitignore` so they remain local working dependencies/reference trees rather than accidental nested git repos inside this repository.

### Source integration findings

- `realsense-ros` is the correct upstream ROS 2 topic producer for RealSense and already publishes stamped image topics under its own camera namespace.
- `gsrobotics` is not a ROS package and does not publish ROS 2 topics out of the box; it is a Python SDK/demo base that still needs a thin ROS 2 wrapper for the `/spark/tactile/...` contract.
- LeRobot already contains RealSense support for direct camera access, but the V1 pipeline should still treat ROS topics and raw bags as the source of truth.

### Environment findings

- The shell default `python` points to Conda Python 3.13 in this workspace.
- ROS 2 Jazzy bindings on this machine are installed for system Python 3.12, so ROS-facing scripts must run under `/usr/bin/python3` or they will fail to import `rclpy` and `rosbag2_py`.
- That runtime split is consistent with the spec: live ROS capture should be system-ROS-native, while Conda can remain available for offline work.

### Immediate implementation direction

- Use `realsense-ros` as the upstream camera publisher base, then remap/bridge its topics into the stable `/spark/cameras/...` contract.
- Build a small ROS 2 GelSight bridge on top of `gsrobotics` to publish `/spark/tactile/{left,right}/color/image_raw` and optional raw-only derived topics with the declared timestamp semantics.
- Keep the recorder/converter under `data_pipeline/` and isolate any sensor/runtime glue from the dataset conversion logic.

### Runtime bridge implementation pass

- Added `data_pipeline/launch/realsense_contract.launch.py` to start two official RealSense ROS 2 camera nodes under the stable V1 namespace: `/spark/cameras/wrist/...` and `/spark/cameras/scene/...`.
- Added `data_pipeline/gelsight_bridge.py` as a ROS 2 node that publishes `/spark/tactile/{left,right}/color/image_raw` from the official `gsrobotics` camera path using host ROS time immediately after frame capture.
- Added `data_pipeline/launch/gelsight_contract.launch.py` to start left and right GelSight bridge processes with explicit device-path or device-index arguments.

### RealSense timestamp caveat

- Reading the official `realsense-ros` source showed that its published image stamps are derived from RealSense frame timestamps rather than the exact `host_capture_time_v1` rule declared in the V1 topic contract.
- The current launch file is still useful for getting the ROS 2 topic names, types, and camera process boundary aligned with the contract.
- We still need one follow-up pass for RealSense timestamp semantics: either patch the local wrapper checkout or replace it with a small SDK-based publisher that stamps frames immediately after `wait_for_frames()` returns.

### Validation notes

- `gelsight_bridge.py` imports and CLI parsing were validated under `/usr/bin/python3`.
- Both launch files were syntax-checked and validated with `ros2 launch ... --show-args`.
- The official `gsrobotics` camera helper imports `cv2.typing`, which is not available in the system OpenCV build here, so the ROS bridge uses a small local OpenCV capture wrapper while still reusing the official image-processing path.

### Raw-layer implementation pass

- Added `data_pipeline/pipeline_utils.py` for shared profile loading, topic selection, manifest writing, topic-type discovery, and sensor metadata helpers.
- Added `data_pipeline/record_episode.py` as the first live recorder CLI. It resolves the `/spark/...` topic set from the profile, snapshots topic types, creates the raw episode folder, seeds `episode_manifest.json` and `notes.md`, and then runs `ros2 bag record`.
- Added `data_pipeline/generate_dummy_episode.py` to write a synthetic rosbag plus matching manifest and notes in the same episode-folder shape expected by V1.
- Added `data_pipeline/__init__.py` so the scripts can be imported as a package and still run directly from the repository checkout.

### Raw-layer validation

- `record_episode.py` and `generate_dummy_episode.py` both passed `py_compile` and CLI help validation under `/usr/bin/python3`.
- `generate_dummy_episode.py` was run successfully against a temporary output root and produced:
  - `bag/bag_0.db3`
  - `bag/metadata.yaml`
  - `episode_manifest.json`
  - `notes.md`
- `ros2 bag info` on the generated dummy bag showed the expected bimanual robot, command, RealSense, and optional GelSight topics with plausible message counts and timestamps.

### Converter environment note

- The system ROS Python runtime on this machine does not currently have `pandas`, `pyarrow`, `datasets`, or `torch`.
- That means the next converter pass should either:
  - run in a dedicated offline environment that has the LeRobot dataset stack installed, or
  - start with a dependency-light alignment/diagnostics pass before wiring in final LeRobot export.

### Offline converter environment pass

- Added `data_pipeline/requirements-converter.txt` as a focused dependency set for rosbag reading and LeRobot dataset export.
- Added `data_pipeline/setup_converter_env.sh` to bootstrap the offline environment reproducibly from the repository root.
- Chose a system-Python 3.12 virtual environment with `--system-site-packages` as the baseline because it keeps `rosbag2_py` and `rclpy` compatible with the installed ROS 2 Jazzy runtime.
- The host is missing `python3.12-venv`, so the bootstrap script falls back to `virtualenv` when the stdlib `venv` path cannot seed pip.

### GPU environment decision

- Initially tested a CPU-only Torch path to keep the environment lighter.
- Switched to GPU-enabled Torch after confirming the machine has discrete GPUs and enough disk headroom to absorb the bundled CUDA runtime wheels.
- The final environment keeps the live ROS tooling on system Python and uses `.venv` only for offline conversion and LeRobot-facing work.

### Offline environment validation

- Bootstrapped `.venv` successfully with:
  - LeRobot installed editable from the local `lerobot/` checkout
  - `torch 2.6.0+cu124`
  - `torchvision 0.21.0`
  - `scipy 1.17.1`
- Verified that the same interpreter can import all of:
  - `rosbag2_py`
  - `rclpy`
  - `lerobot.datasets.lerobot_dataset`
  - `scipy`
  - `torch`
- Verified GPU visibility inside `.venv`:
  - CUDA available: `True`
  - device count: `2`
  - first device reported as `NVIDIA RTX A5500`

### Offline converter implementation pass

- Added `data_pipeline/convert_episode_bag_to_lerobot.py` as the first real raw-bag-to-LeRobot converter for the `multisensor_20hz` profile.
- The converter reads one raw episode folder, loads the manifest and profile, forms the published 20 Hz time grid, aligns state and action with `latest_before`, aligns RGB image streams with `nearest`, and writes one episode into a LeRobot dataset under `published/<dataset_id>/`.
- Conversion artifacts are written per episode under `published/<dataset_id>/meta/spark_conversion/<episode_id>/`:
  - `diagnostics.json`
  - `conversion_summary.json`
  - `effective_profile.yaml`
- Raw-only topics are still read for diagnostics, but only the published image topics are decoded into RGB frame payloads. This avoids coupling the converter to raw-only depth or derived topic encodings.
- Existing LeRobot dataset feature sets are treated as immutable. If a later episode would change the published schema for the same `dataset_id`, conversion should fail rather than silently mutate the dataset contract.

### Converter integration note

- The current LeRobot `add_frame()` path rejects a caller-supplied `timestamp` field during frame validation even though the dataset stores a default timestamp column.
- The converter therefore lets LeRobot synthesize the timestamp column from `frame_index / fps`, which still matches the fixed published 20 Hz grid declared in the spec.

### Converter validation

- `convert_episode_bag_to_lerobot.py` passed `py_compile` inside `.venv`.
- Converted the tactile-inclusive dummy episode at `/tmp/pipeline_dummy_test_run/episode-test` into `published/dummy_multisensor_v1`:
  - status: `pass`
  - published frames: `10`
  - selected image fields: wrist, scene, gelsight left, gelsight right
- Converted an RGB-only dummy episode at `/tmp/pipeline_dummy_rgbonly/episode-rgbonly` into `published/dummy_multisensor_rgbonly_v1`:
  - status: `pass`
  - published frames: `10`
  - selected image fields: wrist, scene
- Validated dataset append by converting `/tmp/pipeline_dummy_append/episode-append-a` and `/tmp/pipeline_dummy_append/episode-append-b` into the same dataset root:
  - reloaded dataset reported `2` episodes and `20` frames
  - the second conversion artifact recorded `dataset_episode_index = 1`
- Inspected the emitted diagnostics and confirmed that raw-only RealSense depth topics still appear in `topic_diagnostics` with counts and observed rates even though they are not part of the published schema.

### Runtime stamped-topic pass

- Patched `TeleopSoftware/launch.py` and `TeleopSoftware/launch_helpers/run.py` so the existing live runtime now publishes the stable stamped robot-state topics directly:
  - `/spark/{arm}/robot/joint_state`
  - `/spark/{arm}/robot/eef_pose`
  - `/spark/{arm}/robot/tcp_wrench`
  - `/spark/{arm}/robot/gripper_state`
- Those stamped state topics are emitted from the same control/update loop that already publishes the legacy unstamped topics, and they reuse a single `control_tick_time_v1` stamp per arm iteration.
- Added stamped command publishing for the Spark joint-control path at the actual `servoJ`/gripper issue point:
  - `/spark/{arm}/teleop/cmd_joint_state`
  - `/spark/{arm}/teleop/cmd_gripper_state`
- This keeps the pipeline consumer side decoupled from legacy topic schemas while giving the live runtime a real stable `/spark/...` surface.

### Runtime scope caveat

- The stable robot-state topics are now emitted continuously from the Teleop runtime loop.
- The stable command topics are currently wired for the Spark joint-control path, because that is where the actual joint command vector and derived gripper command are available in this codebase.
- Other control modes in `TeleopSoftware` still do not publish a V1-compatible joint-command topic, so the current `multisensor_20hz` action contract should still be treated as Spark-mode-first until those modes are either instrumented or split into a different published profile.

### Minimal eval path

- Added `data_pipeline/validate_eval_set.py` as a small standing-eval driver for V1.
- The eval script can:
  - generate the canonical dummy tactile episode,
  - convert it into an isolated published root,
  - optionally convert one or more user-supplied real raw episodes,
  - reload the resulting LeRobot datasets, and
  - write one machine-readable summary to `reports/evaluation_summary.json`.
- Validated the dummy-only path with:
  - `.venv/bin/python data_pipeline/validate_eval_set.py --work-root /tmp/pipeline_eval_test --clean`
- That run completed successfully and produced:
  - `entries = 1`
  - `failures = 0`
  - a published eval dataset under `/tmp/pipeline_eval_test/published/eval_dummy_multisensor_v1`
  - an eval report at `/tmp/pipeline_eval_test/reports/evaluation_summary.json`
- The script intentionally keeps the real-episode check optional unless `--require-real` is passed, so the dummy path can run in CI or on development machines without attached hardware while still supporting the standing real-episode check once one is recorded.

### RealSense timestamp resolution pass

- Revisited the RealSense timestamp problem after the offline converter and eval path were stable.
- Confirmed again from the official `realsense-ros` source that the wrapper computes image header stamps from RealSense frame timestamps and time-base conversion logic rather than from immediate host ROS time at frame acquisition.
- Tried the narrowest official-wrapper path first:
  - patched the local `realsense-ros` checkout to support a host-capture-time mode,
  - built `realsense2_camera_msgs` successfully under system Python,
  - installed missing host packages needed for wrapper and SDK work:
    - `ros-jazzy-diagnostic-updater`
    - `librealsense2`
    - `librealsense2-dev`
- That wrapper build still failed against the available SDK on this machine because the current upstream `ros2-master` wrapper expects newer librealsense APIs and stream types such as safety, occupancy, and labeled point cloud that are not present in the installed 2.56.5 SDK surface.

### Final RealSense runtime decision

- Replaced the contract launch dependency on `realsense-ros` with an in-repository ROS 2 package built directly against the official `librealsense2` SDK:
  - `data_pipeline/ros2/spark_realsense_bridge/`
- Added `spark_realsense_bridge` as a small dedicated ROS 2 node that:
  - opens one RealSense by explicit serial number,
  - publishes `color/image_raw` and optional `depth/image_rect_raw`,
  - stamps both streams with `node->now()` immediately after `pipeline.wait_for_frames()` returns,
  - preserves the same stamp across the color and depth pair from the same frameset, and
  - exposes profile and device identity as ROS parameters so the existing manifest metadata helper can still infer camera serial and model information.
- Updated `data_pipeline/launch/realsense_contract.launch.py` so it now launches two instances of this bridge under:
  - `/spark/cameras/wrist`
  - `/spark/cameras/scene`
- Added `data_pipeline/setup_realsense_contract_runtime.sh` to build the package into `install/spark_realsense_bridge`.

### RealSense bridge validation

- Built the custom package successfully with:
  - `./data_pipeline/setup_realsense_contract_runtime.sh`
- Verified the built package is visible to ROS:
  - `ros2 pkg prefix spark_realsense_bridge`
- Verified the launch file interface under the built overlay:
  - `ros2 launch data_pipeline/launch/realsense_contract.launch.py --show-args`
- Did not run a live camera acquisition test in this turn because no RealSense devices were attached to validate against.
