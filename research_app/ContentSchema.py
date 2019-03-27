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
Content-management schema for the research frontend.
"""
import time
from typed_python import OneOf
from object_database import Schema, Indexed, current_transaction

schema = Schema("research_app.ContentSchema")

@schema.define
class ModuleContents:
    # gives the prior script in edit-time - if we navigate to an old script and edit it,
    # that older script will be the parent.
    parent = OneOf(None, schema.ModuleContents)

    timestamp = float

    # actual contents of the script
    contents = str

@schema.define
class Project:
    name = Indexed(str)
    created_timestamp = float
    last_modified_timestamp = float

    def deleteSelf(self):
        self.delete()

@schema.define
class Module:
    name = Indexed(str)
    project = Indexed(schema.Project)
    current_buffer = str
    prior_contents = OneOf(None, ModuleContents)
    last_modified_timestamp = float
    created_timestamp = float

    def update(self, buffer):
        """the user updated the text in the background, but hasn't tried to execute it yet."""
        self.current_buffer = buffer

    def mark(self):
        """Snapshot this version of the module."""
        self.prior_contents = ModuleContents(
            parent=self.prior_contents,
            contents=self.current_buffer,
            timestamp=time.time()
            )

    def deleteSelf(self):
        self.delete()
