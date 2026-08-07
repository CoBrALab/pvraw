"""BIDS modality-agnostic tables: participants, scans and sessions.

Pure functions over parameter objects rather than over a loader, so a row can be
built -- and tested -- without a dataset on disk. The CLI collects rows while it
converts and writes the files at the end.

Absent values are written as ``n/a``, the BIDS convention, rather than omitted:
a column that disappears when one subject lacks a value would make the table
ragged across subjects.
"""
import datetime as dt
import re

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
    """A Bruker date/time string as a naive ``datetime``, or None.

    ParaVision writes two forms: a PV5.1 ``HH:MM:SS D Mon YYYY`` and an ISO
    ``YYYY-MM-DDThh:mm:ss`` optionally followed by ``,ffffff`` and a UTC offset.

    Naive on purpose. The scanner records wall-clock with no zone, so attaching one
    would shift the time -- the same reasoning as ``loader.get_scan_time``.
    """
    if value is None:
        return None
    text = str(value)
    iso = _ISO_DATETIME.match(text)
    if iso:
        return dt.datetime(*(int(g) for g in iso.groups()))  # noqa: DTZ001
    legacy = _LEGACY_DATETIME.match(text)
    if legacy:
        hour, minute, second, date_part = legacy.groups()
        day = _parse_date(date_part)
        if day is None:
            return None
        return dt.datetime.combine(day, dt.time(int(hour), int(minute), int(second)))
    return None


def _parse_date(value):
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
    born = _parse_date(get_value(subject, 'SUBJECT_dbirth'))
    scanned = parse_datetime(get_value(subject, 'SUBJECT_date')
                             or get_value(subject, 'SUBJECT_study_date'))
    if born is None or scanned is None:
        return None
    days = (scanned.date() - born).days
    return round(days / 365.25, 3) if days >= 0 else None


def is_non_human(subject):
    """True when ParaVision says the subject is not human.

    Worth knowing because BIDS assumes ``homo sapiens`` when `species` is absent,
    which is the wrong default for almost everything this converter is pointed at.
    """
    subject_type = get_value(subject, 'SUBJECT_type')
    if subject_type is None:
        return False
    # PV5.1: Human/Animal/Phantom/Other. PV6+: Biped/Quadruped/Phantom/Other/
    # OtherAnimal -- the enum identity changed between versions, so match by name.
    return str(subject_type).strip().lower() not in ('human', 'biped')


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


def write_tsv(path, columns, rows):
    """Write a BIDS TSV: tab separated, ``n/a`` for absence, newline terminated."""
    def cell(row, column):
        value = row.get(column)
        return NA if value is None else str(value)

    with open(path, 'w', newline='') as handle:
        handle.write('\t'.join(columns) + '\n')
        handle.writelines(
            '\t'.join(cell(row, c) for c in columns) + '\n' for row in rows)
