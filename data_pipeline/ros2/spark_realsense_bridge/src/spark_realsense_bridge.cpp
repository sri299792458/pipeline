#include <atomic>
#include <chrono>
#include <cstdint>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <librealsense2/rs.hpp>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>

namespace
{
struct StreamProfile
{
  int width;
  int height;
  int fps;
};

StreamProfile parse_profile(const std::string & profile)
{
  std::stringstream stream(profile);
  std::string token;
  std::vector<int> values;
  while (std::getline(stream, token, ',')) {
    if (token.empty()) {
      continue;
    }
    values.push_back(std::stoi(token));
  }

  if (values.size() != 3 || values[0] <= 0 || values[1] <= 0 || values[2] <= 0) {
    throw std::invalid_argument(
            "Expected stream profile in WIDTH,HEIGHT,FPS form, got: " + profile);
  }

  return StreamProfile{values[0], values[1], values[2]};
}
}  // namespace

class SparkRealSenseBridge : public rclcpp::Node
{
public:
  SparkRealSenseBridge()
  : Node("spark_realsense_bridge"),
    running_(true)
  {
    camera_name_ = declare_parameter<std::string>("camera_name", this->get_name());
    serial_no_ = declare_parameter<std::string>("serial_no", "");
    color_profile_raw_ = declare_parameter<std::string>("rgb_camera.color_profile", "640,480,30");
    depth_profile_raw_ = declare_parameter<std::string>("depth_module.depth_profile", "640,480,30");
    enable_depth_ = declare_parameter<bool>("enable_depth", true);
    initial_reset_ = declare_parameter<bool>("initial_reset", false);
    declare_parameter<std::string>("device_type", "");
    declare_parameter<std::string>("firmware_version", "");

    if (serial_no_.empty()) {
      throw std::invalid_argument("serial_no must be provided for the V1 RealSense bridge");
    }

    color_profile_ = parse_profile(color_profile_raw_);
    depth_profile_ = parse_profile(depth_profile_raw_);

    color_publisher_ = create_publisher<sensor_msgs::msg::Image>(
      "color/image_raw", rclcpp::SensorDataQoS());
    if (enable_depth_) {
      depth_publisher_ = create_publisher<sensor_msgs::msg::Image>(
        "depth/image_rect_raw", rclcpp::SensorDataQoS());
    }

    start_pipeline();
    worker_ = std::thread(&SparkRealSenseBridge::capture_loop, this);
  }

  ~SparkRealSenseBridge() override
  {
    running_ = false;
    try {
      pipeline_.stop();
    } catch (...) {
    }
    if (worker_.joinable()) {
      worker_.join();
    }
  }

private:
  void start_pipeline()
  {
    if (initial_reset_) {
      rs2::context ctx;
      for (auto device : ctx.query_devices()) {
        if (serial_no_ == device.get_info(RS2_CAMERA_INFO_SERIAL_NUMBER)) {
          RCLCPP_INFO(
            get_logger(), "Hardware-resetting RealSense serial %s before startup", serial_no_.c_str());
          device.hardware_reset();
          std::this_thread::sleep_for(std::chrono::seconds(3));
          break;
        }
      }
    }

    rs2::config config;
    config.enable_device(serial_no_);
    config.enable_stream(
      RS2_STREAM_COLOR,
      color_profile_.width,
      color_profile_.height,
      RS2_FORMAT_RGB8,
      color_profile_.fps);
    if (enable_depth_) {
      config.enable_stream(
        RS2_STREAM_DEPTH,
        depth_profile_.width,
        depth_profile_.height,
        RS2_FORMAT_Z16,
        depth_profile_.fps);
    }

    rs2::pipeline_profile profile = pipeline_.start(config);
    rs2::device device = profile.get_device();

    const std::string device_type =
      device.supports(RS2_CAMERA_INFO_NAME) ? device.get_info(RS2_CAMERA_INFO_NAME) : "";
    const std::string firmware_version =
      device.supports(RS2_CAMERA_INFO_FIRMWARE_VERSION) ?
      device.get_info(RS2_CAMERA_INFO_FIRMWARE_VERSION) : "";

    set_parameter(rclcpp::Parameter("device_type", device_type));
    set_parameter(rclcpp::Parameter("firmware_version", firmware_version));

    RCLCPP_INFO(
      get_logger(),
      "Started RealSense bridge camera=%s serial=%s model=%s color=%s depth=%s depth_enabled=%s",
      camera_name_.c_str(),
      serial_no_.c_str(),
      device_type.c_str(),
      color_profile_raw_.c_str(),
      depth_profile_raw_.c_str(),
      enable_depth_ ? "true" : "false");
  }

  void capture_loop()
  {
    while (rclcpp::ok() && running_) {
      try {
        rs2::frameset frames = pipeline_.wait_for_frames();
        const rclcpp::Time stamp = now();

        rs2::video_frame color_frame = frames.get_color_frame();
        if (color_frame) {
          publish_color(color_frame, stamp);
        }

        if (enable_depth_) {
          rs2::depth_frame depth_frame = frames.get_depth_frame();
          if (depth_frame) {
            publish_depth(depth_frame, stamp);
          }
        }
      } catch (const rs2::error & error) {
        if (!running_) {
          return;
        }
        RCLCPP_ERROR_THROTTLE(
          get_logger(),
          *get_clock(),
          5000,
          "RealSense capture error for %s: %s",
          camera_name_.c_str(),
          error.what());
      } catch (const std::exception & error) {
        if (!running_) {
          return;
        }
        RCLCPP_ERROR_THROTTLE(
          get_logger(),
          *get_clock(),
          5000,
          "Unexpected capture error for %s: %s",
          camera_name_.c_str(),
          error.what());
      }
    }
  }

  void publish_color(const rs2::video_frame & frame, const rclcpp::Time & stamp)
  {
    sensor_msgs::msg::Image msg;
    msg.header.stamp = stamp;
    msg.header.frame_id = camera_name_ + "_color_optical_frame";
    msg.height = static_cast<uint32_t>(frame.get_height());
    msg.width = static_cast<uint32_t>(frame.get_width());
    msg.encoding = "rgb8";
    msg.is_bigendian = false;
    msg.step = static_cast<sensor_msgs::msg::Image::_step_type>(frame.get_stride_in_bytes());

    const auto * data = static_cast<const uint8_t *>(frame.get_data());
    msg.data.assign(data, data + static_cast<std::size_t>(msg.step) * msg.height);
    color_publisher_->publish(std::move(msg));
  }

  void publish_depth(const rs2::depth_frame & frame, const rclcpp::Time & stamp)
  {
    sensor_msgs::msg::Image msg;
    msg.header.stamp = stamp;
    msg.header.frame_id = camera_name_ + "_depth_optical_frame";
    msg.height = static_cast<uint32_t>(frame.get_height());
    msg.width = static_cast<uint32_t>(frame.get_width());
    msg.encoding = "16UC1";
    msg.is_bigendian = false;
    msg.step = static_cast<sensor_msgs::msg::Image::_step_type>(frame.get_stride_in_bytes());

    const auto * data = static_cast<const uint8_t *>(frame.get_data());
    msg.data.assign(data, data + static_cast<std::size_t>(msg.step) * msg.height);
    depth_publisher_->publish(std::move(msg));
  }

  std::string camera_name_;
  std::string serial_no_;
  std::string color_profile_raw_;
  std::string depth_profile_raw_;
  StreamProfile color_profile_;
  StreamProfile depth_profile_;
  bool enable_depth_;
  bool initial_reset_;

  rs2::pipeline pipeline_;
  std::thread worker_;
  std::atomic<bool> running_;

  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr color_publisher_;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr depth_publisher_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<SparkRealSenseBridge>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
