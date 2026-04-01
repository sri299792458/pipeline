# First Raw Demo

This page starts after [hardware-bringup.md](./hardware-bringup.md) is already complete.

The goal is simple:

- record one short raw episode successfully
- verify that the expected raw artifact exists on disk
- stop before published conversion or viewer work


## Before You Start

Make sure these are already true:

- the operator console is running
- the intended devices are enabled in the `Session Devices` table
- `Start Session` has already been run
- the Teleop GUI is connected to the intended robot or robots
- the required health cards are green
- `Validate` passes

If those are not true yet, go back to:

- [hardware-bringup.md](./hardware-bringup.md)


## 1. Prepare A Short Smoke-Test Take

For a first recording, keep it short and boring:

- use a simple task name such as `smoke_test_pick_place`
- keep the language instruction brief and literal
- record only one short successful teleop take
- aim for roughly `5-15 s`, not a full session

The point of this take is pipeline validation, not data volume.


## 2. Start Recording

In the operator console:

1. confirm `Task Name`, `Language Instruction`, `Operator`, and `Active Arms`
2. make sure the `Recorder` card is enabled
3. click `Record`

What should happen:

- the `Recorder` card should switch to:
  - `Recorder running`
- the console should assign a new episode id automatically
- the `Episode` field in the artifacts section should update to that new id

You do **not** need to launch `record_episode.py` manually in the normal workflow.


## 3. Perform The Demo

With recording running:

1. use the Teleop GUI to place the robot in the normal teleoperation mode
2. if your current teleop flow uses `Run Spark`, enable it there
3. press the foot pedal when you are ready to execute
4. perform one short clean demo
5. release the pedal and return the system to a safe idle state

For the first smoke test:

- prefer one clean take over repeated retries
- do not try to debug conversion or viewing yet
- focus only on whether a healthy raw episode is produced


## 4. Stop Recording

When the take is done, click:

- `Stop`

on the `Recorder` card.

After that, the operator console runs its recording integrity check.

Expected sequence:

- `Recorder` briefly shows:
  - `Analyzing last recording`
- then it should settle to:
  - `Last recording complete`

If it instead shows:

- `Recorder failed with exit code ...`
  - the recording process itself failed
- `Last recording incomplete`
  - the bag was written, but one or more required topics were missing or empty

In either failure case, keep the episode folder and inspect the recorder output before taking another long demo.


## 5. Save Optional Post-Take Notes

After the episode is complete, the `Post-take Notes` box now targets that latest episode.

You can:

- type a short note about what happened
- click `Save Episode Notes`

This writes into:

- `raw_episodes/<episode_id>/notes.md`

Use this for:

- operator mistakes
- robot oddities
- sensor issues
- anything future you would want to know before conversion or training


## 6. Verify The Raw Episode On Disk

From the repository root:

```bash
cd /home/srinivas/Desktop/pipeline
ls -td raw_episodes/* | head -n 3
```

The newest episode directory should contain:

- `bag/`
- `episode_manifest.json`
- `notes.md`

Check it directly:

```bash
episode_dir=$(ls -td raw_episodes/* | head -n 1)
echo "$episode_dir"
ls "$episode_dir"
```

You can also inspect the bag metadata:

```bash
python - <<'PY'
import yaml
from pathlib import Path
episode_dir = sorted(Path("raw_episodes").iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[0]
metadata = yaml.safe_load((episode_dir / "bag" / "metadata.yaml").read_text())
info = metadata["rosbag2_bagfile_information"]
print("episode_dir =", episode_dir)
print("storage_id =", info["storage_identifier"])
print("duration_s =", info["duration"]["nanoseconds"] / 1_000_000_000)
print("message_count =", info["message_count"])
PY
```


## What Success Looks Like

Your first raw demo is successful when:

- the `Recorder` card ends at `Last recording complete`
- the newest `raw_episodes/<episode_id>/` folder contains:
  - `bag/`
  - `episode_manifest.json`
  - `notes.md`
- the bag metadata exists under:
  - `raw_episodes/<episode_id>/bag/metadata.yaml`
- the episode id shown in the console matches the folder on disk

At that point, the raw-capture path is working.


## Next Step

Once one raw episode is recorded successfully, move on to:

- [first-published-conversion.md](./first-published-conversion.md)

Viewer inspection should remain separate from this first raw-capture check.
