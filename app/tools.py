"""Tool surface the copilot's agent can call. Every result carries evidence IDs."""
import json, re
from datetime import timedelta
from core import (Copilot, day, parse_dt, SPILL_REPORT_THRESHOLD, SR03_VERIFY_DAYS)

def months_back(today, months):
    return day((parse_dt(today) - timedelta(days=months * 30.4)).isoformat())

class Tools:
    def __init__(self, cp: Copilot):
        self.c = cp

    def _area_id(self, name):
        a = self.c.area_by_name(name)
        return (a or {}).get('area_id'), (a or {}).get('name')

    def resolve(self, name):
        u = self.c.user_by_name(name)
        a = self.c.area_by_name(name)
        w = self.c.well(name.upper()) if re.match(r'(?i)^well-\d+$', name.strip()) else None
        out = {}
        if u: out['user'] = u
        if a: out['area'] = a
        if w: out['well'] = w
        return out or {'error': f'no user, area or well matches {name!r}'}

    def get_well_status(self, well_id):
        st = self.c.well_status(well_id.upper())
        if not st:
            return {'error': f'unknown well {well_id}'}
        w, p, insp = st['well'], st['producing'], st['latest_inspection']
        ev = [insp['inspection_id']] if insp else []
        out = {
            'well_id': w['asset_id'], 'name': w['name'], 'well_type': w['well_type'],
            'area_id': w['area_id'], 'team_id': w['team_id'], 'recorded_status': w['recorded_status'],
            'producing_now': p['producing'], 'wellhead_above_air_c': p['delta_c'],
            'threshold_c': p['threshold_c'], 'threshold_source': p['threshold_source'],
            'latest_inspection': {'id': insp['inspection_id'], 'date': day(insp['inspected_at']),
                                  'method': insp['method'],
                                  'inspector': st['inspector']['name'] if st['inspector'] else insp['inspector_user_id'],
                                  'wellhead_temp_c': insp['wellhead_temp_c'], 'ambient_temp_c': insp['ambient_temp_c'],
                                  'notes': insp['notes']},
            'recorded_status_out_of_date': st['recorded_status_out_of_date'],
            'active_notes': [{'note_id': n.get('note_id'), 'type': n.get('note_type'),
                              'author': self._uname(n.get('author_user_id')), 'text': n['text'],
                              'valid_from': n.get('valid_from'), 'valid_to': n.get('valid_to')} for n in st['active_notes']],
            'open_repairs': [{'maintenance_id': r['maintenance_id'], 'issue': r['issue'],
                              'started_at': day(r['started_at']), 'completed_at': day(r['completed_at'])}
                             for r in st['open_repairs']],
            'claims': [{'author': self._uname(cl['author_user_id']), 'text': cl['text'], 'status': cl['status']}
                       for cl in self.c.claims_for(w['asset_id'])],
        }
        if p.get('temp_correction'):
            tc = p['temp_correction']
            out['temp_correction'] = {'original': tc['original_value'], 'corrected': tc['corrected_value'],
                                      'by': self._uname(tc['author_user_id']), 'reason': tc['reason']}
        out['evidence'] = ev + [n.get('note_id') for n in st['active_notes'] if n.get('note_id')]
        return out

    def _uname(self, uid):
        if not uid: return None
        r = self.c.q("SELECT name FROM users WHERE user_id=?", (uid,))
        return r[0]['name'] if r else uid

    def list_area_wells(self, area, only_not_producing=False):
        aid, aname = self._area_id(area)
        if not aid: return {'error': f'unknown area {area}'}
        rows = []
        for w in self.c.q("SELECT asset_id FROM area_wells WHERE area_id=? ORDER BY asset_id", (aid,)):
            st = self.c.well_status(w['asset_id'])
            p = st['producing']
            if only_not_producing and p['producing']:
                continue
            rows.append({'well_id': w['asset_id'], 'well_type': st['well']['well_type'],
                         'producing_now': p['producing'], 'wellhead_above_air_c': p['delta_c'],
                         'recorded_status': st['recorded_status'],
                         'last_inspected': day(st['latest_inspection']['inspected_at']) if st['latest_inspection'] else None,
                         'inspection_notes': st['latest_inspection']['notes'] if st['latest_inspection'] else '',
                         'open_repairs': [{'maintenance_id': r['maintenance_id'], 'issue': r['issue'][:80],
                                           'started_at': day(r['started_at'])} for r in st['open_repairs'][:3]],
                         'recorded_status_out_of_date': st['recorded_status_out_of_date'],
                         'evidence': [st['latest_inspection']['inspection_id']] if st['latest_inspection'] else []})
        return {'area': aname, 'count': len(rows), 'wells': rows}

    def get_temperature_series(self, well_id, start=None, end=None, last_weeks=None):
        w = self.c.well(well_id.upper())
        if not w: return {'error': f'unknown well {well_id}'}
        if last_weeks:
            rows = self.c.q("SELECT * FROM inspections WHERE asset_id=? ORDER BY inspected_at DESC LIMIT ?",
                            (w['asset_id'], int(last_weeks)))[::-1]
        else:
            rows = self.c.q("SELECT * FROM inspections WHERE asset_id=? AND inspected_at>=? AND inspected_at<?||'T23:59:59Z' ORDER BY inspected_at",
                            (w['asset_id'], start or '1900-01-01', end or self.c.today))
        thr, src = self.c.threshold(w['well_type'])
        pts = []
        for i in rows:
            p = self.c.producing(i, w['well_type'])
            pts.append({'date': day(i['inspected_at']), 'inspection_id': i['inspection_id'],
                        'wellhead_temp_c': i['wellhead_temp_c'], 'ambient_temp_c': i['ambient_temp_c'],
                        'producing': p['producing'], 'delta_c': p['delta_c']})
        return {'well_id': w['asset_id'], 'well_type': w['well_type'], 'threshold_c': thr,
                'points': pts, 'evidence': [p['inspection_id'] for p in pts]}

    def get_downtime(self, well_id=None, area=None, start=None, end=None, months=None, year=None):
        if months: start = months_back(self.c.today, months)
        if year: start, end = f'{year}-01-01', f'{year}-12-31'
        end = end or self.c.today
        if well_id:
            d = self.c.downtime(well_id.upper(), start or '1900-01-01', end)
            return {'well_id': well_id.upper(), 'days_down': d['days'], 'window': [start, end],
                    'non_producing_inspections': d['inspections'],
                    'note': 'each weekly inspection not producing counts 7 days; missed inspections add none',
                    'evidence': [i['inspection_id'] for i in d['inspections']]}
        aid, aname = self._area_id(area)
        if not aid: return {'error': 'give a well_id or a valid area'}
        rows = []
        for w in self.c.q("SELECT asset_id FROM area_wells WHERE area_id=?", (aid,)):
            d = self.c.downtime(w['asset_id'], start or '1900-01-01', end)
            rows.append({'well_id': w['asset_id'], 'days_down': d['days'],
                         'evidence': [i['inspection_id'] for i in d['inspections']]})
        rows.sort(key=lambda r: -r['days_down'])
        return {'area': aname, 'window': [start, end], 'wells': rows}

    def get_spills(self, well_id=None, area=None, start=None, end=None, months=None, days=None, year=None, include_corrected=False):
        if months: start = months_back(self.c.today, months)
        if days: start = day((parse_dt(self.c.today) - __import__('datetime').timedelta(days=days)).isoformat())
        if year: start, end = f'{year}-01-01', f'{year}-12-31'
        aid = None
        if area:
            aid, _ = self._area_id(area)
            if not aid: return {'error': f'unknown area {area}'}
        rows = self.c.spills(asset_id=well_id.upper() if well_id else None, area_id=aid,
                             start=start, end=end or self.c.today, real_only=not include_corrected)
        for s in rows:
            s['evidence'] = [s['inspection_id']] + ([s['correction']['note_id']] if s.get('correction') and isinstance(s.get('correction'), dict) and s['correction'].get('note_id') else [])
            s['month'] = s['date'][5:7]
            s.pop('correction', None); s.pop('volume_correction', None)
        total = round(sum(s['volume_bbl'] or 0 for s in rows if not s['corrected_not_spill']), 1)
        return {'count': len([s for s in rows if not s['corrected_not_spill']]), 'total_bbl': total,
                'report_threshold_bbl': SPILL_REPORT_THRESHOLD, 'spills': rows}

    def get_repairs(self, well_id=None, area=None, start=None, end=None, months=None, year=None,
                    maintenance_type=None, equipment_kind=None):
        if months: start = months_back(self.c.today, months)
        if year: start, end = f'{year}-01-01', f'{year}-12-31'
        aid = None
        if area:
            aid, _ = self._area_id(area)
            if not aid: return {'error': f'unknown area {area}'}
        rows = self.c.repairs(asset_id=well_id.upper() if well_id else None, area_id=aid,
                              start=start, end=end or self.c.today, mtype=maintenance_type, equipment=equipment_kind)
        for r in rows:
            r['evidence'] = [r['maintenance_id']] + ([r['report_id']] if r.get('report_id') else [])
        return {'count': len(rows), 'total_cost_usd': sum(r['cost_total'] or 0 for r in rows), 'repairs': rows}

    def get_regulatory_events(self, well_id=None, area=None, start=None, end=None, months=None):
        if months: start = months_back(self.c.today, months)
        sql = "SELECT r.* FROM regulatory_events r JOIN wells w ON w.asset_id=r.asset_id WHERE 1=1"
        args = []
        if well_id: sql += " AND r.asset_id=?"; args.append(well_id.upper())
        if area:
            aid, _ = self._area_id(area)
            if not aid: return {'error': f'unknown area {area}'}
            sql += " AND w.area_id=?"; args.append(aid)
        if start: sql += " AND r.date>=?"; args.append(day(start))
        if end: sql += " AND r.date<=?"; args.append(day(end))
        rows = self.c.q(sql + " ORDER BY r.date", args)
        for r in rows: r['evidence'] = [r['event_id']]
        return {'count': len(rows), 'events': rows}

    def get_notes(self, well_id):
        rows = self.c.active_notes(well_id.upper(), include_all=True)
        for n in rows:
            n['author'] = self._uname(n.get('author_user_id'))
        return {'well_id': well_id.upper(), 'notes': rows}

    def search_documents(self, query, limit=5):
        docs = self.c.q("SELECT doc_id, title, snippet(docs_fts, 2, '[', ']', '...', 12) AS snip FROM docs_fts WHERE docs_fts MATCH ? LIMIT ?",
                        (query, limit))
        reps = self.c.q("SELECT report_id, snippet(reports_fts, 1, '[', ']', '...', 12) AS snip FROM reports_fts WHERE reports_fts MATCH ? LIMIT ?",
                        (query, limit))
        return {'documents': docs, 'reports': reps, 'note': 'cite doc_id/report_id as evidence'}

    def get_rules(self):
        c = self.c
        t200, s1 = c.threshold('T200'); t350, s2 = c.threshold('T350')
        return {
            'producing_rule': {'T200': t200, 'T350': t350,
                               'text': 'a well is producing oil when wellhead temp is at least the threshold above ambient',
                               'source': {'T200': 'OM-T200 section 9.3', 'T350': 'OM-T350 section 3'},
                               'overridden_by_user': s1 == 'user_correction' or s2 == 'user_correction'},
            'downtime_rule': {'text': 'each weekly inspection not producing counts 7 days; missed inspections add none; never use maintenance downtime_hours',
                              'source': 'Dataset Guide'},
            'spill_classes': {'minor': '< 1 bbl: record and clean up', 'moderate': '1 to <5 bbl: internal review',
                              'reportable': '5 to <25 bbl: external report (SR-01)', 'major': '>=25 bbl: report within 2 h',
                              'source': 'Spill Response SOP section 3'},
            'SR-01': {'text': 'written notice within 24 h of discovery for reportable spills (2 h for major); hours_to_report is time to written notice', 'source': 'Spill Response SOP SR-01'},
            'SR-02': {'text': 'source stopped and spill contained within 4 h of discovery; containment time is in the repair report', 'source': 'Spill Response SOP SR-02'},
            'SR-03': {'text': 'reportable spills: remediation verified within 60 days by a passing agency site inspection', 'source': 'Spill Response SOP SR-03'},
            'RC-01': {'text': 'every well inspected at least once every 14 days', 'source': 'Regulatory Compliance SOP RC-01'},
            'RC-02': {'text': 'flowline integrity test once per calendar year', 'source': 'Regulatory Compliance SOP RC-02'},
            'RC-03': {'text': 'well down > 14 consecutive days must be reported to the area production supervisor', 'source': 'Regulatory Compliance SOP RC-03'},
            'RC-04': {'text': 'notices of violation answered within 30 days and tracked until closed', 'source': 'Regulatory Compliance SOP RC-04'},
            'RCA': {'text': 'root-cause analysis after 3 corrective events on the same equipment kind in 12 months (unless a user rule overrides it per well type)',
                    'source': 'T200 manual section 10; T350 manual section 6'},
        }

    def compliance_check(self, well_id=None, area=None, months=12):
        r = self.c.compliance(asset_id=well_id.upper() if well_id else None, area_id=self._area_id(area)[0] if area else None, months=months)
        return r

    def rca_check(self, area=None, equipment_kind='pump_jack', months=12):
        return {'results': self.c.rca_needed(area_id=self._area_id(area)[0] if area else None,
                                             equipment=equipment_kind, months=months)}

    def record_correction(self, author_user_id, scope, field, corrected_value, reason, original_value=None):
        """scope: 'INS-...' (one inspection), 'WELL-...' (one well), 'type:T350' (whole well type)."""
        author = self.c.user_by_name(author_user_id)
        uid = author['user_id'] if author else author_user_id
        if scope.startswith('type:'):
            scope_type, scope_id = 'well_type', scope[5:]
        elif scope.upper().startswith('WELL-'):
            scope_type, scope_id = 'well', scope.upper()
        else:
            scope_type, scope_id = 'inspection', scope
        if original_value is None and scope_type == 'inspection':
            col = {'wellhead_temp_c': 'wellhead_temp_c', 'ambient_temp_c': 'ambient_temp_c',
                   'spill_est_volume_bbl': 'spill_est_volume_bbl'}.get(field)
            if col:
                r = self.c.q(f"SELECT {col} AS v FROM inspections WHERE inspection_id=?", (scope_id,))
                original_value = r[0]['v'] if r else None
        self.c.record_correction(uid, scope_type, scope_id, field, original_value, corrected_value, reason)
        out = {'recorded': True, 'scope': scope, 'field': field, 'original_value': original_value,
               'corrected_value': corrected_value, 'by': self._uname(uid)}
        # downstream consequences
        if scope_type == 'inspection':
            insp = self.c.q("SELECT * FROM inspections WHERE inspection_id=?", (scope_id,))
            if insp:
                insp = insp[0]
                w = self.c.well(insp['asset_id'])
                if field == 'wellhead_temp_c':
                    p = self.c.producing(insp, w['well_type'])
                    out['recomputed'] = {'well_id': w['asset_id'], 'producing_now': p['producing'],
                                         'wellhead_above_air_c': p['delta_c'], 'threshold_c': p['threshold_c']}
                    conflicts = []
                    if insp['notes'] and p['producing'] and re.search(r'not moving|stopped|down|shut', insp['notes'], re.I):
                        conflicts.append(f"inspection {insp['inspection_id']} note says: \"{insp['notes']}\" "
                                         f"(inspector {self._uname(insp['inspector_user_id'])}), which disagrees with the corrected reading")
                    other = self.c.q("SELECT * FROM notes WHERE inspection_id=? AND note_type!='correction'", (scope_id,))
                    for n in other:
                        conflicts.append(f"note {n['note_id']} by {self._uname(n['author_user_id'])}: {n['text']}")
                    if conflicts:
                        out['conflicts_to_surface'] = conflicts
                        out['must_do'] = 'tell the user about the conflict and ask them to confirm'
                if field == 'spill_est_volume_bbl':
                    vol = float(corrected_value)
                    was = insp['spill_est_volume_bbl'] or 0
                    out['reclassified'] = {'was_bbl': was, 'now_bbl': vol,
                                           'reportable_now': vol >= SPILL_REPORT_THRESHOLD,
                                           'reportable_before': was >= SPILL_REPORT_THRESHOLD}
                    if vol >= SPILL_REPORT_THRESHOLD > was:
                        regs = self.c.q("SELECT * FROM regulatory_events WHERE related_inspection_id=?", (scope_id,))
                        filed = [r for r in regs if r['event_type'] == 'spill_report_filed']
                        due_sr03 = day((parse_dt(insp['inspected_at']) + timedelta(days=SR03_VERIFY_DAYS)).isoformat())
                        out['new_obligations'] = {
                            'SR-01': ('written notice was due within 24 h of the inspection on ' + day(insp['inspected_at']) +
                                      ('; none is recorded - flag as a possible SR-01 breach' if not filed else '; filed')),
                            'SR-03': f'agency verification of clean-up due within 60 days, by {due_sr03}'}
                        for m in self.c.q("SELECT * FROM maintenance WHERE triggered_by_inspection_id=?", (scope_id,)):
                            if m.get('report_file'):
                                rid = m['report_file'].split('/')[-1][:-3]
                                out['stale_report'] = {'report_id': rid,
                                    'note': f'repair report {rid} was written against the old {was} bbl estimate; its spill class no longer holds'}
        return out

    def record_shared_note(self, author_user_id, well_id, text, valid_from=None, valid_to=None):
        author = self.c.user_by_name(author_user_id)
        uid = author['user_id'] if author else author_user_id
        self.c.record_shared_note(uid, well_id.upper(), text, valid_from, valid_to)
        return {'recorded': True, 'shared_with': 'all users', 'well_id': well_id.upper(),
                'by': self._uname(uid), 'text': text}

    def record_claim(self, author_user_id, well_id, text):
        author = self.c.user_by_name(author_user_id)
        uid = author['user_id'] if author else author_user_id
        r = self.c.record_claim(uid, well_id.upper(), text)
        r['by'] = self._uname(uid)
        r['must_do'] = 'if status is contradicted, tell the user what the data shows, keep both statements on record, and ask for confirmation'
        return r

    def recall_conversation(self, user_id, what='wells'):
        user = self.c.user_by_name(user_id)
        if not user: return {'error': f'unknown user {user_id}'}
        wells = self.c.recall_wells(user['user_id'])
        hist = self.c.chat_history(user['user_id'], limit=20)
        return {'user': user['name'], 'wells_discussed': wells,
                'recent_messages': [{'role': h['role'], 'text': h['text'][:300], 'wells': h['wells']} for h in hist],
                'note': "this is only THIS user's own history; never use another user's"}


    def get_spill_matrix(self, year=None, start=None, end=None):
        """Spill counts per area per month - compact, for heatmaps."""
        if year:
            start, end = f'{year}-01-01', f'{year}-12-31'
        areas = self.c.q("SELECT area_id, name FROM areas ORDER BY name")
        rows, cols, values, totals = [], [], [], {}
        months = set()
        per_area = {}
        for a in areas:
            counts = {}
            for s in self.c.spills(area_id=a['area_id'], start=start, end=end or self.c.today):
                m = s['date'][5:7]
                counts[m] = counts.get(m, 0) + 1
                months.add(m)
            per_area[a['name']] = counts
        cols = sorted(months)
        for name, counts in per_area.items():
            rows.append(name)
            values.append([counts.get(m, 0) for m in cols])
            totals[name] = sum(counts.values())
        return {'rows': rows, 'cols': cols, 'values': values, 'totals': totals,
                'window': [start, end or self.c.today],
                'note': 'formal corrections (not-a-spill) already removed',
                'evidence': ['inspections table', 'context correction notes']}

    def get_containment_breaches(self, area=None, well_id=None, days=None, months=None, limit_h=4.0):
        """Spills whose containment (from the repair report) exceeded the SOP limit."""
        if days: start = day((parse_dt(self.c.today) - timedelta(days=days)).isoformat())
        elif months: start = months_back(self.c.today, months)
        else: start = None
        aid = self._area_id(area)[0] if area else None
        out = []
        for s in self.c.spills(asset_id=well_id.upper() if well_id else None, area_id=aid,
                               start=start, end=self.c.today):
            for m in self.c.q("SELECT * FROM maintenance WHERE triggered_by_inspection_id=?", (s['inspection_id'],)):
                if m.get('report_file'):
                    rid = m['report_file'].split('/')[-1][:-3]
                    rep = self.c.q("SELECT containment_hours FROM reports WHERE report_id=?", (rid,))
                    ch = rep[0]['containment_hours'] if rep else None
                    if ch is not None and ch > limit_h:
                        out.append({'well_id': s['asset_id'], 'inspection_id': s['inspection_id'],
                                    'date': s['date'], 'volume_bbl': s['volume_bbl'],
                                    'containment_hours': ch, 'limit_h': limit_h,
                                    'maintenance_id': m['maintenance_id'], 'report_id': rid,
                                    'evidence': [rid, s['inspection_id']]})
        return {'count': len(out), 'breaches': out}

    def list_users(self):
        return {'users': self.c.q("SELECT u.user_id, u.name, u.role, t.name AS team FROM users u LEFT JOIN teams t ON t.team_id=u.team_id")}
