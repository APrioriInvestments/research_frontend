#   Copyright 2019 APriori Investments
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

import os
import subprocess
import sys
import time
import unittest

own_dir = os.path.dirname(os.path.abspath(__file__))


class TestWholeSystemSimulation(unittest.TestCase):
    def test_whole_system_simulation(self):

        simulation = subprocess.Popen(
            [
                sys.executable,
                os.path.join(own_dir, 'whole_system_simulation.py'),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        try:
            # this should throw a subprocess.TimeoutExpired exception if the service did not crash
            # time.sleep(20)
            simulation.wait(timeout=20)
        except subprocess.TimeoutExpired:
            pass
        else:
            stdout, stderr = simulation.communicate()
            def printStream(bytestring):
                for line in bytestring.decode().splitlines():
                    print(line)

            printStream(stdout)
            printStream(stderr)
            raise Exception(
                f"Failed to start whole system simulation (retcode:{simulation.returncode})"
            )
