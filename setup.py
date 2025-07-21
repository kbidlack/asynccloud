from setuptools import find_packages, setup

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="asynccloud",
    version="0.1.0",
    author="Kavi Bidlack",
    author_email="",
    description="An async wrapper for soundcloud.py",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/kbidlack/asynccloud",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3.13",
    ],
    python_requires=">=3.13",
    install_requires=[
        "soundcloud-v2",
    ],
)
