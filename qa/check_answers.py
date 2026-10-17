"""Check scenario-suite answers against the expected key facts.

Reads the suite results JSON (default /tmp/suite_results.json) and runs
deterministic checks per scenario: key facts that must appear in the answer,
facts that must NOT appear, and the visual form where one is expected.
Exit code 0 when every check passes.
"""
import json, re, sys

def load(path):
    return {x['tag']: x for x in json.load(open(path))}

def text(x):
    r = x.get('r') or {}
    parts = [r.get('answer') or '', r.get('follow_up') or '',
             json.dumps(r.get('viz') or {}), ' '.join(r.get('citations') or [])]
    return ' '.join(parts)

def viz(x):
    return (x.get('r') or {}).get('viz') or {}

# tag -> (required patterns, forbidden patterns, expected viz type or None)
CHECKS = {
 'Q1':  ([r'not producing', r'INS-0001-0203', r'Ryan Brooks', r'15'], [], None),
 'Q2':  ([r'WELL-0164', r'WELL-0170', r'WELL-0172', r'WELL-0175', r'15 Oct|2026-10-15'], [], 'table'),
 'Q3':  ([r'8 Oct|2026-10-08', r'15 Oct|2026-10-15'], [], 'line'),
 'Q4':  ([r'6 spills|\b6\b', r'15\.1'], [], 'table'),
 'Q5':  ([r'21 days'], [], None),
 'Q6':  ([r'WELL-0121', r'49', r'WELL-0138', r'42', r'WELL-0107'], [], 'bar'),
 'Q7':  ([r'WELL-0186', r'WELL-0165', r'WELL-0175', r'WELL-0151'], [], 'map'),
 'Q8':  ([], [], 'heatmap'),
 'Q9':  ([r'6\.8', r'5,?000', r'open'], [], None),
 'Q10': ([r'\b2 spills|two spills', r'4 hours|4-hour|four hours'], [], 'table'),
 'Q11b':([r'25,?794', r'46,?942', r'5,?176'], [], None),
 'Q12b':([r'WELL-0170', r'WELL-0172', r'WELL-0175', r'correct'], [r'WELL-0164 (?!.*(correct|no longer|now producing))'], 'table'),
 'Q13': ([r'5\.4'], [], None),
 'Q14a':([r'WELL-0108', r'WELL-0121', r'WELL-0138', r'3'], [], None),
 'Q14c':([r'WELL-0108', r'WELL-0120', r'WELL-0121', r'WELL-0138'], [], None),
 'Q15a':([r'\byes\b|producing', r'correct', r'Michael Turner', r'pump jack'], [], None),
 'Q15b':([r'WELL-0151', r'overdue'], [], None),
 'Q16b':([r'17 Oct|2026-10-17', r'10.day', r'Jake Morales'], [], None),
 'Q16c':([r'no (such )?(earlier |previous )?conversation|don.t have|no record'], [r'25,?794', r'46,?942'], None),
 'Q17b':([r'0\.4', r'not producing', r'unconfirmed'], [], None),
 'Q17c':([r'not producing', r'20 Oct|around 20', r'unconfirmed'], [], None),
 'Q18': ([r'yes|confirmed', r'Ryan Brooks', r'Chris Dalton', r'crude', r'MNT-0101-029'], [], None),
}

def main(path='/tmp/suite_results.json'):
    res = load(path)
    ok = fail = 0
    for tag, (req, forb, vt) in CHECKS.items():
        if tag not in res:
            print(f'FAIL {tag}: missing from results'); fail += 1; continue
        t = text(res[tag])
        problems = [p for p in req if not re.search(p, t, re.I)]
        problems += [f'forbidden:{p}' for p in forb if re.search(p, t, re.I)]
        if vt and viz(res[tag]).get('type') != vt:
            problems.append(f'viz={viz(res[tag]).get("type")!r}, want {vt!r}')
        if problems:
            print(f'FAIL {tag}: {problems}'); fail += 1
        else:
            print(f'PASS {tag}'); ok += 1
    print(f'\n{ok} passed, {fail} failed')
    sys.exit(1 if fail else 0)

if __name__ == '__main__':
    main(*sys.argv[1:])
