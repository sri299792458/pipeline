# Raw, Published, And Archive Artifacts

## Purpose

This page explains the three main artifact types in the pipeline and why they
are intentionally separate.


## One Demo, One Raw Episode

The first durable artifact for a take is always:

- one raw episode folder under `raw_episodes/<episode_id>/`

That folder contains:

- `bag/`
- `episode_manifest.json`
- `notes.md`

The raw episode is the source-of-truth record of what happened during the take.

Current raw-episode contents are:

- `bag/`
- `episode_manifest.json`
- `notes.md`


## Artifact Types

### 1. Capture bag

The capture bag is the immediate ROS-native output of recording.

Current policy:

- one bag per demo
- plain `mcap`
- no live trim
- no live bag rewrite

### Why

Live recording should optimize for:

- reliability
- faithful topic preservation
- post-take debugging
- safe downstream conversion

It should not try to be the final storage-optimized artifact.


### 2. Archive bag

The archive bag is a derived offline artifact created later from the preserved
capture bag.

Its purpose is:

- long-term storage reduction
- ROS-native playback and inspection
- lossless compression of visual topics

### Why archive is offline

Compression, trim, and transcode add runtime risk during recording. The pipeline
separates that work so:

- the demo-to-demo critical path stays simple
- failures in archive generation do not corrupt the original capture
- capture bags remain available for debugging and conversion

See:

- [raw-storage.md](./raw-storage.md)
- [archive-bag.md](./archive-bag.md)

Current archive outputs live under:

- `raw_episodes/<episode_id>/archive/`
- `raw_episodes/<episode_id>/archive/bag/`
- `raw_episodes/<episode_id>/archive/archive_manifest.json`


### 3. Published dataset

The published dataset is the fixed-schema learning artifact under `published/`.

It is derived from the raw episode, not from the operator UI state and not from
the archive bag by default.

Its purpose is:

- fixed-rate aligned training data
- stable LeRobot-compatible schema
- long-term provenance for converted episodes

### Why it is separate from archive

The archive bag stays ROS-native.
The published dataset is model- and tooling-facing.

Keeping them separate avoids a false choice between:

- ROS-native debugging
- training-ready dataset layout


## Source Of Truth Rule

The raw episode remains authoritative because it preserves:

- the original asynchronous topic streams
- the resolved per-episode manifest snapshot
- notes attached to the take

The published dataset may copy source provenance, but it is still a derived
view.

Current conversion artifacts also include:

- `published/<dataset_id>/meta/spark_conversion/<episode_id>/diagnostics.json`
- `published/<dataset_id>/meta/spark_conversion/<episode_id>/conversion_summary.json`
- `published/<dataset_id>/meta/spark_conversion/<episode_id>/effective_profile.yaml`


## Published Provenance Rule

The published dataset now keeps a copy of the raw source snapshot for each
converted episode under:

- `meta/spark_source/<episode_id>/episode_manifest.json`
- `meta/spark_source/<episode_id>/notes.md`

This keeps the learning artifact tied back to the exact raw episode truth
without pretending that dataset-level metadata alone is enough.

If published depth is enabled for the effective schema, the dataset also carries
derived sidecars under:

- `published/<dataset_id>/depth/`
- `published/<dataset_id>/depth_preview/`
- `published/<dataset_id>/meta/depth_info.json`


## Design Consequences

- do not optimize live recording around long-term archive size first
- do not treat the published dataset as a substitute for the raw episode
- do not assume the archive bag is interchangeable with the raw capture unless
  the pipeline is explicitly redesigned around that choice
