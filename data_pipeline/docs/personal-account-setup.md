# Personal Account Setup

This page is for a lab member using their own Linux account on the already-prepared
collection machine.

Use this path when:

- the machine already has ROS Jazzy and the required apt packages
- you do not want to use `shared_account`
- your own account needs its own workspace, `.venv`, or local viewer setup

This is **not** the right page for:

- collection-only users on `shared_account`
- rebuilding the machine itself

Use instead:

- [Lab Machine Quick Start](./lab-machine-quick-start.md) for the shared collection account
- [System Setup](./system-setup.md) for machine provisioning or repair

## What Is Different From `shared_account`

On the same prepared machine, you usually do **not** need to:

- install ROS Jazzy again
- reinstall the machine-wide apt packages
- rebuild the machine-level base setup

But your own account may still need:

- the repo workspace
- the shared local `.venv`
- the local viewer toolchain
- device-access group membership if you need direct hardware access

## Recommended Order

Follow these pages in order:

1. [Workspace Setup](./workspace-setup.md)
2. [Python Environment Setup](./python-env-setup.md)
3. [Viewer Setup](./viewer-setup.md) if you need `Open Viewer`
4. [Hardware Bring-Up](./hardware-bringup.md)
5. [First Raw Demo](./first-raw-demo.md)
6. [First Published Conversion](./first-published-conversion.md)
7. [First Viewer Review](./first-viewer-review.md)

## Group Membership Still Matters

If your personal account needs direct access to the collection hardware, it may
still need the same device-access groups as `shared_account`, especially:

- `dialout`
- `plugdev`
- `video`

If those are missing, treat that as account provisioning work and use:

- [System Setup](./system-setup.md)

## Calibration

Calibration is not part of the shortest smoke-test path, but it remains part of
the real system:

- [Calibration](./calibration.md)
