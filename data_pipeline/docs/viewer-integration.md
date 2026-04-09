# Viewer Integration

## Purpose

This page explains the current local viewer design, what it owns, and where the
remaining design debt still lives.


## Core Decision

The viewer is supported as a local review tool, not as a networked service
surface.

Current supported contract:

- the viewer server runs on the same machine as the operator console
- the browser opens on that same machine
- the base URL is `http://localhost:3000`

This local-only assumption removed a lot of confusion around hostname choice and
stale environment-specific settings.

Current runtime assumptions are also account-local:

- the viewer repo lives at the sibling path `../lerobot-dataset-visualizer`
- `bun` lives under `~/.bun/bin/bun`
- the viewer must already have a production build from
  `data_pipeline/setup_viewer_env.sh`


## Why `Open Viewer` Owns Startup

The operator should not need to manually manage a separate viewer lifecycle for
normal review.

That is why `Open Viewer` owns:

- resolving the current published dataset target
- preparing the local dataset mount for that target
- starting or restarting the viewer server if needed
- opening the resolved episode URL

The setup script prepares the toolchain and production build. Runtime startup is
still owned by the operator console.

In the current backend, `Open Viewer` also checks that the selected dataset's
`meta/info.json` is actually reachable before treating the viewer as ready.


## Why The Viewer Is Separate From Conversion

The viewer inspects published datasets.
It does not define them.

That boundary matters because:

- conversion should succeed without the viewer running
- the viewer should not become a hidden dependency of raw recording
- published datasets remain filesystem artifacts, not viewer-owned objects


## Current Local Dataset Serving Model

The current local viewer integration still uses a compatibility layer under the
viewer repo's `public/` tree so the frontend can read local published datasets
through the expected URL shape.

The exact current mount is:

- `lerobot-dataset-visualizer/public/datasets/local/<dataset_id>/resolve/main`
  -> symlink to
- `spark-data-collection/published/<dataset_id>`

And the backend starts the viewer with:

- `NEXT_PUBLIC_DATASET_URL=http://localhost:3000/datasets`
- `DATASET_URL=http://localhost:3000/datasets`

Operationally, the important current truth is:

- users should not manually create or manage that mount state
- `Open Viewer` should ensure the mount exists for the selected dataset

This keeps the fragile part of the contract in one place instead of leaving it
as tribal knowledge.


## Current Design Debt

The viewer integration still has real design debt:

- local dataset exposure is more implicit than it should be
- the contract still spans two sibling repos
- the frontend toolchain introduces a separate per-account setup surface

So the current design is:

- workable
- documented
- less fragile than before

but not yet a first-principles local dataset-serving architecture.


## Why The Current Design Still Exists

The existing viewer repo already knew how to read dataset files from a URL
shape similar to Hugging Face dataset paths.

The cheapest bridge for local use was to make local published datasets available
through that shape rather than redesign the viewer data layer immediately.

That was a pragmatic choice, not a claim that the architecture is perfect.


## Design Rule

Any future viewer work should preserve these operator-facing truths:

- `Open Viewer` is the one-click review entrypoint
- the operator should not think about mount plumbing
- published datasets remain the source artifact being reviewed

If the implementation changes later, those user-facing properties should stay.
