import setuptools

setuptools.setup(
    name="coldstakepool",
    version="0.0.1",
    author="The Particl Developers",
    author_email="hello@particl.io",
    description="Particl cold-staking pool",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/particl/coldstakepool",
    packages=setuptools.find_packages(),
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
    },
    test_suite="tests.test_suite"

)
