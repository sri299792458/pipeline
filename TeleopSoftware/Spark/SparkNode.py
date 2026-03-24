import signal
import sys

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray, Bool

from spark_runtime import SparkDeviceRunner, SparkDisconnectedError, SparkRuntimeConfig

class SparkNode(Node):
    def __init__(self):
        super().__init__('SparkNode')
        def signal_handler(sig, frame):
            print("Stopped")
            exit()
        signal.signal(signal.SIGINT, signal_handler)

    def _build_runner(self) -> tuple[SparkDeviceRunner, bool]:
        device_path = sys.argv[1]
        buffered_topic = len(sys.argv) > 2
        config = SparkRuntimeConfig(
            device_path=device_path,
            buffered_topic=buffered_topic,
        )
        return SparkDeviceRunner(config), buffered_topic

    def main(self):
        runner, buffered_topic = self._build_runner()
        device_id = runner.connect_until_identified()
        print(f"Connected to Spark: {device_id} ({runner.config.device_path})")

        if buffered_topic:
            topic = f"Spark_angle_buffer/{device_id}"
            print(f"Buffering angles on {topic}")
        else:
            topic = f"Spark_angle/{device_id}"
        pose_publisher = self.create_publisher(Float32MultiArray, topic, 1)
        enable_publisher = None
        if device_id == "lightning":
            enable_publisher = self.create_publisher(Bool, "/spark/session/teleop_active", 1)

        try:
            while True:
                try:
                    sample = runner.read_sample()
                except SparkDisconnectedError:
                    print(f"Spark {device_id} disconnected")
                    runner.reconnect()
                    continue
                if sample is None:
                    continue
                if False in sample.status:
                    print(f"Spark {device_id} has an error in the status: {sample.status}")
                pose_publisher.publish(Float32MultiArray(data=sample.angles_rad))
                if enable_publisher is not None:
                    enable_publisher.publish(Bool(data=sample.enable_switch))
        finally:
            runner.close()
            print("Connection closed")


if __name__ == '__main__':
    rclpy.init()
    node = SparkNode()
    node.main()
    node.destroy_node()
    rclpy.shutdown()
