# Design Choices

## Purpose

This section preserves the design decisions that explain why the pipeline looks
the way it does today.

It is not a changelog and it is not a dump of every implementation note. The goal
is to keep the durable reasoning visible for the next person who needs to
improve the system.

These pages are meant to track the live code and checked-in scripts, not just
intent written down once and then forgotten. If a design page and the implementation diverge, the design
page should be tightened or removed rather than left as decorative prose.


## Core Design Pages

- [System Boundaries](./system-boundaries.md)
  - what `data_pipeline/` owns, what `TeleopSoftware/` still owns, and why the
    runtime is split across raw capture, conversion, archive, calibration, and
    viewing
- [Artifact Model](./artifact-model.md)
  - why one demo produces a raw episode, why archive is offline, and why the
    published dataset is a separate artifact
- [Episode Manifest Design](./episode-manifest-design.md)
  - why `episode_manifest.json` is the single resolved per-episode snapshot
- [Environment and Workspace Model](./environment-and-workspace-model.md)
  - machine-level vs account-level setup, system ROS vs repo-local `.venv`, and
    why the sibling workspace layout exists
- [Calibration Design](./calibration-design.md)
  - why calibration is first-class, how local rig identity differs from solved
    geometry, and why solved results are snapshotted into raw manifests
- [Operator Console Design](./operator-console-design.md)
  - why the console is discovery-first and why session bring-up is separate from
    conversion and viewer review
- [Viewer Integration](./viewer-integration.md)
  - why the local viewer is supported the way it is today, what `Open Viewer`
  owns, and where the current design debt still lives
- [Sensor Runtime Design](./sensor-runtime-design.md)
  - why the pipeline uses a direct RealSense bridge and a thin GelSight ROS
    bridge instead of treating upstream sensor stacks as the final contract
- [Archive and Compression Strategy](./archive-and-compression-strategy.md)
  - why live capture stays simple, why archive is offline, and why compression
    policy is tied to artifact boundaries


## Contract And Runtime Pages

- [Topic Contract](./topic-contract.md)
  - canonical `/spark/...` topic names, timestamp meanings, and semantic rules
- [Session Capture Plan](./session-capture-plan.md)
  - session model, device discovery rules, and canonical sensor-key handling
- [Published Dataset Contract](./dataset-mapping.md)
  - published dataset contract, alignment policy, and schema resolution
- [Calibration](./calibration.md)
  - calibration model and why solved geometry lives outside the sensors file
