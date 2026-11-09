"""Preview entry shim: re-exec the project virtualenv interpreter for launch.py."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_PY = HERE.parent / ".venv" / "bin" / "python"
TARGET = HERE / "launch.py"

if sys.executable != str(VENV_PY) and VENV_PY.exists():
    os.execv(str(VENV_PY), [str(VENV_PY), str(TARGET), *sys.argv[1:]])

from launch import main  # noqa: E402

main()
