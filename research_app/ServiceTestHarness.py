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

from object_database import ServiceBase, service_schema, TcpServer
from object_database.service_manager.SubprocessServiceManager import SubprocessServiceManager
from object_database.service_manager.Task import TaskService, TaskDispatchService
from object_database.util import sslContextFromCertPathOrNone
from object_database.web.ActiveWebService import ActiveWebService
from object_database.web.LoginPlugin import LoginIpPlugin, User

from typed_python.Codebase import Codebase as TypedPythonCodebase

from research_app.ResearchFrontendTestHelper import ResearchFrontendTestHelper
import research_app
import logging
import object_database
import os
import random
import requests
import tempfile
import time
import traceback

class ServiceTestHarness:
    """Class to set up a complete simulation of the all research_app services so we can test them."""
    def __init__(self, port=None):
        self._logger = logging.getLogger(__name__)
        self._port_num = port
        self._auth_token = "fake_auth_token"
        self._tempDirObj = tempfile.TemporaryDirectory()
        self._cleanupFns = []

        self.startObjectDB()

        self.serviceManager = SubprocessServiceManager(
            "localhost", "localhost", self._port_num,
            os.path.join(self.tempDir, "code"),
            os.path.join(self.tempDir, "storage"),
            self._auth_token,
            isMaster=True, shutdownTimeout=.25,
            maxGbRam=128, # our simulated services don't actually use this much, but we need to reserve
            maxCores=16   # enough to be able to do the simulation.
        )
        self.serializationContext = TypedPythonCodebase.FromRootlevelModule(research_app).serializationContext

        self.serviceManager.start()
        self.db = self.connect()
        self.db.subscribeToSchema(service_schema)
        self.db.setSerializationContext(self.serializationContext)

        self.researchFrontendHelper = ResearchFrontendTestHelper(self)
        self.webServiceHelper = WebServiceHelper(self)

    def startObjectDB(self):
        if self._port_num is None:
            maxRetries = 3
            # 8887 and 2 random ports in 8850 - 8899
            portsToTry = [
                8887,
                random.randint(8850, 8886),
                random.randint(8888, 8899)
            ]
        else:
            maxRetries = 1
            portsToTry = [self._port_num]

        assert len(portsToTry) == maxRetries
        retries = 0
        while True:
            self._port_num = portsToTry[retries]
            try:
                self.dbServer = TcpServer(
                    "localhost", self._port_num, None,
                    sslContextFromCertPathOrNone(None), self._auth_token
                )
                self.dbServer.start()
                break
            except Exception as e:
                if retries < maxRetries:
                    retries += 1
                    self._logger.info(
                        f"Encountered Exception '{e}' while trying to start ObjectDB")
                else:
                    raise

    def registerCleanupFunction(self, function, typestr):
        self._cleanupFns.append((function, typestr))

    def shutdown(self):
        self._logger.info("Shutting down")

        for func, typestr in self._cleanupFns:
            try:
                func()
            except Exception:
                self._logger.error(
                    f"Failed to cleanup {typestr}:\n{traceback.format_exc()}"
                )
        self.serviceManager.stop()
        self.dbServer.stop()
        self._tempDirObj.cleanup()

    @property
    def sourceDir(self):
        return os.path.join(self.tempDir, "source")

    @property
    def tempDir(self):
        return self._tempDirObj.name

    def connect(self):
        return self.dbServer.connect(self._auth_token)

    def unlockAllServices(self):
        with self.db.transaction():
            for service in service_schema.Service.lookupAll():
                service.unlock()

class WebServiceHelper:
    def __init__(self, service_test_base ):
        self._base = service_test_base
        self._logger = logging.getLogger(__name__)
        self._host = None
        self._port = None
        self._base_url = None

    @property
    def host(self):
        return self._host

    @property
    def port(self):
        return self._port

    @property
    def base_url(self):
        return self._base_url

    def createWebService(self,
                         port=8000,
                         host='0.0.0.0',
                         timeout=4.0,
                         auth_plugins=(None, ),
                         module=None,
                         sso_pubkey=None):

        module = module or research_app

        if self._host is not None:
            raise Exception(
                "WebServiceHelper already created. Cannot create a second one."
            )

        self._host = host
        self._port = port
        self._base_url = f"http://{self._host}:{self._port}"
        self._logger.info(f"Creating an Active Web Service Helper at {self._base_url}")

        db = self._base.db
        serviceManager = self._base.serviceManager

        with db.transaction():
            self.webService = serviceManager.createOrUpdateService(ActiveWebService, "ActiveWebService", 0)

        ActiveWebService.configure(db, self.webService, host, port)

        ActiveWebService.setLoginPlugin(
            db,
            self.webService,
            LoginIpPlugin,
            [None],
            codebase=None,
            config=dict(company_name="Testing Company")
        )

        with db.transaction():
            serviceManager.startService("ActiveWebService", 1)

        assert serviceManager.waitRunning(db, "ActiveWebService", timeout=10)
        self.waitUntilUp(timeout=timeout)

    def waitUntilUp(self, timeout = 4.0):
        t0 = time.time()

        while True:
            try:
                requests.get(self.base_url + "/status")
                return
            except Exception as e:
                if time.time() - t0 < timeout:
                    time.sleep(.5)
                else:
                    raise Exception(
                        f"ActiveWebservice failed to come up after {timeout} seconds with " +
                        f"error: {repr(e)}"
                    )
