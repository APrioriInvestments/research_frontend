#!/usr/bin/env python3

import sys
import logging
import unittest
import os
import re
import time
import nose
import nose.config
import nose.loader
import nose.plugins.manager
import nose.plugins.xunit
import argparse
import traceback
import json

class DirectoryScope(object):
    def __init__(self, directory):
        self.directory = directory

    def __enter__(self):
        self.originalWorkingDir = os.getcwd()
        os.chdir(self.directory)

    def __exit__(self, exc_type, exc_value, traceback):
        os.chdir(self.originalWorkingDir)

def sortedBy(elts, sortFun):
    return [x[1] for x in sorted([(sortFun(y),y) for y in elts])]

def loadTestModules(testFiles, rootDir, rootModule):
    modules = set()
    for f in testFiles:
        try:
            with DirectoryScope(os.path.split(f)[0]):
                moduleName  = fileNameToModuleName(f, rootDir, rootModule)
                logging.info('importing module %s', moduleName)
                __import__(moduleName)
                modules.add(sys.modules[moduleName])
        except ImportError:
            logging.error("Failed to load test module: %s", moduleName)
            traceback.print_exc()
            raise

    return modules


def fileNameToModuleName(fileName, rootDir, rootModule):
    tr = (
        fileName
            .replace('.py', '')
            .replace(rootDir, '')
            .replace(os.sep, '.')
            )
    if tr.startswith('.'):
        return tr[1:]
    return tr

class OrderedFilterAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if 'ordered_actions' not in namespace:
            setattr(namespace, 'ordered_actions', [])
        previous = namespace.ordered_actions
        previous.append((self.dest, values))
        setattr(namespace, 'ordered_actions', previous)

class PythonTestArgumentParser(argparse.ArgumentParser):
    def __init__(self):
        super(PythonTestArgumentParser,self).__init__(add_help = False)
        self.add_argument(
            '-v',
            dest='testHarnessVerbose',
            action='store_true',
            default=False,
            required=False,
            help="run test harness verbosely"
            )
        self.add_argument(
            '--list',
            dest='list',
            action='store_true',
            default=False,
            required=False,
            help="don't run tests, just list them"
            )
        self.add_argument(
            '-f',
            '--file',
            dest='write_to_files',
            action='store_true',
            default=False,
            help="write test failure logs to individual files and keep them around."
            )
        self.add_argument("-s", "--summary", dest='write_summary_file', default=None,
            help="write a json summary of test results to this file"
            )
        self.add_argument("--tests_from", dest='tests_from', default=None,
            help="run tests listed in this file"
            )
        self.add_argument("--copies", dest='copies', default=None, type=int,
            help="repeat the tests this many times"
            )
        self.add_argument("--mod_pair", dest='mod_pair', default=None, type=int, nargs=2,
            help="given two arguments, n, m, filter for tests whose names hash to n-mod m"
            )

        self.add_argument("--loglevel", help="set logging level", choices=["INFO", "DEBUG", "WARN", "ERROR", "CRITICAL"], default="WARN")
        self.add_argument('--filter',
                            nargs = 1,
                            help = 'restrict tests to a subset matching FILTER',
                            action = OrderedFilterAction,
                            default = None)
        self.add_argument('--add',
                            nargs = 1,
                            help = 'add back tests matching ADD',
                            action = OrderedFilterAction,
                            default = None)
        self.add_argument('--exclude',
                            nargs = 1,
                            help = "exclude python unittests matching 'regex'. "
                                  +"These go in a second pass after -filter",
                            action = OrderedFilterAction,
                            default = None)

    def parse_args(self,toParse):
        argholder = super(PythonTestArgumentParser,self).parse_args(toParse)

        args = None
        if 'ordered_actions' in argholder:
            args = []
            for arg,l in argholder.ordered_actions:
                args.append((arg,l[0]))
        return argholder, args

def regexMatchesSubstring(pattern, toMatch):
    for _ in re.finditer(pattern, toMatch):
        return True
    return False

def applyFilterActions(filterActions, tests):
    filtered = [] if filterActions[0][0] == 'add' else list(tests)

    for action, pattern in filterActions:
        if action == "add":
            filtered += [x for x in tests if
                                    regexMatchesSubstring(pattern, x.id())]
        elif action == "filter":
            filtered = [x for x in filtered if
                                    regexMatchesSubstring(pattern, x.id())]
        elif action == "exclude":
            filtered = [x for x in filtered if
                                    not regexMatchesSubstring(pattern, x.id())]
        else:
            assert False

    return filtered

def printTests(testCases):
    for test in testCases:
        print(test.id())

def runPyTestSuite(config, testFiles, testCasesToRun, testArgs):
    testProgram = nose.core.TestProgram(
        config=config,
        defaultTest=testFiles,
        suite=testCasesToRun,
        argv=testArgs,
        exit=False
        )

    return not testProgram.success

def loadTestsFromModules(config, modules):
    loader = nose.loader.TestLoader(config = config)
    allSuites = []
    for module in modules:
        cases = loader.loadTestsFromModule(module)
        allSuites.append(cases)

    return allSuites

def extractTestCases(suites):
    testCases = flattenToTestCases(suites)
    #make sure the tests are sorted in a sensible way.
    sortedTestCases = sortedBy(testCases, lambda x: x.id())

    return [x for x in sortedTestCases if not testCaseHasAttribute(x, 'disabled')]

def flattenToTestCases(suite):
    if isinstance(suite, list) or isinstance(suite, unittest.TestSuite):
        return sum([flattenToTestCases(x) for x in suite], [])
    return [suite]

def testCaseHasAttribute(testCase, attributeName):
    """Determine whether a unittest.TestCase has a given attribute."""
    if hasattr(getattr(testCase, testCase._testMethodName), attributeName):
        return True
    if hasattr(testCase.__class__, attributeName):
        return True
    return False


def loadTestCases(config, testFiles, rootDir, rootModule):
    modules = sortedBy(loadTestModules(testFiles, rootDir, rootModule), lambda module: module.__name__)
    allSuites = loadTestsFromModules(config, modules)
    return extractTestCases(allSuites)

def findTestFiles(rootDir, testRegex):
    logging.info('finding files from root %s', rootDir)
    testPattern = re.compile(testRegex)
    testFiles = []
    for directory, subdirectories, files in os.walk(rootDir, topdown=True):
        # prune hidden sudirectories and don't descend into them
        subdirectories[:] = [d for d in subdirectories if not d.startswith('.')]
        testFiles += [os.path.join(directory, f) for f in files if testPattern.match(f) is not None]

    return testFiles

def runPythonUnitTests(args, filter_actions):
    """run python unittests in all files in the 'tests' directory in the project.

    Args contains arguments from a UnitTestArgumentParser.

    Returns True if any failed.
    """
    root_dir = os.path.dirname(os.path.abspath(__file__))

    return runPythonUnitTests_(
        args, filter_actions, testGroupName = "python",
        testFiles = findTestFiles(root_dir, '.*_test.py$')
        )

def logAsInfo(*args):
    if len(args) == 1:
        print(time.asctime(), " | ", args)
    else:
        print(time.asctime(), " | ", args[0] % args[1:])

def setLoggingLevel(level):
    format_string = '[%(asctime)s] %(levelname)8s %(filename)30s:%(lineno)4s | %(message)s'
    logging.getLogger().setLevel(level)

    for handler in logging.getLogger().handlers:
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(format_string))

class OutputCapturePlugin(nose.plugins.base.Plugin):
    """
    Output capture plugin. Enabled by default. Disable with ``-s`` or
    ``--nocapture``. This plugin captures stdout during test execution,
    appending any output captured to the error or failure output,
    should the test fail or raise an error.
    """
    enabled = True
    name = 'OutputCaptureNosePlugin'
    score = 16010

    def __init__(self):
        self.stdout = []
        self.stdoutFD = None
        self.stderrFD = None
        self.fname = None
        self.hadError=False
        self.outfile = None
        self.testStartTime = None
        self.nocaptureall = False
        self.write_to_files = False
        self.individualTestResults = {}
        self.loglevel = logging.WARN

    def options(self, parser, env):
        """Register commandline options
        """
        parser.add_option(
            "-s", "--nocapture", action="store_true",
            default=False, dest="nocaptureall"
            )
        parser.add_option(
            "-f", "--file", action="store_true",
            default=False, dest="write_to_files",
            help="Write test log failures to files."
            )
        parser.add_option("--loglevel", default="WARN")

    def configure(self, options, conf):
        """Configure plugin. Plugin is enabled by default.
        """
        self.conf = conf
        self.nocaptureall = options.nocaptureall
        self.write_to_files = options.write_to_files
        self.loglevel = getattr(logging, options.loglevel)

    def safeRemoveOutput(self):
        try:
            os.remove(self.fname)
        except OSError:
            pass

    def afterTest(self, test):
        """Clear capture buffer.
        """
        if self.nocaptureall:
            if not self.hadError:
                logAsInfo("\tpassed in %s", time.time() - self.testStartTime)
            else:
                logAsInfo("\tfailed in %s seconds. See logs in %s", time.time() - self.testStartTime, self.fname)

        self.individualTestResults[test.id()] = {'success': not self.hadError}

        if self.stdoutFD is None:
            return

        setLoggingLevel(logging.ERROR)

        sys.stdout.flush()
        sys.stderr.flush()

        os.dup2(self.stdoutFD, 1)
        os.close(self.stdoutFD)

        os.dup2(self.stderrFD, 2)
        os.close(self.stderrFD)

        self.stdoutFD = None
        self.stderrFD = None

        self.outfile.flush()
        self.outfile.close()
        self.outfile = None

        if not self.hadError:
            self.safeRemoveOutput()
            logAsInfo("\tpassed in %s", time.time() - self.testStartTime)
        else:
            if self.write_to_files:
                #the test failed. Report the failure
                logAsInfo("\tfailed in %s seconds. See logs in %s", time.time() - self.testStartTime, self.fname)
                self.individualTestResults[test.id()]['logs'] = [os.path.abspath(self.fname)]
            else:
                self.safeRemoveOutput()

                logAsInfo("\tfailed in %s seconds.", time.time() - self.testStartTime)

    def begin(self):
        pass

    def beforeTest(self, test):
        """Flush capture buffer.
        """
        if self.nocaptureall:
            logAsInfo("Running test %s without capture.", test)
        else:
            logAsInfo("Running test %s", test)

        self.testStartTime = time.time()

        if self.nocaptureall:
            self.hadError=False
            setLoggingLevel(self.loglevel)
            return

        sys.stdout.flush()
        sys.stderr.flush()

        self.stdoutFD = os.dup(1)
        self.stderrFD = os.dup(2)

        self.fname = "nose.%s.%s.log" % (test.id(), os.getpid())

        if os.getenv("TEST_ERROR_OUTPUT_DIRECTORY", None) is not None:
            self.fname = os.path.join(os.getenv("TEST_ERROR_OUTPUT_DIRECTORY"), self.fname)

        self.outfile = open(self.fname, "w")

        os.dup2(self.outfile.fileno(), 1)
        os.dup2(self.outfile.fileno(), 2)

        self.hadError=False

        setLoggingLevel(self.loglevel)

    def formatError(self, test, err):
        """Add captured output to error report.
        """
        self.hadError=True

        if self.nocaptureall:
            setLoggingLevel(logging.ERROR)
            return err

        ec, ev, tb = err

        if self.write_to_files:
            #print statements here show up in the logfile
            print()
            print("Test ", test, ' failed')
            print()
            print('Traceback (most recent call last):')
            print("".join(traceback.format_tb(tb)))
            if (str(ev)):
                print(ec.__qualname__ + ":", ev)
            else:
                print(ec.__qualname__)
        else:
            self.outfile.flush()
            with open(self.fname, "r") as f:
                contents = f.read()
            contents = contents.strip()
            if contents:
                ev = str(ev) + "\n\n-----------------------------\ncaptured log output:\n-----------------------------\n" + contents

        return (ec, ev, tb)

    def formatFailure(self, test, err):
        """Add captured output to failure report.
        """
        self.hadError=True
        return self.formatError(test, err)

    def end(self):
        pass

    def finalize(self, result):
        """Restore stdout.
        """


def runPythonUnitTests_(args, filterActions, testGroupName, testFiles):
    testArgs = ["dummy"]

    if args.testHarnessVerbose or args.list:
        testArgs.append('--nocapture')

    if args.loglevel:
        testArgs.append("--loglevel="+args.loglevel)

    if args.write_to_files:
        testArgs.append('--file')

    testArgs.append('--verbosity=0')

    if not args.list:
        print("Executing %s unit tests." % testGroupName)

    root_dir = os.path.dirname(os.path.abspath(__file__))

    testCapturePlugin = OutputCapturePlugin()

    plugins = nose.plugins.manager.PluginManager([testCapturePlugin])

    config = nose.config.Config(plugins=plugins)
    config.configure(testArgs)

    testCases = loadTestCases(config, testFiles, root_dir, '.')
    if args.mod_pair:
        n,m = args.mod_pair

        tests_to_keep = []
        for t in testCases:
            test_id = sum(ord(x) for x in t.id())
            if test_id % m == n:
                tests_to_keep.append(t)
        testCases = tests_to_keep
    if args.tests_from:
        with open(args.tests_from, "r") as f:
            test_list = [x.strip() for x in f.read().split("\n") if x.strip()]

        testsByName = {test.id(): test for test in testCases}

        testCases = [testsByName[t] for t in test_list]

    if filterActions:
        testCases = applyFilterActions(filterActions, testCases)

    if args.copies:
        testCases = testCases * args.copies

    if args.list:
        for test in testCases:
            print(test.id())

        os._exit(0)

    runPyTestSuite(config, None, testCases, testArgs)

    return testCapturePlugin.individualTestResults

def executeTests(args, filter_actions):
    if not args.list:
        print("Running python unit tests.")
        print("nose version: ", nose.__version__)
        print(time.ctime(time.time()))

    testResults = runPythonUnitTests(args, filter_actions)

    anyFailed = any([not x['success'] for x in testResults.values()])

    if args.write_summary_file:
        with open(args.write_summary_file,"w") as f:
            f.write(json.dumps(testResults))

    print("\n\n\n")

    if anyFailed:
        return 1
    return 0

def main(args):
    #parse args, return zero and exit if help string was printed
    parser = PythonTestArgumentParser()
    args, filter_actions = parser.parse_args(args[1:])

    try:
        return executeTests(args, filter_actions)
    except Exception:
        import traceback
        logging.error("executeTests() threw an exception: \n%s", traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main(sys.argv))
