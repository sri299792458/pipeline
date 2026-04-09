# Design Choices

## Purpose

This section preserves the design decisions that explain why the pipeline looks
the way it does today.

It is not a changelog and it is not a dump of every historical note. The goal
is to keep the durable reasoning visible for the next person who needs to
improve the system.

These pages are meant to track the live code and checked-in scripts, not just
historical intent. If a design page and the implementation diverge, the design
page should be tightened or removed rather than left as decorative prose.


## Core Design Pages

- [system-boundaries.md](./system-boundaries.md)
  - what `data_pipeline/` owns, what `TeleopSoftware/` still owns, and why the
    runtime is split across raw capture, conversion, archive, calibration, and
    viewing
- [artifact-model.md](./artifact-model.md)
  - why one demo produces a raw episode, why archive is offline, and why the
    published dataset is a separate artifact
- [episode-manifest-design.md](./episode-manifest-design.md)
  - why `episode_manifest.json` is the single resolved per-episode snapshot
- [environment-and-workspace-model.md](./environment-and-workspace-model.md)
  - machine-level vs account-level setup, system ROS vs repo-local `.venv`, and
    why the sibling workspace layout exists
- [calibration-design.md](./calibration-design.md)
  - why calibration is first-class, how local rig identity differs from solved
    geometry, and why solved results are snapshotted into raw manifests
- [operator-console-design.md](./operator-console-design.md)
  - why the console is discovery-first and why session bring-up is separate from
    conversion and viewer review
- [viewer-integration.md](./viewer-integration.md)
  - why the local viewer is supported the way it is today, what `Open Viewer`
  owns, and where the current design debt still lives
- [sensor-runtime-design.md](./sensor-runtime-design.md)
  - why the pipeline uses a direct RealSense bridge and a thin GelSight ROS
    bridge instead of treating upstream sensor stacks as the final contract
- [archive-and-compression-strategy.md](./archive-and-compression-strategy.md)
  - why live capture stays simple, why archive is offline, and why compression
    policy is tied to artifact boundaries


## Contract And Runtime Pages

- [topic-contract.md](./topic-contract.md)
  - canonical `/spark/...` topic names, timestamp meanings, and semantic rules
- [session-capture-plan.md](./session-capture-plan.md)
  - session model, device discovery rules, and canonical sensor-key handling
- [dataset-mapping.md](./dataset-mapping.md)
  - published dataset contract, alignment policy, and schema resolution
- [calibration.md](./calibration.md)
  - calibration model and why solved geometry lives outside the sensors file
- [operator-console-spec.md](./operator-console-spec.md)
  - why the operator console is discovery-first and why session bring-up is
    separate from published conversion


## Storage And Archive References

- [raw-storage.md](./raw-storage.md)
  - raw capture storage policy and why capture bags stay plain MCAP
- [archive-bag.md](./archive-bag.md)
  - offline archive strategy and compression policy
- [depth-storage.md](./depth-storage.md)
  - why published depth is handled separately from RGB and low-dimensional data


## Internal References

These files still contain useful implementation history, but they should feed
the curated design pages above rather than become the public design section on
their own:

- [../V2_SPEC.md](../V2_SPEC.md)
- [../V1_SPEC.md](../V1_SPEC.md)
- [../notes/running-notes.md](../notes/running-notes.md)
