from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.spatial.transform import Rotation as R

from geometry_msgs.msg import PoseStamped, WrenchStamped
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32MultiArray, Float32, Bool, Int32
from UR.fk import forward_6

JOINT_NAMES = [f"joint_{idx}" for idx in range(1, 7)]
THUNDER_OFFSET = [
    0.8322513103485107,
    1.3889789581298828,
    1.4154774993658066,
    -2.7204548865556717,
    -2.634120313450694,
    -2.2259570360183716,
    0.0,
]
LIGHTNING_OFFSET = [
    -1.06043816,
    -4.28556144,
    -1.23235792,
    -1.21208322,
    -0.60609466,
    1.96014991,
    0.0,
]


@dataclass
class TeleopRuntimeState:
    homes: dict[str, list[float]] = field(default_factory=dict)
    spark_enable: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class SparkServoConfig:
    servo_time: float
    servo_lookahead_time: float
    servo_gain: int


def map_value(x, in_min=1.9, in_max=3.0, out_min=0, out_max=255):
    return out_min + (x - in_min) * (out_max - out_min) / (in_max - in_min)


def _copy_stamp(dst, src) -> None:
    dst.sec = src.sec
    dst.nanosec = src.nanosec


def _joint_state_message(stamp, names, positions) -> JointState:
    msg = JointState()
    _copy_stamp(msg.header.stamp, stamp)
    msg.name = list(names)
    msg.position = [float(value) for value in positions]
    return msg


def _gripper_message(stamp, name: str, value: float) -> JointState:
    return _joint_state_message(stamp, [name], [float(value)])


def _pose_message(stamp, pose) -> PoseStamped:
    if len(pose) < 6:
        raise ValueError(f"Expected 6D pose, got {pose}")
    quat = R.from_euler("xyz", pose[3:6]).as_quat()
    msg = PoseStamped()
    _copy_stamp(msg.header.stamp, stamp)
    msg.header.frame_id = "base"
    msg.pose.position.x = float(pose[0])
    msg.pose.position.y = float(pose[1])
    msg.pose.position.z = float(pose[2])
    msg.pose.orientation.x = float(quat[0])
    msg.pose.orientation.y = float(quat[1])
    msg.pose.orientation.z = float(quat[2])
    msg.pose.orientation.w = float(quat[3])
    return msg


def _wrench_message(stamp, wrench) -> WrenchStamped:
    if len(wrench) < 6:
        raise ValueError(f"Expected 6D wrench, got {wrench}")
    msg = WrenchStamped()
    _copy_stamp(msg.header.stamp, stamp)
    msg.header.frame_id = "tool0"
    msg.wrench.force.x = float(wrench[0])
    msg.wrench.force.y = float(wrench[1])
    msg.wrench.force.z = float(wrench[2])
    msg.wrench.torque.x = float(wrench[3])
    msg.wrench.torque.y = float(wrench[4])
    msg.wrench.torque.z = float(wrench[5])
    return msg


def publish_stable_robot_state(arm, pubs, stamp, q, cartesian, wrench, gripper) -> None:
    pubs[arm + "_robot_joint_state"].publish(_joint_state_message(stamp, JOINT_NAMES, q))
    pubs[arm + "_robot_eef_pose"].publish(_pose_message(stamp, cartesian))
    pubs[arm + "_robot_tcp_wrench"].publish(_wrench_message(stamp, wrench))
    pubs[arm + "_robot_gripper_state"].publish(_gripper_message(stamp, "gripper", gripper))


def _publish_stable_spark_command(arm, pubs, stamp, angles, gripper) -> None:
    pubs[arm + "_teleop_cmd_joint_state"].publish(_joint_state_message(stamp, JOINT_NAMES, angles[:6]))
    pubs[arm + "_teleop_cmd_gripper_state"].publish(_gripper_message(stamp, "gripper_cmd", gripper))


def _spark_home_offset(arm: str) -> list[float]:
    if arm == "Thunder":
        return THUNDER_OFFSET.copy()
    if arm == "Lightning":
        return LIGHTNING_OFFSET.copy()
    raise KeyError(f"Unknown arm for Spark home offset: {arm}")


def _spark_gripper_command(arm: str, wrist_angle: float) -> float:
    if arm == "Lightning":
        gripper = map_value(wrist_angle, in_min=-0.4, in_max=0.25, out_min=0, out_max=1)
    else:
        gripper = map_value(wrist_angle, in_min=-2.71, in_max=-1.26, out_min=0, out_max=1)
    gripper = np.clip(gripper, 0, 1)
    return round(float(gripper) * 10) / 10


def process_spark_mode(
    *,
    arm: str,
    fields,
    ros_data,
    control_modes,
    runtime_state: TeleopRuntimeState,
    URs,
    pubs,
    optimize,
    clock,
    servo: SparkServoConfig,
) -> None:
    spark_key = arm.lower() + "_spark_angle"
    if spark_key not in ros_data:
        return
    if not URs.has_receive(arm):
        del ros_data[spark_key]
        return

    angles = ros_data[spark_key]
    if ros_data[arm.lower() + "_change_mode"] is True:
        runtime_state.homes[arm] = _spark_home_offset(arm)
        dq = [a - u + h for a, u, h in zip(angles, URs.getActualQ(arm), runtime_state.homes[arm])]
        if dq[0] > np.pi:
            runtime_state.homes[arm][0] = -2 * np.pi
        elif dq[0] < -np.pi:
            runtime_state.homes[arm][0] = +2 * np.pi
        ros_data[arm.lower() + "_change_mode"] = False

    angles = [angle + runtime_state.homes[arm][i] for i, angle in enumerate(angles)]
    gripper = _spark_gripper_command(arm, angles[6])

    ur_Q = URs.getActualQ(arm)
    ur_pos = forward_6(ur_Q)[0]
    spark_pos = forward_6(angles[:6])[0]
    height, width, center = fields[arm]["hwc"]
    z = spark_pos[2] - ur_pos[2]
    if arm == "Thunder":
        x = -spark_pos[1] + ur_pos[1]
        y = -spark_pos[0] + ur_pos[0]
    elif arm == "Lightning":
        x = +spark_pos[1] - ur_pos[1]
        y = +spark_pos[0] - ur_pos[0]
        x = -x
        z = -z
    x = x * width / 2 + center[0]
    y = y * height / 2 + center[1]
    z = z * 300 + 300
    tmp = z
    z = y
    y = tmp
    fields[arm]["Spark_plot"].itemconfig(fields[arm]["point"], fill="red" if z > 0 else "blue")
    fields[arm]["Spark_plot"].moveto(fields[arm]["point"], y - 10, x - 10)
    fields[arm]["Spark_meter"].moveto(fields[arm]["Spark_z_meter"], 0, z)

    # Preserve the current runtime behavior exactly, including the shared
    # lightning enable key used by both arms in the Spark path.
    enable_topic = "lightning_spark_enable"
    if control_modes[arm] == "Spark" or control_modes[arm] == "Optimization":
        if enable_topic in ros_data:
            old_spark_enable = runtime_state.spark_enable[arm] if arm in runtime_state.spark_enable else False
            runtime_state.spark_enable[arm] = ros_data[enable_topic]
            if runtime_state.spark_enable[arm] is True:
                if old_spark_enable is False:
                    URs.zeroFtSensor(arm)
                    print(f"Zeroed FT sensor on {arm}")
                if control_modes[arm] == "Spark":
                    command_stamp = clock.now().to_msg()
                    URs.servoJ(
                        arm,
                        (angles[:6], 0.0, 0.0, servo.servo_time, servo.servo_lookahead_time, servo.servo_gain),
                    )
                    if URs.gripper_enabled(arm):
                        URs.get_gripper(arm).set(int(gripper * 255))
                    pubs[arm.lower() + "_spark_command_angles"].publish(Float32MultiArray(data=angles[:6]))
                    pubs[arm.lower() + "_spark_command_gripper"].publish(Float32(data=gripper))
                    _publish_stable_spark_command(arm, pubs, command_stamp, angles, gripper)

        if control_modes[arm] == "Optimization":
            optimize.set_spark_angle(arm, angles)
            optimize.set_enable(ros_data[enable_topic])
            if ros_data[enable_topic] and URs.gripper_enabled(arm):
                URs.get_gripper(arm).set(int(gripper * 255))

    del ros_data[spark_key]


def publish_periodic_robot_state(*, arm: str, runtime_state: TeleopRuntimeState, URs, pubs, clock) -> None:
    if not URs.has_receive(arm):
        return

    tick_stamp = clock.now().to_msg()
    norm_ft = URs.get_receive(arm).getActualTCPForce()
    pubs[arm + "_ft"].publish(Float32MultiArray(data=norm_ft))

    raw_ft = URs.get_receive(arm).getFtRawWrench()
    pubs[arm + "_ft_raw"].publish(Float32MultiArray(data=raw_ft))

    q = URs.getActualQ(arm)
    pubs[arm + "_q"].publish(Float32MultiArray(data=q))

    cartesian = URs.get_receive(arm).getActualTCPPose()
    pubs[arm + "_cartesian"].publish(Float32MultiArray(data=cartesian))

    speed = URs.get_receive(arm).getActualTCPSpeed()
    pubs[arm + "_speed"].publish(Float32MultiArray(data=speed))

    gripper = 0.0
    if URs.gripper_enabled(arm):
        gripper = float(URs.get_gripper(arm).get_current_position())
        pubs[arm + "_gripper"].publish(Int32(data=int(gripper)))

    enable = runtime_state.spark_enable[arm] if arm in runtime_state.spark_enable else False
    pubs[arm + "_enable"].publish(Bool(data=enable))

    saftey_mode = URs.get_receive(arm).getSafetyMode()
    pubs[arm + "_safety_mode"].publish(Int32(data=saftey_mode))
    publish_stable_robot_state(arm, pubs, tick_stamp, q, cartesian, norm_ft, gripper)
