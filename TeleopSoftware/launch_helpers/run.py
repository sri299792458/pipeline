import tkinter as tk
import numpy as np
from scipy.spatial.transform import Rotation as R
import os
from std_msgs.msg import Float32MultiArray
from teleop_runtime_core import (
    SparkServoConfig,
    TeleopRuntimeState,
    process_spark_mode,
    publish_periodic_robot_state,
)

# ROS functions ------------------------------------------------------------------------------
current_file = os.path.abspath(__file__)
ur_time = 0.001
ur_lookahead_time = 0.05
ur_gain = 200
start_pose = {}
vr_start_pose = {}
runtime_state = TeleopRuntimeState()
spark_servo = SparkServoConfig(
    servo_time=ur_time,
    servo_lookahead_time=ur_lookahead_time,
    servo_gain=ur_gain,
)

offset = [0,0,0,0]

publish_ft = True

def ros_update(fields, ros_data, control_modes, URs, pubs, optimize, clock):
    if 'thunder_sm_log' in ros_data:
        fields['Thunder']['SMLog'].insert(tk.END, ros_data['thunder_sm_log'])
        fields['Thunder']['SMLog'].see(tk.END)
        del ros_data['thunder_sm_log']
    if 'lightning_sm_log' in ros_data:
        fields['Lightning']['SMLog'].insert(tk.END, ros_data['lightning_sm_log'])
        fields['Lightning']['SMLog'].see(tk.END)
        del ros_data['lightning_sm_log']

    for arm in control_modes:
        # Spark control: ------------------------------------------------------------------------
        # Optimization Control: ------------------------------------------------------------------------
        if control_modes[arm] == 'Spark' or control_modes[arm] == 'Optimization':
            process_spark_mode(
                arm=arm,
                fields=fields,
                ros_data=ros_data,
                control_modes=control_modes,
                runtime_state=runtime_state,
                URs=URs,
                pubs=pubs,
                optimize=optimize,
                clock=clock,
                servo=spark_servo,
            )

        # SpaceMouse control: ----------------------------------------------------------------
        elif control_modes[arm] == 'SpaceMouse':
            data_name = arm.lower()+"_sm_data"
            if data_name in ros_data:
                data = ros_data[data_name]
                del ros_data[data_name]
                # Velocity control: 
                if arm not in start_pose or ros_data[arm.lower() + '_change_mode'] == True:
                    pose = URs.get_receive(arm).getActualTCPPose()
                    start_pose[arm] = pose[:3], R.from_euler('xyz', pose[3:])
                    ros_data[arm.lower() + '_change_mode'] = False
                else:
                    xyz_scale = 0.005 * 200
                    # rot_scale = 0.01 * 300
                    rot_scale = 0.0
                    if arm == 'Thunder':
                        sm_data = np.array([
                        -data[2], data[0], -data[1], 
                        data[5], -data[4], -data[3]])
                    elif arm == 'Lightning':
                        sm_data = np.array([
                        data[2], -data[0], -data[1], 
                        -data[5], data[4], -data[3]])
                    if "SM_Invert" in control_modes:
                        sm_data[4] = -sm_data[4]
                        sm_data[5] = -sm_data[5]
                    sm_xyz = sm_data[:3] * xyz_scale
                    sm_rpy = sm_data[3:] * rot_scale
                    print(sm_xyz, sm_rpy)
                    # sm_rot = R.from_euler('xyz', sm_rpy)
                    # ee_xyz, ee_rot = start_pose[arm]
                    # new_xyz = sm_xyz + ee_xyz
                    # new_rot = ee_rot * sm_rot  # Correct order of multiplication
                    # new_rpy = new_rot.as_euler('xyz', degrees=False)
                    # print(new_rpy)
                    # new_pose = np.append(new_xyz, new_rpy)
                    # URs.servoL(arm, (new_pose, 0.0, 0.0, ur_time, ur_lookahead_time, ur_gain))

                    URs.speedL(arm, (np.append(sm_xyz, sm_rpy), 2, ur_time))

                    # start_pose[arm] = new_xyz, new_rot
                    if data[6] == 1:
                        URs.get_gripper(arm).set(255)
                    elif data[7] == 1:
                        URs.get_gripper(arm).set(0)

        # VR control: --------------------------------------------------------------------------
        elif control_modes[arm] == 'VR':
            if arm not in start_pose or ros_data[arm.lower() + '_change_mode'] == True:
                pose = URs.get_receive(arm).getActualTCPPose()
                start_pose[arm] = pose[:3], R.from_euler('xyz', pose[3:])
                ros_data[arm.lower() + '_change_mode'] = False
            else:
                if arm.lower()+'_vr_data' in ros_data:
                    data = ros_data[arm.lower()+'_vr_data']
                    del ros_data[arm.lower()+'_vr_data']
                    gripper = data[6]
                    gripper = round(gripper*10)/10
                    xyz_button = data[7]
                    rpy_button = data[8]

                    height, width, center = fields[arm]['hwc']
                    x = max(min(data[9]*width/2 + center[0], width-10), 10)
                    y = max(min(data[10]*height/2 + center[1], height-10), 10)
                    fields[arm]['VR_plot'].moveto(fields[arm]['vr_point'], x-10, y-10)

                    if xyz_button > 0.5 or rpy_button > 0.5:
                        if arm not in vr_start_pose: # Set the start pose
                            vr_start_pose[arm] = data
                        ee_xyz, ee_rot = start_pose[arm]

                        vr_xyz = np.array(data[:3]) - np.array(vr_start_pose[arm][:3])
                        vr_rpy = np.array(data[3:6]) - np.array(vr_start_pose[arm][3:6])

                        # Swap vr_xyz[0] and vr_xyz[1] for both arms
                        vr_xyz = [-vr_xyz[2], vr_xyz[1], vr_xyz[0]]
                        vr_rpy = [-vr_rpy[2], vr_rpy[1], vr_rpy[0]]

                        if arm == 'Thunder':
                            new_xyz = (
                                ee_xyz[0] - vr_xyz[1], 
                                ee_xyz[1] - vr_xyz[0], 
                                ee_xyz[2] - vr_xyz[2])
                            new_rot = ee_rot*R.from_euler('xyz', (-vr_rpy[2], vr_rpy[0], vr_rpy[1]))
                        elif arm == 'Lightning':
                            new_xyz = (
                                ee_xyz[0] + vr_xyz[1], 
                                ee_xyz[1] + vr_xyz[0], 
                                ee_xyz[2] - vr_xyz[2])
                            new_rot = ee_rot*R.from_euler('xyz', (-vr_rpy[2], vr_rpy[0], vr_rpy[1]))
                        
                        if not xyz_button > 0.5: # Move the end effector
                            new_xyz = ee_xyz
                        if not rpy_button > 0.5: # Rotate the end effector
                            new_rot = ee_rot

                        new_rpy = R.as_euler(new_rot, 'xyz')
                        URs.servoL(arm, (np.append(new_xyz, new_rpy), 0.0, 0.0, ur_time, ur_lookahead_time, ur_gain))
                        URs.get_gripper(arm).set(int(gripper*255))

                    else: # Reset the start pose
                        if arm in vr_start_pose:
                            del vr_start_pose[arm]
                        if arm in start_pose:
                            del start_pose[arm]

        # Force controller: -------------------------------------------------------------------
        elif control_modes[arm] == 'Force':
            # print(URs.getActualQ(arm))
            if arm == "Lightning":
                if arm.lower()+'_force_start' in ros_data:
                    task_frame = [0, 0, 0, 0, 0, 0]
                    selection_vector = [0, 1, 0, 0, 0, 0]
                    wrench_up = [0, 15, 0, 0, 0, 0]
                    force_type = 2
                    limits = [2, 2, 2, 1, 1, 1]
                    URs.forceMode(arm, (task_frame, selection_vector, wrench_up, force_type, limits))
                    del ros_data[arm.lower()+'_force_start']
                if arm.lower()+'_force_stop' in ros_data:
                    URs.stop(arm)
                    pose = URs.get_receive(arm).getActualTCPPose()
                    pose[1] -= 0.1
                    URs.moveL(arm, (pose, 0.5, 0.5, False))
                    fields[arm]['FT_home'].invoke()
                    fields[arm]['FT_zero'].invoke()
                    del ros_data[arm.lower()+'_force_stop']
                    
            if arm == "Thunder":
                if arm not in start_pose or ros_data[arm.lower() + '_change_mode'] == True:
                    fields[arm]['FT_home'].invoke()
                    fields[arm]['FT_zero'].invoke()
                    start_pose[arm] = URs.get_receive(arm).getActualTCPPose()
                    ros_data[arm.lower() + '_change_mode'] = False
                
                if True: #Teleop
                    if arm.lower()+'_force_ctl' in ros_data:
                        data = ros_data[arm.lower()+'_force_ctl']
                        del ros_data[arm.lower()+'_force_ctl']
                        scale = 0.05
                        offset = [0, 0, 0, 0]
                        new_pose = start_pose[arm].copy()
                        new_pose[0] += data[0]*scale + offset[0]
                        new_pose[2] += data[1]*scale + offset[1]
                        # print("Force: ", new_pose)
                        URs.servoL(arm, (new_pose, 0.0, 0.0, ur_time, ur_lookahead_time, ur_gain))
                        pubs[arm+"_force_offset"].publish(Float32MultiArray(data=offset))
                elif False: #Replay
                    if 'thunder_replay_eef' in ros_data:
                        data = ros_data['thunder_replay_eef']
                        del ros_data['thunder_replay_eef']
                        URs.servoL(arm, (data, 0.0, 0.0, ur_time, ur_lookahead_time, ur_gain))
                elif True: #Policy
                    if 'thunder_actions' in ros_data:
                        print("Policy: ", ros_data['thunder_actions'])
                        data = ros_data['thunder_actions']
                        del ros_data['thunder_actions']
                        start_pose[arm][0] += data[0]
                        start_pose[arm][2] += data[1]
                        # start_pose[arm][0] = data[0]
                        # start_pose[arm][2] = data[1]
                        print("Policy: ", start_pose[arm])
                        URs.servoL(arm, (start_pose[arm], 0.0, 0.0, ur_time, ur_lookahead_time, ur_gain))

        # Always: ----------------------------------------------------------------------
        if publish_ft:
            publish_periodic_robot_state(
                arm=arm,
                runtime_state=runtime_state,
                URs=URs,
                pubs=pubs,
                clock=clock,
            )
