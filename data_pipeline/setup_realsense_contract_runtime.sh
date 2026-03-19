#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_ROOT="$REPO_ROOT/data_pipeline/ros2/spark_realsense_bridge"
BUILD_BASE="$REPO_ROOT/build/spark_realsense_bridge"
INSTALL_BASE="$REPO_ROOT/install/spark_realsense_bridge"

if ! command -v colcon >/dev/null 2>&1; then
  echo "colcon is required but was not found in PATH" >&2
  exit 1
fi

if ! pkg-config --exists realsense2; then
  echo "librealsense2 development files were not found via pkg-config" >&2
  exit 1
fi

export PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/ros/jazzy/bin:$PATH
export AMENT_PYTHON_EXECUTABLE=/usr/bin/python3
export COLCON_PYTHON_EXECUTABLE=/usr/bin/python3

set +u
source /opt/ros/jazzy/setup.bash
set -u

colcon build \
  --base-paths "$PACKAGE_ROOT" \
  --packages-select spark_realsense_bridge \
  --build-base "$BUILD_BASE" \
  --install-base "$INSTALL_BASE" \
  --cmake-args -DCMAKE_BUILD_TYPE=Release -DPython3_EXECUTABLE=/usr/bin/python3

echo
echo "Build complete."
echo "Source the overlay before launching:"
echo "  source \"$INSTALL_BASE/setup.bash\""
