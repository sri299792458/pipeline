from __future__ import annotations

from dataclasses import dataclass

import rtde_control
import rtde_receive

from UR.dashboard import rtde_dashboard
from UR.gripper import RobotiqGripper


@dataclass(frozen=True)
class URArmConnectionConfig:
    name: str
    ip_address: str
    enable_gripper: bool
    control_frequency_hz: int = 500
    gripper_port: int = 63352


class URDashboardAdapter:
    def __init__(self, client: rtde_dashboard):
        self._client = client

    @classmethod
    def connect(cls, config: URArmConnectionConfig) -> "URDashboardAdapter":
        return cls(rtde_dashboard(config.ip_address))

    def unlockProtectiveStop(self):
        return self._client.unlockProtectiveStop()

    def close_popup(self):
        return self._client.close_popup()

    def stop(self):
        return self._client.stop()

    def close(self) -> None:
        try:
            del self._client
        except Exception:
            pass


class URControlAdapter:
    def __init__(self, client: "rtde_control.RTDEControlInterface"):
        self._client = client

    @classmethod
    def connect(cls, config: URArmConnectionConfig) -> "URControlAdapter":
        return cls(rtde_control.RTDEControlInterface(config.ip_address, config.control_frequency_hz))

    def disconnect(self) -> None:
        self._client.disconnect()

    def reconnect(self) -> None:
        self._client.reconnect()

    def zeroFtSensor(self):
        return self._client.zeroFtSensor()

    def servoL(self, *args):
        return self._client.servoL(*args)

    def servoJ(self, *args):
        return self._client.servoJ(*args)

    def moveJ(self, *args):
        return self._client.moveJ(*args)

    def moveL(self, *args):
        return self._client.moveL(*args)

    def speedJ(self, *args):
        return self._client.speedJ(*args)

    def speedL(self, *args):
        return self._client.speedL(*args)

    def forceMode(self, *args):
        return self._client.forceMode(*args)

    def freedriveMode(self):
        return self._client.freedriveMode()

    def endFreedriveMode(self):
        return self._client.endFreedriveMode()

    def servoStop(self):
        return self._client.servoStop()

    def stopJ(self):
        return self._client.stopJ()

    def forceModeStop(self):
        return self._client.forceModeStop()

    def stopL(self):
        return self._client.stopL()

    def speedStop(self):
        return self._client.speedStop()

    def getJointTorques(self):
        return self._client.getJointTorques()

    def triggerProtectiveStop(self):
        return self._client.triggerProtectiveStop()


class URStateAdapter:
    def __init__(self, client: "rtde_receive.RTDEReceiveInterface"):
        self._client = client

    @classmethod
    def connect(cls, config: URArmConnectionConfig) -> "URStateAdapter":
        return cls(rtde_receive.RTDEReceiveInterface(config.ip_address))

    def disconnect(self) -> None:
        self._client.disconnect()

    def reconnect(self) -> None:
        self._client.reconnect()

    def getActualQ(self):
        return self._client.getActualQ()

    def getActualTCPPose(self):
        return self._client.getActualTCPPose()

    def getActualTCPForce(self):
        return self._client.getActualTCPForce()

    def getFtRawWrench(self):
        return self._client.getFtRawWrench()

    def getActualTCPSpeed(self):
        return self._client.getActualTCPSpeed()

    def getSafetyMode(self):
        return self._client.getSafetyMode()


class URGripperAdapter:
    def __init__(self, gripper: RobotiqGripper):
        self._gripper = gripper

    @classmethod
    def connect(cls, config: URArmConnectionConfig) -> "URGripperAdapter":
        gripper = RobotiqGripper()
        gripper.connect(config.ip_address, config.gripper_port)
        return cls(gripper)

    def activate(self):
        return self._gripper.activate()

    def set_enable(self, enable: bool):
        return self._gripper.set_enable(enable)

    def set(self, position):
        return self._gripper.set(position)

    def get_current_position(self):
        return self._gripper.get_current_position()

    def disconnect(self) -> None:
        self._gripper.disconnect()
