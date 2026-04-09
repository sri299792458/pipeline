# Operator Console Design

## Purpose

This page explains the design decisions behind the operator console.

The console is the main lab-facing workflow surface, so it needs a clear model
for what operators are allowed to decide and what the pipeline keeps fixed.


## Core Decision

The operator console is discovery-first.

That means:

- live device discovery is the starting point
- operators confirm and label what is present
- operators do not author a fake rig model from scratch in the UI

This was one of the most important simplifications in the current design.


## Why Discovery Comes First

The console should not drift toward:

- expected-device panes
- missing-device authoring
- profile compatibility matrices
- fake devices coming from presets

That made the console act like a rig editor instead of a session tool.

The current model is narrower and more honest:

- if a device is not discovered, it is not part of the live session
- the sensors file may provide defaults, but it does not invent live devices
- the device table should show discovered devices only


## What The Operator Actually Decides

At session start, the operator chooses:

- session metadata
- which discovered devices are recorded
- which canonical sensor key each recorded device uses

The operator does not redefine:

- canonical topic names
- timestamp semantics
- published dataset schema
- the machine's rig identity model


## Why Session Bring-Up Is Separate From Conversion

The console now keeps a hard boundary between:

- session bring-up
- latest-artifact actions

Session bring-up decides:

- what this session records

Latest-artifact actions decide:

- where the latest raw episode should be converted
- which conversion policy to use
- how to review the resulting published dataset

That is why `Published Folder` and `Conversion Profile` live in `Latest Artifacts`
instead of the session-metadata section.

In the current Qt UI, `Latest Artifacts` holds:

- `Conversion Profile`
- `Published Folder`
- latest `Episode`
- latest `Dataset`
- latest `Viewer` URL
- post-take notes for the latest episode


## Health Cards And Readiness

The health section exists because operators need a measured view of the live
stack:

- SPARK devices
- teleop/runtime
- RealSense
- GelSight
- recorder
- converter

The design rule is:

- readiness must come from measured health and concrete process state
- not from “a command was launched once”

The current health cards are exactly:

- `SPARK Devices`
- `Teleop GUI`
- `RealSense`
- `GelSight`
- `Recorder`
- `Converter`

And the current backend session-state flow is driven by those health checks and
process states:

- `idle`
- `bringing_up`
- `ready_to_record`
- `recording`
- `converting`
- `converted`
- `review_ready`
- `degraded`


## Why Readiness Stays Simple

The operator-facing workflow keeps readiness simple:

- health cards show the live system state
- `Record` readiness follows required-service health and process state
- post-take checks happen after recording, where they can evaluate the actual
  artifact instead of a snapshot guess

This keeps the console focused on session bring-up and recording, instead of
adding extra operator steps that can drift away from the live state moments
later.


## Why Sensor Keys Stay Canonical In The UI

The console should not grow a second naming layer for devices and roles.

The rule is:

- canonical sensor identity is the topic-prefix sensor key itself
- hardware identifiers are runtime display values only

So in the table:

- `Hardware ID` is for discovery and debugging
- `Sensor Key` is the canonical identity the rest of the pipeline uses


## Design Consequence

Future console changes should be judged against one question:

- does this make the console a better session tool, or is it turning it back
  into a rig editor or schema debugger?

If it is the latter, the change is probably moving in the wrong direction.
