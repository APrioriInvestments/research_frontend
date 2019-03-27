#!/usr/bin/env python3

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

import sys
import time
from research_app.ServiceTestHarness import ServiceTestHarness
import argparse

def main(argv):
    parser = argparse.ArgumentParser(description='simulate the entire research_app system')

    parser.add_argument('--large', action='store_true', default=False, help="Put a bigger computation in")

    parsedArgs = parser.parse_args(argv[1:])

    harness = ServiceTestHarness()
    try:
        harness.webServiceHelper.createWebService()
        harness.researchFrontendHelper.createResearchFrontend()

        harness.researchFrontendHelper.execute(f"""
            pointCount = 100000
            xs = numpy.sin(numpy.arange(pointCount) / 1000)

            help(numpy)
            plot(xs, xs ** .5, title='hihi')
            """
            )

        # so that we can autodeploy code if we want
        harness.unlockAllServices()

        while True:
            time.sleep(0.25)
            harness.serviceManager.cleanup()
    finally:
        harness.shutdown()

if __name__ == '__main__':
    main(sys.argv)
