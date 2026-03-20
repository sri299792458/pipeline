import os
import json
import subprocess
import sys
import time
import atexit
import serial
# import rospy
import rclpy
from rclpy.node import Node


# https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber=9029686
class LaunchDevs(Node):
    def __init__(self):
        super().__init__('LaunchDevs')
        self.get_logger().info("Starting LaunchDevs")

    def get_devs(self):
        cmd = "udevadm info --name="
        devs = []
        spark_devs = []
        SM_devs = []
        VR_devs = []
        haptic_devs = []
        for dev in os.listdir('/dev'):
            if 'ttyUSB' in dev:
                devs.append(dev)
            if 'hidraw' in dev:
                devs.append(dev)
            if 'ttyACM' in dev:
                devs.append(dev)
        for dev in devs:
            cmd = "udevadm info --name=/dev/" + dev + " --attribute-walk"
            output = os.popen(cmd).read()
            if "cp210x" in output:
                print("Spark Device found: " + dev)
                spark_devs.append(os.path.join("/dev/", dev))
            if "3Dconnexion" in output:
                print("SpaceMouse Device found: " + dev)
                SM_devs.append(os.path.join("/dev/", dev))
            if "STMicroelectronics" in output:
                print("Haptic Device found: " + dev)
                haptic_devs.append(os.path.join("/dev/", dev))
        if os.path.exists('/dev/serial/by-id/usb-HTC_Hub_Controller-if00'):
            print("VR Device found")
            VR_devs.append('/dev/serial/by-id/usb-HTC_Hub_Controller-if00')

        return spark_devs, SM_devs, VR_devs, haptic_devs
    def cleanup(self, modules, arms):
        for module in modules:
            module.kill()
        print("Exiting")

    def probe_spark_id(self, dev):
        try:
            con = serial.Serial(dev, 921600, timeout=2.0)
            try:
                time.sleep(0.5) # Ignore bootloader messages
                con.reset_input_buffer()
                con.reset_output_buffer()
                payload = con.read_until(b'\x00')[:-1]
                if not payload:
                    raise RuntimeError("no JSON payload received")
                data = json.loads(payload.decode('utf-8'))
                device_id = str(data['ID']).strip().lower()
                print(f"Spark probe: {dev} -> {device_id}")
                return device_id
            finally:
                con.close()
        except Exception as exc:
            print(f"Spark probe failed on {dev}: {exc}")
            return None

    def StartModules(self, Spark_devs, SM_devs, VR_devs, haptic_devs):
        print("Starting modules---------------------")
        # modules = [subprocess.Popen(['roscore'], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)]
        # time.sleep(1)
        # rospy.init_node('Main', anonymous=True)
        path = os.path.dirname(os.path.abspath(__file__))
        python_exe = sys.executable
        # modules.append(subprocess.Popen(['python3', 'Force/ForceNode.py'], start_new_session=True))
        # modules.append(subprocess.Popen(['python3', 'camera/realsense.py', '/both/front/'], start_new_session=True))
        # modules.append(subprocess.Popen(['python3', 'camera/realsense.py', '/lightning/wrist/'], start_new_session=True))
        # modules.append(subprocess.Popen(['python3', 'camera/realsense.py', '/thunder/wrist/'], start_new_session=True))
        # modules.append(subprocess.Popen(['python3', 'camera/realsense.py', '/both/top/'], start_new_session=True))
        # modules.append(subprocess.Popen(['python3', os.path.join(path, 'Spark/SparkNode_buffer.py')], start_new_session=True))

        modules = []
        spark_launch_devs = []
        seen_ids = {}
        for dev in sorted(Spark_devs):
            device_id = self.probe_spark_id(dev)
            if device_id is None:
                spark_launch_devs.append(dev)
                continue
            if device_id in seen_ids:
                print(
                    f"Duplicate Spark firmware ID '{device_id}' detected on {seen_ids[device_id]} and {dev}. "
                    "Skipping the duplicate device. Reflash the Spark firmware with distinct IDs."
                )
                continue
            seen_ids[device_id] = dev
            spark_launch_devs.append(dev)
        for vr in VR_devs:
            modules.append(subprocess.Popen([python_exe, 'VR/VR_Node.py'], start_new_session=True))
        for dev in spark_launch_devs:
            # modules.append(subprocess.Popen(['python3', os.path.join(path, 'Spark/SparkNode.py'), dev, "False"], start_new_session=True)) # Pub to latency buffer
            modules.append(subprocess.Popen([python_exe, os.path.join(path, 'Spark/SparkNode.py'), dev], start_new_session=True)) # Pub to latency buffer
        for dev in SM_devs:
            modules.append(subprocess.Popen([python_exe, os.path.join(path, 'SM/SpaceMouseROS.py'), dev], start_new_session=True))
        # for dev in haptic_devs:
        #     modules.append(subprocess.Popen([python_exe, os.path.join(path, 'Haptic/HapticNode.py'), dev], start_new_session=True))
        time.sleep(8)
        print("Modules started----------------------")
        return modules


    def main(self):
        Spark_devs, SM_devs, VR_devs, haptic_devs = self.get_devs()
        modules = self.StartModules(Spark_devs, SM_devs, VR_devs, haptic_devs)
        atexit.register(self.cleanup, modules, None)
        rclpy.spin(self)

if __name__ == '__main__':
    rclpy.init()
    node = LaunchDevs()
    node.main()
    node.destroy_node()
    rclpy.shutdown()
