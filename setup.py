from setuptools import find_namespace_packages, setup


setup(
    name="cli-anything-unity-mcp",
    version="0.1.0",
    description="CLI-Anything harness for the AnkleBreaker Unity MCP HTTP bridge",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    include_package_data=True,
    install_requires=["click>=8.1"],
    python_requires=">=3.11",
    entry_points={
        "console_scripts": [
            "cli-anything-unity-mcp=cli_anything.unity_mcp.unity_mcp_cli:cli",
        ]
    },
)
