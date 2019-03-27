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

from object_database import ServiceBase, service_schema, revisionConflictRetry
from object_database.web import cells as cells

import research_app.ContentSchema as ContentSchema
from research_app.ContentSchema import Project, Module
import research_app.EvaluationSchema as EvaluationSchema

from typed_python import sha_hash
from typed_python.Codebase import Codebase
import itertools
import scipy.io
import research_app
import os
import traceback
import pytz
import numpy
import argparse
import logging
import time
import sys
import io
import pydoc
from typed_python import python_ast, OneOf, Alternative, TupleOf,\
                        NamedTuple, Tuple, Class, ConstDict, Member
import datetime
import ast
from object_database import Schema, Indexed, current_transaction

BUTTON_COLOR = "#999999"
SELECTED_PROJECT_COLOR = "#EEEEFF"
SELECTED_MODULE_COLOR = "lightblue"

nyc = pytz.timezone("America/New_York")
schema = Schema("research_app.ResearchFrontend")

class CodeSelection(NamedTuple(start_row = int,
                               start_column = int,
                               end_row = int,
                               end_column = int)):
    @staticmethod
    def fromAceEditorJson(selection):
        return CodeSelection(
            start_row = selection["start"]["row"],
            start_column = selection["start"]["column"],
            end_row = selection["end"]["row"],
            end_column = selection["end"]["column"]
            )

    def slice(self, buffer):
        """Select just the text that is in the selection from the given buffer."""
        bufferLines = buffer.split('\n')
        lines = bufferLines[self.start_row:self.end_row+1]

        if len(lines) == 1:
            if self.start_column != self.end_column:
                lines[0] = lines[0][self.start_column:self.end_column]

        elif len(lines):
            lines[0] = lines[0][self.start_column:]
            lines[-1] = lines[-1][:self.end_column]

        return ('\n' * self.start_row) + '\n'.join(lines)


def ModalEditBox(title, currentText, onOK, onCancel):
    slot = cells.Slot(currentText)

    return cells.Modal(
        title,
        cells.SingleLineTextBox(slot),
        Cancel=onCancel,
        OK=lambda: onOK(slot.get())
        )

@schema.define
class ServiceConfig:
    output_path = str

class ResearchFrontend(ServiceBase):
    def initialize(self, chunkStoreOverride=None):
        self._logger = logging.getLogger(__file__)
        self._connectionCache = {}

        self.db.subscribeToSchema(schema)
        self.db.subscribeToSchema(ContentSchema.schema)
        self.db.subscribeToSchema(EvaluationSchema.schema)

        with self.db.transaction().consistency(full=True):
            if not Project.lookupAny():
                proj = Project(
                    name="project",
                    created_timestamp=time.time(),
                    last_modified_timestamp=time.time()
                    )
                Module(
                    name="doc1",
                    project=proj,
                    created_timestamp=time.time(),
                    last_modified_timestamp=time.time()
                    )
                # create the singleton EvaluationContext object
                EvaluationSchema.EvaluationContext()

    @staticmethod
    def configureService(database, serviceObject, matlabFileExportPath):
        database.subscribeToType(ServiceConfig)

        with database.transaction():
            config = ServiceConfig.lookupAny()

            if not config:
                config = ServiceConfig()

            config.output_path = matlabFileExportPath

    @staticmethod
    def serviceHeaderToggles(serviceObject, instance=None):
        ss = cells.sessionState()

        ss.setdefault('showNavTree', True)
        ss.setdefault('showEditor', True)
        ss.setdefault('showEvaluation', True)

        return [
            cells.Subscribed(lambda:
                cells.ButtonGroup([
                    cells.Button(
                        cells.Octicon("list-unordered"),
                        lambda: ss.toggle('showNavTree'),
                        active=ss.showNavTree),
                    cells.Button(
                        cells.Octicon("terminal"),
                        lambda: ss.toggle('showEditor'),
                        active=ss.showEditor),
                    cells.Button(
                        cells.Octicon("graph"),
                        lambda: ss.toggle('showEvaluation'),
                        active=ss.showEvaluation)
                    ])
                )
            ]

    @staticmethod
    def serviceDisplay(serviceObject, instance=None, objType=None, queryArgs=None):
        cells.ensureSubscribedSchema(schema)
        cells.ensureSubscribedSchema(ContentSchema.schema)
        cells.ensureSubscribedSchema(EvaluationSchema.schema)

        ss = cells.sessionState()
        assert ss
        ss.setdefault('showNavTree', True)
        ss.setdefault('showEditor', True)
        ss.setdefault('showEvaluation', True)

        return (
            cells.CollapsiblePanel(
                ResearchFrontend.navDisplay().background_color("#FAFAFA").height("100%"),
                cells.SubscribedSequence(
                    lambda: [x for x in ["showEditor", "showEvaluation"] if cells.sessionState().get(x)],
                    lambda which:
                        ResearchFrontend.editorDisplay() if which == "showEditor" else
                        ResearchFrontend.evaluationDisplay() if which == "showEvaluation" else
                        None
                        ,
                    asColumns=True
                   ).height("100%"),
                lambda: cells.sessionState().showNavTree
            ).height("100%")
            .withContext()
            + cells.Subscribed(lambda: cells.Text("Modal")
            + cells.sessionState().modalOverlay if cells.sessionState().modalOverlay else None)
        )

    @staticmethod
    def navDisplay():
        def projectView(project):
            expander = cells.Expands(
                closed=ResearchFrontend.projectLine(project),
                open=ResearchFrontend.projectLine(project) +
                    cells.SubscribedSequence(
                        lambda: sorted(Module.lookupAll(project=project), key=lambda m: m.name),
                        lambda m: ResearchFrontend.moduleLine(m)
                        )
                ).tagged(f"RFE_ProjectExpander_{project._identity}")

            def onProjectSelectChanged():
                if (cells.sessionState().selected_module and cells.sessionState().selected_module.exists()
                        and cells.sessionState().selected_module.project == project and not expander.isExpanded):
                    expander.isExpanded = True
                    expander.markDirty()

            return expander + cells.Subscribed(onProjectSelectChanged)

        return cells.Card(
            cells.SubscribedSequence(
                lambda: sorted(Project.lookupAll(), key=lambda p: p.name),
                projectView
                ) +
                cells.Code("\n\n\n\n") +
                cells.Button("New Project", ResearchFrontend.createNewProject).tagged("RFE_NewProjectButton")
            ).width(400)

    @staticmethod
    def projectLine(project):
        def deleter():
            def reallyDelete():
                project.deleteSelf()
                setattr(cells.sessionState(), "modalOverlay", None)

            cells.sessionState().modalOverlay = cells.Modal(
                f"Really delete project '{project.name}'?",
                "Because you can't undo this yet.",
                Cancel=lambda: setattr(cells.sessionState(), "modalOverlay", None),
                OK=reallyDelete
                ).tagged("RFE_DeleteProjectModal")

        def renamer():
            cells.sessionState().modalOverlay = ModalEditBox(
                f"Rename project '{project.name}'",
                project.name,
                onOK=lambda newName: (
                    setattr(project, 'name', newName),
                    setattr(cells.sessionState(), "modalOverlay", None)
                    ),
                onCancel=lambda: setattr(cells.sessionState(), 'modalOverlay', None)
                ).tagged("RFE_RenameProjectModal")

        def isSelected():
            if cells.sessionState().selected_module is not None and cells.sessionState().selected_module.exists():
                return cells.sessionState().selected_module.project == project
            return False

        return cells.Sequence([
                cells.Octicon("file-directory").nowrap(),

                cells.Subscribed(
                    lambda: cells.Text(project.name).width(200).nowrap()
                        .background_color(None if not isSelected() else SELECTED_PROJECT_COLOR)
                    ).nowrap(),

                cells.Button(
                    cells.Octicon("pencil").color(BUTTON_COLOR),
                    renamer, small=True, style="light"
                    ).nowrap().tagged(f"RFE_RenameProjectButton_{project._identity}"),

                cells.Button(
                    cells.Octicon("trashcan").color(BUTTON_COLOR),
                    deleter, small=True, style="light"
                    ).nowrap().tagged(f"RFE_DeleteProjectButton_{project._identity}"),

                cells.Button(
                    cells.Octicon("plus").color(BUTTON_COLOR),
                    lambda: ResearchFrontend.createNewModule(project),
                    small=True, style="light"
                    ).nowrap().tagged(f"RFE_NewModuleButton_{project._identity}")
                ]
            ).nowrap()

    @staticmethod
    def moduleLine(module):
        def selectModule():
            cells.sessionState().selected_module = module

        def deleter():
            def reallyDelete():

                module.deleteSelf()
                setattr(cells.sessionState(), "modalOverlay", None)

            cells.sessionState().modalOverlay = cells.Modal(
                f"Really delete '{module.project.name}.{module.name}'?",
                "Because you can't undo this yet.",
                Cancel=lambda: setattr(cells.sessionState(), "modalOverlay", None),
                OK=reallyDelete
                ).tagged("RFE_DeleteModuleModal")

        def renamer():
            cells.sessionState().modalOverlay = ModalEditBox(
                f"Rename module '{module.project.name}.{module.name}'",
                module.name,
                onOK=lambda newName: (
                    setattr(module, 'name', newName),
                    setattr(cells.sessionState(), "modalOverlay", None)
                    ),
                onCancel=lambda: setattr(cells.sessionState(), 'modalOverlay', None)
                ).tagged("RFE_RenameModuleModal")

        def isSelected():
            if cells.sessionState().selected_module is not None and cells.sessionState().selected_module.exists():
                return cells.sessionState().selected_module == module
            return False

        return cells.Sequence([
                cells.Clickable(
                    cells.Octicon("file").nowrap() +
                    cells.Text(module.name).width(200).nowrap(),
                    selectModule
                    ).nowrap().background_color(None if not isSelected() else SELECTED_MODULE_COLOR),

                cells.Button(
                    cells.Octicon("pencil").color(BUTTON_COLOR),
                    renamer, small=True, style="light"
                    ).nowrap().tagged(f"RFE_RenameModuleButton_{module._identity}"),

                cells.Button(
                    cells.Octicon("trashcan").color(BUTTON_COLOR),
                    deleter, small=True, style="light"
                    ).nowrap().tagged(f"RFE_DeleteModuleButton_{module._identity}")
                ]
            ).nowrap()

    @staticmethod
    def editorDisplay():
        module = cells.sessionState().selected_module

        if module is None or not module.exists():
            return cells.Card("Please select a module")

        def onEnter(buffer, selection):
            module.update(buffer)
            module.mark()

            evaluation = EvaluationSchema.EvaluationContext.lookupOrCreate()

            evaluation.request(module, None)

        def onExecuteSelected(buffer, selection):
            module.update(buffer)

            evaluation = EvaluationSchema.EvaluationContext.lookupOrCreate()

            if isinstance(selection,dict):
                selection = CodeSelection.fromAceEditorJson(selection)
                selectedText = selection.slice(buffer)
            else:
                selectedText = None

            evaluation.request(module, selectedText)

        def onTextChange(buffer, selection):
            module.update(buffer)

        ed = cells.CodeEditor(
            keybindings={'Enter': onEnter, 'Space': onExecuteSelected},
            fontSize=14,
            minLines=50,
            onTextChange=onTextChange
            ).height('calc(100vh - 110px)')

        def onCodeChange():
            """Executing this code in a 'subscribed' forces us to check whether the editor
            is out of sync with the current buffer. If so, we set the buffer.

            Any time the buffer changes because a user changes it, we should be forcing
            'current_buffer' to reflect that change immediately. Otherwise this code
            will execute and force it to be the same again.
            """
            if ed.getContents() != module.current_buffer:
                ed.setContents(module.current_buffer)

        return ed.width(1200) + cells.Subscribed(onCodeChange)

    @staticmethod
    def evaluationDisplay():
        evaluation = EvaluationSchema.EvaluationContext.lookupOrCreate()

        # force us to redraw if anything changes in terms of the horizontal width
        # because right now the plotly charts aren't smart enough to do this.
        cells.sessionState().showNavTree
        cells.sessionState().showEditor
        cells.sessionState().showEvaluation

        if not evaluation:
            return None

        return cells.Subscribed(
                lambda:
                    cells.Card("Waiting for backend...") if evaluation.state == "Dirty" else
                    cells.Card("Backend computing...") if evaluation.state == "Calculating" else
                    cells.Traceback(evaluation.error) if evaluation.error is not None else
                    cells.Tabs(
                        Displays=cells.Card(
                            cells.Subscribed(
                                lambda: ResearchFrontend.displaysDisplay(evaluation).tagged("RFE_Displays")
                                )
                            ),
                        Variables=cells.Card(
                            cells.Subscribed(
                                lambda: DisplayForVariables.variablesDisplay(evaluation).tagged("RFE_Variables")
                                )
                            )
                        ).tagged("DisplayTabCell")
                ).overflow("auto").width("100%")

    @staticmethod
    def createNewModule(project, base_name = None):
        all_names = [w.name for w in Module.lookupAll(project=project)]
        now_stamp = time.time()
        if base_name is None:
            base_name = "module"
        name = base_name
        count = 1
        while name in all_names:
            name = base_name+"_%s"%count
            count += 1

        newModule = Module(
            name=name,
            created_timestamp=now_stamp,
            project=project,
            last_modified_timestamp=now_stamp
            )

        cells.sessionState().selected_module = newModule

    @staticmethod
    def createNewProject(base_name = None):
        all_names = [w.name for w in Project.lookupAll()]
        now_stamp = time.time()
        if base_name is None:
            base_name = "project"
        name = base_name
        count = 1
        while name in all_names:
            name = base_name+"_%s"%count
            count += 1
        Project(
            name=name,
            created_timestamp=now_stamp,
            last_modified_timestamp=now_stamp
            )

    @staticmethod
    def displaysDisplay(evaluation):
        return cells.Sequence(
            [cells.Cell.makeCell(display) + cells.Padding() for display in evaluation.displays]
        )

    def doWork(self, shouldStop):
        while not shouldStop.is_set():
            time.sleep(0.25)
