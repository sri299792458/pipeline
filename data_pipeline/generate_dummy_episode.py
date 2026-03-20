#!/usr/bin/python3

"""Generate a synthetic raw episode for offline pipeline validation."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import rosbag2_py
from geometry_msgs.msg import PoseStamped, WrenchStamped
from rclpy.serialization import serialize_message
from sensor_msgs.msg import Image, JointState

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_pipeline.pipeline_utils import (  # noqa: E402
    DEFAULT_PROFILE_PATH,
    DEFAULT_RAW_EPISODES_DIR,
    build_notes_template,
    collect_candidate_topics,
    load_profile,
    make_episode_id,
    now_ns,
    profile_required_arms,
    write_json,
)


TOPIC_TYPES = {
    "/spark/cameras/wrist/color/image_raw": "sensor_msgs/msg/Image",
    "/spark/cameras/wrist/depth/image_rect_raw": "sensor_msgs/msg/Image",
    "/spark/cameras/scene/color/image_raw": "sensor_msgs/msg/Image",
    "/spark/cameras/scene/depth/image_rect_raw": "sensor_msgs/msg/Image",
    "/spark/tactile/left/color/image_raw": "sensor_msgs/msg/Image",
    "/spark/tactile/right/color/image_raw": "sensor_msgs/msg/Image",
    "/spark/lightning/robot/joint_state": "sensor_msgs/msg/JointState",
    "/spark/lightning/robot/eef_pose": "geometry_msgs/msg/PoseStamped",
    "/spark/lightning/robot/tcp_wrench": "geometry_msgs/msg/WrenchStamped",
    "/spark/lightning/robot/gripper_state": "sensor_msgs/msg/JointState",
    "/spark/lightning/teleop/cmd_joint_state": "sensor_msgs/msg/JointState",
    "/spark/lightning/teleop/cmd_gripper_state": "sensor_msgs/msg/JointState",
    "/spark/thunder/robot/joint_state": "sensor_msgs/msg/JointState",
    "/spark/thunder/robot/eef_pose": "geometry_msgs/msg/PoseStamped",
    "/spark/thunder/robot/tcp_wrench": "geometry_msgs/msg/WrenchStamped",
    "/spark/thunder/robot/gripper_state": "sensor_msgs/msg/JointState",
    "/spark/thunder/teleop/cmd_joint_state": "sensor_msgs/msg/JointState",
    "/spark/thunder/teleop/cmd_gripper_state": "sensor_msgs/msg/JointState",
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", default="dummy_multisensor_v1")
    parser.add_argument("--task-name", default="dummy_pick_place")
    parser.add_argument("--robot-id", default="spark_bimanual")
    parser.add_argument("--operator", default="codex")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH))
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_EPISODES_DIR))
    parser.add_argument("--episode-id", default="")
    parser.add_argument("--duration-s", type=float, default=5.0)
    parser.add_argument("--include-tactile", action="store_true")
    return parser


def stamp_from_ns(msg, stamp_ns: int) -> None:
    msg.header.stamp.sec = stamp_ns // 1_000_000_000
    msg.header.stamp.nanosec = stamp_ns % 1_000_000_000


def make_color_image(stamp_ns: int, width: int, height: int, phase: float) -> Image:
    x = np.linspace(0, 255, width, dtype=np.int32)
    y = np.linspace(0, 255, height, dtype=np.int32)
    xv, yv = np.meshgrid(x, y)
    image = np.stack(
        [
            (xv + int(phase * 40)) % 255,
            (yv + int(phase * 70)) % 255,
            ((xv // 2 + yv // 2) + int(phase * 25)) % 255,
        ],
        axis=-1,
    ).astype(np.uint8)

    msg = Image()
    stamp_from_ns(msg, stamp_ns)
    msg.height = height
    msg.width = width
    msg.encoding = "rgb8"
    msg.step = width * 3
    msg.data = image.tobytes()
    return msg


def make_depth_image(stamp_ns: int, width: int, height: int, phase: float) -> Image:
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)
    xv, yv = np.meshgrid(x, y)
    depth_mm = 500 + 200 * np.sin(phase + xv * math.pi) + 100 * np.cos(phase + yv * math.pi)
    depth = np.clip(depth_mm, 0, 65535).astype(np.uint16)

    msg = Image()
    stamp_from_ns(msg, stamp_ns)
    msg.height = height
    msg.width = width
    msg.encoding = "16UC1"
    msg.step = width * 2
    msg.data = depth.tobytes()
    return msg


def make_joint_state(stamp_ns: int, names: list[str], values: list[float]) -> JointState:
    msg = JointState()
    stamp_from_ns(msg, stamp_ns)
    msg.name = names
    msg.position = values
    return msg


def make_pose(stamp_ns: int, phase: float, arm_sign: float) -> PoseStamped:
    msg = PoseStamped()
    stamp_from_ns(msg, stamp_ns)
    msg.header.frame_id = "base"
    msg.pose.position.x = 0.4 + arm_sign * 0.05 + 0.02 * math.sin(phase)
    msg.pose.position.y = arm_sign * 0.25 + 0.03 * math.cos(phase)
    msg.pose.position.z = 0.2 + 0.01 * math.sin(phase * 0.5)
    msg.pose.orientation.x = 0.0
    msg.pose.orientation.y = 0.0
    msg.pose.orientation.z = math.sin(phase * 0.1)
    msg.pose.orientation.w = math.cos(phase * 0.1)
    return msg


def make_wrench(stamp_ns: int, phase: float, arm_sign: float) -> WrenchStamped:
    msg = WrenchStamped()
    stamp_from_ns(msg, stamp_ns)
    msg.header.frame_id = "tool0"
    msg.wrench.force.x = arm_sign * 2.0 * math.sin(phase)
    msg.wrench.force.y = 1.5 * math.cos(phase)
    msg.wrench.force.z = -3.0 + 0.5 * math.sin(phase * 0.5)
    msg.wrench.torque.x = 0.1 * math.sin(phase * 0.2)
    msg.wrench.torque.y = 0.1 * math.cos(phase * 0.2)
    msg.wrench.torque.z = arm_sign * 0.2 * math.sin(phase * 0.3)
    return msg


def create_topic(writer: rosbag2_py.SequentialWriter, topic_id: int, name: str, topic_type: str) -> None:
    writer.create_topic(
        rosbag2_py.TopicMetadata(
            id=topic_id,
            name=name,
            type=topic_type,
            serialization_format="cdr",
        )
    )


def build_manifest(args: argparse.Namespace, profile: dict, episode_id: str, start_ns: int, end_ns: int) -> dict:
    active_arms = profile_required_arms(profile)
    topics = [topic for topic in collect_candidate_topics(profile) if topic in TOPIC_TYPES]
    if not args.include_tactile:
        topics = [topic for topic in topics if "/spark/tactile/" not in topic]

    sensors = [
        {
            "sensor_name": "wrist",
            "sensor_id": "cam_lightning_wrist_0",
            "sensor_type": "realsense",
            "modality": "rgbd_camera",
            "attached_to": "lightning",
            "mount_parent": "arm",
            "mount_site": "wrist",
            "mount_index": 0,
            "semantic_role_hint": "wrist",
            "topic_names": [
                "/spark/cameras/wrist/color/image_raw",
                "/spark/cameras/wrist/depth/image_rect_raw",
            ],
            "serial_number": "DUMMY-WRIST-001",
            "model": "Intel RealSense D405",
            "firmware_version": "dummy",
            "resolution": "640x480",
            "fps": 20,
            "driver_node": "/spark/cameras/wrist",
            "calibration_ref": "dummy://wrist",
            "identity_complete": True,
        },
        {
            "sensor_name": "scene",
            "sensor_id": "cam_scene_0",
            "sensor_type": "realsense",
            "modality": "rgbd_camera",
            "attached_to": "world",
            "mount_parent": "world",
            "mount_site": "scene",
            "mount_index": 0,
            "semantic_role_hint": "scene",
            "topic_names": [
                "/spark/cameras/scene/color/image_raw",
                "/spark/cameras/scene/depth/image_rect_raw",
            ],
            "serial_number": "DUMMY-SCENE-001",
            "model": "Intel RealSense D435",
            "firmware_version": "dummy",
            "resolution": "640x480",
            "fps": 20,
            "driver_node": "/spark/cameras/scene",
            "calibration_ref": "dummy://scene",
            "identity_complete": True,
        },
    ]
    if args.include_tactile:
        sensors.extend(
            [
                {
                    "sensor_name": "left",
                    "sensor_id": "tac_lightning_finger_left_0",
                    "sensor_type": "gelsight",
                    "modality": "tactile_rgb",
                    "attached_to": "lightning",
                    "mount_parent": "robotiq_2f85_gripper",
                    "mount_site": "finger_left",
                    "mount_index": 0,
                    "semantic_role_hint": "tactile_finger_left",
                    "topic_names": ["/spark/tactile/left/color/image_raw"],
                    "serial_number": "DUMMY-GS-LEFT",
                    "model": "GelSight Mini",
                    "firmware_version": "dummy",
                    "resolution": "320x240",
                    "fps": 20,
                    "driver_node": "/gelsight_left_bridge",
                    "calibration_ref": "dummy://gelsight_left",
                    "identity_complete": True,
                },
                {
                    "sensor_name": "right",
                    "sensor_id": "tac_lightning_finger_right_0",
                    "sensor_type": "gelsight",
                    "modality": "tactile_rgb",
                    "attached_to": "lightning",
                    "mount_parent": "robotiq_2f85_gripper",
                    "mount_site": "finger_right",
                    "mount_index": 0,
                    "semantic_role_hint": "tactile_finger_right",
                    "topic_names": ["/spark/tactile/right/color/image_raw"],
                    "serial_number": "DUMMY-GS-RIGHT",
                    "model": "GelSight Mini",
                    "firmware_version": "dummy",
                    "resolution": "320x240",
                    "fps": 20,
                    "driver_node": "/gelsight_right_bridge",
                    "calibration_ref": "dummy://gelsight_right",
                    "identity_complete": True,
                },
            ]
        )

    return {
        "episode_id": episode_id,
        "dataset_id": args.dataset_id,
        "task_name": args.task_name,
        "robot_id": args.robot_id,
        "active_arms": active_arms,
        "operator": args.operator,
        "start_time_ns": start_ns,
        "end_time_ns": end_ns,
        "topics": topics,
        "topic_types": {topic: TOPIC_TYPES[topic] for topic in topics},
        "sensor_inventory_version": 2,
        "sensor_inventory_complete": True,
        "sensors": sensors,
        "mapping_profile": profile["profile_name"],
        "profile_version": profile["profile_version"],
        "clock_policy": profile["dataset"]["clock_policy"],
        "git_commit": "dummy",
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    profile = load_profile(args.profile)
    active_arms = profile_required_arms(profile)
    raw_root = Path(args.raw_root)
    episode_id = args.episode_id or make_episode_id()
    episode_dir = raw_root / episode_id
    bag_dir = episode_dir / "bag"
    episode_dir.mkdir(parents=True, exist_ok=False)

    storage_options = rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id="sqlite3")
    converter_options = rosbag2_py.ConverterOptions("", "")
    writer = rosbag2_py.SequentialWriter()
    writer.open(storage_options, converter_options)

    topics = [topic for topic in collect_candidate_topics(profile) if topic in TOPIC_TYPES]
    if not args.include_tactile:
        topics = [topic for topic in topics if "/spark/tactile/" not in topic]
    for topic_id, topic in enumerate(topics):
        create_topic(writer, topic_id, topic, TOPIC_TYPES[topic])

    start_ns = now_ns()
    end_ns = start_ns + int(args.duration_s * 1_000_000_000)

    image_period_ns = int(1_000_000_000 / 20)
    state_period_ns = int(1_000_000_000 / 50)
    action_period_ns = int(1_000_000_000 / 20)

    joint_names = [f"joint_{idx}" for idx in range(1, 7)]

    for stamp_ns in range(start_ns, end_ns, image_period_ns):
        phase = (stamp_ns - start_ns) / 1_000_000_000
        writer.write(
            "/spark/cameras/wrist/color/image_raw",
            serialize_message(make_color_image(stamp_ns, 640, 480, phase)),
            stamp_ns,
        )
        writer.write(
            "/spark/cameras/wrist/depth/image_rect_raw",
            serialize_message(make_depth_image(stamp_ns, 640, 480, phase)),
            stamp_ns,
        )
        writer.write(
            "/spark/cameras/scene/color/image_raw",
            serialize_message(make_color_image(stamp_ns, 640, 480, phase + 0.2)),
            stamp_ns,
        )
        writer.write(
            "/spark/cameras/scene/depth/image_rect_raw",
            serialize_message(make_depth_image(stamp_ns, 640, 480, phase + 0.2)),
            stamp_ns,
        )

        if args.include_tactile:
            writer.write(
                "/spark/tactile/left/color/image_raw",
                serialize_message(make_color_image(stamp_ns, 320, 240, phase + 0.4)),
                stamp_ns,
            )
            writer.write(
                "/spark/tactile/right/color/image_raw",
                serialize_message(make_color_image(stamp_ns, 320, 240, phase + 0.6)),
                stamp_ns,
            )

    for stamp_ns in range(start_ns, end_ns, state_period_ns):
        phase = (stamp_ns - start_ns) / 1_000_000_000
        if "lightning" in active_arms:
            lightning_joints = [0.2 * math.sin(phase + idx * 0.2) for idx in range(6)]
            writer.write(
                "/spark/lightning/robot/joint_state",
                serialize_message(make_joint_state(stamp_ns, joint_names, lightning_joints)),
                stamp_ns,
            )
            writer.write(
                "/spark/lightning/robot/eef_pose",
                serialize_message(make_pose(stamp_ns, phase, arm_sign=1.0)),
                stamp_ns,
            )
            writer.write(
                "/spark/lightning/robot/tcp_wrench",
                serialize_message(make_wrench(stamp_ns, phase, arm_sign=1.0)),
                stamp_ns,
            )
            writer.write(
                "/spark/lightning/robot/gripper_state",
                serialize_message(make_joint_state(stamp_ns, ["gripper"], [0.5 + 0.2 * math.sin(phase)])),
                stamp_ns,
            )

        if "thunder" in active_arms:
            thunder_joints = [0.25 * math.cos(phase + idx * 0.2) for idx in range(6)]
            writer.write(
                "/spark/thunder/robot/joint_state",
                serialize_message(make_joint_state(stamp_ns, joint_names, thunder_joints)),
                stamp_ns,
            )
            writer.write(
                "/spark/thunder/robot/eef_pose",
                serialize_message(make_pose(stamp_ns, phase, arm_sign=-1.0)),
                stamp_ns,
            )
            writer.write(
                "/spark/thunder/robot/tcp_wrench",
                serialize_message(make_wrench(stamp_ns, phase, arm_sign=-1.0)),
                stamp_ns,
            )
            writer.write(
                "/spark/thunder/robot/gripper_state",
                serialize_message(make_joint_state(stamp_ns, ["gripper"], [0.45 + 0.15 * math.cos(phase)])),
                stamp_ns,
            )

    for stamp_ns in range(start_ns, end_ns, action_period_ns):
        phase = (stamp_ns - start_ns) / 1_000_000_000
        if "lightning" in active_arms:
            lightning_cmd = [0.3 * math.sin(phase + idx * 0.15) for idx in range(6)]
            writer.write(
                "/spark/lightning/teleop/cmd_joint_state",
                serialize_message(make_joint_state(stamp_ns, joint_names, lightning_cmd)),
                stamp_ns,
            )
            writer.write(
                "/spark/lightning/teleop/cmd_gripper_state",
                serialize_message(make_joint_state(stamp_ns, ["gripper_cmd"], [0.4 + 0.25 * math.sin(phase)])),
                stamp_ns,
            )
        if "thunder" in active_arms:
            thunder_cmd = [0.3 * math.cos(phase + idx * 0.15) for idx in range(6)]
            writer.write(
                "/spark/thunder/teleop/cmd_joint_state",
                serialize_message(make_joint_state(stamp_ns, joint_names, thunder_cmd)),
                stamp_ns,
            )
            writer.write(
                "/spark/thunder/teleop/cmd_gripper_state",
                serialize_message(make_joint_state(stamp_ns, ["gripper_cmd"], [0.55 + 0.2 * math.cos(phase)])),
                stamp_ns,
            )

    writer.close()

    manifest = build_manifest(args, profile, episode_id, start_ns, end_ns)
    write_json(episode_dir / "episode_manifest.json", manifest)
    (episode_dir / "notes.md").write_text(build_notes_template(manifest), encoding="utf-8")

    print(f"Created dummy episode at {episode_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
