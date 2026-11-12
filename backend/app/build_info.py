"""Version and build identifier of the running build.

Both values come from the environment at image build time; local runs report a
development placeholder.
"""

from __future__ import annotations

import os
from typing import Final

VERSION: Final[str] = os.environ.get("BAMBUBRIDGE_BUILD_VERSION", "0.0.0-dev")
BUILD_ID: Final[str] = os.environ.get("BAMBUBRIDGE_BUILD_ID", "dev")
