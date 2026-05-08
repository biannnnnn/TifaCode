from setuptools import setup

setup(
    name="tifacode",
    version="0.1.0",
    package_dir={"tifacode": "."},
    packages=[
        "tifacode",
        "tifacode.agent",
        "tifacode.tools",
        "tifacode.cli",
        "tifacode.session",
        "tifacode.config",
    ],
    python_requires=">=3.9",
    install_requires=[
        "anthropic>=0.39.0",
        "openai>=1.60.0",
        "rich>=13.0.0",
        "pyyaml>=6.0",
    ],
    entry_points={
        "console_scripts": [
            "tifacode=tifacode.main:main",
        ],
    },
)
