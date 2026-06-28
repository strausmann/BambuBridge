"""Test bootstrap.

Point the bridge at throwaway config/DB paths *before* ``app.config`` is
imported (it binds the paths at import time), so the suite never touches a real
deployment's data/ directory.
"""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="bridge-test-")
os.environ["BRIDGE_CONFIG"] = os.path.join(_TMP, "config.yaml")
os.environ["BRIDGE_DB"] = os.path.join(_TMP, "state.db")
