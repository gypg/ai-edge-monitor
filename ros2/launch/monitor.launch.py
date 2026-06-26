"""ROS2 launch file for ai_edge_monitor node.

Usage:
    ros2 launch ai_edge_monitor monitor.launch.py
    ros2 launch ai_edge_monitor monitor.launch.py publish_rate:=5.0
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            "publish_rate",
            default_value="1.0",
            description="Publishing rate in Hz",
        ),
        DeclareLaunchArgument(
            "node_name",
            default_value="ai_edge_monitor",
        ),
        Node(
            package="ai_edge_monitor",
            executable="monitor_node",
            name=LaunchConfiguration("node_name"),
            parameters=[{
                "publish_rate": LaunchConfiguration("publish_rate"),
            }],
            output="screen",
        ),
    ])
