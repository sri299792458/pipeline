# Lab Machine Quick Start

This page is the default starting point for a normal lab member.

It assumes:

- you are using the dedicated lab data-collection machine
- the machine-level base setup was already done by an admin
- ROS Jazzy and the required apt packages are already installed
- you are logging into the normal collection account such as `shared_account`
- that account has already been provisioned for collection use

This page is **not** for rebuilding the machine from scratch.

If you are provisioning or repairing the machine itself, use:

- [System Setup](./system-setup.md)

## Normal Operator Workflow

For the normal shared-account path, the operator should only need to:

1. log into `shared_account`
2. open a terminal
3. run:

```bash
collect
```

That command should launch the operator console directly.

The operator should not need to manually:

- source ROS
- activate `.venv`
- type the Qt launch command
- rebuild the viewer
- provision the workspace

## What You Usually Do Not Need To Repeat

On the already-prepared lab machine, normal users usually do **not** need to:

- install ROS Jazzy
- install Ubuntu apt packages
- install `node` or `npm`
- perform other machine-level admin setup

Those are machine-level concerns, not per-user setup.

## What You Still Need To Do

The shared collection account still depends on prior maintainer setup, but the
operator should not need to perform that setup during normal collection.

What still matters operationally is:

- the account has the required device-group membership
- the account's collection launcher exists
- the expected workspace and environment already exist

## Recommended Path On The Shared Lab Machine

After `collect` launches the console, continue with:

1. [Hardware Bring-Up](./hardware-bringup.md)
2. [First Raw Demo](./first-raw-demo.md)
3. [First Published Conversion](./first-published-conversion.md)
4. [First Viewer Review](./first-viewer-review.md)

## Quick Checks

Before going further, these should already work for the shared account:

```bash
type collect
id
```

The group list should include:

- `dialout`
- `plugdev`
- `video`

And these machine-level commands should also already work:

```bash
source /opt/ros/jazzy/setup.bash
ros2 --help
```

If any of those checks fail on the shared machine, that is not a normal user
workflow issue. Treat it as machine/account provisioning work and go to:

- [System Setup](./system-setup.md)
- [Workspace Setup](./workspace-setup.md)
- [Python Environment Setup](./python-env-setup.md)
- [Viewer Setup](./viewer-setup.md)

## Calibration

Calibration is not part of the shortest first-smoke-test path, but it is a
real subsystem and should be treated as first-class work before serious data
collection:

- [Calibration](./calibration.md)
