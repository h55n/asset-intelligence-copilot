import sys, json
sys.path.insert(0, 'app')
from core import Copilot, day, parse_dt
from datetime import timedelta

c = Copilot('/tmp/copilot.db')
ok = fail = 0
def check(name, cond, extra=''):
    global ok, fail
    print(('PASS' if cond else 'FAIL'), name, extra)
    if cond: ok += 1
    else: fail += 1

# Q1
st = c.well_status('WELL-0001')
li = st['latest_inspection']
check('Q1 not producing', st['producing']['producing'] is False, f"delta={st['producing']['delta_c']}")
check('Q1 latest insp', li['inspection_id']=='INS-0001-0203' and day(li['inspected_at'])=='2026-10-15', li['inspection_id'])
insp_user = c.q("SELECT name FROM users WHERE user_id=?", (li['inspector_user_id'],))[0]['name']
check('Q1 inspector Ryan Brooks', insp_user=='Ryan Brooks', insp_user)
check('Q1 delta 3.2', st['producing']['delta_c']==3.2, st['producing']['delta_c'])
check('Q1 recorded out of date', st['recorded_status_out_of_date'] is True)
note = [n for n in st['active_notes'] if n.get('note_id')=='CTX-0001-003']
check('Q1 shut-in note present', len(note)==1)

# Q2
area = c.area_by_name('Northeast Block 8')
rows = []
for w in c.q("SELECT asset_id FROM area_wells WHERE area_id=?", (area['area_id'],)):
    s = c.well_status(w['asset_id'])
    if s['producing'] and not s['producing']['producing']:
        rows.append((w['asset_id'], s['producing']['delta_c'], s['recorded_status']))
ids = sorted(r[0] for r in rows)
check('Q2 four wells', ids==['WELL-0164','WELL-0170','WELL-0172','WELL-0175'], str(rows))
# Q3
w = c.well('WELL-0001')
series = c.q("SELECT * FROM inspections WHERE asset_id='WELL-0001' ORDER BY inspected_at DESC LIMIT 13")
down = [day(i['inspected_at']) for i in series if not c.producing(i, w['well_type'])['producing']]
check('Q3 down days', sorted(down)==['2026-10-08','2026-10-15'], str(down))
check('Q3 first date', day(series[-1]['inspected_at'])=='2026-07-23', day(series[-1]['inspected_at']))
# Q4
sp = c.spills(asset_id='WELL-0001')
tot = round(sum(s['volume_bbl'] for s in sp),1)
check('Q4 6 spills 15.1', len(sp)==6 and tot==15.1, f"{len(sp)} {tot}")
dates = [s['date'] for s in sp]
check('Q4 dates', dates==['2023-03-16','2023-04-27','2023-09-28','2023-10-19','2026-06-11','2026-10-01'], str(dates))
# Q5
dt5 = c.downtime('WELL-0001','2025-01-01','2025-12-31')
check('Q5 21 days', dt5['days']==21, f"{dt5['days']} {[i['inspected_at'][:10] for i in dt5['inspections']]}")
# Q6
a7 = c.area_by_name('Northeast Block 7')
res = []
for wl in c.q("SELECT asset_id FROM area_wells WHERE area_id=?", (a7['area_id'],)):
    d = c.downtime(wl['asset_id'],'2026-06-16','2026-10-16')
    res.append((d['days'], wl['asset_id']))
res.sort(reverse=True)
check('Q6 top3', [(r[1],r[0]) for r in res[:3]]==[('WELL-0121',49),('WELL-0138',42),('WELL-0107',42)], str([(r[1],r[0]) for r in res[:4]]))
# Q7
sp7 = c.spills(area_id=area['area_id'], start='2026-07-19', end='2026-10-17')
got = {s['asset_id']:(s['date'],s['volume_bbl']) for s in sp7}
exp7 = {'WELL-0151':('2026-09-24',4.5),'WELL-0165':('2026-07-30',1.2),'WELL-0175':('2026-07-30',3.9),'WELL-0186':('2026-07-23',0.6)}
check('Q7 four pins', got==exp7, str(got))
# Q8
hm = {}
for a in c.q("SELECT area_id, name FROM areas"):
    counts = {}
    for s in c.spills(area_id=a['area_id'], start='2026-01-01', end='2026-12-31'):
        m = s['date'][5:7]; counts[m] = counts.get(m,0)+1
    hm[a['name']] = counts
exp8 = {'Southwest Block 23':[4,3,3,6,3,4,4,3,3,2],'Southwest Block 24':[7,4,5,6,5,5,3,1,5,2],
        'Northeast Block 7':[5,3,2,4,6,6,2,4,4,1],'Northeast Block 8':[4,4,4,3,2,4,4,0,1,0]}
allok = True
for name, exp in exp8.items():
    got8 = [hm[name].get(f'{m:02d}',0) for m in range(1,11)]
    if got8 != exp:
        allok = False; print('  mismatch', name, got8, 'vs', exp)
check('Q8 heatmap', allok)
# Q9
comp = c.compliance(asset_id='WELL-0001', months=12)
prots = sorted(set(b['protocol'] for b in comp['breaches']))
check('Q9 four breaches', prots==['RC-04','SR-01','SR-02','SR-03'], str([(b['protocol'],b['detail']) for b in comp['breaches']]))
# Q10
a24 = c.area_by_name('Southwest Block 24')
bad = []
for s in c.spills(area_id=a24['area_id'], start='2026-07-19', end='2026-10-17'):
    for m in c.q("SELECT * FROM maintenance WHERE triggered_by_inspection_id=?", (s['inspection_id'],)):
        if m.get('report_file'):
            rid = m['report_file'].split('/')[-1][:-3]
            rep = c.q("SELECT containment_hours FROM reports WHERE report_id=?", (rid,))
            if rep and rep[0]['containment_hours'] and rep[0]['containment_hours'] > 4:
                bad.append((s['asset_id'], rep[0]['containment_hours'], rid))
check('Q10 two spills', sorted((b[0],b[1]) for b in bad)==[('WELL-0082',7.1),('WELL-0100',8.1)], str(bad))
# Q14 base
rca = c.rca_needed(area_id=a7['area_id'])
check('Q14 base 3 wells', [r['asset_id'] for r in rca]==['WELL-0108','WELL-0121','WELL-0138'], str([ (r['asset_id'],r['corrective_repairs']) for r in rca]))
print(f"\n{ok} pass {fail} fail")
