from pathlib import Path

from setuptools import find_namespace_packages, setup


ROOT = Path(__file__).parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


setup(
    name="cli-anything-unity-mcp",
    version="0.1.0",
    description="CLI client and in-editor copilot bridge for Unity projects",
    long_description=README,
    long_description_content_type="text/markdown",
    author="Mazen Shaar",
    url="https://github.com/mazen320/unity-mcp-cli",
    project_urls={
        "Source": "https://github.com/mazen320/unity-mcp-cli",
        "Issues": "https://github.com/mazen320/unity-mcp-cli/issues",
    },
    packages=find_namespace_packages(include=["cli_anything.*"]),
    package_data={"cli_anything.unity_mcp": ["data/*.json"]},
    include_package_data=True,
    install_requires=["click>=8.1"],
    python_requires=">=3.11",
    license="MIT",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Build Tools",
        "Topic :: Software Development :: Testing",
    ],
    entry_points={
        "console_scripts": [
            "cli-anything-unity-mcp=cli_anything.unity_mcp.unity_mcp_cli:cli",
            "cli-anything-unity-mcp-mcp=cli_anything.unity_mcp.mcp_server:main",
        ]
    },
)
