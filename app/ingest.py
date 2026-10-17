"""Load a FlytBase Asset Intelligence dataset folder into SQLite."""
import json, os, re, sqlite3, sys

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS areas(area_id TEXT PRIMARY KEY, name TEXT, team_id TEXT, lat REAL, lon REAL);
CREATE TABLE IF NOT EXISTS teams(team_id TEXT PRIMARY KEY, name TEXT, lead_user_id TEXT);
CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT, team_id TEXT);
CREATE TABLE IF NOT EXISTS area_wells(area_id TEXT, asset_id TEXT, PRIMARY KEY(area_id, asset_id));
CREATE TABLE IF NOT EXISTS wells(asset_id TEXT PRIMARY KEY, name TEXT, well_type TEXT, area_id TEXT, team_id TEXT,
    in_charge_user_id TEXT, lat REAL, lon REAL, installed_on TEXT, recorded_status TEXT,
    last_inspection_id TEXT, last_inspected_at TEXT, last_inspector_user_id TEXT);
CREATE TABLE IF NOT EXISTS equipment(asset_id TEXT, equipment_id TEXT, kind TEXT, model TEXT, PRIMARY KEY(asset_id, equipment_id));
CREATE TABLE IF NOT EXISTS inspections(inspection_id TEXT PRIMARY KEY, asset_id TEXT, inspected_at TEXT,
    inspector_user_id TEXT, method TEXT, ambient_temp_c REAL, wellhead_temp_c REAL,
    spill_detected INTEGER, spill_area_pct REAL, spill_est_volume_bbl REAL, notes TEXT);
CREATE INDEX IF NOT EXISTS idx_insp_well ON inspections(asset_id, inspected_at);
CREATE INDEX IF NOT EXISTS idx_insp_time ON inspections(inspected_at);
CREATE TABLE IF NOT EXISTS maintenance(maintenance_id TEXT PRIMARY KEY, asset_id TEXT, started_at TEXT, completed_at TEXT,
    maintenance_type TEXT, equipment_kind TEXT, issue TEXT, action_taken TEXT, technician_user_id TEXT,
    contractor TEXT, downtime_hours REAL, cost_labor REAL, cost_parts REAL, cost_total REAL,
    triggered_by_inspection_id TEXT, report_file TEXT);
CREATE INDEX IF NOT EXISTS idx_mnt_well ON maintenance(asset_id, started_at);
CREATE TABLE IF NOT EXISTS regulatory_events(event_id TEXT PRIMARY KEY, asset_id TEXT, date TEXT, agency TEXT,
    event_type TEXT, protocol_id TEXT, related_inspection_id TEXT, hours_to_report REAL, detail TEXT,
    fine_usd REAL, status TEXT);
CREATE TABLE IF NOT EXISTS notes(note_id TEXT PRIMARY KEY, asset_id TEXT, created_at TEXT, author_user_id TEXT,
    note_type TEXT, inspection_id TEXT, text TEXT, valid_from TEXT, valid_to TEXT);
CREATE INDEX IF NOT EXISTS idx_notes_well ON notes(asset_id);
CREATE TABLE IF NOT EXISTS reports(report_id TEXT PRIMARY KEY, asset_id TEXT, path TEXT, text TEXT,
    containment_hours REAL, spill_inspection_id TEXT);
CREATE TABLE IF NOT EXISTS docs(doc_id TEXT PRIMARY KEY, kind TEXT, title TEXT, path TEXT, text TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(doc_id, title, text, tokenize='porter');
CREATE VIRTUAL TABLE IF NOT EXISTS reports_fts USING fts5(report_id, text, tokenize='porter');
"""

CONTAIN_RE = re.compile(r'contain(?:ed|ment)\s+(?:was\s+)?(?:took\s+)?(?:about\s+|roughly\s+|approximately\s+)?([\d.]+)\s*hours?', re.I)
SPILL_INS_RE = re.compile(r'inspection\s+(INS-[\w-]+)', re.I)

def load_jsonl(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

def ingest(data_dir, db_path, append=False):
    if os.path.exists(db_path) and not append:
        os.remove(db_path)
    fresh = not os.path.exists(db_path)
    db = sqlite3.connect(db_path)
    if fresh or not append:
        db.executescript(SCHEMA)
    fleet = os.path.join(data_dir, 'fleet')
    areas = json.load(open(os.path.join(fleet, 'areas.json')))
    for t in areas.get('teams', []):
        db.execute("INSERT OR REPLACE INTO teams VALUES (?,?,?)", (t['team_id'], t['name'], t.get('lead_user_id')))
    for a in areas['areas']:
        db.execute("INSERT OR REPLACE INTO areas VALUES (?,?,?,?,?)",
                   (a['area_id'], a['name'], a['team_id'], a['center']['lat'], a['center']['lon']))
        for w in a['asset_ids']:
            db.execute("INSERT OR REPLACE INTO area_wells VALUES (?,?)", (a['area_id'], w))
    users = json.load(open(os.path.join(fleet, 'users.json')))
    for u in users['users']:
        db.execute("INSERT OR REPLACE INTO users VALUES (?,?,?,?)", (u['user_id'], u['name'], u['role'], u['team_id']))
    # fleet documents (manuals + sops)
    for sub, kind in (('well-types', 'manual'), ('sops', 'sop')):
        d = os.path.join(fleet, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith('.md'):
                continue
            text = open(os.path.join(d, fn)).read()
            doc_id = fn[:-3]
            title = text.split('\n', 1)[0].lstrip('# ').strip()
            db.execute("INSERT OR REPLACE INTO docs VALUES (?,?,?,?,?)", (doc_id, kind, title, f'fleet/{sub}/{fn}', text))
            db.execute("INSERT INTO docs_fts(doc_id, title, text) VALUES (?,?,?)", (doc_id, title, text))
    assets_dir = os.path.join(data_dir, 'assets')
    wells = sorted(os.listdir(assets_dir))
    for w in wells:
        wdir = os.path.join(assets_dir, w)
        if not os.path.isdir(wdir):
            continue
        md = json.load(open(os.path.join(wdir, 'metadata.json')))
        li = md.get('last_inspection') or {}
        db.execute("INSERT OR REPLACE INTO wells VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (md['asset_id'], md['name'], md['well_type'], md['area_id'], md['team_id'],
                    md.get('in_charge_user_id'), md['location']['lat'], md['location']['lon'],
                    md.get('installed_on'), md.get('recorded_status'),
                    li.get('inspection_id'), li.get('inspected_at'), li.get('inspector_user_id')))
        for e in md.get('equipment', []):
            db.execute("INSERT OR REPLACE INTO equipment VALUES (?,?,?,?)",
                       (md['asset_id'], e['equipment_id'], e['kind'], e['model']))
        for fn, table in (('inspections.jsonl', 'inspections'), ('maintenance.jsonl', 'maintenance'),
                          ('regulatory-events.jsonl', 'regulatory_events'), ('context.jsonl', 'notes')):
            p = os.path.join(wdir, fn)
            if not os.path.exists(p):
                continue
            for r in load_jsonl(p):
                if table == 'inspections':
                    db.execute("INSERT OR REPLACE INTO inspections VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (r['inspection_id'], r['asset_id'], r['inspected_at'], r['inspector_user_id'], r['method'],
                         r['ambient_temp_c'], r['wellhead_temp_c'], int(bool(r['spill_detected'])),
                         r.get('spill_area_pct'), r.get('spill_est_volume_bbl'), r.get('notes') or ''))
                elif table == 'maintenance':
                    c = r.get('cost_usd') or {}
                    db.execute("INSERT OR REPLACE INTO maintenance VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r['maintenance_id'], r['asset_id'], r['started_at'], r.get('completed_at'),
                         r['maintenance_type'], r['equipment_kind'], r['issue'], r['action_taken'],
                         r.get('technician_user_id'), r.get('contractor'), r.get('downtime_hours'),
                         c.get('labor'), c.get('parts'), c.get('total'),
                         r.get('triggered_by_inspection_id'), r.get('report_file')))
                elif table == 'regulatory_events':
                    db.execute("INSERT OR REPLACE INTO regulatory_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (r['event_id'], r['asset_id'], r['date'], r['agency'], r['event_type'], r.get('protocol_id'),
                         r.get('related_inspection_id'), r.get('hours_to_report'), r.get('detail'),
                         r.get('fine_usd'), r.get('status')))
                elif table == 'notes':
                    db.execute("INSERT OR REPLACE INTO notes VALUES (?,?,?,?,?,?,?,?,?)",
                        (r['note_id'], r['asset_id'], r['created_at'], r['author_user_id'], r['note_type'],
                         r.get('inspection_id'), r['text'], r.get('valid_from'), r.get('valid_to')))
        rdir = os.path.join(wdir, 'maintenance-reports')
        if os.path.isdir(rdir):
            for fn in sorted(os.listdir(rdir)):
                if not fn.endswith('.md'):
                    continue
                text = open(os.path.join(rdir, fn)).read()
                rid = fn[:-3]
                m = CONTAIN_RE.search(text)
                hours = float(m.group(1)) if m else None
                sm = SPILL_INS_RE.search(text)
                db.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?,?,?,?)",
                           (rid, w, f'assets/{w}/maintenance-reports/{fn}', text, hours,
                            sm.group(1) if sm else None))
                db.execute("INSERT INTO reports_fts(report_id, text) VALUES (?,?)", (rid, text))
    db.execute("INSERT OR REPLACE INTO meta VALUES ('data_dir', ?)", (data_dir,))
    db.commit()
    stats = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
             for t in ('wells', 'inspections', 'maintenance', 'regulatory_events', 'notes', 'reports', 'docs', 'users')}
    db.close()
    return stats

if __name__ == '__main__':
    stats = ingest(sys.argv[1], sys.argv[2], append='--append' in sys.argv)
    print(json.dumps(stats, indent=1))
