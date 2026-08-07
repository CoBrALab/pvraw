"""Parameter-value resolution (lib.utils.get_value / unquote).

Pure-unit (offline). `brukerapi` 0.4.3 types JCAMP-DX values itself: a bare
numeric literal comes back as an int or a float, a delimited ``<...>`` string
comes back as a str without its delimiters
(isi-nmr/brukerapi-python#176). So what is left here is absence, not typing.

Re-typing on top of that was actively wrong. A subject or study identifier is a
string whose leading zeros are part of it, and coercing ``'01'`` to ``1`` wrote
``ses-1`` for a session ParaVision had called ``01`` -- six studies in
``resources/testdata`` are affected.
"""
import numpy as np
import pytest

from brkraw_legacy.lib.utils import get_value, unquote


class _Params(dict):
    def get_parameter(self, key):
        return _Value(self[key])


class _Value:
    def __init__(self, value):
        self.value = value
        self.val_str = str(value)
        self.nested = value


@pytest.mark.parametrize('value', ['01', '02', '0042', '4007', '0'])
def test_identifier_strings_keep_their_digits(value):
    """A numeric-looking string is a string. Coercing it dropped leading zeros
    from identifiers that BIDS turns into `sub-`/`ses-` directory names."""
    assert unquote(value) == value


def test_numbers_are_left_as_brukerapi_typed_them():
    """Bare numeric literals arrive already typed; nothing to do."""
    assert unquote(2) == 2
    assert unquote(1.5) == pytest.approx(1.5)
    assert isinstance(unquote(2), int)


def test_empty_reads_as_absent():
    """`<>` and a parameter written with no value are absence, not ''."""
    assert unquote('') is None


def test_containers_are_resolved_element_wise():
    """Lists, tuples and object arrays carry the same rule to their elements."""
    assert unquote(['01', '', 'name']) == ['01', None, 'name']
    assert unquote(('01', 2)) == ('01', 2)
    resolved = unquote(np.array(['01', ''], dtype=object))
    assert list(resolved) == ['01', None]


def test_numeric_arrays_pass_through_untouched():
    """A numeric array is already typed; it must not be rebuilt as objects."""
    array = np.array([1.0, 2.0])
    assert unquote(array) is array


def test_get_value_defaults_an_absent_key():
    """Which parameters exist is ParaVision-version dependent, so an unguarded
    read must not raise."""
    parameters = _Params({'SUBJECT_id': '01'})
    assert get_value(parameters, 'SUBJECT_id') == '01'
    assert get_value(parameters, 'SUBJECT_missing') is None
    assert get_value(parameters, 'SUBJECT_missing', 'fallback') == 'fallback'
    assert get_value(None, 'SUBJECT_id') is None
