"""BIDS modality-agnostic tables: participants, scans and sessions.

Pure functions over parameter objects rather than over a loader, so a row can be
built -- and tested -- without a dataset on disk. The CLI collects rows while it
converts and writes the files at the end.

Absent values are written as ``n/a``, the BIDS convention, rather than omitted:
a column that disappears when one subject lacks a value would make the table
ragged across subjects.
"""
import csv
import datetime as dt
import os
import re

from .subject_orient import uses_quadruped_frame
from .utils import get_value

#: participants.tsv columns, in order.
PARTICIPANT_COLUMNS = ('participant_id', 'species', 'age', 'sex', 'weight')

#: What participants.json says about each of them. `weight` is not a BIDS-defined
#: column, so describing it is not optional politeness -- an undescribed
#: non-standard column is a validator warning.
PARTICIPANT_DESCRIPTIONS = {
    'species': {'Description': 'Binomial species name. Not recorded by ParaVision: '
                               'SUBJECT_type states a body plan (Biped/Quadruped/'
                               'Phantom), never a taxonomy. Fill this in yourself.'},
    'age': {'Description': 'Age of the subject at acquisition, derived from '
                           'SUBJECT_dbirth and the study date.',
            'Units': 'years'},
    'sex': {'Description': 'Phenotypical sex, from SUBJECT_sex_animal / '
                           'SUBJECT_sex_human / SUBJECT_gender.',
            'Levels': {'male': 'male', 'female': 'female'}},
    'weight': {'Description': 'Subject weight, from SUBJECT_weight. ParaVision uses '
                              '0.001 as its unset sentinel, which is read as absent.',
               'Units': 'kg'},
}

NA = 'n/a'

#: ParaVision's unset sentinel for SUBJECT_weight. A real 1 g subject is not a
#: thing this scanner images, so treating it as absent is safe.
_UNSET_WEIGHT_KG = 0.001

_SEX = {'male': 'male', 'm': 'male', 'female': 'female', 'f': 'female'}

_LEGACY_DATETIME = re.compile(r'(\d{2}):(\d{2}):(\d{2})\s+(\d+\s+\w+\s+\d{4})')
_ISO_DATETIME = re.compile(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})')
_DAY_MONTH_YEAR = re.compile(r'^\s*(\d+\s+\w+\s+\d{4})\s*$')


def parse_datetime(value):
    """A Bruker date/time as a naive ``datetime``, or None.

    ParaVision writes three forms: a PV5.1 ``HH:MM:SS D Mon YYYY`` string, an
    ISO ``YYYY-MM-DDThh:mm:ss`` string optionally followed by ``,fff`` and a UTC
    offset, and -- PV360's ``SUBJECT_study_date`` -- the ``pvtime_t`` struct
    ``(seconds, milliseconds, tzMinutes)`` (FILE_FORMAT.md section 2.2), which
    ``get_value`` returns as a one-row list.

    Naive on purpose. The scanner records wall-clock with no zone, so attaching one
    would shift the time -- the same reasoning as ``loader.get_scan_time``. The
    struct form carries its offset, which is applied so that the result is the
    same wall-clock the string forms give.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return _from_pvtime(value)
    text = str(value)
    iso = _ISO_DATETIME.match(text)
    if iso:
        return dt.datetime(*(int(g) for g in iso.groups()))  # noqa: DTZ001
    legacy = _LEGACY_DATETIME.match(text)
    if legacy:
        hour, minute, second, date_part = legacy.groups()
        day = parse_date(date_part)
        if day is None:
            return None
        return dt.datetime.combine(day, dt.time(int(hour), int(minute), int(second)))
    return None


def _from_pvtime(value):
    """A ``pvtime_t`` struct ``(seconds, milliseconds, tzMinutes)`` as the naive
    local wall-clock ``datetime``, or None for anything else."""
    rows = value.tolist() if hasattr(value, 'tolist') else value
    if isinstance(rows, (list, tuple)) and len(rows) == 1 and isinstance(rows[0], (list, tuple)):
        rows = rows[0]
    if not isinstance(rows, (list, tuple)) or len(rows) != 3:
        return None
    try:
        seconds, _millis, tz_minutes = (int(v) for v in rows)
    except (TypeError, ValueError):
        return None
    stamp = dt.datetime.fromtimestamp(seconds, dt.UTC) + dt.timedelta(minutes=tz_minutes)
    return stamp.replace(tzinfo=None)


def parse_date(value):
    """A bare ``D Mon YYYY`` date, or None. Used for SUBJECT_dbirth."""
    if value is None:
        return None
    match = _DAY_MONTH_YEAR.match(str(value))
    if not match:
        return None
    try:
        # The month name is ParaVision's own English abbreviation, not the locale's.
        return dt.datetime.strptime(match.group(1), '%d %b %Y').date()  # noqa: DTZ007
    except ValueError:
        return None


def acq_time(visu_pars):
    """A scan's acquisition time as a BIDS ``datetime``, or None.

    ``VisuAcqDate`` is when the acquisition started, which is what BIDS asks for --
    not ``VisuCreationDate`` (when the reconstruction was written) and not
    ``get_scan_time``'s ``scan_time``, which adds the duration and so is the end.

    No sub-second part and no UTC offset: both are optional in the BIDS format and
    Bruker's zone would be a guess.
    """
    stamp = parse_datetime(get_value(visu_pars, 'VisuAcqDate'))
    return stamp.strftime('%Y-%m-%dT%H:%M:%S') if stamp else None


def session_date(subject):
    """The study date/time as a BIDS ``datetime``, or None."""
    stamp = parse_datetime(get_value(subject, 'SUBJECT_date')
                           or get_value(subject, 'SUBJECT_study_date'))
    return stamp.strftime('%Y-%m-%dT%H:%M:%S') if stamp else None


def sex(subject):
    """Phenotypical sex as BIDS spells it, or None.

    ParaVision states it three different ways depending on version and subject
    type, and its 'UNDEFINED'/'UNKNOWN' are absence rather than a third value.
    """
    for key in ('SUBJECT_sex_animal', 'SUBJECT_sex_human', 'SUBJECT_gender', 'SUBJECT_sex'):
        value = get_value(subject, key)
        if value is not None:
            resolved = _SEX.get(str(value).strip().lower())
            if resolved:
                return resolved
    return None


def weight_kg(subject):
    """Subject weight in kg, or None. PV360 renames the parameter."""
    for key in ('SUBJECT_weight', 'SUBJECT_study_weight'):
        value = get_value(subject, key)
        if isinstance(value, (int, float)) and value > _UNSET_WEIGHT_KG:
            return float(value)
    return None


def age_years(subject):
    """Age at acquisition in years, or None.

    Derived, never read: ParaVision records a date of birth, and BIDS has no column
    for one. Emitting the birth date would be both non-conforming and careless --
    the age is the fact worth keeping, the birth date is only its source.
    """
    born = parse_date(get_value(subject, 'SUBJECT_dbirth'))
    scanned = parse_datetime(get_value(subject, 'SUBJECT_date')
                             or get_value(subject, 'SUBJECT_study_date'))
    if born is None or scanned is None:
        return None
    days = (scanned.date() - born).days
    return round(days / 365.25, 3) if days >= 0 else None


def is_non_human(visu_pars):
    """True when the subject is not in the primate frame, i.e. cannot be human.

    Worth knowing because BIDS assumes ``homo sapiens`` when `species` is absent,
    which is the wrong default for nearly everything this converter is pointed at.

    The subject frame is where that information lives -- ParaVision's coordinate
    system is chosen per specimen (PV6.0.1 manual S1.3.6: Rodent for quadrupeds,
    Primate for bipeds, Material for phantoms) -- so the taxon falls out of the
    orientation the scan was acquired in.

    Read per scan from ``VisuSubjectType`` and resolved by ``uses_quadruped_frame``,
    the same rule the affine uses, rather than from the study ``subject`` file.
    That distinction is not pedantic: PV5.1 cannot express a subject type and
    writes ``SUBJECT_type=Human`` for every study regardless of specimen, so
    trusting it would report human for the rodent data that makes up most of PV5.1.
    ``uses_quadruped_frame`` already treats an absent type as rodent, a rule
    validated against paired PV5.1/PV6 acquisitions of one phantom.

    A True answer is definite -- a quadruped is not homo sapiens. A False answer
    only narrows it to a primate, so it still yields no binomial name.
    """
    return uses_quadruped_frame(get_value(visu_pars, 'VisuSubjectType'))


def participant_row(subject, participant_id):
    """One participants.tsv row.

    `species` is always ``n/a``: no Bruker parameter carries a binomial name, and
    SUBJECT_type is a body plan. It is written rather than omitted on purpose --
    BIDS reads an *absent* species column as ``homo sapiens``, so leaving it out
    would make every animal dataset silently claim to be human. ``n/a`` at least
    says "not stated"; the caller warns as well.
    """
    return {
        'participant_id': participant_id,
        'species': NA,
        'age': age_years(subject),
        'sex': sex(subject),
        'weight': weight_kg(subject),
    }


def merge_participants(path, rows):
    """`rows` merged into any participants.tsv already at `path`, new rows winning.

    participants.tsv is the one table that spans conversions: every other table lives
    inside a subject directory, so re-converting a subject rewrites only its own.
    Converting a second study into an existing dataset must therefore ADD to this
    file, not replace it -- overwriting leaves a `sub-` directory with no row, which
    is a PARTICIPANT_ID_MISMATCH error rather than a warning.

    Keyed on participant_id so re-converting the same subject updates its row in
    place rather than duplicating it.
    """
    merged = {}
    if os.path.exists(path):
        with open(path, newline='') as handle:
            reader = csv.DictReader(handle, delimiter='\t')
            for row in reader:
                key = row.get('participant_id')
                if key:
                    merged[key] = {k: (None if v == NA else v) for k, v in row.items()}
    for row in rows:
        merged[row['participant_id']] = row
    write_tsv(path, PARTICIPANT_COLUMNS, list(merged.values()))


def write_tsv(path, columns, rows):
    """Write a BIDS TSV: tab separated, ``n/a`` for absence, newline terminated."""
    def cell(row, column):
        value = row.get(column)
        return NA if value is None else str(value)

    with open(path, 'w', newline='') as handle:
        handle.write('\t'.join(columns) + '\n')
        handle.writelines(
            '\t'.join(cell(row, c) for c in columns) + '\n' for row in rows)
