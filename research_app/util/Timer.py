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

import logging
import time
import types

class Timer:
    granularity = .1

    def __init__(self, message=None, *args):
        self.message = message or  ""
        self.loud = False
        self.args = args
        self.t0 = None
        self._granularity = Timer.granularity

    def __enter__(self):
        self.t0 = time.time()
        return self

    def always(self):
        self._granularity = 0.0
        return self

    def threshold(self, thresh):
        self._granularity = thresh
        return self

    def loudly(self, thresh=None):
        self.loud = True
        if thresh is not None:
            self._granularity=thresh
        return self

    def __exit__(self, a,b,c):
        t1 = time.time()
        if t1 - self.t0 > self._granularity:
            m = self.message
            a = []
            for arg in self.args:
                if isinstance(arg, types.FunctionType):
                    try:
                        a.append(arg())
                    except Exception:
                        a.append("<error>")
                else:
                    a.append(arg)

            if a:
                try:
                    m = m % tuple(a)
                except Exception:
                    logging.error("Couldn't format %s with %s", m, a)

            if '{elapsed}' in m:
                if t1 - self.t0 < 0.1:
                    m = m.replace('{elapsed}', "%.6f seconds" % (t1 - self.t0))
                else:
                    m = m.replace('{elapsed}', "%.2f seconds" % (t1 - self.t0))
            else:
                if t1 - self.t0 < 0.1:
                    m += " took %.6f seconds" % (t1 - self.t0)
                else:
                    m += " took %.2f seconds" % (t1 - self.t0)

            if self.loud:
                print(m)
            else:
                logging.info(m)

    def __call__(self, f):
        def inner(*args, **kwargs):
            with Timer(self.message or f.__name__, *self.args):
                return f(*args, **kwargs)

        inner.__name__ = f.__name__
        return inner
