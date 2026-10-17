"""Domain rules + canonical queries over the ingested dataset.

This module is the deterministic heart of the copilot: producing status,
downtime, spills (with corrections applied), repairs, compliance and
memory overlays are all computed here so that answers are grounded in the
records, not in model guesses.
"""
import json, re, sqlite3
from datetime import datetime, timedelta, timezone

TODAY = "2026-10-17"  # overridden per dataset at ingest/questions time

DEFAULT_THRESHOLDS = {"T200": 15.0, "T350": 20.0}
THRESHOLD_DOC = {"T200": ("OM-T200", "T200.md section 9.3 (production temperature rule)"),
                 "T350": ("OM-T350", "T350.md section 3 (production temperature rule)")}
SPILL_REPORT_THRESHOLD = 5.0      # bbl, Spill Response SOP section 3 (reportable class)
SR01_WRITTEN_NOTICE_H = 24.0      # SR-01
SR01_MAJOR_NOTICE_H = 2.0
SR02_CONTAINMENT_H = 4.0          # SR-02
SR03_VERIFY_DAYS = 60             # SR-03
RC04_NOV_RESPONSE_DAYS = 30       # RC-04
RCA_CORRECTIVE_COUNT = 3          # T200 manual section 10 / T350 section 6
RCA_WINDOW_DAYS = 365
DOWN_REPORT_DAYS = 14             # T200 manual section 10 / RC-03
INSPECTION_GAP_DAYS = 14          # RC-01
MAJOR_SPILL_BBL = 25.0

def parse_dt(s):
    if not s:
        return None
    s = s.replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)

def day(s):
    return (s or '')[:10]

class Copilot:
    def __init__(self, db_path, today=TODAY):
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
        self.today = today
        self._ensure_memory()

    # ---------- memory layer ----------
    def _ensure_memory(self):
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS corrections(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT, author_user_id TEXT, scope_type TEXT, scope_id TEXT,
            field TEXT, original_value TEXT, corrected_value TEXT, reason TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS shared_notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT, author_user_id TEXT, asset_id TEXT, text TEXT,
            valid_from TEXT, valid_to TEXT, kind TEXT DEFAULT 'info');
        CREATE TABLE IF NOT EXISTS claims(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT, author_user_id TEXT, asset_id TEXT, text TEXT,
            status TEXT DEFAULT 'unconfirmed', assessment TEXT);
        CREATE TABLE IF NOT EXISTS chat_messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, session_id TEXT, role TEXT, text TEXT, wells TEXT, created_at TEXT);
        """)
        self.db.commit()

    def q(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    # ---------- lookups ----------
    def user_by_name(self, name):
        r = self.q("SELECT * FROM users WHERE lower(name)=lower(?)", (name,))
        if not r:
            r = self.q("SELECT * FROM users WHERE lower(name) LIKE lower(?)", (f'%{name}%',))
        return r[0] if r else None

    def area_by_name(self, name):
        r = self.q("SELECT * FROM areas WHERE lower(name)=lower(?)", (name,))
        if not r:
            r = self.q("SELECT * FROM areas WHERE lower(name) LIKE lower(?) OR lower(area_id)=lower(?)", (f'%{name}%', name))
        return r[0] if r else None

    def well(self, asset_id):
        r = self.q("SELECT * FROM wells WHERE asset_id=?", (asset_id,))
        return r[0] if r else None

    def threshold(self, well_type):
        """Producing threshold for a well type, honouring well-type rule corrections."""
        c = self.q("""SELECT corrected_value FROM corrections
                      WHERE active=1 AND scope_type='well_type' AND scope_id=? AND field='producing_threshold_c'
                      ORDER BY id DESC LIMIT 1""", (well_type,))
        if c:
            return float(c[0]['corrected_value']), 'user_correction'
        return DEFAULT_THRESHOLDS.get(well_type, 15.0), 'manual'

    def rca_threshold(self, well_type):
        c = self.q("""SELECT corrected_value, author_user_id FROM corrections
                      WHERE active=1 AND scope_type='well_type' AND scope_id=? AND field='rca_corrective_count'
                      ORDER BY id DESC LIMIT 1""", (well_type,))
        if c:
            return int(float(c[0]['corrected_value'])), c[0]['author_user_id']
        return RCA_CORRECTIVE_COUNT, None

    # ---------- corrections overlay ----------
    def correction_for(self, inspection_id, field):
        r = self.q("""SELECT * FROM corrections WHERE active=1 AND scope_type='inspection'
                      AND scope_id=? AND field=? ORDER BY id DESC LIMIT 1""", (inspection_id, field))
        return r[0] if r else None

    def effective_wellhead_temp(self, insp):
        c = self.correction_for(insp['inspection_id'], 'wellhead_temp_c')
        if c:
            return float(c['corrected_value']), c
        return insp['wellhead_temp_c'], None

    def effective_spill_volume(self, insp):
        c = self.correction_for(insp['inspection_id'], 'spill_est_volume_bbl')
        if c:
            return float(c['corrected_value']), c
        return insp['spill_est_volume_bbl'], None

    def is_formally_corrected_not_spill(self, inspection_id):
        """Dataset correction notes (context.jsonl) or runtime corrections that void a spill."""
        r = self.q("SELECT * FROM notes WHERE note_type='correction' AND inspection_id=?", (inspection_id,))
        if r:
            return r[0]
        r = self.q("""SELECT * FROM corrections WHERE active=1 AND scope_type='inspection'
                      AND scope_id=? AND field='spill_detected' AND corrected_value='false'
                      ORDER BY id DESC LIMIT 1""", (inspection_id,))
        return r[0] if r else None

    # ---------- producing / downtime ----------
    def producing(self, insp, well_type):
        thr, src = self.threshold(well_type)
        wt, corr = self.effective_wellhead_temp(insp)
        delta = None if wt is None or insp['ambient_temp_c'] is None else round(wt - insp['ambient_temp_c'], 1)
        return {'producing': (delta is not None and delta >= thr), 'delta_c': delta,
                'threshold_c': thr, 'threshold_source': src, 'temp_correction': corr}

    def latest_inspection(self, asset_id):
        r = self.q("SELECT * FROM inspections WHERE asset_id=? ORDER BY inspected_at DESC LIMIT 1", (asset_id,))
        return r[0] if r else None

    def well_status(self, asset_id):
        w = self.well(asset_id)
        if not w:
            return None
        insp = self.latest_inspection(asset_id)
        p = self.producing(insp, w['well_type']) if insp else None
        inspector = self.q("SELECT * FROM users WHERE user_id=?", (insp['inspector_user_id'],))[0] if insp else None
        notes = self.active_notes(asset_id)
        open_repairs = self.q("""SELECT * FROM maintenance WHERE asset_id=? AND completed_at > ? ORDER BY started_at""",
                              (asset_id, self.today + 'T23:59:59Z'))
        return {'well': w, 'latest_inspection': insp, 'producing': p, 'inspector': inspector,
                'recorded_status': w['recorded_status'],
                'recorded_status_out_of_date': bool(p) and ((w['recorded_status'] == 'active') != p['producing']),
                'active_notes': notes, 'open_repairs': open_repairs}

    def active_notes(self, asset_id, include_all=False):
        rows = self.q("SELECT * FROM notes WHERE asset_id=? ORDER BY created_at DESC", (asset_id,))
        out = []
        for n in rows:
            vf, vt = n.get('valid_from'), n.get('valid_to')
            if include_all or (not vt or vt >= self.today) or (vf and vf <= self.today):
                out.append(n)
        shared = self.q("SELECT * FROM shared_notes WHERE asset_id=? ORDER BY id DESC", (asset_id,))
        for s in shared:
            if not s['valid_to'] or s['valid_to'] >= self.today:
                out.append({'note_id': f"SHARED-{s['id']}", 'note_type': 'shared_note', 'text': s['text'],
                            'author_user_id': s['author_user_id'], 'created_at': s['created_at'],
                            'valid_from': s['valid_from'], 'valid_to': s['valid_to'], 'asset_id': asset_id})
        return out

    def downtime(self, asset_id, start, end):
        """Days down in [start, end] by weekly inspections (each non-producing inspection = 7 days)."""
        w = self.well(asset_id)
        rows = self.q("""SELECT * FROM inspections WHERE asset_id=? AND inspected_at>=? AND inspected_at<? || 'T23:59:59Z'
                         ORDER BY inspected_at""", (asset_id, start, end))
        down = []
        for i in rows:
            p = self.producing(i, w['well_type'])
            if not p['producing']:
                down.append({'inspection_id': i['inspection_id'], 'inspected_at': i['inspected_at'],
                             'delta_c': p['delta_c'], 'threshold_c': p['threshold_c']})
        return {'asset_id': asset_id, 'days': len(down) * 7, 'inspections': down}

    def spills(self, asset_id=None, area_id=None, start=None, end=None, real_only=True):
        sql = """SELECT i.*, w.well_type, w.area_id, w.lat, w.lon FROM inspections i
                 JOIN wells w ON w.asset_id=i.asset_id WHERE i.spill_detected=1"""
        args = []
        if asset_id:
            sql += " AND i.asset_id=?"; args.append(asset_id)
        if area_id:
            sql += " AND w.area_id=?"; args.append(area_id)
        if start:
            sql += " AND i.inspected_at>=?"; args.append(start)
        if end:
            sql += " AND i.inspected_at<? || 'T23:59:59Z'"; args.append(end)
        sql += " ORDER BY i.inspected_at"
        out = []
        for i in self.q(sql, args):
            corr = self.is_formally_corrected_not_spill(i['inspection_id'])
            vol, vcorr = self.effective_spill_volume(i)
            row = {'inspection_id': i['inspection_id'], 'asset_id': i['asset_id'], 'area_id': i['area_id'],
                   'inspected_at': i['inspected_at'], 'date': day(i['inspected_at']),
                   'spill_area_pct': i['spill_area_pct'], 'volume_bbl': vol,
                   'ai_est_volume_bbl': i['spill_est_volume_bbl'], 'lat': i['lat'], 'lon': i['lon'],
                   'corrected_not_spill': bool(corr), 'correction': corr, 'volume_correction': vcorr,
                   'reportable': (vol is not None and vol >= SPILL_REPORT_THRESHOLD and not corr)}
            if real_only and corr:
                continue
            out.append(row)
        return out

    def repairs(self, asset_id=None, area_id=None, start=None, end=None, mtype=None, equipment=None):
        sql = "SELECT m.*, w.area_id, w.well_type FROM maintenance m JOIN wells w ON w.asset_id=m.asset_id WHERE 1=1"
        args = []
        if asset_id:
            sql += " AND m.asset_id=?"; args.append(asset_id)
        if area_id:
            sql += " AND w.area_id=?"; args.append(area_id)
        if start:
            sql += " AND m.started_at>=?"; args.append(start)
        if end:
            sql += " AND m.started_at<? || 'T23:59:59Z'"; args.append(end)
        if mtype:
            sql += " AND m.maintenance_type=?"; args.append(mtype)
        if equipment:
            sql += " AND m.equipment_kind=?"; args.append(equipment)
        sql += " ORDER BY m.started_at"
        rows = self.q(sql, args)
        for r in rows:
            if r.get('report_file'):
                rep = self.q("SELECT report_id, containment_hours, spill_inspection_id FROM reports WHERE report_id=?",
                             (r['report_file'].split('/')[-1][:-3],))
                if rep:
                    r['containment_hours'] = rep[0]['containment_hours']
                    r['report_id'] = rep[0]['report_id']
        return rows

    # ---------- compliance ----------
    def compliance(self, asset_id=None, area_id=None, months=12):
        start = day((parse_dt(self.today) - timedelta(days=months * 30.4)).isoformat())
        breaches, pending = [], []
        wells = [asset_id] if asset_id else [r['asset_id'] for r in self.q("SELECT asset_id FROM wells WHERE area_id=?", (area_id,))]
        for wid in wells:
            for s in self.spills(asset_id=wid, start=start, end=self.today):
                if not s['reportable']:
                    continue
                insp = self.q("SELECT * FROM inspections WHERE inspection_id=?", (s['inspection_id'],))[0]
                regs = self.q("SELECT * FROM regulatory_events WHERE related_inspection_id=?", (s['inspection_id'],))
                filed = [r for r in regs if r['event_type'] == 'spill_report_filed']
                limit = SR01_MAJOR_NOTICE_H if (s['volume_bbl'] or 0) >= MAJOR_SPILL_BBL else SR01_WRITTEN_NOTICE_H
                if not filed:
                    breaches.append({'asset_id': wid, 'protocol': 'SR-01', 'inspection_id': s['inspection_id'],
                                     'detail': f"reportable spill ({s['volume_bbl']} bbl) on {s['date']} has no written notice on record",
                                     'evidence': [s['inspection_id']]})
                else:
                    h = filed[0]['hours_to_report']
                    if h is not None and h > limit:
                        novs = [r for r in regs if r['event_type'] == 'notice_of_violation']
                        breaches.append({'asset_id': wid, 'protocol': 'SR-01', 'inspection_id': s['inspection_id'],
                                         'detail': f"written notice filed after {h} h (limit {limit} h)",
                                         'fine_usd': sum(n['fine_usd'] or 0 for n in novs),
                                         'nov_open': any(n['status'] == 'open' for n in novs),
                                         'evidence': [filed[0]['event_id']] + [n['event_id'] for n in novs]})
                        for n in novs:
                            resp = [r for r in regs if r['event_type'] == 'nov_response_filed']
                            due = day((parse_dt(n['date']) + timedelta(days=RC04_NOV_RESPONSE_DAYS)).isoformat())
                            if not resp and due < self.today:
                                breaches.append({'asset_id': wid, 'protocol': 'RC-04', 'inspection_id': s['inspection_id'],
                                                 'detail': f"notice of violation {n['event_id']} needed a response by {due}; none recorded",
                                                 'evidence': [n['event_id']]})
                reps = self.q("""SELECT m.maintenance_id, r.containment_hours, r.report_id FROM maintenance m
                                 LEFT JOIN reports r ON r.report_id = replace(m.report_file,'maintenance-reports/','') 
                                 WHERE m.triggered_by_inspection_id=?""", (s['inspection_id'],))
                # fix: report_file replace needs .md strip
                reps = []
                for m in self.q("SELECT * FROM maintenance WHERE triggered_by_inspection_id=?", (s['inspection_id'],)):
                    if m.get('report_file'):
                        rid = m['report_file'].split('/')[-1][:-3]
                        rep = self.q("SELECT * FROM reports WHERE report_id=?", (rid,))
                        reps.append({'maintenance_id': m['maintenance_id'], 'report_id': rid,
                                     'containment_hours': rep[0]['containment_hours'] if rep else None})
                for rp in reps:
                    ch = rp['containment_hours']
                    if ch is not None and ch > SR02_CONTAINMENT_H:
                        breaches.append({'asset_id': wid, 'protocol': 'SR-02', 'inspection_id': s['inspection_id'],
                                         'detail': f"contained after about {ch} h (limit {SR02_CONTAINMENT_H} h); found in repair report {rp['report_id']}",
                                         'evidence': [rp['report_id'], s['inspection_id']]})
                due = day((parse_dt(s['inspected_at']) + timedelta(days=SR03_VERIFY_DAYS)).isoformat())
                ver = [r for r in regs if r['event_type'] == 'site_inspection' and r['status'] == 'closed']
                if due < self.today and not ver:
                    open_ver = [r for r in regs if r['event_type'] == 'site_inspection']
                    breaches.append({'asset_id': wid, 'protocol': 'SR-03', 'inspection_id': s['inspection_id'],
                                     'detail': f"clean-up verification was due by {due} and is still open" if open_ver else
                                               f"clean-up verification was due by {due}; no agency verification recorded",
                                     'evidence': [r['event_id'] for r in open_ver] or [s['inspection_id']]})
                elif due >= self.today and not ver:
                    pending.append({'asset_id': wid, 'protocol': 'SR-03', 'inspection_id': s['inspection_id'],
                                    'detail': f"agency verification of clean-up due by {due}"})
        return {'breaches': breaches, 'pending': pending, 'window_start': start}

    def rca_needed(self, area_id=None, equipment='pump_jack', months=12):
        """Wells needing root-cause analysis: corrective repairs on equipment >= threshold in window.
        Threshold comes from the manual unless a well-type rule correction overrides it."""
        start = day((parse_dt(self.today) - timedelta(days=months * 30.4)).isoformat())
        rows = self.q("""SELECT m.asset_id, w.well_type, w.area_id, count(*) AS n,
                         group_concat(m.maintenance_id) AS ids
                         FROM maintenance m JOIN wells w ON w.asset_id=m.asset_id
                         WHERE m.maintenance_type='corrective' AND m.equipment_kind=?
                         AND m.started_at>=? """ + ("AND w.area_id=?" if area_id else "") +
                      " GROUP BY m.asset_id", (equipment, start) + ((area_id,) if area_id else ()))
        out = []
        for r in rows:
            thr, author = self.rca_threshold(r['well_type'])
            if r['n'] >= thr:
                out.append({'asset_id': r['asset_id'], 'well_type': r['well_type'], 'area_id': r['area_id'],
                            'corrective_repairs': r['n'], 'maintenance_ids': r['ids'].split(','),
                            'threshold': thr, 'rule_source': f"user rule by {author}" if author else 'T200 manual section 10'})
        return sorted(out, key=lambda x: x['asset_id'])

    # ---------- memory ----------
    def record_correction(self, author, scope_type, scope_id, field, original, corrected, reason):
        self.db.execute("""INSERT INTO corrections(created_at, author_user_id, scope_type, scope_id, field,
                           original_value, corrected_value, reason, active) VALUES (?,?,?,?,?,?,?,?,1)""",
                        (datetime.now(timezone.utc).isoformat(), author, scope_type, scope_id, field,
                         str(original), str(corrected), reason))
        self.db.commit()

    def record_shared_note(self, author, asset_id, text, valid_from=None, valid_to=None, kind='info'):
        self.db.execute("INSERT INTO shared_notes(created_at, author_user_id, asset_id, text, valid_from, valid_to, kind) VALUES (?,?,?,?,?,?,?)",
                        (datetime.now(timezone.utc).isoformat(), author, asset_id, text, valid_from, valid_to, kind))
        self.db.commit()

    def record_claim(self, author, asset_id, text):
        """Store a user statement and assess it against the data. Never deletes conflicts."""
        st = self.well_status(asset_id)
        assessment, status = None, 'unconfirmed'
        if st and st['producing']:
            prod = st['producing']['producing']
            says_running = bool(re.search(r'\b(running|back online|online|producing|fine|up)\b', text, re.I)) and not re.search(r'\b(not|shut|down)\b', text, re.I)
            says_down = bool(re.search(r'\b(shut|down|stopped|offline)\b', text, re.I))
            if says_running and not prod:
                insp = st['latest_inspection']
                assessment = (f"Latest inspection {insp['inspection_id']} ({day(insp['inspected_at'])}) shows the wellhead "
                              f"{st['producing']['delta_c']} C above air, below the {st['producing']['threshold_c']} C rule: "
                              f"the well is not producing. Recorded as unconfirmed.")
                status = 'contradicted'
            elif says_down and prod:
                assessment = "Latest inspection shows the well producing. Recorded as unconfirmed."
                status = 'contradicted'
        cur = self.db.execute("INSERT INTO claims(created_at, author_user_id, asset_id, text, status, assessment) VALUES (?,?,?,?,?,?)",
                              (datetime.now(timezone.utc).isoformat(), author, asset_id, text, status, assessment))
        self.db.commit()
        return {'claim_id': cur.lastrowid, 'status': status, 'assessment': assessment}

    def claims_for(self, asset_id):
        return self.q("SELECT * FROM claims WHERE asset_id=? ORDER BY id DESC", (asset_id,))

    def log_chat(self, user_id, session_id, role, text, wells=()):
        self.db.execute("INSERT INTO chat_messages(user_id, session_id, role, text, wells, created_at) VALUES (?,?,?,?,?,?)",
                        (user_id, session_id, role, text, json.dumps(sorted(set(wells))), datetime.now(timezone.utc).isoformat()))
        self.db.commit()

    def recall_wells(self, user_id, ref_date=None, days=1, limit=10):
        """Wells discussed with THIS user in earlier sessions (never another user's)."""
        rows = self.q("SELECT * FROM chat_messages WHERE user_id=? ORDER BY id DESC LIMIT 200", (user_id,))
        seen, out = set(), []
        for r in rows:
            for w in json.loads(r['wells'] or '[]'):
                if w not in seen:
                    seen.add(w); out.append(w)
                if len(out) >= limit:
                    return out
        return out

    def chat_history(self, user_id, session_id=None, limit=12):
        if session_id:
            return self.q("SELECT * FROM chat_messages WHERE user_id=? AND session_id=? ORDER BY id DESC LIMIT ?", (user_id, session_id, limit))[::-1]
        return self.q("SELECT * FROM chat_messages WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))[::-1]
