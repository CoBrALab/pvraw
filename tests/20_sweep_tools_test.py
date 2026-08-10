"""Unit tests for the sweep tools' argument handling (tools/).

Pure-unit (offline). The tools themselves need a corpus, but their argument parsing
does not, and that is where the damage was: the documented ``--compare <file>`` form
made the tool overwrite the baseline it was asked to compare against.
"""
import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parent.parent / 'tools'


def _parse_argv():
    """`_parse_argv` from sweep_nifti.py, without running the sweep.

    The module does its work at import time against a corpus, so the function is
    lifted out rather than imported.
    """
    source = (_TOOLS / 'sweep_nifti.py').read_text()
    start = source.index('def _parse_argv')
    end = source.index('_ARGV, _COMPARE')
    namespace = {'sys': sys}
    exec(compile(source[start:end], 'sweep_nifti.py', 'exec'), namespace)  # noqa: S102
    return namespace['_parse_argv']


@pytest.mark.parametrize(('argv', 'positional', 'compare'), [
    (['/corpus', '--compare', 'old.json'], ['/corpus'], 'old.json'),
    (['/corpus', '--compare=old.json'], ['/corpus'], 'old.json'),
    (['--compare', 'old.json'], [], 'old.json'),
    (['--compare=old.json', '/corpus'], ['/corpus'], 'old.json'),
])
def test_compare_accepts_both_spellings(argv, positional, compare):
    """Both forms must work, and the value must never land in `positional`.

    It used to: `--compare` was dropped as an option and its value stood as the
    second positional, which is the OUTPUT path -- so following the tool's own
    docstring overwrote the goldens it was meant to check against.
    """
    assert _parse_argv()(argv) == (positional, compare)


@pytest.mark.parametrize(('argv', 'positional'), [
    (['/corpus'], ['/corpus']),
    (['/corpus', 'out.json'], ['/corpus', 'out.json']),
    ([], []),
])
def test_positional_arguments_are_unchanged_without_compare(argv, positional):
    assert _parse_argv()(argv) == (positional, None)


def test_compare_without_a_path_is_an_error_not_a_silent_no_op():
    with pytest.raises(SystemExit, match='--compare needs a path'):
        _parse_argv()(['/corpus', '--compare'])
