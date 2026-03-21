# Operator Console V1 Spec

## 1. Goal

Build a lab-facing Operator Console for capture bring-up, recording, conversion, and review.

V1 is for:

- launching and supervising the existing capture processes
- checking real readiness before recording
- collecting required episode metadata
- starting and stopping raw recording
- converting the recorded episode to the published LeRobot dataset
- opening the existing browser visualizer for the converted episode

V1 is not for:

- replacing the current Teleop GUI
- changing robot-control behavior
- embedding policy inference
- inventing new data contracts
- hiding the existing command-line tools


## 2. Problem

The current workflow is operationally correct but too fragile for routine lab use.

The operator currently has to:

- start SPARK device processes
- start the Teleop GUI / robot runtime
- start RealSense publishers
- start GelSight publishers
- run recorder dry-run
- run the real recorder
- perform the demo in Teleop
- stop the recorder
- convert the raw episode
- open the browser viewer

The observed failure modes are already known:

- a process can start without being healthy
- a topic can exist with `0` messages
- camera enumeration can be runtime-specific
- stale permission/session state can break SPARK access
- active-arm auto-detection can fail at bring-up time
- operators currently need to read raw logs and remember ordering

So the required product is not "a prettier launcher." It is an operator console with explicit workflow staging and hard readiness gates.


## 3. Boundary

- `TeleopSoftware/` remains the robot-control runtime.
- `data_pipeline/` remains the owner of capture, metadata, conversion, and review.
- The Operator Console may launch and supervise the Teleop GUI.
- The Operator Console must not modify the Teleop GUI code path in V1.
- The Operator Console must wrap the existing CLIs rather than replacing them first.

Source-of-truth commands in scope:

- `TeleopSoftware/launch_devs.py`
- `TeleopSoftware/launch.py`
- `data_pipeline/launch/realsense_contract.launch.py`
- `data_pipeline/launch/gelsight_contract.launch.py`
- `data_pipeline/record_episode.py`
- `data_pipeline/convert_episode_bag_to_lerobot.py`


## 4. Runtime Base

The console must respect the current runtime split:

- Teleop runtime uses the current Teleop Python environment
- live RealSense capture uses system ROS Jazzy and `/usr/bin/python3`
- GelSight and recorder use system ROS Jazzy and `/usr/bin/python3`
- conversion and LeRobot export use the local `.venv`

The console must not depend on shell aliases like `spark`.


## 5. Core Rules

### 5.1 Explicit over implicit

The operator must explicitly choose:

- embodiment: `lightning`, `thunder`, or `lightning,thunder`
- hardware preset
- required metadata for the episode

The console must not silently infer embodiment from partial runtime state.

### 5.2 Readiness must be measured

`process started` is not a valid readiness signal.

Readiness must be based on some combination of:

- process alive
- required topics present
- required topics receiving messages
- minimum message-rate checks
- explicit success signals in logs when needed

### 5.3 Fail closed

The console must block recording when required inputs are unhealthy.

It must not:

- start recording with a red required subsystem
- silently drop required sensors
- silently publish incomplete episodes under the wrong profile

### 5.4 Reuse the existing tools first

V1 should orchestrate the existing commands instead of rewriting their logic in the GUI layer.


## 6. V1 Scope

The first validated target is the currently working Lightning-only flow:

- `lightning`
- D405 wrist camera
- D455 or L515 scene camera
- optional left GelSight
- raw recording
- LeRobot conversion
- browser viewer launch

Thunder-only and bimanual should be represented in the configuration and state model, but do not need to be the first implementation target.


## 7. Non-Goals

- Do not replace the current Teleop GUI.
- Do not add robot-control widgets to the new console.
- Do not patch Teleop just to make the console usable.
- Do not merge capture orchestration and robot control into one window.
- Do not support every possible hardware topology in V1.
- Do not create a second independent implementation of recording or conversion.


## 8. Architecture

The Operator Console should have two parts:

- a backend supervisor
- a frontend UI

### 8.1 Backend supervisor

The backend supervisor must:

- launch subprocesses
- track process state
- collect recent logs
- probe ROS topics
- evaluate readiness rules
- persist per-session state

The backend supervisor is the only component allowed to spawn or stop capture-related processes.

### 8.2 Frontend UI

The frontend must:

- show workflow state
- show subsystem health
- collect metadata
- trigger validate / record / convert / review actions
- expose logs and exact failure points

V1 implementation decision:

- the production frontend should be `PySide6` / Qt
- it remains a local Python desktop app
- it must not become a browser/server application

The backend contract and state model remain more important than presentation details, but the frontend toolkit is no longer open-ended for V1.

The existing Tk implementation is a prototype/reference only until the Qt frontend reaches feature parity.

Qt migration must preserve:

- the same backend supervisor
- the same named-process model
- the same readiness gates
- the same record / convert / review workflow
- the same failure visibility or better


## 9. Process Model

The backend must manage named processes explicitly.

Minimum V1 process set:

- `spark_devices`
  - `python TeleopSoftware/launch_devs.py`
- `teleop_gui`
  - `python TeleopSoftware/launch.py`
- `realsense_contract`
  - `ros2 launch data_pipeline/launch/realsense_contract.launch.py ...`
- `gelsight_contract`
  - `ros2 launch data_pipeline/launch/gelsight_contract.launch.py ...`
- `recorder`
  - `/usr/bin/python3 data_pipeline/record_episode.py ...`
- `converter`
  - `.venv/bin/python data_pipeline/convert_episode_bag_to_lerobot.py ...`
- `viewer`
  - Bun process for `lerobot-dataset-visualizer`

Per process, the backend must track:

- command
- environment block
- cwd
- pid
- start time
- current state:
  - `stopped`
  - `starting`
  - `running`
  - `failed`
  - `stopping`
- last exit code
- recent log lines


## 10. Configuration Model

The console should use checked-in presets plus local machine overrides.

### 10.1 Checked-in presets

Examples:

- `lightning_d405_d455_left_gelsight`
- `lightning_d405_l515_no_tactile`
- `bimanual_d405_d455_dual_tactile`

Each preset should define:

- embodiment
- required services
- required topics
- camera serial assignments
- tactile expectations
- default `dataset_id`
- default `robot_id`
- expected published profile

### 10.2 Local overrides

Local untracked config should define machine-specific values such as:

- actual serial numbers
- device paths
- default operator name
- viewer URL
- local `sensors.local.yaml` path

This should follow the same local-override model already used for hardware metadata.


## 11. Readiness Contract

This is the main contract of the console.

Each subsystem must have a health card with `red`, `yellow`, or `green` status.

### 11.1 SPARK devices

Required checks:

- `launch_devs.py` process alive
- `/Spark_angle/<arm>` publisher count nonzero for required arms
- `/Spark_enable/<arm>` publisher count nonzero for required arms

The subsystem must stay red if the process exists but the expected topics do not.

### 11.2 Teleop / robot runtime

Required checks per active arm:

- `/spark/<arm>/robot/joint_state`
- `/spark/<arm>/robot/eef_pose`
- `/spark/<arm>/robot/tcp_wrench`
- `/spark/<arm>/robot/gripper_state`
- `/spark/<arm>/teleop/cmd_joint_state`
- `/spark/<arm>/teleop/cmd_gripper_state`

Green means:

- each required topic exists
- each required topic has recent messages

### 11.3 RealSense

Required checks per enabled camera:

- RealSense process alive
- explicit bridge success observed
- required image topics exist
- required image topics have nonzero message rate

This must guard against the known failure mode where a scene topic is advertised but records `0` messages.

### 11.4 GelSight

Required checks per enabled tactile stream:

- process alive
- topic exists
- nonzero message rate

### 11.5 Recorder readiness

The console must disable `Record` until:

- embodiment is selected
- required metadata fields are filled
- all required subsystem cards are green
- a dry-run has passed for the current selection


## 12. Workflow State Model

The console must model the operator workflow explicitly.

Top-level states:

- `idle`
- `bringing_up`
- `degraded`
- `ready_for_dry_run`
- `ready_to_record`
- `recording`
- `recorded`
- `converting`
- `converted`
- `review_ready`

Required transitions:

- `idle -> bringing_up`
  - operator starts the session
- `bringing_up -> ready_for_dry_run`
  - required services are healthy
- `ready_for_dry_run -> ready_to_record`
  - dry-run succeeds
- `ready_to_record -> recording`
  - recorder starts successfully
- `recording -> recorded`
  - recorder stops cleanly
- `recorded -> converting`
  - operator starts conversion
- `converting -> converted`
  - converter exits successfully
- `converted -> review_ready`
  - published dataset and viewer link are ready

Any state may transition to `degraded` if a required subsystem fails.


## 13. Metadata Contract

The V1 console must collect at least:

- `dataset_id`
- `task_name`
- `language_instruction`
- `robot_id`
- `operator`
- `active_arms`
- `sensors_file`

Optional:

- notes
- extra topics

The console may use templates, but the required fields must remain visible and editable.


## 14. Recording Contract

The console must separate:

- `Validate`
- `Record`

### 14.1 Validate

`Validate` must run:

- `record_episode.py --dry-run`

using the current metadata, preset, and embodiment.

The UI must show:

- resolved profile
- selected topic list
- selected sensor metadata

### 14.2 Record

`Record` must:

1. start the real recorder
2. confirm the recorder process is alive
3. transition the UI to `recording`
4. tell the operator to perform the demo in the existing Teleop GUI

The console must not auto-toggle Teleop control buttons such as `Run Spark`.


## 15. Conversion and Review Contract

After recording finishes, the console must support:

- `Convert Episode`
- `Open Viewer`

Conversion must:

- use `.venv`
- target the just-recorded episode unless the operator selects another one

The UI must show:

- converter exit code
- published dataset path
- viewer URL

If conversion fails, the actual converter error must be shown.


## 16. Logging and Audit

The console must not become a black box.

For every session, it should persist a simple machine-readable log containing:

- launched commands
- selected preset
- selected local overrides
- start and stop timestamps
- exit codes
- validation failures
- latest episode id
- latest published dataset path


## 17. UX Requirements

V1 should be operational, not decorative.

Recommended layout:

- left column:
  - preset selection
  - metadata form
  - action buttons
- center column:
  - subsystem health cards
- right column:
  - recent process logs

Each subsystem card should show:

- status color
- required topics
- current rates when available
- last error

The UI should make it possible to debug common failures without immediately dropping to shell.


## 18. Safety Rules

The console must never:

- infer embodiment silently
- silently drop required sensors from a profile
- start recording when required subsystems are red
- hide which runtime/interpreter is being used
- pretend a process is healthy just because it was spawned

The console should also avoid:

- combining robot-control buttons and capture orchestration in one panel
- automatically restarting failed processes without making that explicit


## 19. Acceptance Criteria

V1 is acceptable when all of the following are true:

- an operator can complete the Lightning-only workflow without typing the existing command sequence by hand
- the console blocks recording when a required topic is missing or has zero throughput
- the console can show which process or topic is failing
- the console can launch recording, stop recording, convert the result, and open the viewer
- the console does not require changes to the current Teleop GUI


## 20. Delivery Plan

### Phase 1

Deliver:

- process orchestration
- readiness cards
- metadata form
- dry-run
- record
- convert
- open viewer

Do not rewrite or patch Teleop in this phase.

### Phase 2

Add:

- stronger diagnostics
- topic-rate history
- session history
- preset editor

### Phase 3

Only after Phase 1 is stable, consider:

- richer review history
- multi-episode collection workflows


## 21. Open Questions

- Should the frontend be Tk, Qt, or a local web app?
- Should Teleop be launched from the console or simply supervised if already running?
- Should V1 ship with Lightning-only enabled first and keep bimanual behind a feature gate until validated?


## 22. Recommendation

Proceed with a separate Phase 1 Operator Console that:

- wraps the existing commands
- keeps Teleop untouched
- uses explicit presets and explicit embodiment
- gates recording on real subsystem health
- supports record -> convert -> review end to end

That is the highest-leverage path to reduce lab operator error without introducing a second unsafe control plane.
