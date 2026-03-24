# Operator Console V2 Spec

## Goal

Build a lab-facing console for:

- session setup
- readiness validation
- raw recording
- conversion
- viewer launch

without turning the UI into:

- a robot-control replacement
- a device authoring tool
- a schema debugger


## Governing Model

The operator console follows the V2 session-profile model.

See:

- [session-capture-plan.md](./session-capture-plan.md)
- [topic-contract.md](./topic-contract.md)
- [../V2_SPEC.md](../V2_SPEC.md)


## Workflow

1. fill session metadata
2. choose the sensors file
3. click `Discover Devices`
4. set `Record` and `Role` for discovered devices
5. click `Start Session`
6. click `Validate`
7. record one or more episodes
8. convert
9. open viewer

The operator should not need to rebuild the rig model every episode.


## UI Sections

### 1. Session metadata

Includes:

- dataset id
- robot type
- task name
- language instruction
- operator
- active arms
- sensors file
- viewer base URL

This is session-level metadata, not device identity.

### 2. Discovered devices

This is the main device table.

It must show discovered devices only.

Columns:

- `Record`
- `Kind`
- `Model`
- `Identifier`
- `Role`

Rules:

- `Kind`, `Model`, and `Identifier` are read-only
- `Record` is editable
- `Role` is editable
- role choices are filtered by device kind

Forbidden behavior:

- fabricate live devices from presets or the sensors file
- add arbitrary camera rows
- add arbitrary GelSight rows
- delete discovered rows
- type a new device identifier into the main table
- expose raw topic selection in the main workflow

If the operator does not want a discovered device in this session, they uncheck `Record`.

### 3. Subsystem health

This section shows:

- SPARK devices
- Teleop GUI
- RealSense
- GelSight
- recorder
- converter

Readiness must be based on measured health, not merely “process started”.

### 4. Action output and logs

The operator must always be able to see:

- exact failure point
- last validation output
- last recording check
- last conversion output
- recent process logs

### 5. Latest episode notes

Post-take episode notes are optional.

They must:

- attach to the latest recorded episode only
- be saved after a take, not before recording starts
- reset to blank when a new episode becomes current


## Hidden Mechanics

The console may use the sensors file to suggest default roles and metadata.

It must not expose internal categories such as:

- overlay
- expected devices
- missing devices
- profile compatibility
- blocked profiles
- resolved topic explanations

Those are implementation details, not operator-facing concepts.
