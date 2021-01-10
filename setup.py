import setuptools
import re
import io

__version__ = re.search(
    r'__version__\s*=\s*[\'"]([^\'"]*)[\'"]',
    io.open('coldstakepool/__init__.py', encoding='utf_8_sig').read()
).group(1)

setuptools.setup(
    name="coldstakepool",
    version=__version__,
    author="tecnovert",
    author_email="tecnovert@tecnovert.net",
    description="Particl cold-staking pool",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/tecnovert/coldstakepool",
    packages=setuptools.find_packages(),
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: Linux",
    ],
    install_requires=[
        "pyzmq",
        "plyvel",
    ],
    entry_points={
        "console_scripts": [
            "coldstakepool-prepare=bin.coldstakepool_prepare:main",
            "coldstakepool-run=bin.coldstakepool_run:main",
        ]
    }
)
