"""Unseen-data generalization probe.

Copies the sample dataset with every ID shifted to new values
(WELL/INS/MNT/REG/CTX-0xxx -> 9xxx, U-xxx -> U-9xxx), ingests the shifted
copy into a fresh database, and checks that the pipeline produces the same
verdicts under the new IDs. The rules come from the manuals and the data,
not from the sample IDs - this is how we know.

Usage: python qa/generalization.py [sample-data-dir]
"""
import os, re, shutil, subprocess, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else 'sample-data'
DST = '/tmp/copilot-gen-data'
DB = '/tmp/copilot_gen.db'

def shift(text):
    text = re.sub(r'\b(WELL|INS|MNT|REG|CTX)-0(\d{3})', r'\1-9\2', text)
    text = re.sub(r'\bU-(\d{3})\b', r'U-9\1', text)
    return text

def transform():
    if os.path.exists(DST): shutil.rmtree(DST)
    for root, dirs, files in os.walk(SRC):
        rel = os.path.relpath(root, SRC)
        out_root = os.path.join(DST, shift(rel) if rel != '.' else '')
        os.makedirs(out_root, exist_ok=True)
        for f in files:
            src_f = os.path.join(root, f)
            dst_f = os.path.join(out_root, shift(f))
            try:
                with open(src_f, 'r', encoding='utf-8') as fh: data = fh.read()
                with open(dst_f, 'w', encoding='utf-8') as fh: fh.write(shift(data))
            except UnicodeDecodeError:
                shutil.copyfile(src_f, dst_f)
    print('shifted dataset at', DST)

def ingest():
    if os.path.exists(DB): os.remove(DB)
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))
    from ingest import ingest as do_ingest
    print('ingested:', do_ingest(DST, DB))

def probes():
    from core import Copilot
    c = Copilot(DB)
    ok = fail = 0
    def check(name, cond, extra=''):
        nonlocal ok, fail
        print(('PASS' if cond else 'FAIL'), name, extra)
        if cond: ok += 1
        else: fail += 1

    st = c.well_status('WELL-9001')
    check('WELL-9001 not producing, delta 3.2', st['producing']['producing'] is False and abs(st['producing']['delta_c'] - 3.2) < 0.05, str(st['producing']))
    check('latest inspection INS-9001-0203', st['latest_inspection']['inspection_id'] == 'INS-9001-0203', st['latest_inspection']['inspection_id'])
    area = c.area_by_name('Northeast Block 8')
    down = sorted(w['asset_id'] for w in c.wells_in_area(area['area_id']) if not c.well_status(w['asset_id'])['producing']['producing']) if hasattr(c, 'wells_in_area') else None
    if down is None:
        rows = c.q("SELECT asset_id FROM wells WHERE area_id=?", (area['area_id'],))
        down = sorted(r['asset_id'] for r in rows if not c.well_status(r['asset_id'])['producing']['producing'])
    check('NE8 down wells', down == ['WELL-9164', 'WELL-9170', 'WELL-9172', 'WELL-9175'], str(down))
    sp = c.spills(asset_id='WELL-9001')
    tot = round(sum(s['volume_bbl'] for s in sp), 1)
    check('WELL-9001 spills 6 / 15.1 bbl', len(sp) == 6 and tot == 15.1, f'{len(sp)} {tot}')
    u = c.q("SELECT name FROM users WHERE user_id='U-9104'")
    check('U-9104 is Ryan Brooks', u and u[0]['name'] == 'Ryan Brooks', u[0]['name'] if u else 'missing')
    rules = c.q("SELECT COUNT(*) AS n FROM parsed_rules")
    check('parsed_rules populated', rules[0]['n'] > 0, str(rules[0]['n']))
    th = c.threshold('T200'); th = th[0] if isinstance(th, tuple) else th
    check('T200 threshold 15 C', abs(th - 15) < 0.01, str(th))
    print(f'\n{ok} passed, {fail} failed')
    return fail

if __name__ == '__main__':
    transform(); ingest()
    sys.exit(1 if probes() else 0)
