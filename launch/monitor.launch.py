# Launch file for ai_edge_monitor ROS2 node.
#
# Usage:
#   ros2 launch ai_edge_monitor monitor.launch.py
#
# Override parameters:
#   ros2 launch ai_edge_monitor monitor.launch.py publish_rate:=2.0

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='ai_edge_monitor',
            executable='monitor_node',
            name='ai_edge_monitor',
            parameters=[{
                'publish_rate': 1.0,
                'power_source': 'auto',
                'include_inference': True,
            }],
            output='screen',
        ),
    ])
