"""Schema-driven BIDS path construction and sidecar value checking.

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
from jsonschema import Draft202012Validator, FormatChecker

from .errors import InvalidApproach

_SCHEMA = _bst_schema.load_schema()

#: BIDS version of the loaded schema.  The single source for the ``BIDSVersion`` we
#: write and for the schema tag we validate against, so a dataset can never claim one
#: version while being checked against another.  Bumping ``bidsschematools`` in
#: ``uv.lock`` is what moves this -- there is no literal to forget.
BIDS_VERSION = _SCHEMA.bids_version

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


# --------------------------------------------------------------------------- #
# Fieldmap pairing
# --------------------------------------------------------------------------- #

#: Suffixes whose images are distorted by B0 inhomogeneity, so a fieldmap can
#: correct them. Anatomical scans are not in the list: they are not EPI readouts,
#: and naming one here would claim a correction nobody applies.
CORRECTABLE_SUFFIXES = ('bold', 'sbref', 'dwi', 'asl')

#: Fieldmap suffixes. `epi` is both -- a reversed-PE spin-echo IS the fieldmap --
#: so it is listed here and deliberately not above.
FIELDMAP_SUFFIXES = ('fieldmap', 'phasediff', 'phase1', 'phase2', 'epi')


def suffix_of(filename):
    """The BIDS suffix of a filename, or None."""
    stem = str(filename).split('/')[-1].split('.')[0]
    return stem.rsplit('_', 1)[-1] if '_' in stem else None


def pair_fieldmaps(rows):
    """Map each fieldmap onto the images it plausibly corrects.

    ``rows`` are ``{'filename', 'acq_time'}`` dicts for one subject/session, i.e.
    what ``_scans.tsv`` already collects.

    The rule is: a fieldmap corrects the correctable images acquired AFTER it and
    before the next fieldmap. Claiming every image in the session instead is wrong
    the moment a session has two fieldmaps, which is the normal case -- and on the
    PV6 corpus study it would wrongly claim three dwi runs acquired an hour BEFORE
    the fieldmap was measured.

    This is inference about intent, not something Bruker records. Nothing in the
    file says which images a fieldmap was meant for, so callers must let the user
    override it.

    A row carrying a ``b0group`` label overrides all of that: rows sharing a label
    are paired with each other and acquisition order is not consulted. That is the
    datasheet's say, and it wins because the operator knows what the fieldmap was
    for and the clock does not.

    Returns ``{fieldmap filename: [target filename, ...]}``, fieldmaps with no
    targets included, so a caller can report them.
    """
    if any(r.get('b0group') for r in rows):
        return _pair_by_label(rows)
    return _pair_by_time(rows)


def _pair_by_label(rows):
    pairs = {}
    for label in {r.get('b0group') for r in rows if r.get('b0group')}:
        group = [r for r in rows if r.get('b0group') == label]
        maps = [r['filename'] for r in group if suffix_of(r['filename']) in FIELDMAP_SUFFIXES]
        targets = [r['filename'] for r in group
                   if suffix_of(r['filename']) in CORRECTABLE_SUFFIXES]
        for fieldmap in maps:
            pairs[fieldmap] = list(targets)
    return pairs


def _pair_by_time(rows):
    ordered = sorted((r for r in rows if r.get('acq_time')),
                     key=lambda r: (r['acq_time'], r['filename']))
    pairs = {}
    current = None
    for row in ordered:
        suffix = suffix_of(row['filename'])
        if suffix in FIELDMAP_SUFFIXES:
            current = row['filename']
            pairs.setdefault(current, [])
        elif suffix in CORRECTABLE_SUFFIXES and current is not None:
            pairs[current].append(row['filename'])
    return pairs


# --------------------------------------------------------------------------- #
# Sidecar value checking
#
# Which fields a sidecar must carry is decided by ``rules/sidecars``, whose
# selectors are a small expression language that ``bidsschematools`` can parse but
# not evaluate -- only the reference validator has an evaluator. So field
# *inventory* stays the validator's job, and what is checked here is field
# *values*, which needs no selectors: every ``objects/metadata`` entry is already
# valid JSON Schema, and the reference validator feeds it to Ajv verbatim.
# --------------------------------------------------------------------------- #

def _build_format_checker():
    """A ``FormatChecker`` carrying the schema's own ``format`` patterns.

    ``objects/formats`` entries are plain regexes that metadata definitions refer to
    by name (``Units`` is ``format: unit``, ``IntendedFor`` is
    ``format: participant_relative``). jsonschema ignores a format it does not know,
    so without registering these every ``format`` constraint would silently pass.
    """
    checker = FormatChecker()
    for name in _SCHEMA.objects.formats:
        pattern = _SCHEMA.objects.formats[name].get('pattern')
        if not pattern:
            continue
        matcher = re.compile(f'^(?:{pattern})$')
        # A format applies to strings only; anything else is the `type` rule's business.
        checker.checks(name)(
            lambda value, _m=matcher: not isinstance(value, str) or bool(_m.match(value)))
    return checker


_FORMAT_CHECKER = _build_format_checker()


def value_problem(field, value):
    """The first BIDS schema violation of ``value`` for ``field``, else ``None``.

    Also ``None`` for a name the schema does not define. A sidecar may legitimately
    carry non-BIDS keys, and deciding about those belongs to whoever put them there
    (see the deliberate ones marked in ``lib/reference.py``) -- not to a check whose
    only source of truth is the schema.
    """
    definition = _SCHEMA.objects.metadata.get(field)
    if definition is None:
        return None
    errors = sorted(
        Draft202012Validator(definition, format_checker=_FORMAT_CHECKER).iter_errors(value),
        key=str)
    return errors[0].message if errors else None
