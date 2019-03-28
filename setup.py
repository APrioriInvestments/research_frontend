#   Copyright 2018 Braxton Mckee
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import setuptools


INSTALL_REQUIRES = [line.strip() for line in open('requirements.txt')]

setuptools.setup(
    name='researchfrontend',
    version='0.0.1',
    description='Web application.',
    author='Braxton Mckee',
    author_email='braxton.mckee@gmail.com',
    url='https://github.com/braxtonmckee/research_frontend/',
    install_requires=INSTALL_REQUIRES,
)
