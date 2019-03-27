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


import unittest
import os
import textwrap
import research_app
from typed_python.Codebase import Codebase as TypedPythonCodebase
from object_database.web.cells import Cells, Plot, Tabs, SessionState
from research_app.ServiceTestHarness import ServiceTestHarness
from research_app.ResearchFrontend import schema as research_schema
from research_app.ResearchFrontend import ResearchFrontend, Module, Project
from research_app.Displayable import Display
from research_app.ResearchBackend import ResearchBackend, Error
import research_app.ContentSchema as ContentSchema
import research_app.EvaluationSchema as EvaluationSchema


class ResearchFrontendServiceTest(unittest.TestCase):
    def setUp(self):
        self.harness = ServiceTestHarness()
        self.harness.researchFrontendHelper.createResearchFrontend()

        self.ser_ctx = TypedPythonCodebase.FromRootlevelModule(research_app).serializationContext

    def tearDown(self):
        self.harness.shutdown()

    @property
    def helper(self):
        return self.harness.researchFrontendHelper

    def assertNoCellExceptions(self, cells: Cells):
        exceptions = cells.childrenWithExceptions()
        self.assertTrue(not exceptions, "\n\n".join([e.childByIndex(0).contents for e in exceptions]))

    def assertCellTagExists(self, cells: Cells, tag: str, expected_count=1):
        res = self.helper.waitForCellsCondition(
            cells,
            lambda: cells.findChildrenByTag(tag)
            )
        self.assertIsNotNone(res)
        self.assertEqual(len(res), expected_count)

    def assertCellTypeExists(self, cells: Cells, typ, expected_count=1):
        res = self.helper.waitForCellsCondition(
            cells,
            lambda: cells.findChildrenMatching(lambda cell: isinstance(cell, typ))
            )
        self.assertIsNotNone(res)
        self.assertEqual(len(res), expected_count)

    def objectsIdAndName(self, objType):
        with self.helper.db.view():
            return [(obj._identity, obj.name) for obj in objType.lookupAll()]

    def checkDisplays(self, displays, expected=None):
        """ Check that the displays match our expectations

        Parameters
        ----------
        displays: list of Displayable.Display
            the list of displays whose types we want to check

        expected: list of string
            A list of expected alternative types for the displays.
            Can be one of "Object", "Print", or
            "Displays: <list of DatasetDisplay>", where
            DatasetDisplay is one of "Plot" or "Plot".
            For the common case where a Displays list has a single
            element, we allow the shorthands "Plot" and "Plot"
            instead of the longer "Displays: Plot" and
            "Displays: Plot"

        Example
        -------
        The following two calls are not equvalent:
            self.checkDisplays(displays, ['Plot', 'Plot'])
            self.checkDisplays(displays, ['Displays: Plot, Plot'])
        """
        if expected is None:
            expected = ["Plot", "Plot"]

        self.assertEqual(len(displays), len(expected))

        for ix in range(len(displays)):
            self.checkDisplay(displays[ix], expected[ix])

    def checkDisplay(self, display, expected):
        if expected in ["Object", "Print"]:
            self.assertTrue(getattr(display.matches, expected))
        else:  # this is a Displays type. It could be in the default form
               # "Displays: List, Of, DatasetDisplay" or, if the list has a
               # single element, it could be in the shorthand form
               # "Plot" or "Plot"
            self.assertTrue(display.matches.Displays, display)

            parts = expected.split(":")
            if len(parts) == 1:
                # shorthand form
                assert expected in ["Plot", "Plot"]
                self.assertEqual(len(display.displays), 1)
                self.assertTrue(getattr(display.displays[0].matches, expected))
            else:
                parts = parts[1].split(",")
                self.assertEqual(len(display.displays), len(parts))

                for ix in range(len(parts)):
                    self.assertTrue(
                        getattr(display.displays[ix].matches, parts[ix])
                        )

    def check_ui_script(self, cells: Cells, script, root_cell=None):
        """ Perform a sequence of actions on the UI and check the results

        Parameters
        ----------
        cells: Cells
            the Cells object against which to perform the script

        script: list of steps
            the list of steps to be performed. The syntax of the steps
            is described below

        root_cell: Cell
            the root cell from which to start the script; normally this
            is None and we execute the script on the cells root, but useful
            for recursive scripts

        Step Syntax
        -----------
        Each step is a dictionary. The keys of the dictionary determine the
        types of actions that will be taken, and the values determine the
        specific actions. Each step can be divided in the selection phase
        and the execution phase. In the selection phase, we select the set
        of cells that we will be operating on, typically a single cell, and
        in the execution phase we perform actions and checks on the selected
        cells.

        * Step Keys
        -----------
        * A. Selection Phase
        --------------------
        tag: str
            when this key is present, we start by selecting the cells that have
            a matching tag

        exp_cnt: int
            the number of cells we expect to find; defaults to 1 when undefined

        cond: str

        * B. Execution Phase
        --------------------
        msg: dictionary
            when present, call `onMessageWithTransaction` with its value on
            all matching cells

        check: tuple(code:str, vars_in_scope:dict(name:str, var:obj)) or code:str
            an expression to check for truthiness and the variables needed to
            evaluate it. The expression is evaluated against each cell selected
            in the previous phase and will usually contain a reference to the
            variable `cell` which will be defined by the script execution engine.

        script: list of steps
            a script to be executed recursively on the selected cells. This
            capability comes in handy when we want to interact with elements
            of modal windows which appear as we click on buttons.

        """

        def codeAndVars(codeAndMaybeVars, cell):
            if isinstance(codeAndMaybeVars, str):
                # just code; no vars
                code = codeAndMaybeVars
                vars_in_ctx = {}
            else:
                # code and vars
                code = codeAndMaybeVars[0]
                vars_in_ctx = codeAndMaybeVars[1]

            vars_in_ctx['cell'] = cell

            return code, vars_in_ctx

        root_cell = root_cell or cells
        for step in script:
            selected_cells = []

            if 'tag' in step:
                selected_cells = root_cell.findChildrenByTag(step['tag'])

            if 'cond' in step:
                for cell in selected_cells:
                    code, vars_in_ctx = codeAndVars(step['cond'], cell)
                    pass

            expected_count = step['exp_cnt'] if 'exp_cnt' in step else 1

            self.assertEqual(
                len(selected_cells), expected_count,
                f"{len(selected_cells)} != {expected_count} for cells with tag '{step['tag']}'"
                )

            for cell in selected_cells:
                if 'msg' in step:
                    cell.onMessageWithTransaction(step['msg'])
                    cells.renderMessages()

                if 'check' in step:
                    code, vars_in_ctx = codeAndVars(step['check'], cell)

                    res = eval(compile(code, "<string>", "eval"), vars_in_ctx)
                    self.assertTrue(
                        res,
                        f"'{code}' is not True"
                        )

                if 'script' in step:
                    self.check_ui_script(cells, step['script'], root_cell=cell)

    def expandProjects(self, cells, project_ids_names=None):
        project_ids_names = project_ids_names or self.objectsIdAndName(Project)

        # expand all projects
        script = []
        for project_id, project_name in project_ids_names:
            script.append({'tag': f'RFE_ProjectExpander_{project_id}', 'cond': 'cell.isExpanded', 'msg': {}})

        self.check_ui_script(cells, script)

        # check that all projects are expanded
        script = []
        for project_id, project_name in project_ids_names:
            script.append({'tag': f'RFE_ProjectExpander_{project_id}', 'check': 'cell.isExpanded'})
        self.check_ui_script(cells, script)

    @staticmethod
    def collectTaggedCells(cells: Cells):
        return cells.findChildrenMatching(
            lambda cell: cell._tag is not None and "RFE_" in cell._tag
            )

    def test_can_submit_datasets(self):
        _, variables = self.helper.execute("""
            cube = numpy.array([1,2,3])
            """)

        self.helper.execute("""cube2 = cube+cube+cube""")

        displays, _ = self.helper.execute("""print(cube2)""")

        self.checkDisplays(displays, ["Print"])

        displays, _ = self.helper.execute("""plot(cube2)""")
        self.checkDisplays(displays, ["Plot"])

        self.assertEqual(len(displays[0].displays[0].args), 1)

    def test_modules(self):
        # first we check to see if we can create projects
        cells = self.helper.makeCells()

        with self.helper.db.view():
            initCount = len(Project.lookupAll())

        script = [{'tag': 'RFE_NewProjectButton', 'msg': {}}]
        self.check_ui_script(cells, script)

        project_ids_names = self.objectsIdAndName(Project)

        project_id = project_ids_names[0][0]
        self.assertEqual(initCount+1, len(project_ids_names))

        self.expandProjects(cells)

        # next we check to see if we can rename projects
        script = [
            {'tag': f"RFE_RenameProjectButton_{project_id}", 'msg': {}},
            {'tag': "RFE_RenameProjectModal",
             'script': [
                {'tag': 'message', 'msg': {'text': 'new_name'}},
                {'tag': 'OK', 'msg': {}}
                ]},
            ]
        self.check_ui_script(cells, script)

        project_ids_names = self.objectsIdAndName(Project)
        project_name = project_ids_names[0][1]
        assert project_ids_names[0][0] == project_id

        self.assertEqual(initCount+1, len(project_ids_names))
        self.assertEqual("new_name", project_name)

        # next we check to see if we can create modules that display correctly
        initModuleCount = len(self.objectsIdAndName(Module))

        script = [{'tag': f'RFE_NewModuleButton_{project_id}', 'msg': {}}]
        script = script + script
        self.check_ui_script(cells, script)

        module_ids_names = self.objectsIdAndName(Module)

        self.assertEqual(len(module_ids_names), initModuleCount+2)

        # check that all the module names are unique
        for ix in range(len(module_ids_names)):
            mod_name = module_ids_names[ix][1]
            for m in module_ids_names[ix+1:]:
                self.assertNotEqual(mod_name, m[1])

        module_id = module_ids_names[0][0]
        module_name = module_ids_names[0][1]

        code = """
            cube = numpy.array([1,2,3])

            plot(cube)

            plot(cube + cube)
            """
        expected_displays = ['Plot', 'Plot']

        displays, variables = self.helper.execute(code, module_id = module_id)
        cells.renderMessages()
        self.checkDisplays(displays, expected_displays)

        script = [{'tag': 'RFE_Displays', 'check': 'len(cell.children) == 2'}]
        self.check_ui_script(cells, script)

        # next we check to see if we can delete modules
        script =[
            {'tag': f'RFE_DeleteModuleButton_{module_id}', 'msg': {}},
            {'tag': 'RFE_DeleteModuleModal', 'script': [{'tag': 'OK', 'msg': {}}]}
            ]
        self.check_ui_script(cells, script)

        module_ids_names = self.objectsIdAndName(Module)

        self.assertEqual(len(module_ids_names), initModuleCount+1)
        self.assertTrue(module_name not in [p[1] for p in module_ids_names])

        module_id = module_ids_names[0][0]
        module_name = module_ids_names[0][1]

        # next we check to see if we can rename modules that display correctly
        script = [
            {'tag': f'RFE_RenameModuleButton_{module_id}', 'msg': {}},
            {'tag': 'RFE_RenameModuleModal', 'script': [
                {'tag': 'message', 'msg': {'text': 'new_name'}},
                {'tag': 'OK', 'msg': {}}]}
            ]
        self.check_ui_script(cells, script)

        module_ids_names = self.objectsIdAndName(Module)

        self.assertEqual(len(module_ids_names), initModuleCount+1)

        new_module_name = [m[1] for m in module_ids_names if m[0] == module_id][0]

        self.assertEqual(new_module_name, 'new_name')

        displays, variables = self.helper.execute(code, append = False, module_id = module_id)
        cells.renderMessages()
        self.checkDisplays(displays, expected_displays)

        script = [{'tag': 'RFE_Displays', 'check': 'len(cell.children) == 2'}]
        self.check_ui_script(cells, script)

        new_code = """
            plot(cube**2)
            """
        new_expected_displays = ['Plot']

        displays, variables = self.helper.execute(
            code+new_code, append = False, module_id = module_id)
        cells.renderMessages()
        self.checkDisplays(displays, expected_displays+new_expected_displays)

        script = [{'tag': 'RFE_Displays', 'check': 'len(cell.children) == 3'}]
        self.check_ui_script(cells, script)

        # next we check to see if we can delete projects
        script = [
            {'tag': f"RFE_DeleteProjectButton_{project_id}", 'msg': {}},
            {'tag': 'RFE_DeleteProjectModal', 'script': [{'tag': 'OK', 'msg': {}}]}
            ]
        self.check_ui_script(cells, script)

        project_ids_names = self.objectsIdAndName(Project)

        self.assertTrue(project_id not in [p[0] for p in project_ids_names])

    def test_print(self):
        displays, variables = self.helper.execute("""
            cube = numpy.array([1,2,3])

            print(cube)
            cube2 = cube+cube+cube

            plot(cube2)

            print(cube2)
            """)

        self.checkDisplays(displays, ["Print", "Plot", "Print"])

        cells = self.helper.cellsForOnlyExistingModule()
        script =[{'tag': 'RFE_Displays', 'check': 'len(cell.children) == 3'}]
        self.check_ui_script(cells, script)

        # wait until we see a plot
        self.assertCellTypeExists(cells, Plot)
        self.assertNoCellExceptions(cells)


class ResearchFrontendParsingTest(unittest.TestCase):
    def test_divide_into_blocks_basic_single_line(self):
        self.assertEqual(len(ResearchBackend.breakCodeIntoSegments("1+2")), 1)

    def test_divide_into_blocks_basic(self):
        blocks = ResearchBackend.breakCodeIntoSegments(textwrap.dedent("""
            print('hi')

            1+2+3

            while True:
                x = 1+2+3
            """))

        self.assertEqual(len(blocks), 3)

        self.assertTrue('hi' in blocks[0].code)
        self.assertEqual(blocks[0].line_range, (2,4))

        self.assertTrue('1+2' in blocks[1].code)
        self.assertEqual(blocks[1].line_range, (4,6))

        self.assertTrue('x' in blocks[2].code and 'True' in blocks[2].code)
        self.assertEqual(blocks[2].line_range, (6,9))

    def test_divide_into_blocks_whitespace(self):
        blocks = ResearchBackend.breakCodeIntoSegments(textwrap.dedent("""
            while True:

                x = 1+2+3
            """))

        self.assertEqual(len(blocks), 1)

    def test_parse_syntax_error(self):
        err = ResearchBackend.breakCodeIntoSegments("if (")
        self.assertTrue(isinstance(err, Error))
