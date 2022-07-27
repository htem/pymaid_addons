import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="pymaid-addons",
    version="0.0.1",
    author="Jasper Phelps",
    author_email="jasper.s.phelps@gmail.com",
    description="Some functions built on top of pymaid",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/htem/pymaid_addons",
    license='GNU GPL v3',
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        "Operating System :: OS Independent",
        'Intended Audience :: Science/Research',
        'Topic :: Scientific/Engineering :: Bio-Informatics'
    ],
    python_requires='>=3.6',
)
