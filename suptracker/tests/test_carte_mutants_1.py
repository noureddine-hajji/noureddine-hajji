"""Carte red team C8 (mutation test) on the real warehouse, part 1/3: a file of its own so the CI shards spread the parts."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_carte as T  # noqa: E402


@pytest.mark.skipif(not T.REAL_OK, reason="real warehouse not available")
def test_real_mutants_part_1():
    T.real_mutants(1)
