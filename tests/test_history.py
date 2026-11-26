import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import history as h


class Response(io.BytesIO):
    def __init__(self, data, url, headers):
        super().__init__(data)
        self.url = url
        self.headers = headers


class HistoryTests(unittest.TestCase):
    def test_truncated_transport_is_retried(self):
        with patch.object(h, 'fetch_package', side_effect=[ValueError('Incomplete historical package'), {'verified': True}]) as fetch, patch.object(h.time, 'sleep'):
            self.assertEqual(h.fetch_with_retry({'url': 'test'}), {'verified': True})
            self.assertEqual(fetch.call_count, 2)

    def test_historical_digest_mismatch_is_not_treated_as_network_retry(self):
        with patch.object(h, 'fetch_package', side_effect=ValueError('Live CDN payload differs from all archived binary SHA-1 digests')) as fetch:
            with self.assertRaisesRegex(ValueError, 'differs from all archived'):
                h.fetch_with_retry({'url': 'test'})
            fetch.assert_called_once()

    def test_checkpoint_reuses_only_matching_plan_and_remote_digest(self):
        url = 'https://a56.gdl.netease.com/uuyc_4.3.1.apk'
        candidate = h.package_url(url)
        package = {'resolved_url': url, 'asset_name': 'android--uuyc_4.3.1.apk', 'sha256': 'a' * 64, 'size': 2048}
        saved = {'tag': h.TAG, 'source_plan_sha256': 'plan-hash', 'packages': [package], 'run_url': 'https://github.com/owner/repo/actions/runs/1'}
        assets = {package['asset_name']: {'size': 2048, 'digest': 'sha256:' + 'a' * 64}}
        self.assertEqual(len(h.checkpoint_packages(saved, {'packages': [candidate]}, assets, 'plan-hash')), 1)
        self.assertEqual(h.checkpoint_packages(saved, {'packages': [candidate]}, assets, 'other-plan'), [])
        assets[package['asset_name']]['digest'] = 'sha256:' + 'b' * 64
        self.assertEqual(h.checkpoint_packages(saved, {'packages': [candidate]}, assets, 'plan-hash'), [])

    def test_prefetch_never_accumulates_more_than_three_packages(self):
        started = []
        three_started = threading.Event()
        def fetch(package):
            started.append(package)
            if len(started) == 3:
                three_started.set()
            return package
        with patch.object(h, 'fetch_with_retry', side_effect=fetch):
            generator = h.prefetched_packages(list(range(12)))
            number, package, future = next(generator)
            self.assertTrue(three_started.wait(2))
            self.assertEqual(len(started), 3)
            self.assertEqual(future.result(), 0)
            generator.close()
            self.assertEqual(len(started), 3)

    def test_unwrap_historical_redirect_and_remove_expired_query(self):
        url = 'https://web.archive.org/web/20241209064814id_/https://a56.gdl.netease.com/GameViewer_Setup_2.5.1.2910_1208161902_gwqd.exe?key1=old&key2=expired'
        package = h.package_url(url)
        self.assertEqual(package['platform'], 'windows')
        self.assertEqual(package['version'], '2.5.1.2910')
        self.assertNotIn('?', package['url'])

    def test_reject_unrelated_or_unofficial_binary(self):
        for url in ('https://evil.example/UURemote_Setup_1.2.3.exe',
                    'https://a56.gdl.netease.com.evil.example/UURemote_Setup_1.2.3.exe',
                    'https://a56.gdl.netease.com/OtherApp_Setup_1.2.3.exe',
                    'https://user@a56.gdl.netease.com/UURemote_Setup_1.2.3.exe',
                    'https://a56.gdl.netease.com/UURemote_Setup_1.2.3.html'):
            with self.subTest(url=url):
                self.assertIsNone(h.package_url(url))

    def test_archive_redirect_is_not_followed_to_live_api(self):
        row = {'timestamp': '20241209064814', 'original': 'https://api.nrd.nie.163.com/api/v1/release/dl/1?channel=gwqd'}
        location = 'https://web.archive.org/web/20241209064814id_/https://a56.gdl.netease.com/GameViewer_Setup_2.5.1.2910_1208161902_gwqd.exe'
        with patch.object(h, 'archive_get', return_value=(302, {'Memento-Datetime': 'Mon, 09 Dec 2024 06:48:14 GMT', 'Location': location}, b'')) as get:
            evidence, _ = h.replay(row)
        self.assertEqual(evidence['actual_timestamp'], '20241209064814')
        self.assertEqual(evidence['location'], location)
        get.assert_called_once()

    def test_reject_archive_error_page(self):
        with patch.object(h, 'archive_get', return_value=(200, {}, b'temporarily offline')):
            with self.assertRaisesRegex(ValueError, 'missing Memento'):
                h.replay({'timestamp': '20250101000000', 'original': h.PAGE})

    def test_cdx_redirects_are_not_collapsed_by_body_digest(self):
        with patch.object(h, 'archive_get', return_value=(200, {}, b'[["timestamp","original","statuscode","digest"]]')) as get:
            h.cdx('https://api.nrd.nie.163.com/api/v1/release/dl/', '20261127', prefix=True, status='302')
        self.assertNotIn('collapse', get.call_args.args[0])

    def test_compare_current_official_bytes_to_archived_payload_digest(self):
        body = b'MZ' + b'x' * 2046
        sha1 = base64.b32encode(hashlib.sha1(body).digest()).decode()
        package = h.package_url('https://a56.gdl.netease.com/UURemote_Setup_1.2.3.4_0101123456_gwqd.exe')
        package['evidence'] = [{'kind': 'archived-binary-index', 'digest': sha1}]
        source = {'http': {'content-length': str(len(body))}, 'platform': 'windows'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(h, 'OUT', Path(tmp)), patch.object(h, 'source_for', return_value=source), patch.object(h.mirror, 'request', return_value=Response(body, package['url'], source['http'])):
            result = h.fetch_package(package)
        self.assertTrue(result['archived_payload_sha1_verified'])
        self.assertEqual(result['sha256'], hashlib.sha256(body).hexdigest())

    def test_reject_changed_historical_payload(self):
        body = b'MZ' + b'x' * 2046
        package = h.package_url('https://a56.gdl.netease.com/UURemote_Setup_1.2.3.4_0101123456_gwqd.exe')
        package['evidence'] = [{'kind': 'archived-binary-index', 'digest': 'A' * 32}]
        source = {'http': {'content-length': str(len(body))}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(h, 'OUT', Path(tmp)), patch.object(h, 'source_for', return_value=source), patch.object(h.mirror, 'request', return_value=Response(body, package['url'], source['http'])):
            with self.assertRaisesRegex(ValueError, 'differs from all archived'):
                h.fetch_package(package)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_template_expansion_only_uses_observed_versions_and_labels_inference(self):
        android = h.package_url('https://a56.gdl.netease.com/uuyc_4.3.1.apk')
        windows = h.package_url('https://a56.gdl.netease.com/UURemote_Setup_4.4.0.1234_0101123456_gwqd.exe')
        for p in (android, windows):
            p['evidence'] = [{'kind': 'archived-binary-index', 'digest': 'A' * 32}]
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / 'plan.json'
            plan.write_text(json.dumps({'packages': [android, windows]}), encoding='utf-8')
            import os
            previous = os.getcwd()
            os.chdir(tmp)
            Path('dist').mkdir()
            try:
                with patch.object(h, 'PLAN', plan), patch.object(h.mirror, 'request', side_effect=ValueError('offline current template; use archived template')), patch.object(h.mirror.OPENER, 'open', return_value=Response(b'', 'https://a56.gdl.netease.com/uuyc_4.4.0.apk', {'Content-Length': '2048'})) as opened:
                    h.expand_plan()
                self.assertEqual(opened.call_count, 1)
                expanded = json.loads(plan.read_text(encoding='utf-8'))
                inferred = expanded['packages'][-1] if expanded['packages'][-1]['platform'] == 'android' else next(p for p in expanded['packages'] if p['url'].endswith('uuyc_4.4.0.apk'))
                self.assertEqual(inferred['evidence'][0]['kind'], 'version-template-derived')
                self.assertFalse(inferred['evidence'][0]['archive_evidence_is_direct'])
            finally:
                os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
