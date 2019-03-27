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

from research_app.ContentSchema import Module
from research_app.ResearchFrontend import ResearchFrontend, CodeSelection
from research_app.ResearchBackend import ResearchBackend
from research_app.ResearchFrontend import schema as research_schema
import research_app.ContentSchema as ContentSchema
import research_app.EvaluationSchema as EvaluationSchema
import research_app.DisplayForPlot

from object_database import revisionConflictRetry
from object_database.web.cells import Subscribed, Cells
from typed_python.Codebase import Codebase as TypedPythonCodebase
import research_app
import time
import textwrap
import os


class ResearchFrontendTestHelper:
    def __init__(self, service_test_base ):
        self._base = service_test_base
        self._db = None
        self.ser_ctx = TypedPythonCodebase.FromRootlevelModule(research_app).serializationContext

    @property
    def db(self):
        if self._db is None:
            self._db = self._base.db
            self._db.subscribeToSchema(ContentSchema.schema)
            self._db.subscribeToSchema(EvaluationSchema.schema)

        return self._db

    def createResearchFrontend(self, path=None, timeout=10.0):
        serviceManager = self._base.serviceManager
        db = self._base.db

        with db.transaction():
            self.serviceObject = serviceManager.createOrUpdateService(
                ResearchFrontend, "ResearchFrontend", 1)
            self.backendServiceObject = serviceManager.createOrUpdateService(
                ResearchBackend, "ResearchBackend", 1)

            if not path:
                path = os.path.join(self._base.tempDir, "FrontendExports")

            if not os.path.exists(path):
                os.makedirs(path)

        ResearchFrontend.configureService(db, self.serviceObject, path)

        serviceManager.waitRunning(db, "ResearchFrontend", timeout=timeout)
        serviceManager.waitRunning(db, "ResearchBackend", timeout=timeout)

    def makeCells(self, queryArgs=None):
        queryArgs = queryArgs or {}

        rootCell = Subscribed(
            lambda: ResearchFrontend.serviceDisplay(
                self.serviceObject,
                queryArgs=queryArgs
                )
            ).withSerializationContext(self.ser_ctx)

        cells = Cells(self.db).withRoot(rootCell)
        cells.renderMessages()
        return cells

    def cellsForOnlyExistingModule(self):
        """Find the one module that exists in 'cells' and set the root cell to render it."""
        with self.db.view():
            module_ids_names = [(mod._identity, mod.name) for mod in Module.lookupAll()]

        assert len(module_ids_names) == 1

        module_id = module_ids_names[0][0]

        return self.makeCells(queryArgs={"module" : module_id})

    def execute(self, text, append=True, module_id=None):
        """Set the test buffer to 'text' and then wait for the service to execute it.

        returns the resulting 'display' object.
        """
        text = textwrap.dedent(text)

        if module_id is not None:
            def getModule():
                return Module.fromIdentity(module_id)
        else:
            def getModule():
                return Module.lookupAny()


        if not self.db.waitForCondition(
                getModule,
                timeout=5.0
                ):
            raise Exception("Never produced a module.")

        with self.db.transaction():
            module = getModule()

            if append:
                module.current_buffer = module.current_buffer + "\n" + text
            else:
                module.current_buffer = text

            evaluation = EvaluationSchema.EvaluationContext.lookupOrCreate()

            existingCount = (len(evaluation.displays), 0)

            evaluation.request(module, None)

        if not self.db.waitForCondition(
                lambda: evaluation.state == "Complete",
                timeout=5.0
                ):
            raise Exception("Research script timed out.")

        with self.db.view():
            if append:
                return (evaluation.displays[existingCount[0]:], [])
            else:
                return (evaluation.displays, [])

    @revisionConflictRetry
    def execute_selected(self, text, selection, module_id=None):
        """Set the test buffer to 'text' and then wait for the service to execute it.

        returns the resulting 'display' object.
        """
        text = textwrap.dedent(text)

        if not isinstance(selection, str):
            selectedText = CodeSelection.fromAceEditorJson(selection).slice(text)
        else:
            selectedText = selection

        if module_id is not None:
            def getModule():
                return Module.fromIdentity(module_id)
        else:
            def getModule():
                return Module.lookupAny()


        if not self.db.waitForCondition(
                getModule,
                timeout=5.0
                ):
            raise Exception("Never produced a module.")

        with self.db.transaction():
            module = getModule()

            module.current_buffer = text

            evaluation = EvaluationSchema.EvaluationContext.lookupOrCreate()

            evaluation.request(module, selectedText)

        if not self.db.waitForCondition(
                lambda: evaluation.state == "Complete",
                timeout=5.0
                ):
            raise Exception("Research script timed out.")

        with self.db.view():
            return (evaluation.displays, [])

    def waitForCellsCondition(self, cells, condition, timeout=10.0):
        assert cells.db.serializationContext is not None

        t0 = time.time()
        while time.time() - t0 < timeout:
            condRes = condition()

            if not condRes:
                time.sleep(.1)
                while cells.processOneTask():
                    pass
                cells.renderMessages()
            else:
                return condRes

        exceptions = cells.childrenWithExceptions()
        if exceptions:
            raise Exception("\n\n".join([e.childByIndex(0).contents for e in exceptions]))

        return None
