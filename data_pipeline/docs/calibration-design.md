# Calibration Design

## Purpose

This page explains why calibration became a first-class subsystem in the
pipeline instead of staying a loose set of local notes and ad hoc scripts.


## Core Decision

The pipeline now treats calibration as three separate things:

- canonical sensor identity
- solved camera geometry
- per-episode calibration snapshot

Those three must not be collapsed into one file or one operator action.


## Sensors File Vs Calibration Results

### Sensors file

The sensors file answers:

- which physical device is which canonical sensor key?

Examples:

- which RealSense serial is `/spark/cameras/world/scene_1`?
- which device path is `/spark/tactile/lightning/finger_left`?

It is about rig identity and role assignment.

### Calibration results

`calibration.local.json` answers:

- where is that camera?
- what are its solved intrinsics and extrinsics?
- what hand-eye result was solved for a wrist camera?

It is about geometry, not identity.

### Why they stay separate

Device identity and solved geometry change on different timescales and for
different reasons. Mixing them makes both files harder to trust:

- the sensors file should stay simple enough to edit safely
- calibration results should be treated as solved outputs, not hand-edited rig
  inventory


## Why Calibration Is First-Class

The pipeline reached a point where calibration was no longer optional metadata.

It matters for:

- wrist-camera hand-eye alignment
- scene-camera extrinsics in a robot-base frame
- downstream validation of what the recorded visual streams mean geometrically

Without a first-class calibration subsystem, the pipeline would still record
bags, but the episode truth would be much weaker.


## Current Solving Model

The current design uses:

- ChArUco observations for camera geometry
- recorded robot poses from `record_calibration_poses.py`
- UR `getActualTCPPose()` for wrist-camera hand-eye
- one selected wrist camera as the reference path for solving static scene
  cameras in that arm's base frame

This gives one coherent geometry model without inventing custom per-camera
special cases.

More concretely, `calibrate_rig.py` currently does this:

1. open the selected RealSense cameras
2. replay the recorded pose list from `calibration_poses.local.json`
3. detect the ChArUco board in each camera
4. solve wrist-camera `flange_from_camera`
5. solve each scene camera against one reference wrist camera

If both wrist cameras are available and no explicit reference is requested, the
current lab default is to prefer Lightning as the reference wrist camera.


## Why The Manifest Snapshots Calibration

Record time should not depend forever on whatever calibration file happens to be
present later.

That is why the recorder snapshots active solved calibration into
`episode_manifest.json` when available.

### Why this matters

If calibration changes later, the old episode must still remain interpretable as
it was when recorded.

The design rule is:

- local calibration files are the current working state
- the manifest snapshot is the episode-time truth

The current working file is:

- `data_pipeline/configs/calibration.local.json`

and `calibrate_rig.py` writes camera-centric results there, including:

- per-camera intrinsics
- wrist-camera hand-eye results
- scene-camera extrinsics
- optional `reference_wrist_camera`
- `coordinate_frame` for scene-camera solutions


## Operator Boundary

Calibration is intentionally not part of the normal session-start UI.

Operators should not be typing geometry into the console.

The console uses:

- selected sensors file
- discovered devices
- current solved calibration when present

But the solve-and-validate workflow remains its own subsystem.

Also, the current calibration subsystem is camera-only. The operator console may
record GelSight devices, but `calibrate_rig.py` does not solve GelSight
geometry.


## Design Consequence

Any future change should preserve this split:

- rig identity in the sensors file
- solved geometry in calibration results
- per-episode resolved snapshot in the manifest

If those collapse back together, the pipeline will become harder to trust over
time.
