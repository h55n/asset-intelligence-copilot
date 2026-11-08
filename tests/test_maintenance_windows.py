"""Offline synthetic SQLite regressions; no sample dataset or model is needed."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import Copilot
from tools import Tools


class MaintenanceWindows(unittest.TestCase):
    def setUp(self):
        self.c = Copilot(':memory:', today='2026-11-08')
        self.c.db.executescript('''
            CREATE TABLE wells(asset_id TEXT, well_type TEXT, area_id TEXT, lat REAL, lon REAL);
            INSERT INTO wells VALUES ('W1', 'T200', 'A1', 0, 0);
            INSERT INTO wells VALUES ('W2', 'T200', 'A2', 0, 0);
            CREATE TABLE maintenance(maintenance_id TEXT, asset_id TEXT,
                maintenance_type TEXT, equipment_kind TEXT, started_at TEXT);
        ''')

    def tearDown(self):
        self.c.db.close()

    def add(self, id, date, well='W1', kind='corrective', equipment='pump_jack'):
        self.c.db.execute('INSERT INTO maintenance VALUES (?,?,?,?,?)', (id, well, kind, equipment, date))

    def test_future_repairs_cannot_trigger_rca(self):
        self.add('past1', '2026-10-01T09:00:00Z')
        self.add('past2', '2026-11-08T23:59:59.999Z')
        self.add('future', '2026-11-09T00:00:00Z')
        self.assertEqual(self.c.rca_needed(), [])

    def test_rca_counts_today_but_not_tomorrow_or_other_areas(self):
        for id, date in [('a', '2026-10-01T09:00:00Z'), ('b', '2026-11-08T00:00:00Z'), ('c', '2026-11-08T23:59:59.999Z')]:
            self.add(id, date)
        self.add('future', '2026-11-09')
        for i in range(3):
            self.add(f'other{i}', '2026-10-01', well='W2')
        rows = self.c.rca_needed(area_id='A1')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['corrective_repairs'], 3)
        self.assertEqual(set(rows[0]['maintenance_ids']), {'a', 'b', 'c'})

    def test_repairs_include_last_second_and_fractional_last_second(self):
        self.add('last', '2026-11-08T23:59:59Z')
        self.add('fraction', '2026-11-08T23:59:59.999Z')
        self.add('next', '2026-11-09T00:00:00Z')
        self.assertEqual([r['maintenance_id'] for r in self.c.repairs(end='2026-11-08')], ['fraction', 'last'])

    def test_downtime_includes_the_whole_end_date(self):
        self.c.db.executescript('''
            CREATE TABLE inspections(inspection_id TEXT, asset_id TEXT,
                inspected_at TEXT, wellhead_temp_c REAL, ambient_temp_c REAL);
            INSERT INTO inspections VALUES ('last', 'W1', '2026-11-08T23:59:59Z', 20, 20);
            INSERT INTO inspections VALUES ('fraction', 'W1', '2026-11-08T23:59:59.999Z', 20, 20);
            INSERT INTO inspections VALUES ('next', 'W1', '2026-11-09T00:00:00Z', 20, 20);
        ''')
        result = self.c.downtime('W1', '2026-11-08', '2026-11-08')
        self.assertEqual(result['days'], 14)
        self.assertEqual([r['inspection_id'] for r in result['inspections']], ['fraction', 'last'])
        series = Tools(self.c).get_temperature_series('W1', start='2026-11-08', end='2026-11-08')
        self.assertEqual(series['evidence'], ['fraction', 'last'])

    def test_spills_include_the_whole_end_date(self):
        self.c.db.executescript('''
            CREATE TABLE notes(note_type TEXT, inspection_id TEXT);
            CREATE TABLE inspections(inspection_id TEXT, asset_id TEXT,
                inspected_at TEXT, spill_detected INTEGER, spill_area_pct REAL,
                spill_est_volume_bbl REAL);
            INSERT INTO inspections VALUES ('last', 'W1', '2026-11-08T23:59:59Z', 1, 2, 6);
            INSERT INTO inspections VALUES ('fraction', 'W1', '2026-11-08T23:59:59.999Z', 1, 2, 6);
            INSERT INTO inspections VALUES ('next', 'W1', '2026-11-09T00:00:00Z', 1, 2, 6);
        ''')
        self.assertEqual([r['inspection_id'] for r in self.c.spills(end='2026-11-08')], ['fraction', 'last'])

    def test_existing_type_equipment_and_lower_bound_filters_stay_active(self):
        for i in range(3):
            self.add(f'old{i}', '2024-01-01')
            self.add(f'preventive{i}', '2026-10-01', kind='preventive')
            self.add(f'other-equipment{i}', '2026-10-01', equipment='motor')
        self.assertEqual(self.c.rca_needed(), [])


if __name__ == '__main__':
    unittest.main()
