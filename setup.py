from setuptools import setup

import versioneer

with open("README.md", "r") as f:
    long_description = f.read()

setup(
    name='pyexclient',
    description='Expel Workbench Client',
    long_description=long_description,
    long_description_content_type="text/markdown",
    author='Expel Inc.',
    url='https://github.com/expel-io/pyexclient',
    license='BSD',
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    packages=['pyexclient'],
    python_requires='>=3.7',
    install_requires=[
        'requests'
    ],
)
