#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
import traceback
import tempfile
import yaml
import time

from object_database.service_manager.ServiceManager import ServiceManager
from object_database import (
    connect,
    core_schema,
    service_schema
)
from object_database.util import formatTable
from typed_python.Codebase import Codebase as TypedPythonCodebase

import research_app
from research_app.ResearchFrontend import ResearchFrontend
from research_app.ResearchBackend import ResearchBackend

def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser("Redeploy code to the simulation")

    subparsers = parser.add_subparsers()

    info_parser = subparsers.add_parser('info', help='list current services')
    info_parser.set_defaults(command='info')

    redeploy_parser = subparsers.add_parser('redeploy', help='redeploy a set of specific services')
    redeploy_parser.set_defaults(command='redeploy')
    redeploy_parser.add_argument('--watch', action='store_true')

    parsedArgs = parser.parse_args(argv[1:])

    name = "Simulation"

    # add a fake deployment for 'Simulation'
    deploymentConfig = dict(
        name="Simulation",
        host="localhost",
        port=8887,
        token="fake_auth_token"
        )

    try:
        database = connect(deploymentConfig['host'], deploymentConfig['port'], deploymentConfig['token'])

        database.subscribeToSchema(core_schema, service_schema)

        if parsedArgs.command == "info":
            info(database, deploymentConfig)
        elif parsedArgs.command == "redeploy":
            redeploy(database, deploymentConfig, parsedArgs.watch)
        else:
            raise UserWarning(f"Unknown command {parsedArgs.command}")
    except UserWarning as e:
        print("ERROR: ", e)
        return 1

    return 0

def info(db, config):
    table = [['Service', 'Codebase', 'Module', 'Class', 'Placement', 'TargetCount', 'Cores', 'RAM']]

    with db.view():
        for s in sorted(service_schema.Service.lookupAll(), key=lambda s: s.name):
            table.append([
                s.name,
                str(s.codebase),
                s.service_module_name,
                s.service_class_name,
                s.placement,
                str(s.target_count),
                s.coresUsed,
                s.gbRamUsed
            ])

    print(formatTable(table))

def configureResearchFrontend(database, config):
    with database.transaction():
        frontend_svc = ServiceManager.createOrUpdateService(ResearchFrontend, "ResearchFrontend", placement="Master")
        ServiceManager.createOrUpdateService(ResearchBackend, "ResearchBackend", placement="Master")

def hashCurrentCodebase():
    return TypedPythonCodebase.FromRootlevelModule(research_app, ignoreCache=True).hash()

def redeploy(database, config, watch=False):
    if watch:
        curHash = None

        while True:
            time.sleep(0.25)

            if curHash != hashCurrentCodebase():
                print("Codebase changed to ", curHash, ". redeploying")
                try:
                    redeploy(database, config)
                except Exception:
                    print("ERROR: ")
                    traceback.print_exc()

                curHash = hashCurrentCodebase()

        return


    with database.transaction():
        ServiceManager.createOrUpdateService(ResearchFrontend, "ResearchFrontend", placement="Master")
        ServiceManager.createOrUpdateService(ResearchBackend, "ResearchBackend", placement="Master")

if __name__ == '__main__':
    sys.exit(main())
