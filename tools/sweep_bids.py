#!/usr/bin/env python3
"""BIDS-conversion sweep: run the real bids_helper -> bids_convert pipeline on
every study/archive unit and capture crashes + validator errors.

Mirrors tests/06_bids_test.py's approach (symlink the study into a throwaway
parent) but uses the *auto-generated* bids_helper sheet -- i.e. exercises the
real auto-classification + conversion path end to end, no manual sheet edits.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from brkraw_legacy.lib.bids import BIDS_VERSION

_REPO = Path(__file__).resolve().parent.parent
TESTDATA = Path(sys.argv[1]) if len(sys.argv) > 1 else _REPO / 'resources' / 'testdata'
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else 'sweep_bids_results.json')
VALIDATOR = shutil.which('bids-validator-deno') or \
    str(_REPO / '.venv' / 'bin' / 'bids-validator-deno')
EXCLUDE = {'_sources', '_cache', '.git'}


def excluded(p):
    return any(part in EXCLUDE or part.startswith('.') for part in p.parts)


def discover(root):
    units = []
    for pat in ('*.zip', '*.PvDatasets'):
        for p in sorted(root.rglob(pat)):
            if p.is_file() and not excluded(p):
                units.append((str(p.relative_to(root)), p, 'archive'))
    for s in sorted(root.rglob('subject')):
        if s.is_file() and not excluded(s):
            units.append((str(s.parent.relative_to(root)), s.parent, 'study'))
    return units


def run(cmd, timeout):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, (p.stdout or '')[-1500:], (p.stderr or '')[-2500:]
    except subprocess.TimeoutExpired:
        return 'timeout', '', f'TIMEOUT after {timeout}s'


def sweep_unit(label, path, kind):
    rec = {'label': label, 'kind': kind, 'helper_rc': None, 'convert_rc': None,
           'n_nii': 0, 'n_json': 0, 'validator_errors': None, 'error': None}
    tmp = Path(tempfile.mkdtemp(prefix='bidssweep_'))
    try:
        parent = tmp / 'sample'
        parent.mkdir()
        (parent / path.name).symlink_to(path.resolve())
        sheet = tmp / 'map'
        out = tmp / 'raw'
        rc, _so, se = run(['brkraw-legacy', 'bids_helper', str(parent), str(sheet), '-j'], 240)
        rec['helper_rc'] = rc
        if rc != 0:
            rec['error'] = 'bids_helper failed: ' + se[-400:]
            return rec
        csv = Path(str(sheet) + '.csv')
        if not csv.exists():
            rec['error'] = 'no sheet produced'
            return rec
        rc, _so, se = run(['brkraw-legacy', 'bids_convert', str(parent),
                           str(sheet) + '.csv', '-j', str(sheet) + '.json',
                           '--output', str(out)], 600)
        rec['convert_rc'] = rc
        if rc != 0:
            rec['error'] = 'bids_convert failed: ' + se[-600:]
            return rec
        niis = list(out.rglob('*.nii.gz'))
        rec['n_nii'] = len(niis)
        rec['n_json'] = len(list(out.rglob('*.json')))
        if niis and Path(VALIDATOR).exists():
            vjson = tmp / 'validation.json'
            _vrc, vso, _vse = run([VALIDATOR, str(out), '--schema', f'v{BIDS_VERSION}',
                                   '--format', 'json', '--outfile', str(vjson)], 240)
            try:
                report = json.loads(vjson.read_text() if vjson.exists() else (vso or '{}'))
                issues = report.get('issues', {})
                items = issues.get('issues', issues) if isinstance(issues, dict) else issues
                errs = [it for it in (items or []) if it.get('severity') == 'error']
                rec['validator_errors'] = [(e.get('code'), e.get('subCode')) for e in errs]
            except Exception as e:
                rec['validator_errors'] = f'parse-failed: {e}'
    except Exception as e:
        rec['error'] = f'{type(e).__name__}: {e}'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return rec


def main():
    units = discover(TESTDATA)
    print(f'BIDS sweep over {len(units)} study/archive units\n', flush=True)
    report = []
    for label, path, kind in units:
        rec = sweep_unit(label, path, kind)
        report.append(rec)
        bad = rec['error'] or (rec['validator_errors'] not in (None, []))
        flag = 'FAIL' if bad else 'ok  '
        print(f'[{flag}] {kind[:4]:<4} nii={rec["n_nii"]:<3} json={rec["n_json"]:<3} '
              f'helper={rec["helper_rc"]} convert={rec["convert_rc"]}  {label[:60]}', flush=True)
        if rec['error']:
            print('        ERROR: ' + str(rec['error'])[:300], flush=True)
        if rec['validator_errors']:
            print('        VALIDATOR: ' + str(rec['validator_errors'])[:300], flush=True)
    OUT.write_text(json.dumps(report, indent=2))
    n_err = sum(bool(r['error']) for r in report)
    n_vld = sum(bool(r['validator_errors']) for r in report)
    print(f'\n==== BIDS: units={len(report)}  pipeline-errors={n_err}  validator-flagged={n_vld} ====')
    print(f'Report -> {OUT}')


if __name__ == '__main__':
    main()
