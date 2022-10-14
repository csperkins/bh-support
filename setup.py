import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="bh_support",
    version="0.0.1",
    author="Colin Perkins",
    author_email="csp@csperkins.org",
    description="Helper to access Bear.app",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/csperkins/bh-support/",
    packages=setuptools.find_packages(),
    package_data = {
        'bh_support': ['py.typed'],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.9',
    setup_requires=["setuptools-pipfile"],
    use_pipfile=True
)
