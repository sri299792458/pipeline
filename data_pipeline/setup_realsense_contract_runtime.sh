#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "Missing ${VENV_PYTHON}" >&2
  echo "Run ./data_pipeline/setup_converter_env.sh first." >&2
  exit 1
fi

set +u
source /opt/ros/jazzy/setup.bash
set -u

if ! command -v ros2 >/dev/null 2>&1; then
  echo "ros2 was not found after sourcing /opt/ros/jazzy/setup.bash" >&2
  exit 1
fi

"${VENV_PYTHON}" - <<'PY'
import pyrealsense2 as rs
import rclpy

devices = []
for device in rs.context().query_devices():
    try:
        name = device.get_info(rs.camera_info.name)
    except Exception:
        name = "<unknown>"
    try:
        serial = device.get_info(rs.camera_info.serial_number)
    except Exception:
        serial = "<unknown>"
    devices.append((name, serial))

print("Direct RealSense runtime ready in .venv")
print(f"Enumerated devices: {devices}")
PY
