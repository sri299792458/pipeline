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
