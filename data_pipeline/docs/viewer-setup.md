# Viewer Setup

For the higher-level viewer design rationale, see
[Viewer Integration](./viewer-integration.md).

This is a setup page for any account that needs local dataset viewing.

Use it when you are:

- provisioning the shared collection account for local viewer use
- setting up your own Linux account on the existing collection machine
- repairing the viewer toolchain or production build
- setting up a maintainer account that needs `Open Viewer`

Normal operators on the already-prepared lab machine should not need to run this during collection.

The local dataset viewer is not required for raw recording itself, but it is an
important part of the normal workflow:

- inspect a converted dataset locally
- use `Open Viewer` from the operator console
- sanity-check RGB and depth outputs after conversion

The viewer lives in the sibling repo:

- `../lerobot-dataset-visualizer`

## Prerequisites

Before running the viewer setup script:

- complete [Workspace Setup](./workspace-setup.md)
- complete [System Setup](./system-setup.md) if the machine does not already have the required system packages
- complete [Python Environment Setup](./python-env-setup.md) if this account environment is not provisioned yet

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

That last check prevents partial viewer builds from being treated as ready when
`.next/` exists but the production build marker does not.

## Relationship To Open Viewer

The operator console still owns viewer startup at runtime.

`Open Viewer` in the operator console:

- checks the current published dataset target
- ensures the local dataset mount for that folder exists
- starts the viewer server if needed
- opens the resolved local episode URL

What the setup script does is only prepare the viewer toolchain and production
build so that `Open Viewer` does not fail due to missing `bun` or a missing
production bundle.

The supported viewer contract is local-only:

- the viewer server runs on the same machine as the operator console
- the browser is opened on that same machine
- the viewer base URL is always `http://localhost:3000`

## Next Step

After the viewer toolchain is ready, the next step is usually:

- [Personal Account Setup](./personal-account-setup.md) if you are following the personal-account path
- [Lab Machine Quick Start](./lab-machine-quick-start.md) if you are preparing the shared account
- [Hardware Bring-Up](./hardware-bringup.md) if you are testing the flow immediately
