# Offline Archive Bag Spec

For the higher-level design rationale behind this archive path, see
[archive-and-compression-strategy.md](./archive-and-compression-strategy.md).

## Goal

Add an offline archive step that reduces episode storage size without adding
runtime risk to live capture.

This step is specifically about:

- what is recorded during teleop
- what is kept as the long-term ROS-native artifact
- which compression is allowed for each modality


## Decision Direction

The intended direction is:

1. capture with minimal runtime work
2. archive offline after the episode is over
3. keep published dataset export as a separate downstream step

This is explicitly different from trying to make the live capture bag also be
the final storage-optimized artifact.


## Artifact Model

### 1. Capture bag

The capture bag is the immediate post-demo artifact written by
`record_episode.py`.

It exists to optimize:

- recording reliability
- faithful raw topic preservation
- post-demo debugging
- dataset conversion

The capture bag should prefer minimal runtime overhead over maximum final
compactness.

Capture-bag policy:

- format:
  - plain `mcap`
- trim:
  - none
- mutation after record:
  - do not rewrite the capture bag in place

The capture bag is the preserved source-of-truth ROS artifact.

### 2. Archive bag

The archive bag is a derived offline artifact created from the capture bag.

It exists to optimize:

- storage size
- ROS-native playback/debug tooling
- long-term retention

It is not the source of truth for conversion unless we explicitly redesign the
pipeline later.

Archive generation is intentionally not on the demo-to-demo critical path.

It may run:

- per episode later
- in batch after a session
- in batch overnight across many episodes

### 3. Published dataset

The published dataset remains a separate artifact derived from the capture bag.

It is not the same thing as the archive bag.

Retention consequence:

- the capture bag must be retained through published conversion
- archive generation does not make the capture bag immediately disposable
- capture-bag deletion is only allowed after one of these becomes true:
  - published conversion has already completed from that capture bag and archive
    generation has also completed successfully
  - or the conversion pipeline is explicitly updated to trust the archive bag as
    an equivalent source


## Compression Policy

### Canonical requirement

The archive path must remain lossless for all currently important visual
modalities.

### RGB camera

- allowed archive codecs:
  - PNG
- explicitly not allowed:
  - JPEG

Reason:

- preserve future options like stereo, fine visual correspondence, and exact
  appearance debugging

### Tactile RGB

- allowed archive codecs:
  - PNG
- explicitly not allowed:
  - JPEG

Reason:

- preserve fine texture/deformation information

### Depth

- allowed archive codecs in priority order:
  - `compressedDepth` with PNG
  - `compressedDepth` with RVL only after validation

Reason:

- depth is geometry data and must remain lossless


## ROS-Native Archive Design

The archive-bag design is ROS-native:

- read the capture bag
- republish raw image topics through image transport plugins
- record a second bag containing compressed transport topics

This means the archive bag is expected to use:

- `compressed` transport for RGB/tactile with `format=png`
- `compressedDepth` transport for depth with `format=png`

`RVL` is a follow-on option for depth only after explicit validation.


## Current Local Environment

This machine now has the required ROS Jazzy image transport plugins installed:

- `ros-jazzy-image-transport-plugins`
- `ros-jazzy-compressed-image-transport`
- `ros-jazzy-compressed-depth-image-transport`

The current archive tool should assume these transports are available:

- `raw`
- `compressed`
- `compressedDepth`


## Archive Pipeline Order

The archive bag is derived from the preserved untrimmed capture bag in this
order:

1. validate and inspect the capture bag
2. compute and apply head/tail trim
3. re-encode image payloads losslessly
4. apply container-level MCAP compression

This defines the transformation order for one episode. It does not require the
archive job to run immediately after recording.

### Step 1: Validate and inspect capture bag

Before archive generation, the pipeline must verify that the capture bag is
readable and has the expected topic inventory.

This step exists to avoid generating a “clean” archive artifact from a corrupt
or incomplete capture bag.

### Step 2: Compute and apply head/tail trim

Head/tail trim belongs to the archive step, not the live capture step.

Trim basis:

- `/spark/<arm>/teleop/cmd_*`
- `/spark/session/teleop_active`

Trim policy:

- trim only leading and trailing idle time
- do not split or delete mid-episode idle spans
- keep a small fixed pad before and after the active interval

### Step 3: Re-encode image payloads losslessly

After trim, image topics are re-encoded through ROS image transport:

- RGB/tactile:
  - `compressed` with `format=png`
- depth:
  - `compressedDepth` with `format=png`

The archive bag is therefore smaller primarily because the image payloads are
losslessly compressed offline, not because of generic bag-level compression
alone.

### Step 4: Apply container-level MCAP compression

After trim and image-payload compression, the archive bag should also use MCAP
chunk compression.

Preferred direction:

- capture bag:
  - plain `mcap`
- archive bag:
  - `mcap` with zstd chunk compression

The archive spec does not lock to one exact MCAP preset name yet. The required
property is:

- archive bag uses MCAP zstd chunk compression

The current implementation uses a conservative playback-start delay before the
offline transcode pass, because the image transport graph needs time to settle
before the source bag starts publishing.

Preset selection should be benchmarked during implementation, but the design
target is already fixed:

- archive bag uses MCAP zstd chunk compression


## Archive Provenance Requirement

The archive artifact must carry an explicit machine-readable provenance record.

This should live as a separate JSON file alongside the archive bag, rather than
rewriting the raw `episode_manifest.json` in place.

Recommended filename:

- `archive_manifest.json`

Minimum required fields:

- archive creation time
- tool/script version or git commit
- source capture bag path
- source capture bag storage type
- source capture bag size
- source capture bag content fingerprint if available
- whether the source bag was verified successfully
- final archive bag verification result
- trim basis:
  - teleop command topics
  - teleop-active topic
- trim policy:
  - head/tail only
  - pad before/after
- trim outcome:
  - applied or skipped
  - trim window
  - message and size before/after
- image transcode policy per modality:
  - RGB -> `compressed/png`
  - tactile RGB -> `compressed/png`
  - depth -> `compressedDepth/png`
- final archive MCAP compression setting
- output archive bag path
- output archive bag size
- capture bag retention state:
  - retained
  - deleted
  - deletion time if deleted

The point of this file is to make the archive bag auditable:

- what was done
- in what order
- with which settings
- from which source artifact


## Scope

### In scope

- one offline CLI, likely `archive_episode.py`
- input: one recorded capture bag
- output: one archive bag
- capture bag remains preserved and unmodified
- archive step performs head/tail trim
- RGB/tactile re-encoded through PNG transport
- depth re-encoded through PNG compressedDepth transport
- archive bag uses MCAP zstd compression after image transcoding
- `archive_manifest.json` stamps the archive derivation and settings

### Out of scope

- rewriting the capture bag in place during recording
- changing published dataset conversion to read archive bags
- JPEG or other lossy visual codecs
- making RVL the default depth codec immediately
- changing training dataset storage in this step


## Validation Requirements

Before the archive path is adopted, it must prove:

- archive bag is smaller than the capture bag
- RGB/tactile round-trip decode is lossless
- depth round-trip decode is lossless
- archive bag remains usable with normal ROS playback/debug tooling
- published conversion from the capture bag remains unchanged


## Verification Model

Archive confidence should come from two levels of verification.

### Per archive bag

Every archive bag should get lightweight structural verification.

This verifies:

- expected archive topic inventory
- passthrough topic counts
- image-topic counts
- image header-stamp correspondence

This is the default archive-time verification recorded into
`archive_manifest.json`.

### After archive-code changes and periodic spot checks

We also need exact payload round-trip verification on representative bags.

This verifies:

- raw RGB/tactile image bytes match decoded archive PNG bytes exactly
- raw depth image bytes match decoded `compressedDepth/png` bytes exactly

This does not need to run on every bag by default, but it must be rerun when:

- archive transcode logic changes
- image-transport parameterization changes
- codec policy changes

It is also the right stronger check before trusting capture-bag deletion
policy.


## Capture Bag Deletion Policy

The archive bag is the intended long-term ROS storage artifact.

But because published conversion currently still reads the capture bag, the
capture bag is a transient working artifact, not an immediately disposable one.

So the policy is:

1. record and preserve untrimmed capture bag
2. run published conversion from the capture bag if needed
3. generate and verify archive bag at a convenient offline time
4. only then allow capture-bag deletion

If later the pipeline is redesigned so published conversion can trust the
archive bag directly, this deletion policy can be simplified.


## Session-Level Operating Model

Archive generation should not block the operator from proceeding to the next
demo.

Preferred operating model:

1. record multiple demos in a session
2. optionally run published conversion from the preserved capture bags
3. run archive generation later, per episode or as a batch job for the session
4. delete capture bags only after the needed downstream work is complete

So the archive step is a storage-maintenance workflow, not an immediate
post-demo operator task.


## Follow-On Work

After the PNG-based archive path is working, evaluate:

- whether depth RVL materially improves size
- whether archive bags should replace trimmed raw bags for long-term retention
- whether a non-bag archive format is still worth considering later
