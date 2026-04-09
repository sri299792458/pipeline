# System Boundaries

## Purpose

This page explains the main architectural boundary lines in the pipeline.

The system became easier to reason about once a few responsibilities were made
explicit instead of being mixed together in one runtime or one UI.


## Repository Boundary

### `TeleopSoftware/` owns

- live robot and teleop runtime
- robot-side `/spark/{arm}/robot/...` producers
- teleop command `/spark/{arm}/teleop/...` producers
- the existing teleop GUI and device-launch helpers

Current entrypoints that still live there:

- `TeleopSoftware/launch.py`
- `TeleopSoftware/launch_devs.py`
- `TeleopSoftware/Spark/SparkNode.py`

### `data_pipeline/` owns

- raw episode recording
- per-episode manifests and notes
- session planning and device discovery
- raw-to-published conversion
- offline archive generation
- calibration tools and manifest calibration snapshots
- operator-console workflow
- local viewer startup for published-dataset review

Current entrypoints that live here:

- `data_pipeline/record_episode.py`
- `data_pipeline/convert_episode_bag_to_lerobot.py`
- `data_pipeline/archive_episode.py`
- `data_pipeline/calibrate_rig.py`
- `data_pipeline/operator_console_backend.py`
- `data_pipeline/launch/realsense_contract.launch.py`
- `data_pipeline/launch/gelsight_contract.launch.py`

### Why this split exists

The teleop runtime and the dataset pipeline have different optimization goals:

- teleop code is about live control and device bring-up
- pipeline code is about reproducible capture, provenance, conversion, and
  review

Trying to collapse those into one layer makes both sides harder to evolve.


## Contract Boundary

Three objects are intentionally separate:

- the shared topic contract
- local rig configuration
- one resolved session state

### Shared topic contract

This is the lab-wide contract:

- canonical `/spark/...` topic names
- timestamp meanings
- canonical sensor-key grammar
- topic-level semantics

It must not vary by operator or by one session.

### Local rig configuration

This is machine or rig local:

- device serial or path to canonical sensor-key mapping
- optional local calibration references

It explains which physical device is which canonical sensor, but it does not
invent live devices.

### Resolved session state

This is the per-session truth:

- active arms
- discovered devices chosen for recording
- the canonical sensor key assigned to each recorded device
- the resolved raw topic set for that session

It is a concrete operational decision, not a contract definition.


## Runtime Boundary

The pipeline is intentionally split into separate phases:

1. bring up live producers
2. record one raw episode
3. optionally archive offline
4. convert into a published dataset
5. review in the viewer

Today those phases map to concrete tools:

1. `launch_devs.py`, `launch.py`, `realsense_contract.launch.py`, `gelsight_contract.launch.py`
2. `record_episode.py`
3. `archive_episode.py`
4. `convert_episode_bag_to_lerobot.py`
5. `Open Viewer` via `operator_console_backend.py`

### Why these are separate

- raw capture should stay reliable and low-overhead
- archive compression should not add live recording risk
- published conversion should not redefine what happened during recording
- viewer review should not mutate the raw or published artifacts


## Operator Boundary

The operator console is deliberately not:

- a robot-control replacement
- a fake device authoring tool
- a published-schema debugger

Its job is narrower:

- choose session metadata
- discover live devices
- decide what to record this session
- show health
- trigger recording, conversion, and viewer review

This is why publish-time settings like `Published Folder` and `Conversion Profile`
live in the later artifact flow rather than the session-start section.

In the current Qt UI, those later settings live under `Latest Artifacts`, not
inside the session-start controls.


## Design Rule

When a new feature is proposed, the first question should be:

- which layer actually owns this decision?

If the answer is unclear, the feature probably crosses a boundary that the
pipeline has already learned to keep separate.
