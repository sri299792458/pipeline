# Setup

This section is the curated setup path for this system.

The goal is not to explain every design detail up front. The goal is to get a
lab user from:

- the real starting point they actually have

to:

- a healthy operator-console bring-up
- one successful raw recording
- one successful published conversion
- one successful local viewer review

## Three Different Starting Points

There are three different setup audiences:

- operator using `shared_account` on the already-prepared collection machine
- lab member using their own Linux account on the already-prepared collection machine
- admin or maintainer provisioning or repairing the machine itself

Those are not the same workflow.

## Default Path: Shared Collection Account

For the normal collection-only workflow on the dedicated lab machine, start
here:

- [Lab Machine Quick Start](./lab-machine-quick-start.md)

That is the shortest operator path we expect many collection-only users to use.

## Personal Account Path: Existing Lab Machine

If you are a lab member using your own Linux account on the same prepared
machine, start here:

- [Personal Account Setup](./personal-account-setup.md)

This is the right path when the machine already has ROS and system packages,
but your own account still needs a workspace, `.venv`, or viewer setup.

## Admin Path: Machine Provisioning

If you are:

- building a fresh machine
- repairing the machine-level base install
- reinstalling ROS or apt packages
- recovering the machine after a system-level break

use:

- [System Setup](./system-setup.md)

## Recommended Order

For a collection-only user on `shared_account`, follow these pages in order:

1. [Lab Machine Quick Start](./lab-machine-quick-start.md)
2. [Hardware Bring-Up](./hardware-bringup.md)
3. [First Raw Demo](./first-raw-demo.md)
4. [First Published Conversion](./first-published-conversion.md)
5. [First Viewer Review](./first-viewer-review.md)

For a lab member using their own account on the existing machine, the normal
path is:

1. [Personal Account Setup](./personal-account-setup.md)
2. [Hardware Bring-Up](./hardware-bringup.md)
3. [First Raw Demo](./first-raw-demo.md)
4. [First Published Conversion](./first-published-conversion.md)
5. [First Viewer Review](./first-viewer-review.md)

## Supporting Setup Pages

These pages still matter, but they are supporting setup pages rather than the
default operator flow on `shared_account`:

- [Workspace Setup](./workspace-setup.md)
- [Python Environment Setup](./python-env-setup.md)
- [Viewer Setup](./viewer-setup.md)
- [System Setup](./system-setup.md)

## Optional But Important

Calibration is not part of the shortest first-smoke-test path, but it is part
of the real system and should be treated as first-class work before serious data
collection:

- [Calibration](./calibration.md)

## What This Section Covers

This setup section is for:

- the normal shared lab machine path
- the personal-account path on the same machine
- operator-console bring-up
- first end-to-end smoke-test workflow
- maintainer setup pages when the shared account or machine must be repaired or rebuilt

This setup section is **not** the place for:

- architecture rationale
- topic-contract deep dives
- storage design rationale
- internal implementation history
- speculative or archive-only design docs

Those belong in the later documentation sections:

- design choices
- operations and debugging
