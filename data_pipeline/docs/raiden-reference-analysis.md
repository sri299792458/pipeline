# Raiden Reference Analysis

## Bottom line

[`raiden/`](../../raiden/) is not just a repo with a few overlapping ideas.
It is a coherent reference implementation of the full lab operating model we
have been trying to build:

- hardware setup and bill of materials
- live device discovery
- local rig configuration
- calibration
- teleoperation
- multi-episode recording sessions
- post-take metadata correction
- offline conversion
- replay
- visualization
- downstream training export

The important consequence is that our current stack should not be judged only as
"operator console + rosbag recorder + LeRobot converter". It should be judged as
a lab system.


## What Raiden Actually Is

Raiden's official docs and code define a full end-to-end workflow:

- [`raiden/README.md`](../../raiden/README.md)
- [`raiden/docs/guide/quickstart.md`](../../raiden/docs/guide/quickstart.md)
- [`raiden/docs/api/index.md`](../../raiden/docs/api/index.md)

That workflow includes:

1. device discovery via `rd list_devices`
2. local camera config in `~/.config/raiden/camera.json`
3. calibration into `~/.config/raiden/calibration_results.json`
4. `rd teleop` for control without recording
5. `rd record` for multi-episode raw capture
6. `rd console` for metadata correction
7. `rd convert` for processed dataset construction
8. `rd replay` for hardware replay
9. `rd visualize` for converted-episode inspection
10. `rd shardify` for training export

This is the strongest external evidence we have seen that the architectural
pressure we were feeling was real.


## Direct Mapping To Our Stack

| Raiden concept | Raiden implementation | Current pipeline equivalent | Judgment |
|---|---|---|---|
| Local rig device config | [`camera.json`](../../raiden/docs/guide/hardware.md) + [`camera_config.py`](../../raiden/raiden/camera_config.py) | [`sensors.local.yaml`](../configs/sensors.example.yaml) + discovery in [`device_discovery.py`](../device_discovery.py) | Same core idea. Our concept was right. |
| Device discovery | `rd list_devices` in [`README.md`](../../raiden/README.md) / [`quickstart.md`](../../raiden/docs/guide/quickstart.md) | `Discover Devices` in [`operator_console_qt.py`](../operator_console_qt.py) | We now have the right primitive. |
| Calibration as first-class workflow | [`guide/calibration.md`](../../raiden/docs/guide/calibration.md) | Only placeholders like `calibration_ref` in sensors metadata | Raiden is substantially ahead. |
| Session recording with fixed setup | Cameras opened once across episodes in [`recorder.py`](../../raiden/raiden/recorder.py) and [`guide/recording.md`](../../raiden/docs/guide/recording.md) | Session profile in [`session-capture-plan.md`](./session-capture-plan.md) and [`session_capture_plan.py`](../session_capture_plan.py) | Strong conceptual match. |
| Raw recording as source of truth | `data/raw/<task>/<episode>/` in [`api/index.md`](../../raiden/docs/api/index.md) | `raw_episodes/<episode_id>/` in [`record_episode.py`](../record_episode.py) | Both are raw-first; storage format differs. |
| Episode metadata truth | `metadata.json` + DB entries | `episode_manifest.json` in [`record_episode.py`](../record_episode.py) | Our manifest is stronger and more explicit. |
| Metadata correction tool | `rd console` in [`guide/console.md`](../../raiden/docs/guide/console.md) | Operator console currently mixes session bring-up, record, convert, viewer | Raiden has cleaner separation. |
| Offline conversion | [`guide/conversion.md`](../../raiden/docs/guide/conversion.md) | [`convert_episode_bag_to_lerobot.py`](../convert_episode_bag_to_lerobot.py) | Both separate conversion from recording. |
| Processed intermediate dataset | `data/processed/<task>/<episode>/` in [`api/index.md`](../../raiden/docs/api/index.md) | None; we convert raw directly into LeRobot | Raiden has an extra middle layer we currently do not. |
| Replay | [`guide/replay.md`](../../raiden/docs/guide/replay.md) | None | Clear missing capability on our side. |
| Visualization | [`guide/visualization.md`](../../raiden/docs/guide/visualization.md) | dataset viewer for converted LeRobot output | Raiden is broader; ours is LeRobot-specific. |
| Training export | [`guide/shardify.md`](../../raiden/docs/guide/shardify.md) | None beyond LeRobot output | Raiden is ahead here too. |


## Where Raiden Validates Our Current Direction

### 1. One local rig file is a real abstraction

Raiden uses `~/.config/raiden/camera.json` to map semantic camera names to
serial numbers and roles:

- [`raiden/docs/guide/hardware.md`](../../raiden/docs/guide/hardware.md)
- [`raiden/raiden/camera_config.py`](../../raiden/raiden/camera_config.py)

That is the same abstraction pressure that led us to:

- [`data_pipeline/configs/sensors.example.yaml`](../configs/sensors.example.yaml)
- local `sensors.local.yaml`
- discovery plus role assignment in [`device_discovery.py`](../device_discovery.py)

So the local rig file concept was not bloat. It was correct.

### 2. Session-level fixed setup is the right unit

Raiden records multiple episodes under one fixed live setup and keeps cameras
open across episodes:

- [`raiden/docs/guide/recording.md`](../../raiden/docs/guide/recording.md)
- [`raiden/raiden/recorder.py`](../../raiden/raiden/recorder.py)

That validates the direction we converged on in:

- [`data_pipeline/docs/session-capture-plan.md`](./session-capture-plan.md)

The correct unit is not "every episode redefines the world". It is:

- one session setup
- multiple episodes under that setup

### 3. Convert later, do not front-load publish concerns into recording

Raiden separates:

- `rd record`
- `rd convert`

and does not center session-time recording around publish identifiers.

That validates our cleanup of removing dataset naming from session-start UI and
moving publish target to conversion time.

### 4. Calibration should be first-class, not an afterthought

Raiden has an explicit calibration workflow and a real calibration-results file:

- [`raiden/docs/guide/calibration.md`](../../raiden/docs/guide/calibration.md)

This validates our earlier concern that geometry/extrinsics are not optional
hand-waving if we care about geometry-aware policies.


## Where Raiden Exposes Weaknesses In Our Current Design

### 1. We still overload the operator console

Raiden separates:

- recording control
- metadata correction
- conversion
- visualization

across distinct commands:

- [`rd record`](../../raiden/docs/guide/recording.md)
- [`rd console`](../../raiden/docs/guide/console.md)
- [`rd convert`](../../raiden/docs/guide/conversion.md)
- [`rd visualize`](../../raiden/docs/guide/visualization.md)

Our current operator console still owns too much:

- session setup
- subsystem health
- recording
- conversion
- viewer launch
- post-take notes

See:

- [`data_pipeline/docs/operator-console-spec.md`](./operator-console-spec.md)
- [`data_pipeline/operator_console_qt.py`](../operator_console_qt.py)

The cleanup we already did was directionally right, but Raiden shows that a
single all-purpose console is still not the cleanest final operating model.

### 2. Our calibration layer is mostly still on paper

Right now our sensors metadata carries values like:

- `calibration_ref`

but we do not have a first-class workflow equivalent to:

- record calibration poses
- compute results
- persist intrinsics/extrinsics
- feed them back into conversion and replay

Relevant current files:

- [`data_pipeline/configs/sensors.example.yaml`](../configs/sensors.example.yaml)
- [`data_pipeline/docs/topic-contract.md`](./topic-contract.md)

Raiden makes this a real user workflow. We do not.

### 3. We do not have replay

Raiden explicitly supports:

- raw replay
- processed replay

See:

- [`raiden/docs/guide/replay.md`](../../raiden/docs/guide/replay.md)

For a lab system, replay is not a nice-to-have. It is a direct way to verify:

- the recording is meaningful
- the converted action trajectory is sane
- the system can round-trip a demonstration

We currently have no equivalent first-class tool.

### 4. We do not have a post-conversion export layer

Raiden does not stop at "processed dataset exists". It also has:

- `rd shardify`

for training-friendly export:

- [`raiden/docs/guide/shardify.md`](../../raiden/docs/guide/shardify.md)

Our current pipeline ends at:

- raw rosbag
- LeRobot dataset

That may be enough today, but Raiden shows the likely next pressure point:
training consumers often want their own export/view on top of converted data.

### 5. Task metadata lifecycle is cleaner in Raiden

Raiden has a real task system:

- task name
- language instruction
- teacher
- demonstration status

with a metadata store and console:

- [`raiden/docs/guide/tasks.md`](../../raiden/docs/guide/tasks.md)
- [`raiden/docs/guide/console.md`](../../raiden/docs/guide/console.md)
- [`raiden/raiden/db/database.py`](../../raiden/raiden/db/database.py)

Our current system is still more ad hoc:

- task name and language instruction live in session metadata
- operator notes are per-episode
- there is no first-class task/teacher metadata store

This does not mean we need to copy Raiden's DB immediately, but it does mean
their task lifecycle is more mature than ours.


## Where Our Current System Is Stronger Or Should Stay Different

### 1. Our raw source of truth is more explicit

Raiden's raw truth is split across:

- raw files
- metadata.json
- local config files
- DB records

Our raw truth is more explicit per episode because we already have:

- one rosbag
- one `episode_manifest.json`

See:

- [`data_pipeline/record_episode.py`](../record_episode.py)

That manifest-centric design is valuable and should be preserved.

### 2. Our ROS topic contract is more explicit

We have a real written topic contract:

- [`data_pipeline/docs/topic-contract.md`](./topic-contract.md)

Raiden has strong conventions, but it does not need the same ROS contract
because it records camera SDK outputs and robot files directly.

For our lab, keeping the explicit ROS contract is a strength, not overhead.

### 3. Our role names reflect our actual embodiment

Raiden uses YAM-centric naming:

- `left_wrist`
- `right_wrist`
- `scene`

Our system uses:

- `lightning`
- `thunder`
- `scene_1`
- `lightning_finger_left`

That is more appropriate for our actual hardware and existing runtime topics.
We should not flatten our lab's identity just to copy Raiden's naming.

### 4. Direct LeRobot export may still be the right default

Raiden writes a processed intermediate dataset first. We currently write
directly from raw rosbag into LeRobot.

That is not automatically wrong.

If LeRobot is our main downstream contract, direct export can be simpler than
introducing a second processed dataset layer prematurely.

The lesson from Raiden is not "we must copy their processed layout". The lesson
is "do not force all downstream needs into the recording UI". If we later need
another export layer, add it after raw capture, not before.


## What This Means For Our Architecture

### The good news

Some of the hardest recent decisions were actually correct:

- discovery-first device setup
- one local rig file
- role-based canonical naming
- session-level fixed setup
- publish choice at conversion time, not session start
- per-episode manifest truth

### The bad news

Our system is still incomplete at the "lab operating model" level.

The biggest missing or weak areas are:

1. calibration as a real workflow
2. replay
3. clearer separation between live recording and metadata curation
4. a future post-conversion export layer beyond raw-to-LeRobot


## Recommended Next Moves

These are ordered by architectural leverage, not by easiest patch size.

### 1. Stop expanding the operator console's scope

The current console should remain focused on:

- session setup
- device discovery
- health
- record / validate / convert

Do not keep adding metadata-management responsibilities to it.

Raiden strongly suggests that long-term we will want a separate metadata review
tool rather than one giant console.

### 2. Make calibration a first-class subsystem

Add a real calibration workflow and output file, not just `calibration_ref`
placeholders.

The cleanest likely shape is:

- keep `sensors.local.yaml` for hardware identity and role mapping
- add a separate calibration-results file for solved geometry

Raiden's split between camera config and calibration results is cleaner than
trying to make one file do everything.

### 3. Keep `sensors.local.yaml` as the one local rig config

Do not reintroduce extra concepts like "overlay" as first-class operator terms.

Use the sensors file for:

- serial/path to role mapping
- local rig metadata
- default hints

That part is already conceptually correct.

### 4. Add replay

Replay is the clearest missing verification primitive in our current system.

Even a first version that replays only raw command trajectories would materially
improve trust in the pipeline.

### 5. Keep raw manifests as the grouping truth

Raiden relies more on its DB and processed dataset organization.

For us, continue treating:

- `episode_manifest.json`

as the primary truth for later grouping, filtering, and dataset construction.

That preserves one of our strongest design choices.


## Final Judgment

Raiden should be treated as a reference lab system, not just an inspirational
repo.

The two most important conclusions are:

1. We were right to move toward:
   - discovery
   - one local rig file
   - session-level fixed setup
   - raw-first then convert

2. We should stop pretending the current system is finished once the operator
   console works. A real lab stack also needs:
   - calibration
   - replay
   - metadata curation
   - downstream export layers

So the real lesson is not "copy Raiden". It is:

- keep our stronger ROS topic contract and manifest truth
- keep our embodiment-specific naming
- but adopt Raiden's broader operating-model discipline

That is the standard our next architectural decisions should be measured
against.
