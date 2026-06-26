"""ROS2 Python package setup for ai_edge_monitor."""

import os
from glob import glob

from setuptools import find_packages, setup

package_name = "ai_edge_monitor"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    data_files=[
        # Register package with ament so ros2 launch can find the launch file.
        (
            "share/ament_index/resource_index/packages",
            [f"resource/{package_name}"],
        ),
        (f"share/{package_name}", ["package.xml"]),
        # Install launch files.
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
    ],
    install_requires=[
        "setuptools",
    ],
    zip_safe=True,
    maintainer="ai-edge-monitor maintainers",
    maintainer_email="noreply@example.com",
    description=(
        "ROS2 bridge node for ai-edge-monitor -- publishes system and "
        "inference metrics as ROS2 topics."
    ),
    license="Proprietary",
    tests_require=["unittest"],
    entry_points={
        "console_scripts": [
            "monitor_node = ros2_bridge.node:main",
        ],
    },
)
