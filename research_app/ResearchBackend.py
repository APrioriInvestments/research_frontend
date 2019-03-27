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
from typed_python import sha_hash
from typed_python.Codebase import Codebase
from research_app.ContentSchema import Project, Module
from research_app.EvaluationSchema import EvaluationContext
import research_app.ContentSchema as ContentSchema
import research_app.EvaluationSchema as EvaluationSchema

import itertools
import scipy.io
import research_app
import os
import traceback
import pytz
import numpy
import argparse
import logging
import types
import time
import sys
import io
import pydoc
import research_app.Displayable as Displayable
from typed_python import python_ast, OneOf, Alternative, TupleOf,\
                        NamedTuple, Tuple, Class, ConstDict, Member, ListOf
import datetime
import ast
from object_database import Schema, Indexed, current_transaction

schema = Schema("research_app.ResearchBackend")

@schema.define
class ServiceConfig:
    pass

Error = NamedTuple(error=str, line=int, trace = str)

CodeBlock = NamedTuple(code=str, line_range=Tuple(int,int))

class ResearchBackend(ServiceBase):
    def initialize(self, chunkStoreOverride=None):
        self._logger = logging.getLogger(__file__)

        self.db.subscribeToSchema(schema)
        self.db.subscribeToSchema(ContentSchema.schema)
        self.db.subscribeToSchema(EvaluationSchema.schema)

    @staticmethod
    def configureService(database, serviceObject):
        pass

    def doWork(self, shouldStop):
        while not shouldStop.is_set():
            time.sleep(0.25)
            try:
                ids_scripts_and_selections = []
                with self.db.transaction():
                    evaluation = EvaluationSchema.EvaluationContext.lookupOrCreate()
                    if evaluation.state in ["Dirty", "Calculating"]:
                        evaluation.state = "Calculating"

                        curScript = evaluation.module.current_buffer
                        snippet = evaluation.displaySnippet

                        ids_scripts_and_selections.append(
                            (evaluation, evaluation.module, curScript, snippet)
                            )

                for evaluation, module, curScript, snippet in ids_scripts_and_selections:
                    t0 = time.time()
                    self.executeResearchScript(
                        self.db,
                        self.runtimeConfig,
                        evaluation, module, curScript, snippet
                        )

                    self._logger.info(
                        "Took %s seconds to execute research display for",
                        (time.time() - t0)
                        )
            except Exception:
                self._logger.error(
                    "Unexpected exception in ResearchBackend:\n%s",
                    traceback.format_exc()
                    )

    @staticmethod
    def breakCodeIntoSegments(code):
        """Break a string containing python code into a list of module-level CodeBlock objects.

        If the code doesn't parse, return a Error object.
        """
        try:
            ast.parse(code)
        except SyntaxError as e:
            return Error(error=e.args[0], line=e.args[1][1], trace=traceback.format_exc() )

        statements = python_ast.convertPyAstToAlgebraic(ast.parse(code), "<interactive>").body

        #find contiguous blocks of code that parse
        lines = code.split("\n")
        blocks = []

        for i in range(len(statements)):
            nextLine = statements[i+1].line_number if i + 1 < len(statements) else len(lines) + 1

            blocks.append(
                CodeBlock(
                    code="\n".join(lines[statements[i].line_number-1:nextLine-1]),
                    line_range=(statements[i].line_number,nextLine)
                    )
                )

        return blocks

    @staticmethod
    def executeResearchScript(db, runtimeConfig, evaluation, module, curScript, snippet):
        logger = logging.getLogger(__name__)

        def _updateModule(error, displays):
            with db.transaction():
                evaluation.error = error
                evaluation.displays = displays
                evaluation.state = "Complete"

                logger.info("Marking display complete.")

        # parse the script
        codeBlocksOrErr = ResearchBackend.breakCodeIntoSegments(curScript)
        if isinstance(codeBlocksOrErr, Error):
            return _updateModule(codeBlocksOrErr.trace, [])

        outputDisplay = ListOf(Displayable.Display)()

        def _plot(*args, title="", **kwargs):
            disp = Displayable.Display.Plot(
                args=args,
                kwargs=kwargs,
                title=title
                )

            return Displayable.Display.Displays(displays=(disp,))

        def _print(obj, title=""):
            return Displayable.Display.Print(
                str=str(obj)[:10000],
                title=title
                )

        def _help(obj, title=""):
            if not isinstance(obj, (type, types.ModuleType, types.FunctionType)):
                obj = type(obj)

            return Displayable.Display.Object(
                object=obj,
                title=title
                )

        varsInScope = {
            '__builtins__': __builtins__,
            'numpy': numpy,
            'plot': _plot,
            'print': _print,
            'help': _help
            }

        logger.info("Evaluating code blocks.")

        for block in codeBlocksOrErr:
            res = ResearchBackend.displayForBlock(runtimeConfig, block, varsInScope)

            if res.get('error'):
                # we encoded an error string
                return _updateModule(res.get('error'), [])

            for d in res.get('displays', []):
                outputDisplay.append(d)

        logger.info("Done evaluating code blocks.")

        if snippet is None or not snippet.strip():
            return _updateModule(None,
                                 outputDisplay)

        logger.info("Starting snippet evaluation")
        selectedBlocksOrErr = ResearchBackend.breakCodeIntoSegments(snippet)

        if isinstance(selectedBlocksOrErr, Error):
            return _updateModule(selectedBlocksOrErr.trace, [])

        logger.info("Snipped parsed successfully")

        outputDisplay = []

        lastBlock = None
        for block in selectedBlocksOrErr:
            res = ResearchBackend.displayForBlock(runtimeConfig, block, dict(varsInScope))
            if res.get('error'):
                # we encoded an error string
                return _updateModule(res.get('error'), [])

            for d in res.get('displays', []):
                outputDisplay.append(d)

            lastBlock = block

        if lastBlock is not None:
            blockCode = "\n" * (lastBlock.line_range[0]-1) + lastBlock.code
            filename = os.path.join(
                runtimeConfig.serviceTemporaryStorageRoot,
                "interactive_" + sha_hash(blockCode).hexdigest
                )
            try:
                lastVal = eval(compile(blockCode, filename, "eval"), dict(varsInScope))
                if isinstance(lastVal, Displayable.Display):
                    pass
                elif lastVal is not None:
                    if isinstance(lastVal, (type, types.ModuleType, types.FunctionType)):
                        outputDisplay.append(
                            _help(lastVal, title=lastBlock.code)
                            )
                    else:
                        outputDisplay.append(
                            _print(lastVal, title=lastBlock.code)
                            )
            except SyntaxError:
                pass

        return _updateModule(None,
                             outputDisplay)


    @staticmethod
    def displayForBlock(runtimeConfig, block, curVarsInScope, displayAll=False):
        # clear the buffer of datasets, so we can track anything we touch, even
        # if its already there.
        logger = logging.getLogger(__name__)

        initVarsInScope = dict(curVarsInScope)

        blockCode = "\n" * (block.line_range[0]-1) + block.code

        filename = os.path.join(
            runtimeConfig.serviceTemporaryStorageRoot,
            "interactive_" + sha_hash(blockCode).hexdigest
            )

        with open(filename, "w") as codeFile:
            codeFile.write(blockCode)

        try:
            compiledEval = compile(blockCode + "\n", filename, "eval")
        except Exception:
            compiledEval = None

        if compiledEval:
            try:
                result = eval(compiledEval, curVarsInScope)

                if isinstance(result, Displayable.Display):
                    if result.title == "" and block.code.count("\n") < 10:
                        result = result.titled(block.code)

                    return {'displays': [result]}

            except Exception as e:
                logger.info(
                    f"User code produced exception ({e}):\n%s",
                    traceback.format_exc()
                    )
                return {'error': traceback.format_exc()}

        try:
            exec(compile(blockCode, filename, "exec"), curVarsInScope)
        except Exception as e:
            logger.info(
                f"User code produced exception ({e}):\n%s",
                traceback.format_exc()
                )
            return {'error': traceback.format_exc()}

        return {'displays': []}
