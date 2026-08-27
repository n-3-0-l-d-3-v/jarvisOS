from setuptools import setup, find_packages

setup(
    name="jarvis",
    version="0.3.0",
    packages=find_packages(),
    install_requires=[
        "click>=8.1.0",
        "rich>=13.0.0",
        "python-dotenv>=1.0.0",
        "google-generativeai>=0.8.0",
        "gitpython>=3.1.0",
        "httpx>=0.27.0",
        "fastapi>=0.110.0",
        "uvicorn>=0.29.0",
        "youtube-transcript-api>=0.6.2",
        "discord.py>=2.3.0",
        "mcp>=2.0.0",
        "sounddevice>=0.4.6",
        "numpy>=1.24.0",
    ],
    entry_points={
        "console_scripts": [
            "jar=jarvis.cli:main",
        ]
    },
)
