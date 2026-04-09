# Operator Console V2 Spec

For the higher-level design rationale behind the console workflow, see
[operator-console-design.md](./operator-console-design.md).

## Goal

Build a lab-facing console for:

- session setup
- health checks
- raw recording
- conversion
- viewer launch

without turning the UI into:

- a robot-control replacement
- a device authoring tool
- a schema debugger


## Governing Model

The operator console follows the V2 session-state model.

See:

- [session-capture-plan.md](./session-capture-plan.md)
- [topic-contract.md](./topic-contract.md)
- [../V2_SPEC.md](../V2_SPEC.md)


## Workflow

1. fill session metadata
2. optionally load a presets file
3. choose the sensors file
4. click `Discover Devices`
5. set `Record` and `Sensor Key` for discovered devices
6. optionally save the current presets file or sensors file for later reuse
7. click `Start Session`
8. record one or more episodes
9. convert
10. open viewer

The operator should not need to rebuild the rig model every episode.


## UI Sections

### 1. Session metadata

Includes:

- presets file
- task name
- language instruction
- operator
- active arms
- sensors file

This is session-level metadata, not device identity.

The presets-file control may:

- browse to a presets YAML file and apply it immediately
- save the current session metadata and device choices with `Save As`
- remember the currently selected file as the default for the next launch

The operator should be able to choose both:

- the presets file
- the sensors file

through file dialogs instead of pasting paths manually.

For the sensors file:

- browsing to a file should be enough
- `Save As` should write the currently assigned sensor mappings
- the currently selected file should become the default for the next launch

### 2. Discovered devices

This is the main device table.

It must show discovered devices only.

Columns:

- `Record`
- `Device`
- `Hardware ID`
- `Sensor Key`

Rules:

- `Device` and `Hardware ID` are read-only
- `Record` is editable
- `Sensor Key` is editable
- sensor-key choices are filtered by device kind
- the `Sensor Key` dropdown may include `Custom...`:
  - it should accept a manually entered canonical sensor key
  - the key must validate against the shared topic-prefix grammar for that device kind
- `Hardware ID` is only a display field:
  - RealSense rows show the device serial number
  - GelSight rows show the device path
  - it is not a second canonical naming layer

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

### 6. Published dataset target

This is a convert-time setting, not session metadata.

It must:

- live in the `Latest Artifacts` area
- point at one direct child under `published/`
- be remembered locally across sessions
- support `Browse` for existing dataset folders
- support manual entry for a new dataset folder name


## Hidden Mechanics

The console may use the selected sensors file to suggest default sensor-key matches.

It must not expose internal categories such as:

- overlay
- expected devices
- missing devices
- profile compatibility
- blocked profiles
- resolved topic explanations

Those are implementation details, not operator-facing concepts.
