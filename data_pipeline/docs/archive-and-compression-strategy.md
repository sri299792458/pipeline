# Archive And Compression Strategy

## Purpose

This page explains why live recording, archive generation, and published export
are separate stages with different compression policies.


## Core Decision

The pipeline does not try to make the live capture bag also be the final
storage-optimized artifact.

Instead, it separates:

- raw capture
- offline archive generation
- published dataset export

That separation is deliberate.


## Why Live Capture Stays Simple

The capture path is optimized for:

- recording reliability
- low runtime overhead
- faithful raw topic preservation
- safe post-take debugging

That is why the capture bag stays:

- one bag per demo
- plain `mcap`
- untrimmed
- not rewritten in place after recording

The design assumption is that recording integrity matters more than squeezing
maximum storage savings out of the first write.


## Why Archive Is Offline

Archive generation does the work that is too risky or too expensive to put on
the live recording path:

- head/tail trim
- lossless image transcode
- MCAP chunk compression
- archive verification and provenance

Doing this offline means:

- the original capture stays preserved if archive generation fails
- one bad archive job does not corrupt the source-of-truth artifact
- heavy transcode work does not sit on the demo-to-demo critical path

In the current implementation, `archive_episode.py` also writes a separate
`archive_manifest.json` so trim, transcode, and final archive settings are
auditable without mutating the raw episode manifest.


## Why Compression Policy Depends On Artifact Type

Compression is not one global policy. It depends on what the artifact is for.

### Capture bag

Primary goal:

- trustworthy recording

Preferred properties:

- minimal runtime work
- simple storage backend
- no in-place mutation

### Archive bag

Primary goal:

- smaller long-term ROS-native artifact

Preferred properties:

- lossless image compression
- offline trim
- MCAP chunk compression

Current implementation note:

- `archive_episode.py` currently exposes `zstd_fast` and `zstd_small`
- the default archive preset is `zstd_small`

### Published dataset

Primary goal:

- aligned learning artifact

Preferred properties:

- fixed-rate frames
- model-facing schema
- copied source provenance


## Why The Archive Path Is Lossless

The archive path is designed to stay lossless for the currently important visual
modalities.

That is why the current direction is:

- RGB and tactile archived with PNG-backed compressed image transport
- depth archived with lossless `compressedDepth` PNG

The design reasoning is simple:

- archive should reduce storage cost
- but it should not give up future debugging or geometry fidelity casually


## Why Head/Tail Trim Moved Out Of Recording

Trim is now an archive-time decision, not a record-time mutation.

That avoids two older problems:

- recording logic doing too much on the critical path
- source-of-truth bags being rewritten to fit later storage preferences

The raw capture remains what was recorded.
The archive is the curated long-term ROS-native derivative.


## Design Consequence

Future work should preserve this artifact logic:

- capture first
- archive later
- publish separately

If one stage starts trying to impersonate another, the pipeline will become
harder to trust and harder to debug.
