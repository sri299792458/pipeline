# Environment And Workspace Model

## Purpose

This page explains the environment split that the pipeline now depends on:

- machine-level setup
- account-level setup
- system ROS Python vs repo-local `.venv`
- sibling workspace layout


## Machine-Level Vs Account-Level Setup

These are different responsibilities.

### Machine-level setup

This is admin work done once per machine:

- ROS Jazzy installation
- apt-installed base packages
- RealSense runtime prerequisites
- system device permissions and group provisioning
- prepared `shared_account` if the machine has one

Current machine-level helpers include:

- `/opt/ros/jazzy`
- `data_pipeline/setup_realsense_contract_runtime.sh`

On the dedicated collection machine, this setup is already expected to exist.

### Account-level setup

This is what a lab member does in their own account on the same machine:

- clone the workspace
- create the repo-local `.venv`
- prepare the viewer toolchain if they need local review
- verify access to hardware devices through group membership

Current account-level helpers include:

- `data_pipeline/setup_shared_venv.sh`
- `data_pipeline/setup_viewer_env.sh`

This split matters because a second user on the same machine should not be told
to reinstall ROS just because they are using a different Linux account.


## System ROS Python Vs Repo-Local `.venv`

The runtime deliberately uses two Python contexts.

### System ROS Python

Use system ROS Python for live ROS producers and ROS launch paths:

- `/usr/bin/python3`
- `/opt/ros/jazzy/...`

That is the correct environment for:

- ROS nodes
- launch files
- the RealSense bridge runtime
- the GelSight bridge runtime

### Repo-local `.venv`

Use the repository `.venv` for offline and application-side tools such as:

- conversion
- Qt operator console
- archive generation
- calibration helpers
- validation scripts

### Why the split exists

ROS Jazzy and the RealSense runtime are tied to the system environment. The
offline tools need their own Python dependencies without trying to replace the
system ROS runtime.


## Sibling Workspace Layout

The intended workspace layout is:

- `spark-data-collection/`
- `TeleopSoftware/`
- `lerobot/`
- `lerobot-dataset-visualizer/`
- `librealsense/`

### Why this exists

The pipeline has explicit dependencies on sibling repositories:

- `TeleopSoftware/` for the live robot and teleop runtime
- `lerobot/` for dataset creation and loading
- `lerobot-dataset-visualizer/` for local published-dataset review
- `librealsense/` as the upstream checkout used to build the pinned local
  RealSense runtime

Keeping them side by side makes the local bring-up and tooling contracts
predictable without turning this repo into a monorepo.


## Shared Account Vs Personal Account

The docs now assume two real user paths on the prepared collection machine.

### `shared_account`

This is the operator path:

- log in
- launch the collection workflow
- record, convert, and review

It should not require `sudo` for normal use.

### Personal lab account

This is the maintainer or power-user path:

- same machine-level ROS install
- own workspace clone
- own `.venv`
- own viewer setup if needed

This path still depends on the machine already being provisioned correctly.


## Device Permissions

Hardware access should be solved with device groups, not with blanket sudo.

Current collection-machine expectation:

- SPARK serial devices require `dialout`
- camera access may require `plugdev` and `video`

That is why a prepared account should be added to the right groups rather than
made a sudo-capable operator account by default.


## Design Rule

When environment problems appear, first identify which layer they belong to:

- machine provisioning
- account workspace setup
- ROS runtime environment
- repo-local tool environment

Most setup confusion came from mixing those layers together.
