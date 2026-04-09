# Replay

## Goal

Replay lets a recorded raw episode be sent back to the robot hardware for
verification.

The purpose of replay is not dataset publishing. It is a trust and debugging
tool for the raw capture path.


## Scope

The current replay scope is intentionally narrow:

- raw episode replay only
- raw episode folders only
- joint-space replay only
- UR hardware only
- command topics only

It does not attempt to be a complete lab playback system.


## Why Replay Exists

Replay answers questions that conversion and visualization cannot:

- did raw recording capture sane teleop commands?
- does the raw bag round-trip to hardware motion?
- did trimming and timing preserve the real demonstration?
- if a later published dataset looks wrong, is the bug upstream or downstream?


## Inputs

Replay reads one raw episode under:

- `raw_episodes/<episode_id>/`

and specifically replays these raw topics:

- `/spark/{arm}/teleop/cmd_joint_state`
- `/spark/{arm}/teleop/cmd_gripper_state`
- `/spark/session/teleop_active`


## Replay Contract

### Episode source

The replay tool accepts either:

- an episode directory
- a bag directory
- an episode id under `raw_episodes/`

### Supported arms

The tool supports:

- `lightning`
- `thunder`

If no explicit arm list is given, it replays whichever arms have both command
topics present in the raw bag.

### Timing

Replay uses the recorded command timestamps from the command messages'
`header.stamp` when present.

The shared teleop-activity topic has no header, so replay uses its bag
timestamp.

The event stream is then replayed in timestamp order, with an optional global
speed multiplier.

### Command semantics

For each selected arm:

- joint commands are replayed with the existing `servoJ` path
- gripper commands are replayed by converting normalized `0..1` values to
  Robotiq `0..255`

The replay tool reuses the current Spark teleop servo parameters so replay uses
the same UR command path as the live teleop stack.

At the runtime layer, replay reuses the existing `TeleopSoftware` UR stack
rather than introducing a second hardware-control path.

### Teleop activity gating

Replay respects `/spark/session/teleop_active`.

When teleop activity is false:

- no new joint commands are issued
- active servo motion is stopped

When teleop activity returns true:

- replay resumes issuing recorded commands

This keeps replay faithful to the raw contract, where pedal-off spans are
intentional raw-session state, not fake command continuity.

### Startup behavior

Before replay starts:

- the selected UR arm(s) connect
- the operator sees a summary and confirmation prompt
- the selected arm(s) move to their configured home joint pose

Replay does not start automatically on hardware without explicit confirmation.

### End behavior

At the end of replay:

- command streaming stops
- the robot is left at the final replayed pose

Replay does not automatically return home after completion.


## Non-Goals

Replay does not include:

- processed replay from published LeRobot `action`
- IK or Cartesian replay
- UI integration in the operator console
- camera/video playback
- synchronized scene review
- bimanual transform logic
- policy inference or closed-loop execution


## Implementation Shape

The implementation is a single CLI:

- `data_pipeline/replay_episode.py`

That CLI should:

1. resolve the requested raw episode
2. detect bag storage from `bag/metadata.yaml`
3. load replayable command topics
4. prompt for confirmation
5. move the selected UR arm(s) home
6. stream the recorded commands back to hardware


## Safety Boundary

Replay is still a hardware-moving tool. So the implementation stays simple:

- explicit confirmation prompt
- no hidden auto-run
- no implicit IK
- no silent arm inference beyond topic presence
- no attempt to "improve" the original demonstration while replaying it

If replay fails, it should fail loudly and early instead of guessing.
