"""The preparation module must stay importable without the Lean runtime."""

import os
import subprocess
import sys


def test_quantconnect_import_without_lean_and_version():
    subprocess.run(
        [sys.executable, "-c", """
import importlib.abc
import sys

class NoLean(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'QuantConnect', 'AlgorithmImports'}:
            raise AssertionError('Importing the preparation module requested Lean')

sys.meta_path.insert(0, NoLean())
import arkleon
import arkleon.quantconnect as qc
assert arkleon.__version__ == '0.1.6'
assert callable(qc.prepare_snapshot)
assert callable(qc.visible_as_filed)
assert 'arkleon.quantconnect.data' not in sys.modules
"""],
        check=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True,
    )
