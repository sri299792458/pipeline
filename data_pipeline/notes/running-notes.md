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

### Teleop hardware-tuning sync pass

- Compared the current `TeleopSoftware/` runtime against the hardware-tested `SPARK-Remote-data_collection` branch and ported the teleop-side calibration deltas without removing the newer stamped `/spark/...` publishers.
- Updated arm ordering in `TeleopSoftware/launch.py` to `Lightning` then `Thunder`, matching the tested branch and the published fixed-arm ordering already used by the data pipeline profile.
- Replaced the generic degree-based UR home positions with the measured radian home values from the tested branch.
- Added the legacy `/{arm}_spark_command_angles` and `/{arm}_spark_command_gripper` publishers back into `TeleopSoftware/launch.py` so the legacy raw topic surface matches the tested hardware branch alongside the stable stamped topics.
- Ported the tested Spark-to-UR offset tables, trigger calibration ranges, and Lightning visualization transform into `TeleopSoftware/launch_helpers/run.py`.
- Updated `TeleopSoftware/UR/arms.py` so `enable_grippers` can be either a boolean or a per-arm map, matching the tested branch structure without breaking the existing call sites.
- Intentionally left the `lightning_spark_enable` topic-selection bug unchanged for now because it exists in the tested branch as well; this sync pass is preserving calibrated behavior rather than changing control semantics.

### Teleop bring-up findings

- The host system Python had `rclpy` but did not have `ur_rtde`; the existing Conda interpreters had the opposite problem and could not load the ROS 2 Jazzy bindings.
- Installed `ur_rtde` only into the local `.venv`, which already had working ROS bindings, so the current non-actuating Teleop bring-up path is `source /opt/ros/jazzy/setup.bash && .venv/bin/python TeleopSoftware/launch.py`.
- Live launch testing showed both robot dashboards are reachable, but RTDE control is refused until remote control is enabled on the robot side.
- The Teleop GUI previously crashed in the main loop if an arm failed RTDE initialization because `ros_update()` always dereferenced `URs.get_receive(arm)`.
- Patched `TeleopSoftware/UR/arms.py` and `TeleopSoftware/launch_helpers/run.py` so the GUI stays up and continues advertising the expected raw and stamped topics even when RTDE receive interfaces are missing.
- Verified live topic advertisement from `/gui_node` after the crash fix:
  - `/lightning_spark_command_angles`
  - `/lightning_spark_command_gripper`
  - `/thunder_spark_command_angles`
  - `/thunder_spark_command_gripper`
  - `/spark/lightning/robot/*`
  - `/spark/lightning/teleop/*`
  - `/spark/thunder/robot/*`
  - `/spark/thunder/teleop/*`

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

## 2026-03-20

### Single-arm vs bimanual profile decision

- Hardware bring-up made the profile boundary concrete: the raw capture path should tolerate either one active arm or two active arms, but the published LeRobot datasets should remain embodiment-specific.
- Rejected the idea of zero-filling the inactive arm into the bimanual schema by default. The storage overhead would be tiny, but the semantic cost would be high because it would mix single-arm and bimanual behavior in one dataset contract.
- Locked in the intended published split:
  - `multisensor_20hz`
    - current bimanual profile
  - `multisensor_20hz_lightning`
    - planned Lightning-only profile
  - `multisensor_20hz_thunder`
    - planned Thunder-only profile
- Added the corresponding documentation rule: one `dataset_id` should contain episodes from exactly one published profile.
- Preserved the current bimanual `multisensor_20hz.yaml` config, but documented that it should now be treated explicitly as the bimanual published profile rather than the universal raw-capture shape.

### Implementation consequence

- The next pipeline change should separate raw-capture topic selection from published-profile selection.
- Raw recording should record the available `/spark/...` topic surface and store active-arm metadata.
- Published conversion should choose the matching embodiment profile and write into the corresponding dataset instead of padding into a larger schema.

### Profile-split implementation pass

- Added `data_pipeline/configs/multisensor_20hz_lightning.yaml` and `data_pipeline/configs/multisensor_20hz_thunder.yaml` as the single-arm published profiles alongside the existing bimanual `multisensor_20hz.yaml`.
- Extended `data_pipeline/pipeline_utils.py` with active-arm normalization, active-arm probing from live `/spark/{arm}/robot/joint_state` messages, and published-profile resolution based on the detected embodiment.
- Updated `data_pipeline/record_episode.py` so `--active-arms auto` now probes which robot-state topics are actually producing messages, resolves the matching published profile, and records `active_arms` plus the selected `mapping_profile` in the raw manifest.
- Updated `data_pipeline/convert_episode_bag_to_lerobot.py` so omitting `--profile` now means "use the manifest-selected profile", and conversion validates `active_arms` against the loaded profile instead of assuming the bimanual default.
- Updated `data_pipeline/generate_dummy_episode.py` so dummy bags honor the selected profile's active arms, which keeps eval and schema validation meaningful for both single-arm and bimanual cases.
- Updated `data_pipeline/validate_eval_set.py` so real-episode validation can use the manifest-selected profile automatically instead of forcing the bimanual default.

### Validation

- `py_compile` passed for:
  - `pipeline_utils.py`
  - `record_episode.py`
  - `convert_episode_bag_to_lerobot.py`
  - `generate_dummy_episode.py`
  - `validate_eval_set.py`
- Re-ran dummy conversion for the bimanual profile:
  - dataset feature shapes remained `observation.state=(38,)`, `action=(14,)`
- Ran a Lightning-only dummy conversion without passing `--profile` to the converter:
  - manifest recorded `mapping_profile=multisensor_20hz_lightning`
  - dataset feature shapes were `observation.state=(19,)`, `action=(7,)`

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

### Workflow documentation pass

- Added `data_pipeline/configs/sensors.example.yaml` so the `--sensors-file` path in `record_episode.py` has a concrete starting template for inventory serials and calibration references.
- Added `data_pipeline/README.md` as a minimal operator runbook covering:
  - environment setup,
  - RealSense bridge build,
  - contract sensor launch using the existing per-sensor entrypoints,
  - raw recording,
  - single-episode conversion, and
  - standing eval usage.
- Updated the repository root `README.md` so the data-pipeline section now points readers to the new runbook first instead of only the spec and notes.
- Deliberately did not keep extra orchestration or batch-conversion wrappers before hardware validation; the runtime surface remains the existing recorder, converter, eval script, and per-sensor launch entrypoints.

### Hardware bring-up doc pass

- Added `data_pipeline/docs/hardware-bringup.md` as the explicit first-real-run checklist.
- Kept that guide procedural and narrow:
  - one-time environment setup,
  - device-ID discovery,
  - Teleop runtime bring-up,
  - RealSense and GelSight contract launch,
  - recorder dry-run,
  - short smoke-test recording,
  - bag and manifest inspection,
  - offline conversion, and
  - standing real-episode eval.
- Updated `data_pipeline/README.md` to point directly to the new hardware bring-up guide.

### RealSense hardware-debug pass

- On this machine, the immediate RealSense blocker was lower than ROS:
  - both cameras showed up in `lsusb`,
  - but their USB video interfaces were initially unbound from `uvcvideo`,
  - so neither the custom bridge nor the ROS-packaged wrapper could see working devices.
- Confirmed this by inspecting `lsusb -t`, which showed the RealSense video interfaces as `Driver=[none]` while GelSight was already bound to `uvcvideo`.
- Added `data_pipeline/bind_realsense_uvc.sh` as the repeatable hardware-bootstrap step that binds unclaimed RealSense video interfaces to `uvcvideo`.
- After binding:
  - `/dev/video*` nodes appeared for both the L515 and the D405,
  - `/dev/v4l/by-id/` gained stable RealSense symlinks,
  - `v4l2-ctl --list-devices` showed both cameras,
  - and `rs-enumerate-devices` started seeing the D405.

### Official RealSense runtime correction

- Re-checked the official `realsense2_camera` path from a clean local source tree and from the distro-installed ROS package.
- The official wrapper already publishes `/color/metadata` and `/depth/metadata` topics whose JSON payload includes:
  - `clock_domain`
  - `frame_timestamp`
  - `time_of_arrival`
  - `backend_timestamp`
  - `hw_timestamp`
- Live D405 probing showed the stock wrapper currently stamps `Image.header.stamp` from `frame_timestamp` rather than `time_of_arrival`.
- Live D405 probing also showed that this distro wrapper publishes the color topic as `color/image_rect_raw`, so the V1 launch wrapper now remaps that private topic to the stable contract name `color/image_raw`.
- Measured one live D405 sample and confirmed:
  - `header.stamp == frame_timestamp`
  - `time_of_arrival` trails by a small positive delta on this host
- Updated the V1 converter so that when the official RealSense metadata topics are present in the bag, the corresponding RealSense image series uses `time_of_arrival` for alignment instead of the wrapper header stamp.
- Updated the published profile so the recorder keeps these official metadata topics in the raw bag:
  - `/spark/cameras/wrist/color/metadata`
  - `/spark/cameras/wrist/depth/metadata`
  - `/spark/cameras/scene/color/metadata`
  - `/spark/cameras/scene/depth/metadata`

### L515 limitation on this host

- The current upstream `realsense-ros` line removed L500/L515 support starting in `4.55.1`; this is documented in the upstream changelog.
- The distro-installed ROS wrapper on this machine is `realsense2_camera v4.56.4`, so it is already on the post-L500-removal line.
- Stock probing with:
  - `ros2 launch realsense2_camera rs_launch.py ... serial_no:=_00000000F1380660`
  - and `rs-enumerate-devices -s`
  still sees only the D405 and not the L515.
- A previous `realsense-viewer --debug` log that looked like "2 RealSense devices" turned out to be misleading:
  - one of the two device paths was actually the attached GelSight USB camera path, not the L515 path
  - so that log should not be interpreted as proof that the stock ROS/runtime stack can currently use the L515 on this host
- Current practical state:
  - official ROS path for D405 wrist camera: usable
  - official ROS path for L515 scene camera: still blocked on this host
  - converter-side timestamp semantics for official RealSense metadata: implemented

### Runtime cleanup after the official-path switch

- Removed the abandoned active fallback artifacts from the current working tree:
  - `data_pipeline/ros2/spark_realsense_bridge/`
  - `data_pipeline/v4l_camera_bridge.py`
  - `data_pipeline/launch/realsense_v4l_contract.launch.py`
  - `data_pipeline/bind_realsense_uvc.sh`
- Older notes above that mention those pieces are retained as historical debug context only; they are no longer the intended V1 runtime path.
- The custom C++ `spark_realsense_bridge` is still not usable:
  - it segfaults during ROS FastDDS participant creation before camera startup,
  - and the currently installed system `librealsense2` exports embedded FastDDS symbols, which is the leading conflict hypothesis.
- The ROS-packaged `realsense2_camera` node became usable for the D405 after the manual UVC bind, but the current L515 path is still not clean in that wrapper on this host.
- Added `data_pipeline/v4l_camera_bridge.py` and `data_pipeline/launch/realsense_v4l_contract.launch.py` as the smallest working RGB-only fallback so hardware recording can proceed for the required published color streams while the SDK/depth path is still unresolved.

### Direct SDK RealSense pivot

- Revisited the legacy Teleop camera path and confirmed it uses `pyrealsense2` directly rather than the ROS `realsense2_camera` wrapper.
- Based on that and the current upstream L500/L515 support gap, switched the intended V1 RealSense runtime back to a single direct-SDK stack for all RealSense cameras.
- Added `data_pipeline/realsense_bridge.py` as a small ROS2 publisher that:
  - connects to one device by serial using `pyrealsense2`,
  - publishes `/spark/cameras/<name>/color/image_raw`,
  - publishes `/spark/cameras/<name>/depth/image_rect_raw` when enabled,
  - stamps both streams with host ROS time immediately after `wait_for_frames()` returns,
  - and exposes serial/model/firmware/profile parameters so the episode manifest can still infer camera metadata.
- Updated `data_pipeline/launch/realsense_contract.launch.py` to launch one bridge process per configured camera from `.venv/bin/python`.
- Updated `data_pipeline/setup_realsense_contract_runtime.sh` to validate the direct `.venv` runtime instead of checking for `realsense2_camera`.
- Added `pyrealsense2==2.56.5.9235` to the shared `.venv` bootstrap so the RealSense publisher and offline converter use the same ROS-friendly Python environment.
- Removed the RealSense metadata topics from the active recording profile because the direct bridge now produces the correct V1 header stamps directly.
- Kept converter support for older bags that already contain official RealSense metadata topics.
- Current direct-SDK discovery state on this host:
  - `pyrealsense2` in `.venv` sees the D405,
  - the L515 is visible to `lsusb` and `/dev/v4l/by-id`,
  - but `pyrealsense2` still does not enumerate the L515 in the current session,
  - so full two-camera hardware validation still depends on the live L515 state at bring-up time.
- Live D405 validation of the new bridge passed:
  - `ros2 launch data_pipeline/launch/realsense_contract.launch.py wrist_serial_no:=130322273305`
  - published `/spark/cameras/wrist/color/image_raw`
  - published `/spark/cameras/wrist/depth/image_rect_raw`
  - `ros2 param dump /spark/cameras/wrist` exposed serial/model/firmware/profile
  - `ros2 topic hz /spark/cameras/wrist/color/image_raw` stabilized at about 30 Hz
- Differential hardware check after adding a D455 showed:
  - D405 and D455 enumerate in the installed `pyrealsense2` / `rs-enumerate-devices`
  - L515 does not
  - the failure follows the L515 across ports, so it is not a hub-port issue
- Built an isolated official `librealsense v2.54.2` runtime with Python bindings against `.venv`, using `FORCE_RSUSB_BACKEND=ON`.
- Validated that the locally built `pyrealsense2` from `build/librealsense-v2.54.2/Release` enumerates:
  - D455 `213622251272`
  - D405 `130322273305`
  - L515 `f1380660`
- Updated the RealSense setup/launch path so the bridge now uses that local `v2.54.2` runtime instead of the installed `2.56.x` module.
- Added serial normalization in the bridge so the physical USB serial and the SDK-reported short L515 serial both resolve to the same device.
- Live validation of the final target pair passed:
  - D405 wrist `130322273305`
  - L515 scene `f1380660`
  - both published their contract topics at roughly 30 Hz through the local `v2.54.2` runtime
- Three-camera stress check also passed when the D455 was launched on a temporary non-contract namespace:
  - D405 on `/spark/cameras/wrist/...`
  - L515 on `/spark/cameras/scene/...`
  - D455 on `/spark/cameras_aux/extra/...`
  - all three color streams produced stamped `sensor_msgs/Image` samples concurrently

### Raw sensor identity decision

- The current published profile names like `wrist`, `scene`, `left`, and `right` are too narrow to treat as long-term raw identity.
- The raw episode manifest should preserve enough information to remap old episodes later without recollecting data.
- The chosen compromise is:
  - keep the current runtime topic surface for now,
  - enrich each manifest sensor record with stable raw identity fields,
  - and let published profiles map those raw sensor identities into dataset field names.
- Final lean per-sensor manifest fields:
  - `sensor_id`
  - `modality`
  - `attached_to`
  - `mount_site`
  - `topic_names`
  - `serial_number`
  - `model`
  - `calibration_ref`
- Added top-level manifest field:
  - `sensor_inventory_version`
- `sensors.example.yaml` is now the place where the operator can remove ambiguity for the current rig by filling in fields such as:
  - `attached_to: lightning`
  - `mount_site: finger_left`
- This keeps the current runtime conservative while making the raw layer explicit enough to support later renaming or profile changes, without carrying debug-style per-episode sensor clutter.

### Episode language field

- Added an optional `language_instruction` field to the raw episode manifest.
- This is intentionally episode-level only for now.
- `task_name` remains the stable internal task identifier.
- During conversion, published LeRobot `task` now prefers `language_instruction` and falls back to `task_name` if no instruction was supplied.
- This keeps the change low-complexity while preserving a clean path for future language-conditioned training.

### March 20 hardware bring-up and first real episode

- Brought up a real Lightning-only hardware stack successfully with:
  - `TeleopSoftware/launch_devs.py`
  - `TeleopSoftware/launch.py`
  - `data_pipeline/launch/realsense_contract.launch.py`
- Live dry-run succeeded once the active camera serials were corrected for the current session:
  - wrist camera: D405 `130322273305`
  - scene camera: D455 `213622251272`
- The first real raw episode recorded successfully:
  - `raw_episodes/episode-20260320-110232`
  - `dataset_id=spark_multisensor_lightning_v1`
  - `mapping_profile=multisensor_20hz_lightning`
  - duration about `49s`
  - bag size about `4.2 GiB`
- Bag review showed the core arm trajectory data was healthy:
  - both RGB and depth streams recorded for wrist and scene cameras at about 30 Hz
  - robot state recorded at about 121 Hz
  - teleop joint command stream recorded at about 28 Hz
- Bag review also exposed a real gripper problem:
  - `/spark/lightning/teleop/cmd_gripper_state` stayed constant at `1.0`
  - `/spark/lightning/robot/gripper_state` stayed constant at `228.0`
  - joint motion was still present, so the problem was isolated to the gripper path
- Root cause was a Lightning trigger calibration mismatch in `TeleopSoftware/launch_helpers/run.py`.
  - The current pipeline copy was using the wrong Lightning Spark trigger mapping range.
  - Updated Lightning gripper calibration to match `SPARK-Remote`:
    - `in_min=-0.4`
    - `in_max=0.25`
- Found one additional remaining hardware-tuning mismatch against `SPARK-Remote` and corrected it:
  - updated `LIGHTNING_OFFSET` in `TeleopSoftware/launch_helpers/run.py` to the tested branch values
- Left the hardcoded `enable_topic = 'lightning_spark_enable'` unchanged for now because the current setup uses a single foot pedal wired through Lightning.

### Real episode conversion and local LeRobot visualizer

- Converted the first real raw episode to LeRobot format:
  - input: `raw_episodes/episode-20260320-110232`
  - output: `published/spark_multisensor_lightning_v1`
  - converter reported:
    - `episode_index=0`
    - `status=truncated_tail`
    - `published_frames=898`
- Verified the published dataset layout is LeRobot `v3.0` compatible:
  - `meta/info.json`
  - `meta/episodes/chunk-000/...`
  - `data/chunk-000/file-000.parquet`
  - `videos/observation.images.wrist/...`
  - `videos/observation.images.scene/...`
- Cloned the official browser visualizer repo locally:
  - `lerobot-dataset-visualizer`
- Found a real local-viewer bug during bring-up:
  - the client-side browser code ignored `DATASET_URL`
  - it fell back to `https://huggingface.co/datasets/...`
  - for the local dataset path `local/spark_multisensor_lightning_v1`, this produced a `401`
- Verified the failure directly with Playwright using the system Chrome:
  - the failing request was:
    - `https://huggingface.co/datasets/local/spark_multisensor_lightning_v1/resolve/main/meta/info.json`
- Patched `lerobot-dataset-visualizer/src/utils/versionUtils.ts` locally so browser-side fetches use a public/same-origin dataset base instead of silently falling back to Hugging Face.
- Rebuilt the visualizer and re-verified with Playwright:
  - the dataset page now loads successfully
  - both wrist and scene videos render
  - language instruction renders
  - charts render
  - remaining 404s are only optional progress files:
    - `sarm_progress.parquet`
    - `srm_progress.parquet`
- Verified working viewer URL for this machine context:
  - `http://10.33.55.65:3000/local/spark_multisensor_lightning_v1/episode_0`
- Important operational note:
  - for this IDE/browser environment, `localhost:3000` is not the reliable access path
  - use the machine IP URL above instead

### Machine-specific command runbook

- Added a concrete machine-specific runbook at `data_pipeline/docs/current-lightning-gelsight-runbook.md`.
- Scope of that runbook is intentionally narrow:
  - `lightning` only
  - D405 wrist + D455 scene
  - one left GelSight
  - raw record -> convert -> browser visualizer
- Linked that runbook from:
  - `data_pipeline/README.md`
  - `data_pipeline/docs/hardware-bringup.md`
- Purpose is operational clarity during bring-up, not to replace the more general hardware guide.

### SPARK identity and launcher fixes

- Found a real long-term SPARK identity problem:
  - `Hardware/Firmware/SparkSerialTX/src/main.cpp` in both this repo and `SPARK-Remote` hardcoded `doc["ID"] = "lightning"`.
  - That means the repo state itself does not encode distinct Lightning vs Thunder firmware identities.
- Added a proper firmware-level fix:
  - `SPARK_DEVICE_ID` compile-time macro in `SparkSerialTX`
  - PlatformIO envs for:
    - `esp32doit-devkit-v1` -> Lightning
    - `esp32doit-devkit-v1-thunder` -> Thunder
- Added a launcher-side guard in `TeleopSoftware/launch_devs.py`:
  - probes each Spark device ID before spawning child nodes
  - refuses to launch duplicate firmware IDs silently
  - prints an explicit reflash message instead of allowing GUI flicker/corruption
- Also fixed `launch_devs.py` to spawn child processes with `sys.executable` instead of plain `python3`, so it stays on the intended interpreter.

### SPARK firmware now fixed on hardware

- Verified directly from raw serial JSON that both physical SPARK boards were initially reporting `ID=lightning`.
- Flashed the physical SPARK boards into a known symmetric state:
  - `/dev/ttyUSB0` -> `lightning`
  - `/dev/ttyUSB1` -> `thunder`
- Re-verified from raw serial JSON after flashing:
  - both boards report all encoder `status` bits as `true`
  - the firmware IDs are now distinct at the hardware source
- Because hardware identity is now correct, removed the duplicate-ID skip/probe behavior from `TeleopSoftware/launch_devs.py`.
- Kept the useful runtime fixes:
  - `launch_devs.py` still uses `sys.executable`
  - `SparkNode.py` now tolerates ESP32 boot chatter / delayed first JSON packet instead of crashing at startup

### Recorder simplification: explicit active arms

- Removed `--active-arms auto` from `data_pipeline/record_episode.py`.
- Recording now requires an explicit embodiment declaration:
  - `--active-arms lightning`
  - `--active-arms thunder`
  - `--active-arms lightning,thunder`
- Reason:
  - the auto-detection path introduced avoidable hardware flakiness during bring-up
  - explicit active-arm selection is simpler and more reliable for real collection
- Removed the now-unused active-arm probe helpers from `data_pipeline/pipeline_utils.py`.

### Capture/runtime split for RealSense

- Confirmed the stable machine boundary is:
  - live capture: system ROS Python `/usr/bin/python3`
  - offline conversion / LeRobot: local `.venv`
- Reason:
  - `lerobot` requires Python `>=3.12`
  - the stable local RealSense runtime on this host is the official `librealsense v2.54.2` build wired into system ROS Python
  - mixing both into one environment created repeated `pyrealsense2` packaging and enumeration failures
- Updated `data_pipeline/launch/realsense_contract.launch.py` so the RealSense bridge now launches with `/usr/bin/python3`, not `.venv/bin/python`.
- Updated `data_pipeline/setup_realsense_contract_runtime.sh` so it now builds the local `pyrealsense2` binding for system Python and validates imports without relying on `query_devices()`.
- Kept the earlier `data_pipeline/realsense_bridge.py` fix that removes upfront `query_devices()` dependence and instead canonicalizes the provided serials before per-camera startup.

### Operator Console spec pass

- Added `data_pipeline/docs/operator-console-spec.md` as the contract for the planned lab-facing capture GUI.
- Kept the boundary explicit:
  - the Operator Console is separate from `TeleopSoftware/launch.py`
  - Teleop remains untouched in V1
- Wrote the console spec in the same contract-oriented style as `data_pipeline/V1_SPEC.md`:
  - explicit goal
  - boundary
  - runtime base
  - readiness contract
  - workflow state model
  - metadata / record / convert contracts
  - acceptance criteria
- Linked the new spec from `data_pipeline/README.md`.

### Operator Console Phase 1 skeleton

- Added the first separate Operator Console implementation:
  - `data_pipeline/operator_console.py`
  - `data_pipeline/operator_console_backend.py`
  - `data_pipeline/configs/operator_console_presets.yaml`
- Kept the Teleop boundary intact:
  - the console launches or stops the existing Teleop processes
  - it does not modify `TeleopSoftware/launch.py`
- Current Phase 1 scope of the implementation:
  - preset selection
  - metadata form
  - process orchestration for SPARK, Teleop, RealSense, GelSight, recorder, and converter
  - subsystem health cards
  - validate / record / convert / open-viewer actions
  - per-process log view
- The first prototype is intentionally operational rather than polished.
- Added `.operator_console/` to `.gitignore` because the backend now persists local session state there.

### Operator Console runtime validation pass

- Validated the new console backend against the real Lightning runtime by driving the backend directly, not just opening the Tk window.
- The first backend run exposed a real design issue:
  - continuous health polling was using `ros2 topic echo --once`
  - that made healthy services look dead or too slow during startup
- Split the health model into two layers:
  - lightweight continuous health cards
  - stronger stream probes only during `Validate`
- Added startup grace handling for:
  - SPARK
  - Teleop
  - RealSense
  - GelSight
- Updated session-state behavior:
  - if a required subsystem is truly red, the session now transitions to `degraded`
  - otherwise startup remains `bringing_up`
- Added process-log hints into degraded health cards so the operator can see the latest actionable failure without opening a shell immediately.
- Real runtime result with the current `lightning_d405_d455_left_gelsight` preset:
  - SPARK: healthy
  - Teleop: healthy
  - RealSense: healthy
  - GelSight: red / degraded
  - `Validate` failed for the real reason:
    - timed out waiting for `/spark/tactile/left/color/image_raw`
  - the health card also surfaced the underlying launch failure for the GelSight bridge process

### Operator Console readiness-model correction

- Follow-up observation from real use:
  - the earlier backend run was not a full success signal because the robot was not actually turned on
  - and the active preset incorrectly assumed a connected GelSight when the tactile device was absent
- Adjusted the console accordingly:
  - added a `lightning_d405_d455_no_tactile` preset so the default path does not flag a missing GelSight unnecessarily
  - restored representative message-flow probes for continuous health, but with caching and startup grace instead of probing every refresh cycle
  - kept the stronger end-to-end stream probe in `Validate`
- Result:
  - GelSight can now be removed from the required set cleanly by preset
  - Teleop and SPARK no longer become green purely from process spawn plus topic presence
  - the console health model is closer to "runtime up vs actually validated" instead of collapsing those into one signal

### Operator Console explicit validation state and per-process controls

- Continued the console without changing the overall layout:
  - added explicit validation-state reporting in the header
  - added per-card Start/Stop controls for the existing subsystem cards
- Backend changes:
  - added `validation_state(config)` with explicit states:
    - `not_run`
    - `running`
    - `passed`
    - `failed`
    - `stale`
  - added `start_named_process(...)` and `stop_named_process(...)` so the UI can restart one subsystem without tearing down the whole session
  - made validation re-entrant safe by ignoring duplicate validate clicks while a validation thread is already running
- UI changes:
  - header now shows both session state and validation state
  - subsystem cards now expose lightweight Start/Stop controls
  - recorder controls now respect the explicit validation state rather than only the old boolean flag
- Smoke validation:
  - `python3 -m py_compile data_pipeline/operator_console_backend.py data_pipeline/operator_console.py`
  - `timeout 5s python3 data_pipeline/operator_console.py`
  - both passed without Tk/runtime errors

### Operator Console button-state tightening

- Followed up immediately on the first controls pass to make the UI harder to misuse:
  - `Start Session` now disables once the session is already up or bringing up
  - `Stop Session` disables when nothing session-level is active
  - `Validate` disables while a validation run is already in progress
- Also mirrored the current session state and validation state into the Action Output pane so operators do not have to infer them only from the header or button enablement.
- Re-ran the same smoke checks:
  - `python3 -m py_compile data_pipeline/operator_console_backend.py data_pipeline/operator_console.py`
  - `timeout 5s python3 data_pipeline/operator_console.py`

### Operator Console ROS-native stream probe

- Replaced the console's representative-message probe path:
  - removed reliance on `ros2 topic echo --once` for health and validate checks
  - added `data_pipeline/ros_topic_probe.py`, a small ROS-native one-shot subscriber probe using `rclpy`
- Wired the backend health cache and `Validate` path to use that probe instead of the slower CLI echo path.
- Reason:
  - the CLI echo path was producing repeated false negatives on image and startup-sensitive topics
  - that made healthy SPARK and RealSense services stay yellow even after they were actually streaming
- Real backend validation result with the full `lightning_d405_d455_left_gelsight` preset:
  - SPARK: healthy
  - Teleop: healthy
  - RealSense: healthy
  - GelSight: healthy
  - session state reached `ready_for_dry_run`
  - `Validate` passed and reported the expected `11` bag topics for the Lightning+tactile configuration
- Important nuance from the logs:
  - the Teleop process still emitted an early Tk callback traceback around gripper activation
  - but by the end of the probe window the required Lightning robot and teleop topics were flowing, so the console correctly treated Teleop as healthy for readiness purposes

### Operator Console recording integrity check

- Ran a short end-to-end console smoke recording with a dedicated smoke dataset id to exercise:
  - `Start Session`
  - `Validate`
  - `Start Recording`
  - `Stop Recording`
- Result:
  - the recorder lifecycle worked and wrote a real raw episode directory plus bag metadata
  - but the recorded bag had `0` messages for:
    - `/spark/lightning/teleop/cmd_joint_state`
    - `/spark/lightning/teleop/cmd_gripper_state`
  - which is exactly the failure mode you would get if an operator forgets to actually start teleop execution after recording begins
- Added a post-stop recording integrity check in the console backend:
  - parses `raw_episodes/<episode_id>/bag/metadata.yaml`
  - verifies every required recorded topic for the chosen config has a nonzero message count
  - surfaces failure through:
    - `latest_recording_check_output`
    - `last_action_error`
    - recorder health card turns red with a concise missing-topic summary
  - `Convert Latest` is now disabled when the last recording failed this integrity check
- Validated the new behavior directly against the known-bad smoke episode:
  - recorder health becomes `Last recording incomplete`
  - the two zero-message teleop command topics are surfaced explicitly

### Converter runtime fix

- Hit a separate usability bug while converting a real episode from shell:
  - running `.venv/bin/python data_pipeline/convert_episode_bag_to_lerobot.py ...` without ROS sourced fails with `ModuleNotFoundError: rosbag2_py`
- Confirmed this is only a shell/runtime issue:
  - `.venv` can import `rosbag2_py` correctly once `/opt/ros/jazzy/setup.bash` is sourced
- Fixed the console and docs accordingly:
  - `data_pipeline/operator_console_backend.py` now sources ROS before launching `convert_episode_bag_to_lerobot.py`
  - updated conversion command examples in:
    - `data_pipeline/README.md`
    - `data_pipeline/docs/hardware-bringup.md`
    - `data_pipeline/docs/current-lightning-gelsight-runbook.md`
- Re-tested conversion on `episode-20260320-232548` with ROS sourced:
  - the `rosbag2_py` import issue is gone
  - conversion now fails for the real data reason:
    - missing required teleop command topics `/spark/lightning/teleop/cmd_joint_state` and `/spark/lightning/teleop/cmd_gripper_state`

### Profile-driven bounded action hold

- Investigated the newer tactile episodes and separated two different failure modes:
  - `episode-20260320-232548`
    - still invalid because the teleop command topics were missing entirely
  - `episode-20260320-234600`
    - command topics were present and dense overall
    - conversion failed only because of two isolated mid-episode command gaps, with the worst gap around `135 ms`
- Verified an important semantic point before changing anything:
  - the converter already discards pre-roll before the first action sample
  - so this was not caused by starting the recorder before pressing the foot pedal
- Implemented the pipeline fix in `data_pipeline/convert_episode_bag_to_lerobot.py`:
  - removed the old hard-coded `STATE_AGE_NS`, `ACTION_AGE_NS`, and `IMAGE_SKEW_NS` assumptions
  - converter now reads:
    - `published.observation_state.max_age_ms`
    - `published.action.max_age_ms`
    - per-image `max_skew_ms`
    directly from the profile
  - kept the same `latest_before` semantics for state and action, which is already a bounded zero-order hold
  - added minimal action-hold diagnostics:
    - `max_action_age_ms`
    - `num_frames_over_50ms`
    - `num_frames_over_100ms`
- Updated `data_pipeline/configs/multisensor_20hz_lightning.yaml`:
  - `action.max_age_ms` is now `150`
  - state and image tolerances remain strict
- Validation result after the change:
  - `episode-20260320-232443` still fails
    - first failure now at `157.36 ms`, so the older clearly-bad episode is still rejected
  - `episode-20260320-234600` now converts successfully
    - `status=pass`
    - `published_frames=386`

### Tactile dataset id split

- The successful bounded-hold conversion exposed a schema issue:
  - tactile episodes were still being pointed at `spark_multisensor_lightning_v1`
  - that dataset had already been created without `observation.images.gelsight_left`
  - so LeRobot correctly rejected the append due to feature mismatch
- Fixed the checked-in defaults:
  - `data_pipeline/configs/operator_console_presets.yaml`
    - `lightning_d405_d455_left_gelsight` now defaults to `spark_multisensor_lightning_tactile_v1`
  - `data_pipeline/docs/current-lightning-gelsight-runbook.md`
    - updated record/convert/viewer examples to the tactile dataset id
  - `data_pipeline/docs/hardware-bringup.md`
    - clarified that tactile and non-tactile episodes should not share one published `dataset_id`
- Added a converter escape hatch for already-recorded episodes:
  - `--published-dataset-id`
  - this allows re-targeting conversion without manually editing the raw manifest
- Updated the console conversion path so `Convert Latest` uses the current preset dataset id as the published dataset target.
- Verified end to end:
  - `episode-20260320-234600` converted successfully with:
    - `--published-dataset-id spark_multisensor_lightning_tactile_v1`
  - output:
    - `published/spark_multisensor_lightning_tactile_v1`
    - `episode_index=1`

### Recorder card action clarity

- Tightened one operator-console usability issue in `data_pipeline/operator_console.py`:
  - the recorder health card could say `Last recording ready for conversion`
  - but still showed generic `Start` / `Stop` buttons
  - which made it easy for an operator to press `Start` expecting conversion and accidentally begin a new recording
- Fixed the recorder card so its controls now follow recorder state instead of staying generic:
  - while recording:
    - `Record` disabled
    - `Stop` enabled
  - when the latest recording is ready for conversion:
    - `Convert` enabled
    - `Record New` offered as the secondary action
  - otherwise:
    - `Record`
    - `Stop` disabled
- Tightened the global `Convert Latest` button to enable only when the latest recording has explicitly passed the post-stop integrity check, instead of allowing the intermediate `unknown` state.
- Validation:
  - `python3 -m py_compile data_pipeline/operator_console.py data_pipeline/operator_console_backend.py`
  - `timeout 5s python3 data_pipeline/operator_console.py`

### Console conversion command assembly fix

- Found a real operator-console bug in `data_pipeline/operator_console_backend.py`:
  - when the current preset provided a `dataset_id`, the backend built the conversion shell command with
    `--published-dataset-id ...--published-root ...`
    as one concatenated token
  - the symptom at runtime was the exact argparse failure:
    `error: unrecognized arguments: /home/srinivas/Desktop/pipeline/published`
- Fixed `_build_convert_command(...)` to assemble the converter invocation from an argument list and join it once, instead of relying on fragile string concatenation.
- Validation:
  - printed the generated command for `episode-20260321-001038`
  - confirmed it now contains:
    - `--published-dataset-id spark_multisensor_lightning_tactile_v1`
    - `--published-root /home/srinivas/Desktop/pipeline/published`
    as separate flags
  - `python3 -m py_compile data_pipeline/operator_console_backend.py data_pipeline/operator_console.py`

### Recorder controls deduplicated

- Removed the duplicate recording/conversion controls from the top-level Session form in `data_pipeline/operator_console.py`.
- Reason:
  - after the recorder card became state-aware, the UI had two separate control surfaces for the same recorder actions:
    - recorder card `Record` / `Stop` / `Convert`
    - global `Start Recording` / `Stop Recording` / `Convert Latest`
  - that duplication was unnecessary and made the UI harder to trust
- New boundary:
  - Session form now owns only session-level actions:
    - `Start Session`
    - `Stop Session`
    - `Validate`
    - `Open Viewer`
  - Recorder card owns recorder-level actions:
    - `Record`
    - `Stop`
    - `Convert`
    - `Record New`
- Validation:
  - `python3 -m py_compile data_pipeline/operator_console.py data_pipeline/operator_console_backend.py`
  - `timeout 5s python3 data_pipeline/operator_console.py`

### Viewer action resilience

- Found a separate Operator Console weakness around `Open Viewer`:
  - the button state depended too heavily on the console's in-memory `latest_dataset_id`
  - so if a dataset already existed on disk, or conversion happened outside the current console process, the viewer action could be unavailable or misleading
- Tightened the viewer path in `data_pipeline/operator_console_backend.py` and `data_pipeline/operator_console.py`:
  - `Open Viewer` now resolves the target dataset from disk, preferring the current form `dataset_id` and falling back to the console's latest known dataset
  - the button now enables when a valid `published/<dataset_id>/meta/info.json` exists for the current config, not only when the current session memory has `latest_dataset_id`
  - on Linux, the backend now uses `xdg-open` when available, with `webbrowser.open(...)` as fallback
- Runtime diagnosis from the latest check:
  - the generated URL was correct:
    - `http://10.33.55.65:3000/local/spark_multisensor_lightning_tactile_v1/episode_2`
  - the actual reason it failed was simpler:
    - no viewer server was running on port `3000`
- Brought the viewer back up with:
  - `cd /home/srinivas/Desktop/pipeline/lerobot-dataset-visualizer`
  - `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy -u NO_PROXY -u no_proxy NEXT_PUBLIC_DATASET_URL=http://10.33.55.65:3000/datasets DATASET_URL=http://localhost:3000/datasets REPO_ID=local/spark_multisensor_lightning_tactile_v1 EPISODES=2 ~/.bun/bin/bun start`
- Validation after bring-up:
  - `curl` with proxy vars stripped returned `HTTP/1.1 200 OK` for:
    - `http://localhost:3000/`
    - `http://10.33.55.65:3000/`
  - the specific episode route returned HTML successfully:
    - `http://localhost:3000/local/spark_multisensor_lightning_tactile_v1/episode_2`

### Open Viewer now owns viewer startup

- Tightened the Operator Console contract for `Open Viewer`:
  - the user should not be expected to manually start `lerobot-dataset-visualizer`
  - pressing `Open Viewer` should ensure the server exists, then open the episode URL
- Implemented this in `data_pipeline/operator_console_backend.py`:
  - added an on-demand managed process: `viewer_server`
  - `open_viewer(...)` now:
    - resolves the dataset and latest episode from `published/<dataset_id>/meta/info.json`
    - starts `lerobot-dataset-visualizer` automatically if the configured viewer base URL is not already reachable
    - waits for the server to come up
    - then opens the URL with `xdg-open` on Linux
- `data_pipeline/operator_console.py` now enables `Open Viewer` whenever the current config points at a dataset that exists on disk, rather than depending on in-memory conversion state.
- Validation:
  - `python3 -m py_compile data_pipeline/operator_console_backend.py data_pipeline/operator_console.py`
  - backend probe on the tactile dataset returned:
    - `available=True`
    - target URL `http://10.33.55.65:3000/local/spark_multisensor_lightning_tactile_v1/episode_2`
    - `reachable=True`
  - `timeout 5s python3 data_pipeline/operator_console.py`

### Viewer launch path simplified

- After the viewer-startup fix, revisited the browser-launch code in `data_pipeline/operator_console_backend.py`.
- Kept the code minimal:
  - removed the extra `webbrowser.open(...)` fallback path
  - kept only the Linux-native `xdg-open` launch path that this machine already has
- Reason:
  - for the actual incident, the root cause was that the server was not running
  - the browser-launch fallback was not part of the required fix
  - keeping both launch paths only added unnecessary branching
- Validation:
  - `python3 -m py_compile data_pipeline/operator_console_backend.py data_pipeline/operator_console.py`
  - viewer target resolution for the tactile dataset still returns:
    - `('spark_multisensor_lightning_tactile_v1', 2, 'http://10.33.55.65:3000/local/spark_multisensor_lightning_tactile_v1/episode_2')`

### Recorder post-stop analyzing state

- Fixed a small but misleading recorder-card transition in the Operator Console:
  - after `Stop`, the recorder process would exit immediately
  - then the post-stop integrity check would run
  - during that gap the UI briefly fell back to the default `Record` state before changing to `Convert` / `Record New`
- Added an explicit backend flag `recording_check_running` in `data_pipeline/operator_console_backend.py`.
- The recorder health card now reports:
  - `Analyzing last recording`
  while the post-stop bag integrity check is still running.
- The recorder card buttons in `data_pipeline/operator_console.py` now show a neutral disabled state during that window:
  - `Analyzing`
  - `Wait`
- This keeps the UI honest and removes the brief flash of the wrong next action.
- Validation:
  - `python3 -m py_compile data_pipeline/operator_console_backend.py data_pipeline/operator_console.py`
  - `timeout 5s python3 data_pipeline/operator_console.py`
