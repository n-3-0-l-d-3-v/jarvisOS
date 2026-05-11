from setuptools import setup, find_packages

setup(
    name="jarvis",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "click>=8.1.0",
        "rich>=13.0.0",
        "python-dotenv>=1.0.0",
        "google-generativeai>=0.8.0",
    ],
    entry_points={
        "console_scripts": [
            "jar=jarvis.cli:main",
        ]
    },
)
