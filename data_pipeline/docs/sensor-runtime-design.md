# Sensor Runtime Design

## Purpose

This page explains the sensor-runtime choices behind the current pipeline.

The important design question was never just “can we read camera frames?” It was
whether the runtime could produce the pipeline's canonical `/spark/...` contract
with trustworthy timing and stable per-episode metadata.


## Core Decision

The pipeline treats upstream vendor or community packages as inputs and
references, not automatically as the final raw-contract runtime.

That is why the runtime uses:

- direct RealSense bridge for the active `/spark/cameras/...` contract
- thin GelSight ROS bridge over the official SDK path


## RealSense Runtime Choice

### RealSense path

The RealSense path is the direct SDK bridge backed by a pinned local
`librealsense v2.54.2` runtime.

Current entrypoints:

- `data_pipeline/setup_realsense_contract_runtime.sh`
- `data_pipeline/launch/realsense_contract.launch.py`
- `data_pipeline/realsense_bridge.py`

### Why this was chosen

The important requirements were:

- stable canonical `/spark/cameras/...` topics
- host-capture-time stamping immediately after `wait_for_frames()`
- paired color and depth stamp semantics
- reliable access to record-time device and stream metadata for the manifest

The direct bridge satisfies those requirements more explicitly than treating an
arbitrary system `realsense2_camera` path as the contract.

Concretely, the current launch path injects:

- `build/librealsense-v2.54.2/Release`

into `PYTHONPATH` and `LD_LIBRARY_PATH`, then launches the bridge with
`/usr/bin/python3`.

### Why `realsense2_camera` was not made the contract

The pipeline did not reject the official wrapper as useless. It rejected the
idea that the wrapper's default behavior should define the pipeline contract.

The raw contract cares about:

- canonical topic shape
- explicit timestamp semantics
- stable metadata capture

Those had to remain pipeline-owned decisions.


## GelSight Runtime Choice

### GelSight path

GelSight uses a thin ROS bridge over the official `gsrobotics` path.

Current entrypoints:

- `data_pipeline/launch/gelsight_contract.launch.py`
- `data_pipeline/gelsight_bridge.py`

### Why this was chosen

`gsrobotics` is the authoritative SDK reference, but it is not itself a ROS
topic producer for the pipeline's contract.

The bridge layer is intentionally small:

- capture the image
- stamp it with host ROS time immediately after acquisition
- publish canonical `/spark/tactile/...` topics

Today that bridge publishes only:

- `/spark/tactile/{arm}/{finger_slot}/color/image_raw`

after local crop-and-resize preprocessing.

That keeps the pipeline from pretending that an SDK demo path is already a full
dataset-contract runtime.


## Raw-Only Vs Published Streams

This runtime split also supports an important design rule:

- not every raw stream has to become a published dataset field

Examples:

- RealSense depth may remain raw-only unless the effective published schema
  includes published depth
- derived tactile outputs can exist as runtime or raw-only signals without being
  forced into the published schema

That keeps the runtime honest and the published dataset smaller.


## Metadata Consequence

The sensor runtime is also responsible for exposing the record-time metadata the
manifest needs.

For RealSense, that includes information such as:

- device type
- firmware version
- stream profiles
- intrinsics
- depth scale

The current manifest path gets those from parameters declared by
`realsense_bridge.py` and read back by `infer_sensor_metadata()`.

That was a major reason to keep the runtime decision tied to the manifest design
instead of treating it as a purely transport-level implementation detail.


## Design Rule

Future sensor-runtime changes should be judged against this question:

- does the runtime make the canonical raw contract and manifest metadata more
  explicit, or is it pushing those decisions back into opaque upstream behavior?

If it is the latter, the pipeline is giving away too much contract ownership.
