"""Schema-driven BIDS path and suffix construction.

This module replaces the hand-rolled filename/entity-ordering logic that used to
live in ``brkraw_legacy.scripts.brkraw_legacy``.  Filenames are assembled from the authoritative
BIDS schema (``bidsschematools``, the schema engine that ships with PyBIDS) so that
entity ordering, allowed suffixes per datatype, and label validity always track the
specification rather than a frozen copy of it.

Why ``bidsschematools`` instead of ``pybids.layout.writing.build_path``: PyBIDS'
bundled ``default_path_patterns`` lag the schema (e.g. they reject the valid
``_magnitude`` fieldmap suffix, only allowing ``magnitude1``/``magnitude2``).  The
schema is the source of truth used by the reference ``bids-validator``.
"""
import re

from bidsschematools import schema as _bst_schema

from .errors import InvalidApproach

_SCHEMA = _bst_schema.load_schema()

#: BIDS entity *long* names in canonical filename order (e.g. ``acquisition``).
ENTITY_ORDER = list(_SCHEMA.rules.entities)

#: Map of long entity name -> short key used in filenames (e.g. ``acquisition`` -> ``acq``).
ENTITY_KEY = {name: ent.name for name, ent in _SCHEMA.objects.entities.items()}

#: Datasheet column name -> BIDS long entity name.
COLUMN_TO_ENTITY = {
    'task': 'task',
    'acq': 'acquisition',
    'ce': 'ceagent',
    'rec': 'reconstruction',
    'dir': 'direction',
    'run': 'run',
    'inv': 'inversion',
    'flip': 'flip',
    'mt': 'mtransfer',
    'part': 'part',
    'echo': 'echo',
}

#: Datatypes BrkRaw-legacy emits into the validated BIDS tree.
DATATYPES = ('anat', 'func', 'dwi', 'fmap')

_LABEL_RE = re.compile(r'^[0-9a-zA-Z]+$')


def suffixes_for(datatype):
    """Return the set of valid BIDS suffixes for a raw ``datatype``."""
    out = set()
    group = _SCHEMA.rules.files.raw.get(datatype, {})
    for rule in group.values():
        out.update(rule.get('suffixes', []))
    return out


def default_suffix(datatype, method):
    """Best-guess BIDS suffix for a scan when the datasheet leaves ``modality`` blank.

    Returns ``None`` when no valid BIDS suffix can be inferred; the caller is then
    responsible for routing the scan out of the validated tree (e.g. ``.bidsignore``)
    rather than emitting an invalid suffix derived from the Bruker method string.
    """
    if datatype == 'func':
        return 'bold'
    if datatype == 'dwi':
        return 'dwi'
    if datatype == 'anat':
        if re.search('flash', method, re.IGNORECASE):
            return 'FLASH'
        if re.search('rare', method, re.IGNORECASE):
            return 'T2w'
        if re.search('msme', method, re.IGNORECASE):
            return 'MESE'
    return None


def validate_suffix(datatype, suffix):
    """Raise ``InvalidApproach`` unless ``suffix`` is valid for ``datatype``."""
    if datatype not in DATATYPES:
        raise InvalidApproach(
            f"'{datatype}' is not a BIDS datatype handled by BrkRaw-legacy {DATATYPES}.")
    valid = suffixes_for(datatype)
    if suffix not in valid:
        raise InvalidApproach(
            f"'{suffix}' is not a valid BIDS suffix for datatype '{datatype}'. "
            f"Valid suffixes: {sorted(valid)}.")
    return True


def build_stem(entities, suffix):
    """Assemble a BIDS filename stem (no extension) in canonical entity order.

    ``entities`` maps long entity names (e.g. ``subject``, ``acquisition``) to values;
    ``None``/empty values are skipped.  Ordering follows the BIDS schema, which fixes
    the long-standing bug where ``dir`` was emitted before ``rec``.
    """
    parts = []
    for name in ENTITY_ORDER:
        val = entities.get(name)
        if val is None or val == '':
            continue
        parts.append(f'{ENTITY_KEY[name]}-{val}')
    parts.append(suffix)
    return '_'.join(parts)


def build_prefix(entities, datatype):
    """Return ``(relative_dir, prefix)`` excluding ``run``/``echo``/suffix.

    BrkRaw-legacy appends ``_run-XX``, ``_echo-X`` and the suffix downstream (run indices are
    resolved only after conflict detection, echoes only while splitting multi-echo
    volumes).  This returns everything up to but not including those, in canonical
    schema order, so the later appends land in the spec-correct positions.
    """
    trimmed = {k: v for k, v in entities.items() if k not in ('run', 'echo')}
    subject = trimmed.get('subject')
    session = trimmed.get('session')
    if not subject:
        raise InvalidApproach('A subject label is required to build a BIDS path.')

    parts = []
    for name in ENTITY_ORDER:
        if name in ('run', 'echo'):
            continue
        val = trimmed.get(name)
        if val is None or val == '':
            continue
        parts.append(f'{ENTITY_KEY[name]}-{val}')

    rel_parts = [f'sub-{subject}']
    if session:
        rel_parts.append(f'ses-{session}')
    rel_parts.append(datatype)
    return '/'.join(rel_parts), '_'.join(parts)


def build_path(entities, datatype, suffix, validate=True):
    """Return ``(relative_dir, stem)`` for a scan.

    ``relative_dir`` is the datatype directory relative to the dataset root
    (``sub-XX[/ses-YY]/<datatype>``); ``stem`` is the filename without extension.
    """
    if validate:
        validate_suffix(datatype, suffix)
    subject = entities.get('subject')
    session = entities.get('session')
    if not subject:
        raise InvalidApproach('A subject label is required to build a BIDS path.')

    rel_parts = [f'sub-{subject}']
    if session:
        rel_parts.append(f'ses-{session}')
    rel_parts.append(datatype)
    rel_dir = '/'.join(rel_parts)
    return rel_dir, build_stem(entities, suffix)


def is_valid_label(value):
    """True when ``value`` is a valid BIDS entity label/index (alphanumeric only)."""
    return bool(_LABEL_RE.match(str(value)))
