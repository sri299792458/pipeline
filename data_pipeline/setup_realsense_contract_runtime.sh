#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEM_PYTHON="/usr/bin/python3"
UPSTREAM_LIBREALSENSE_DIR="${ROOT_DIR}/librealsense"
WORKTREE_DIR="${ROOT_DIR}/librealsense-v2.54.2"
BUILD_DIR="${ROOT_DIR}/build/librealsense-v2.54.2"
RELEASE_DIR="${BUILD_DIR}/Release"

if [[ ! -x "${SYSTEM_PYTHON}" ]]; then
  echo "Missing ${SYSTEM_PYTHON}" >&2
  exit 1
fi

set +u
source /opt/ros/jazzy/setup.bash
set -u

if ! command -v ros2 >/dev/null 2>&1; then
  echo "ros2 was not found after sourcing /opt/ros/jazzy/setup.bash" >&2
  exit 1
fi

if [[ ! -d "${UPSTREAM_LIBREALSENSE_DIR}/.git" ]]; then
  echo "Missing upstream librealsense checkout at ${UPSTREAM_LIBREALSENSE_DIR}" >&2
  exit 1
fi

if [[ ! -d "${WORKTREE_DIR}" ]]; then
  git -C "${UPSTREAM_LIBREALSENSE_DIR}" worktree add "${WORKTREE_DIR}" v2.54.2
fi

mkdir -p "${BUILD_DIR}"

cmake \
  -S "${WORKTREE_DIR}" \
  -B "${BUILD_DIR}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="${ROOT_DIR}/local/librealsense-2.54.2" \
  -DBUILD_PYTHON_BINDINGS=ON \
  -DPYTHON_EXECUTABLE="${SYSTEM_PYTHON}" \
  -DBUILD_EXAMPLES=OFF \
  -DBUILD_TOOLS=OFF \
  -DBUILD_UNIT_TESTS=OFF \
  -DBUILD_GRAPHICAL_EXAMPLES=OFF \
  -DFORCE_RSUSB_BACKEND=ON \
  -DCMAKE_CXX_FLAGS="-include cstdint"

cmake --build "${BUILD_DIR}" --target pyrealsense2 -j"$(nproc)"

export PYTHONPATH="${RELEASE_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
export LD_LIBRARY_PATH="${RELEASE_DIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

"${SYSTEM_PYTHON}" - <<'PY'
import sys
import pyrealsense2 as rs
import rclpy

print("Direct RealSense runtime ready from local librealsense v2.54.2 build")
print(f"Python executable: {sys.executable}")
print(f"pyrealsense2 module: {rs.__file__}")
print(f"rclpy module: {rclpy.__file__}")
PY
