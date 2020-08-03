#!/usr/bin/python

from setuptools import setup, find_packages

setup(
    name="ooniapi",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    entry_points={"console_scripts": ["ooniapi = measurements.cli:cli",]},
    package_data={
        "ooniapi": (
            "*.adoc",
            "templates/*",
            "static/*/*",
            "countries/country-list.json",
        ),
    },
)
