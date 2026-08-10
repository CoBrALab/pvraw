#!/usr/bin/env python3
"""NIfTI-conversion sweep over every Bruker unit under resources/testdata.

For each discovered unit (full study dir, .zip/.PvDatasets archive, or
standalone exported scan dir) run get_niftiobj() on every (scan, reco) and
classify: ok / skip-nonimage (clean rejection) / FAIL (a real conversion bug).
Writes a JSON report and prints a per-unit summary with every failure's message.

Every converted image also records its *golden* values -- the affine at full
float64 precision, a sha256 of the stored data array, the shape/dtype, and the
NIfTI header fields -- so two reports can be diffed to prove a refactor changed
nothing. ``--compare <old.json>`` does that diff.
"""
import hashlib
import json
import logging
import sys
import traceback
import warnings
from pathlib import Path

import numpy as np

logging.disable(logging.CRITICAL)  # silence brkraw's own logging noise

from brkraw_legacy import BrukerLoader

_REPO = Path(__file__).resolve().parent.parent
def _parse_argv(argv):
    """``(positional, compare)`` accepting ``--compare=X`` and ``--compare X``.

    Both spellings, because only the first used to work: the space form left
    ``--compare`` dropped as an option and its VALUE standing as a positional, which
    made the baseline you asked to compare against the output path instead -- the
    tool overwrote the goldens it was meant to check. The docstring showed that form.
    """
    positional, compare, expecting = [], None, False
    for arg in argv:
        if expecting:
            compare, expecting = arg, False
        elif arg.startswith('--compare='):
            compare = arg.split('=', 1)[1]
        elif arg == '--compare':
            expecting = True
        elif not arg.startswith('--'):
            positional.append(arg)
    if expecting:
        raise SystemExit('--compare needs a path, e.g. --compare earlier.json')
    return positional, compare


_ARGV, _COMPARE = _parse_argv(sys.argv[1:])
TESTDATA = Path(_ARGV[0]) if _ARGV else _REPO / 'resources' / 'testdata'
OUT = Path(_ARGV[1] if len(_ARGV) > 1 else 'sweep_nifti_results.json')

EXCLUDE_PARTS = {'_sources', '_cache', '.git'}

#: NIfTI header fields recorded as goldens. Everything the conversion sets --
#: geometry codes, slice timing, scaling and the display window.
HEADER_FIELDS = ('scl_slope', 'scl_inter', 'slice_code', 'slice_start', 'slice_end',
                 'slice_duration', 'dim_info', 'qform_code', 'sform_code',
                 'xyzt_units', 'cal_min', 'cal_max', 'descrip', 'pixdim')


def _jsonable(value):
    """A JSON-serialisable form that round-trips float64 exactly."""
    if isinstance(value, np.ndarray):
        # header fields come back as 0-d arrays for scalars and as bytes_ for
        # text; .tolist() unwraps both, so recurse on the unwrapped value.
        return _jsonable(value.tolist()) if value.ndim == 0 else [_jsonable(v) for v in value.tolist()]
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        return value.rstrip(b'\x00').decode('latin-1')
    return value


def golden(nii):
    """Exact values pinning one converted image.

    ``dataobj`` is the array as stored (an in-memory Nifti1Image holds it
    verbatim), so the sha256 plus scl_slope/scl_inter fully determine the true
    voxel values without materialising a float copy of the whole volume.
    """
    data = np.asarray(nii.dataobj)
    header = nii.header
    return {
        'shape': list(nii.shape),
        'dtype': str(data.dtype),
        'affine': _jsonable(np.asarray(nii.affine, dtype=float)),
        'sha256': hashlib.sha256(np.ascontiguousarray(data).tobytes()).hexdigest(),
        'header': {f: _jsonable(header[f]) for f in HEADER_FIELDS},
    }


def excluded(p: Path) -> bool:
    # skip explicit dirs and any hidden file/dir (e.g. extraction markers)
    return any(part in EXCLUDE_PARTS or part.startswith('.') for part in p.parts
               if part not in ('.', '..'))


def discover(root: Path):
    """Return list of (label, path, kind)."""
    units = []
    # 1. archives brkraw reads directly
    for pat in ('*.zip', '*.PvDatasets'):
        for p in sorted(root.rglob(pat)):
            if p.is_file() and not excluded(p):
                units.append((str(p.relative_to(root)), p, 'archive'))
    # 2. full studies (a 'subject' file marks a study root)
    study_roots = set()
    for s in sorted(root.rglob('subject')):
        if s.is_file() and not excluded(s):
            study_roots.add(s.parent)
            units.append((str(s.parent.relative_to(root)), s.parent, 'study'))
    # 3. standalone exported scans: a dir with acqp whose ancestors hold no
    #    'subject' file (i.e. not part of a study) and that isn't excluded.
    for aq in sorted(root.rglob('acqp')):
        d = aq.parent
        if excluded(d):
            continue
        if any(str(d).startswith(str(sr) + '/') or d == sr for sr in study_roots):
            continue  # a scan inside a full study -- already covered
        # only treat as standalone if it's a bare scan dir (acqp at root)
        units.append((str(d.relative_to(root)), d, 'standalone'))
    return units


def convert_unit(path: Path):
    rec = {'loadable': True, 'is_pvdataset': None, 'error': None, 'scans': []}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            loader = BrukerLoader(str(path))
    except Exception as e:
        rec['loadable'] = False
        rec['error'] = f'{type(e).__name__}: {e}'
        return rec
    rec['is_pvdataset'] = bool(getattr(loader, 'is_pvdataset', False))
    if not rec['is_pvdataset']:
        return rec
    try:
        avail = dict(loader.avail_reco_id)
    except Exception as e:
        rec['error'] = f'avail_reco_id failed: {type(e).__name__}: {e}'
        return rec
    for sid in sorted(avail):
        for rid in avail[sid]:
            entry = {'scan': int(sid), 'reco': int(rid)}
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    obj = loader.get_niftiobj(sid, rid)
                objs = obj if isinstance(obj, list) else [obj]
                entry['status'] = 'ok'
                entry['n_images'] = len(objs)
                entry['shapes'] = [list(getattr(o, 'shape', ())) for o in objs]
                entry['goldens'] = [golden(o) for o in objs]
            except Exception as e:
                msg = f'{type(e).__name__}: {e}'
                if 'non-image data' in str(e):
                    entry['status'] = 'skip-nonimage'
                    entry['msg'] = str(e)[:200]
                else:
                    entry['status'] = 'FAIL'
                    entry['msg'] = msg[:400]
                    entry['tb'] = traceback.format_exc()[-1200:]
            rec['scans'].append(entry)
    return rec


def compare(old_path, report):
    """Print every golden that changed between a previous report and this one."""
    def index(rep):
        return {(r['label'], s['scan'], s['reco']): s
                for r in rep for s in r.get('scans', ())}

    def same(a, b):
        # NaN marks an unset header field (e.g. scl_slope); two unset fields are
        # the same field, but NaN != NaN, so compare them by repr.
        return a == b or repr(a) == repr(b)

    old, new = index(json.loads(Path(old_path).read_text())), index(report)
    changed = []
    for key in sorted(old.keys() | new.keys()):
        a, b = old.get(key), new.get(key)
        if a is None or b is None:
            changed.append((key, 'only in {}'.format('new' if a is None else 'old')))
        elif a['status'] != b['status']:
            changed.append((key, '{} -> {}'.format(a['status'], b['status'])))
        elif not same(a.get('goldens'), b.get('goldens')):
            for field in ('shape', 'dtype', 'affine', 'sha256', 'header'):
                av = [g.get(field) for g in a.get('goldens') or ()]
                bv = [g.get(field) for g in b.get('goldens') or ()]
                if not same(av, bv):
                    changed.append((key, f'{field}: {str(av)[:120]} -> {str(bv)[:120]}'))
    for key, what in changed:
        print(f'CHANGED {key[0][:50]} scan {key[1]} reco {key[2]}: {what}')
    print(f'\n==== COMPARE vs {old_path}: {len(changed)} differing entries ====')
    return changed


def main():
    units = discover(TESTDATA)
    print(f'Discovered {len(units)} units under {TESTDATA}\n')
    report = []
    for label, path, kind in units:
        rec = convert_unit(path)
        rec.update(label=label, path=str(path), kind=kind)
        report.append(rec)
        n_ok = sum(s['status'] == 'ok' for s in rec['scans'])
        n_skip = sum(s['status'] == 'skip-nonimage' for s in rec['scans'])
        n_fail = sum(s['status'] == 'FAIL' for s in rec['scans'])
        flag = 'FAIL' if (n_fail or not rec['loadable']) else 'ok  '
        note = ''
        if not rec['loadable']:
            note = ' LOAD-ERROR: ' + str(rec['error'])[:150]
        elif not rec['is_pvdataset']:
            note = ' (not a PvDataset)'
        print(f'[{flag}] {kind[:4]:<4} ok={n_ok:<3} skip={n_skip:<3} FAIL={n_fail:<3}  {label[:70]}{note}')
        for s in rec['scans']:
            if s['status'] == 'FAIL':
                print('        scan {} reco {}: {}'.format(s['scan'], s['reco'], s['msg']))
    OUT.write_text(json.dumps(report, indent=2))

    # aggregate
    tot_ok = sum(s['status'] == 'ok' for r in report for s in r['scans'])
    tot_skip = sum(s['status'] == 'skip-nonimage' for r in report for s in r['scans'])
    tot_fail = sum(s['status'] == 'FAIL' for r in report for s in r['scans'])
    load_err = [r for r in report if not r['loadable']]
    print(f'\n==== TOTAL: ok={tot_ok}  skip-nonimage={tot_skip}  FAIL={tot_fail}  load-errors={len(load_err)} ====')
    print(f'Report -> {OUT}')

    if _COMPARE:
        compare(_COMPARE, report)


if __name__ == '__main__':
    main()
