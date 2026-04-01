# Published Depth Storage Contract

## Goal

Add RealSense depth to the published dataset in a way that is:

- lossless
- aligned to the same published frame grid as RGB/state/action
- practical to upload and read later
- independent of a private LeRobot core fork


## Decision

- Published depth must not be encoded through the current LeRobot RGB video path.
- Published depth must be stored as a separate lossless sidecar under the published dataset root.
- The first supported published depth fields are:
  - one field for each recorded RealSense sensor with a published depth stream
- Depth values must be preserved as native raw `uint16` images.
- The canonical on-disk payload for each published depth frame is:
  - PNG-encoded 16-bit grayscale bytes
- These depth frames must be stored in chunked parquet files rather than as one file per frame.


## Why

- The current LeRobot dataset path is designed around:
  - parquet for low-dimensional data
  - image/video features for visual streams
- The current local LeRobot checkout is not depth-ready as a published feature path:
  - `video_utils.py` reports `video.is_depth_map = False`
  - `image_writer.py` still assumes 3-channel images for writing
- RealSense depth is already native `uint16` and should not be quantized down to 8-bit by default.
- RGB-D manipulation stacks commonly treat depth as a geometry signal that should stay lossless at storage time, even if training-time preprocessing later converts it to:
  - float depth
  - normalized depth
  - point clouds
  - voxels


## Boundary

- This contract applies only to the published dataset under:
  - `published/<dataset_id>/`
- It does not change:
  - raw rosbag capture
  - raw topic names
  - the existing RGB LeRobot export path
  - tactile publication policy
- This step does not require or imply a LeRobot core fork.


## First Scope

### Included

- RealSense depth from any recorded sensor key that resolves to a published depth field
- alignment to the published frame grid
- lossless storage
- metadata sufficient to locate and decode the depth sidecar later

### Excluded

- GelSight derived depth
- point cloud publication
- normal maps
- tactile marker offsets
- training-loader integration in this step


## Dataset Shape

The published RGB/state/action dataset remains the primary LeRobot dataset.

Depth is added as a sidecar tree next to it:

```text
published/<dataset_id>/
  data/
  meta/
  videos/
  depth/
    observation.depth.lightning.wrist_1/
      chunk-000/
        file-000000.parquet
        file-000001.parquet
    observation.depth.world.scene_1/
      chunk-000/
        file-000000.parquet
        file-000001.parquet
  depth_preview/
    observation.depth.lightning.wrist_1/
      chunk-000/
        file-000000.mp4
    observation.depth.world.scene_1/
      chunk-000/
        file-000000.mp4
  meta/depth_info.json
```

`depth/` is the canonical lossless payload.

`depth_preview/` is a viewer-oriented companion only:

- generated from the canonical depth sidecar
- not a replacement for it
- allowed to be lossy because it is not the training/storage source of truth
- intended to match the default `realsense-viewer` preview semantics


## Row Contract

Each row in a depth parquet file must contain:

- `episode_index`
- `frame_index`
- `timestamp`
- `png16_bytes`
- `height`
- `width`
- `source_topic`

Field requirements:

- `episode_index`
  - integer
  - matches the published LeRobot episode index
- `frame_index`
  - integer
  - matches the published frame index within that episode
- `timestamp`
  - float seconds on the same published grid used for RGB/state/action
- `png16_bytes`
  - binary blob containing a single 16-bit grayscale PNG frame
- `height`
  - integer
- `width`
  - integer
- `source_topic`
  - exact raw depth topic used for the aligned sample


## Metadata Contract

`meta/depth_info.json` must include at least:

- `dataset_id`
- `depth_fields`
- `encoding`
- `unit`
- `alignment_policy`
- `chunking`
- `episode_indices_present`

Expected values:

- `encoding`
  - `png16_gray`
- `unit`
  - `raw_uint16`
- `alignment_policy`
  - nearest-to-grid from the same published frame grid already used by the converter

`meta/depth_info.json` is only a dataset-level sidecar index.

Metric interpretation must come from the copied source manifest for the episode that produced the depth frames:

- `meta/spark_source/<episode_id>/episode_manifest.json`
- use the corresponding RealSense sensor entry's `depth_scale_meters_per_unit`


## Alignment Policy

Depth must align to the same published frame grid as RGB/state/action.

For each published depth field:

- source topic:
  - the recorded RealSense depth topic for that sensor key
  - for example:
    - `/spark/cameras/lightning/wrist_1/depth/image_rect_raw`
    - `/spark/cameras/world/scene_4/depth/image_rect_raw`
- selection rule:
  - nearest frame to the published timestamp
- tolerance:
  - use the same skew policy family as image alignment
  - define a field-level `max_skew_ms` for depth explicitly in the profile

If depth fails alignment:

- do not silently fabricate a depth frame
- follow the same episode failure policy style used for the current converter:
  - tail failure may truncate
  - mid-episode failure should fail the episode unless explicitly redesigned later


## Why Chunked Parquet Instead of Loose PNG Files

- uploading many tiny files is operationally bad
- parquet keeps the artifact count manageable
- binary payloads in parquet are easy to shard and stream later
- this avoids forcing depth into the current video feature path just to get fewer files


## Why `uint16` Lossless Storage

- RealSense depth is natively `uint16`
- preserving it avoids premature quantization
- later loaders can always convert to:
  - float32 meters
  - clipped normalized depth
  - point clouds
  - voxel grids
- the reverse is not true if we first collapse depth to 8-bit


## Non-Goals

- Do not normalize depth into RGB-like images in this step.
- Do not add a private `depth_image` feature type inside LeRobot in this step.
- Do not publish tactile-derived depth in this step.
- Do not replace the canonical lossless sidecar with preview video.


## Follow-On Work

1. Keep depth field generation aligned with the generic conversion profile and effective per-episode schema.
2. Extend `convert_episode_bag_to_lerobot.py` to emit the depth sidecar.
3. Add per-episode conversion artifacts for depth:
   - row counts
   - depth alignment diagnostics
   - per-field shape and source-topic metadata
4. Keep the viewer-specific preview path aligned with the default `realsense-viewer` preview behavior.
5. Decide later whether to add:
   - depth-aware loaders
   - an upstream LeRobot contribution once the sidecar contract is stable
