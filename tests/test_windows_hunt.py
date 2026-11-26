import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('windows_hunt', Path(__file__).parents[1] / 'scripts/windows-hunt.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


class WindowsHuntTests(unittest.TestCase):
    def test_old_timestamp_beijing_rollover(self):
        items = list(h.candidates({'version': '4.38.3.9325', 'timestamp_hints': ['20260821160752Z']}, 0))
        self.assertEqual(items[0][0], h.ROOT + 'UURemote_Setup_4.38.3.9325_0822000752_gwqd.exe')
        self.assertEqual(len(items), 2)

    def test_recent_timestamp_utc_radius_boundary(self):
        items = list(h.candidates({'version': '4.49.0.6162', 'timestamp_hints': ['20261126083942Z']}, 300))
        self.assertIn((h.ROOT + 'UURemote_Setup_4.49.0.6162_1126083648_gwqd.exe', -174), items)
        self.assertEqual(len(items), 1202)
        self.assertEqual(len({url for url, _ in items}), 1202)

    def test_delta_across_year(self):
        items = list(h.candidates({'version': '4.49.0.6162', 'timestamp_hints': ['20270101000001Z']}, 2))
        self.assertIn((h.ROOT + 'UURemote_Setup_4.49.0.6162_1231235959_gwqd.exe', -2), items)
