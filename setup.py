#!/usr/bin/env python3

from setuptools import find_packages, setup
from aws_cost_mutilator import _version

with open("./README.md") as readme_file:
    readme = readme_file.read()

with open("./requirements.txt") as requirements_file:
    requirements = requirements_file.read().splitlines()

setup(
    author="Sky Moore",
    author_email="i@msky.me",
    classifiers=[
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    description="cli to mutilate aws costs, it's what accounting craves.",
    include_package_data=True,
    install_requires=requirements,
    keywords=[],
    long_description_content_type="text/markdown",
    long_description=readme,
    name="aws-cost-mutilator",
    packages=find_packages(include=["aws_cost_mutilator", "aws_cost_mutilator.*"]),
    entry_points={"console_scripts": ["acm = aws_cost_mutilator.__main__:cli"]},
    url="https://github.com/skymoore/aws-cost-mutilator",
    version=_version,
    zip_safe=True,
)
