cmake_minimum_required(VERSION 3.16)
project(spark_realsense_bridge)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(realsense2 REQUIRED)

add_executable(spark_realsense_bridge src/spark_realsense_bridge.cpp)
ament_target_dependencies(spark_realsense_bridge rclcpp sensor_msgs)
target_link_libraries(spark_realsense_bridge realsense2::realsense2)
target_compile_features(spark_realsense_bridge PUBLIC cxx_std_17)

install(TARGETS spark_realsense_bridge
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
