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

"""
schema for the evaluation state of the research frontend.
"""
import time
from typed_python import OneOf, TupleOf
from object_database import Schema, Indexed, current_transaction
from research_app.ContentSchema import Module
from research_app.Displayable import Display

schema = Schema("research_app.EvaluationSchema")

@schema.define
class EvaluationContext:
    """A place to store evaluation outputs"""
    module = OneOf(None, Module)
    displaySnippet = OneOf(None, str)  # the snippet to display, or None for the whole thing

    state = OneOf(
        "Empty",        # the module hasn't been set yet via 'request'
        "Dirty",        # client wants us to compute
        "Calculating",  # the engine is calculating
        "Complete"      # the calculation is complete
        )

    error = OneOf(None, str)

    displays = TupleOf(Display)

    def request(self, module, snippetOrNone):
        self.module = module
        self.displaySnippet = snippetOrNone
        self.displays = ()
        self.error = None
        self.state = 'Dirty'

    @staticmethod
    def lookupOrCreate():
        res = EvaluationContext.lookupAny()
        if not res:
            return EvaluationContext()
        return res

    @staticmethod
    def lookupAll():
        raise NotImplementedError(
            "Singleton object type does not implement lookupAll, use lookupOrCreate")
