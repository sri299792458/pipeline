# Viewer Setup

The local dataset viewer is not required for raw recording itself, but it is an
important part of the normal workflow:

- inspect a converted dataset locally
- use `Open Viewer` from the operator console
- sanity-check RGB and depth outputs after conversion

The viewer lives in the sibling repo:

- `../lerobot-dataset-visualizer`

## Prerequisites

Before running the viewer setup script:

- complete [workspace-setup.md](./workspace-setup.md)
- complete [system-setup.md](./system-setup.md)

In particular, the viewer setup expects:

- `node`
- `npm`

The script will install `bun` under:

- `~/.bun/bin/bun`

if it is not already present.

## Setup Command

From the main repo root:

```bash
./data_pipeline/setup_viewer_env.sh
```

What the script does:

- checks that the sibling `lerobot-dataset-visualizer` checkout exists
- checks that `node` and `npm` exist
- installs `bun` if missing
- runs `bun install --frozen-lockfile`
- runs `bun run build`
- verifies that `.next/BUILD_ID` exists

That last check matters because we previously saw a broken local viewer state
where `.next/` existed but the production build marker did not.

## Relationship To Open Viewer

The operator console still owns viewer startup at runtime.

`Open Viewer` in the operator console:

- checks the current published dataset target
- starts the viewer server if needed
- strips proxy environment variables for the local dataset path
- opens the resolved local episode URL

What the setup script does is only prepare the viewer toolchain and production
build so that `Open Viewer` does not fail due to missing `bun` or a missing
production bundle.

You do not need to manage the local proxy/runtime quirks manually during normal
use. The operator console's `Open Viewer` path already handles those at runtime.

## Next Step

After the viewer toolchain is ready, the normal workflow is:

- [python-env-setup.md](./python-env-setup.md)
- [hardware-bringup.md](./hardware-bringup.md)
- [first-raw-demo.md](./first-raw-demo.md)
- [first-published-conversion.md](./first-published-conversion.md)
- [first-viewer-review.md](./first-viewer-review.md)
