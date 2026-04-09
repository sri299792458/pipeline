# First Viewer Review

This page starts after [First Published Conversion](./first-published-conversion.md) is already complete.

It applies to both:

- `shared_account` after [Lab Machine Quick Start](./lab-machine-quick-start.md)
- a lab member using their own account after [Personal Account Setup](./personal-account-setup.md)

The goal is simple:

- open the converted dataset locally in the browser viewer
- confirm that the newest episode actually renders
- recognize the most common local viewer failures quickly


## Before You Start

Make sure these are already true:

- the current account already has the viewer toolchain prepared
- at least one episode was converted successfully
- the `Converter` card ended at:
  - `Latest dataset ready for review`
- the `Published Folder` field still points at the dataset you want to inspect

If those are not true yet, go back to:

- [Viewer Setup](./viewer-setup.md)
- [Personal Account Setup](./personal-account-setup.md) if you are using your own account
- [First Published Conversion](./first-published-conversion.md)

Normal workflow note:

- on `shared_account`, local viewer setup should already be part of account provisioning
- on a personal account, the viewer setup should already be covered by [Personal Account Setup](./personal-account-setup.md)


## 1. Check The Viewer Target

Before clicking anything, confirm the operator console still points at the right published dataset:

- `Published Folder`
  - should be the dataset you just converted into

The viewer path uses that target to resolve the local dataset to open.

Important:

- `Open Viewer` opens the latest episode in that dataset
- for a first smoke test, that is usually exactly what you want


## 2. Open The Viewer

In the operator console, use:

- `Open Viewer`

on the `Converter` card.

What should happen:

- the backend checks that the published dataset exists
- it ensures the local viewer mount for that dataset is available
- it starts the local viewer server if needed
- it opens the resolved local episode URL for the latest episode in that dataset

The supported workflow is local-only:

- the viewer server runs on this machine
- the browser also runs on this machine
- the viewer URL is `http://localhost:3000/...`

You do **not** need to manually start the viewer server in the normal workflow.
You also do **not** need to manually create any local viewer dataset mount.


## 3. What Success Looks Like

The artifacts section should now show:

- `Dataset`
  - the published folder name
- `Viewer`
  - the resolved local viewer URL

A successful first viewer review means:

- the browser opens the local dataset page
- the newest episode loads
- RGB streams render
- depth preview streams render if depth was published
- the episode-level charts and metadata load without obvious missing-data errors


## 4. If `Open Viewer` Fails Immediately

Typical causes are:

- the viewer repo is missing
  - expected at:
    - `../lerobot-dataset-visualizer`
- `bun` is missing
  - expected at:
    - `~/.bun/bin/bun`
- the production viewer bundle was never built
- the published dataset target does not exist on disk

In that case, go back to:

- [Viewer Setup](./viewer-setup.md)

and rerun:

```bash
cd ~/spark-workspace/spark-data-collection
./data_pipeline/setup_viewer_env.sh
```


## 5. If The Viewer Server Starts But The Page Still Looks Wrong

Known local issues we have already seen:

- stale viewer process from a different dataset target
- missing production build marker:
  - `.next/BUILD_ID`
- proxy environment variables interfering with local dataset requests

The normal `Open Viewer` path already handles the local proxy/runtime setup, so
the first response should be:

- stop trying manual browser-side workarounds
- rerun the viewer setup script
- try `Open Viewer` again

If you still need a manual check, verify the local dataset metadata exists:

```bash
cd ~/spark-workspace/spark-data-collection
ls published/<dataset_id>/meta/info.json
ls published/<dataset_id>/meta/spark_conversion
```


## 6. Optional Manual Fallback

Only if `Open Viewer` is still failing and you need to isolate whether the
problem is in the dataset or the console integration, you can start the viewer
manually from the sibling repo.

Important:

- this only makes sense after at least one `Open Viewer` attempt
- the console path is what prepares the local dataset mount for the selected folder

Manual start:

```bash
cd ~/spark-workspace/lerobot-dataset-visualizer
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy -u NO_PROXY -u no_proxy \
NEXT_PUBLIC_DATASET_URL=http://localhost:3000/datasets \
DATASET_URL=http://localhost:3000/datasets \
REPO_ID=local/<dataset_id> \
EPISODES=0 \
~/.bun/bin/bun start
```

That is only for debugging. The normal workflow should stay:

- `Open Viewer`


## What Success Looks Like

Your first viewer review is successful when:

- `Open Viewer` opens a local dataset URL
- the newest episode page loads
- RGB streams render
- depth preview renders when depth exists
- the dataset shown in the browser matches the dataset in the operator console

At that point, the basic end-to-end local workflow is working:

- raw recording
- published conversion
- browser inspection
