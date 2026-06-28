"""Test bootstrap.

Point the bridge at throwaway config/DB paths *before* ``app.config`` is
imported (it binds the paths at import time), so the suite never touches a real
deployment's data/ directory.
"""
import atexit
import os
import shutil
import tempfile

_TMP = tempfile.mkdtemp(prefix="bridge-test-")
os.environ["BRIDGE_CONFIG"] = os.path.join(_TMP, "config.yaml")
os.environ["BRIDGE_DB"] = os.path.join(_TMP, "state.db")

# Remove the throwaway directory when the test process exits.
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))
