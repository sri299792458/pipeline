from __future__ import annotations

from geometry_msgs.msg import PoseStamped, WrenchStamped
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool, Float32, Float32MultiArray, Int32, String


class TeleopROSAdapter:
    def __init__(self, node, ros_data: dict):
        self._node = node
        self._ros_data = ros_data

    def create_publishers(self, arms: list[str]) -> dict:
        pubs = {}
        for arm in arms:
            pubs[arm + "_reset_estop"] = self._node.create_publisher(Bool, "/reset_estop", 10)
            pubs[arm + "_ft"] = self._node.create_publisher(Float32MultiArray, f"/{arm.lower()}_ft", 10)
            pubs[arm + "_ft_raw"] = self._node.create_publisher(Float32MultiArray, f"/{arm.lower()}_raw_ft_raw", 10)
            pubs[arm + "_q"] = self._node.create_publisher(Float32MultiArray, f"/{arm.lower()}_q", 10)
            pubs[arm + "_cartesian"] = self._node.create_publisher(Float32MultiArray, f"/{arm.lower()}_cartesian_eef", 10)
            pubs[arm + "_speed"] = self._node.create_publisher(Float32MultiArray, f"/{arm.lower()}_speed", 10)
            pubs[arm + "_gripper"] = self._node.create_publisher(Int32, f"/{arm.lower()}_gripper", 10)
            pubs[arm + "_enable"] = self._node.create_publisher(Bool, f"/{arm.lower()}_enable", 10)
            pubs[arm + "_safety_mode"] = self._node.create_publisher(Int32, f"/{arm.lower()}_safety_mode", 10)
            pubs[arm + "_force_offset"] = self._node.create_publisher(Float32MultiArray, f"/{arm.lower()}_force_offset", 10)
            pubs[arm.lower() + "_spark_command_angles"] = self._node.create_publisher(
                Float32MultiArray, f"/{arm.lower()}_spark_command_angles", 10
            )
            pubs[arm.lower() + "_spark_command_gripper"] = self._node.create_publisher(
                Float32, f"/{arm.lower()}_spark_command_gripper", 10
            )
            pubs[arm + "_robot_joint_state"] = self._node.create_publisher(
                JointState, f"/spark/{arm.lower()}/robot/joint_state", 10
            )
            pubs[arm + "_robot_eef_pose"] = self._node.create_publisher(
                PoseStamped, f"/spark/{arm.lower()}/robot/eef_pose", 10
            )
            pubs[arm + "_robot_tcp_wrench"] = self._node.create_publisher(
                WrenchStamped, f"/spark/{arm.lower()}/robot/tcp_wrench", 10
            )
            pubs[arm + "_robot_gripper_state"] = self._node.create_publisher(
                JointState, f"/spark/{arm.lower()}/robot/gripper_state", 10
            )
            pubs[arm + "_teleop_cmd_joint_state"] = self._node.create_publisher(
                JointState, f"/spark/{arm.lower()}/teleop/cmd_joint_state", 10
            )
            pubs[arm + "_teleop_cmd_gripper_state"] = self._node.create_publisher(
                JointState, f"/spark/{arm.lower()}/teleop/cmd_gripper_state", 10
            )
        return pubs

    def register_core_subscriptions(self) -> None:
        self._node.create_subscription(String, "/SpaceMouseThunderLog", self.thunder_sm_log, 10)
        self._node.create_subscription(String, "/SpaceMouseLightningLog", self.lightning_sm_log, 10)
        self._node.create_subscription(Float32MultiArray, "/SpaceMouseThunder", self.thunder_sm_data, 10)
        self._node.create_subscription(Float32MultiArray, "/SpaceMouseLightning", self.lightning_sm_data, 10)
        self._node.create_subscription(Float32MultiArray, "/Spark_angle/thunder", self.spark_angle_thunder, 10)
        self._node.create_subscription(Float32MultiArray, "/Spark_angle/lightning", self.spark_angle_lightning, 10)
        self._node.create_subscription(Bool, "/spark/session/teleop_active", self.spark_session_enable, 10)

    def thunder_sm_log(self, data):
        self._ros_data["thunder_sm_log"] = data.data
        print(data.data)

    def lightning_sm_log(self, data):
        self._ros_data["lightning_sm_log"] = data.data
        print(data.data)

    def thunder_sm_data(self, data):
        self._ros_data["thunder_sm_data"] = data.data

    def lightning_sm_data(self, data):
        self._ros_data["lightning_sm_data"] = data.data

    def spark_angle_thunder(self, data):
        self._ros_data["thunder_spark_angle"] = data.data

    def spark_angle_lightning(self, data):
        self._ros_data["lightning_spark_angle"] = data.data

    def spark_session_enable(self, data):
        self._ros_data["lightning_spark_enable"] = data.data
        self._ros_data["thunder_spark_enable"] = data.data
