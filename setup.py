from setuptools import setup

import versioneer

setup(
    name='pyexclient',
    description='Expel Workbench Client',
    author='Expel Inc.',
    url='https://github.com/expel-io/pyexclient',
    license='BSD',
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    packages=['pyexclient'],
    python_requires='>=3.7',
)
