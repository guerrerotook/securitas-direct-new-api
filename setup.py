import os
from codecs import open

from setuptools import setup, find_packages

base_dir = os.path.abspath(os.path.dirname(__file__))
info = {}
with open(os.path.join(base_dir, "securitas-direct-new-api", "__version__.py"), "r") as v:
    exec(v.read(), info)

with open("README.md", "r", "utf-8") as r:
    readme = r.read()

packages = ["securitas-direct-new-api"]

requires = [
    "requests>=2.26.0"
]

test_requirements = [
    
]

setup(
    name=info["__title__"],
    version=info["__version__"],
    description=info["__description__"],
    long_description=readme,
    long_description_content_type="text/markdown",
    author=info["__author__"],
    author_email=info["__author_email__"],
    url=info["__url__"],
    packages=find_packages(include=[
        "securitas-direct-new-api", "securitas-direct-new-api.*"
    ]),
    package_data={"": ["LICENSE", "NOTICE"]},
    include_package_data=True,
    python_requires=">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*",
    install_requires=requires,
    license=info["__license__"],
    zip_safe=False,
    tests_require=test_requirements,
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9"
    ],   
    project_urls={
        "Source": info["__url__"],
        "Tracker": info["__url__"] + "/issues",
    },
)
