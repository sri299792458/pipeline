# Operations and Debugging

This section is for practical lab knowledge that should not stay in one
person's head.

Setup gets a new user working. Design Choices explains why the system looks the
way it does. This section is for the things you learn by actually running the
rig:

- machine-specific USB controller layout
- hardware habits that prevent bad sessions
- concrete runbooks for the current validated rig
- debugging paths for viewer, recording, and conversion failures

The goal is not to turn this into a scratchpad. The goal is to preserve the
knowledge that operators and maintainers will need again.

## Current Pages

- [USB Port and Controller Mapping](./usb-port-and-controller-mapping.md)

## What Belongs Here

Examples of good content for this section:

- which physical USB ports should be used for multiple RealSense cameras
- what the healthy hardware layout looks like on the current machine
- known viewer failure modes and how to recognize them
- dataset-folder mistakes that cause conversion or review failures
- machine/account quirks that affect real data collection

Examples of content that should usually live elsewhere:

- first-time operator instructions
- put those in [Setup](./setup.md)
- stable architectural rationale
- put that in [Design Choices](./design-choices.md)
- implementation notes, abandoned approaches, or scratch notes
- keep those out of the curated docs surface

## Planned Additions

This section should grow over time. Likely future pages include:

- home-position and joint-range guidance once the helper exists
- viewer troubleshooting patterns
- dataset schema and published-folder gotchas
- per-rig hardware notes as the setup evolves
