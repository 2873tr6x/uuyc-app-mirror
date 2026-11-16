import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import io
import zipfile
import argparse

spec = importlib.util.spec_from_file_location('mirror', Path(__file__).parents[1] / 'scripts/mirror.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Response(io.BytesIO):
    def __init__(self, content, url, headers=None):
        super().__init__(content)
        self.url = url
        self.headers = headers or {}


class MirrorTests(unittest.TestCase):
    def test_source_host_validation(self):
        m.allowed('https://a56.gdl.netease.com/a.exe?key1=temporary')
        for url in ('http://api.nrd.nie.163.com/a', 'https://netease.com.attacker.com/a',
                    'https://user@netease.com/a', 'https://localhost/a', 'file:///tmp/a',
                    'https://netease.com:8443/a'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                m.allowed(url)

    def test_signed_query_not_part_of_identity(self):
        self.assertEqual(m.stable_url('https://a56.gdl.netease.com/a.exe?key1=x&n=a#x'),
                         'https://a56.gdl.netease.com/a.exe')

    def test_resolve_official_adl_without_executing_javascript(self):
        page = '<button data-adl-type="pc"></button><a href="https://adl.netease.com/d/g/uuremote/c/gw?type=pc">'
        adl = b'var pc_link = "https://api.nrd.nie.163.com/api/v1/release/dl/1?channel=gwqd";'
        url = 'https://a56.gdl.netease.com/UURemote_Setup_4.48.0.5446_1116_gwqd.exe?key1=x'
        with patch.object(m, 'request', side_effect=[Response(adl, 'https://adl.netease.com/'), Response(b'', url, {'Content-Length': '2048'})]):
            source = m.probe('windows', page)
        self.assertEqual(source['version'], '4.48.0.5446')
        self.assertNotIn('key1', source['resolved_url'])
        self.assertEqual(source['http']['content-length'], '2048')

    def test_fail_closed_on_missing_source(self):
        with self.assertRaises(ValueError):
            m.probe('windows', '<html>maintenance</html>')

    def source(self, platform='windows'):
        return {'platform': platform, 'upstream_filename': 'uuyc_1.2.3.exe',
                'resolved_url': 'https://a56.gdl.netease.com/uuyc_1.2.3.exe',
                '_download_url': 'https://a56.gdl.netease.com/uuyc_1.2.3.exe?key1=x',
                'http': {'content-length': '2048', 'etag': 'same'}}

    def test_reject_html_even_with_success_status(self):
        source = self.source()
        with tempfile.TemporaryDirectory() as tmp, patch.object(m, 'DIST', Path(tmp)), patch.object(m.time, 'sleep'), patch.object(m, 'request', side_effect=lambda *a: Response(b'<' * 2048, source['resolved_url'], source['http'])):
            with self.assertRaisesRegex(ValueError, 'magic'):
                m.download(source)

    def test_reject_rollout_race(self):
        source = self.source()
        with tempfile.TemporaryDirectory() as tmp, patch.object(m, 'DIST', Path(tmp)), patch.object(m.time, 'sleep'), patch.object(m, 'request', side_effect=lambda *a: Response(b'MZ' + b'x' * 2046, source['resolved_url'], {**source['http'], 'etag': 'changed'})):
            with self.assertRaisesRegex(ValueError, 'metadata changed'):
                m.download(source)

    def test_download_hash_and_private_url_exclusion(self):
        source = self.source()
        with tempfile.TemporaryDirectory() as tmp, patch.object(m, 'DIST', Path(tmp)), patch.object(m, 'request', return_value=Response(b'MZ' + b'x' * 2046, source['resolved_url'], source['http'])):
            package = m.download(source)
        self.assertEqual(package['size'], 2048)
        self.assertEqual(len(package['sha256']), 64)
        self.assertNotIn('_download_url', package)

    def test_unchanged_probe_never_downloads(self):
        sources = [{**self.source(), 'platform': p, 'version': '1.2.3',
                    'endpoint_url': 'https://api.nrd.nie.163.com/a'} for p in m.PLATFORMS]
        args = argparse.Namespace(repo='owner/repo', publish=True, audit=False, probe_only=False)
        with tempfile.TemporaryDirectory() as tmp, patch.object(m, 'DIST', Path(tmp)), patch.object(m, 'request', return_value=Response(b'page', m.HOME)), patch.object(m, 'probe', side_effect=lambda p, _: next(s for s in sources if s['platform'] == p)), patch.object(m, 'latest', return_value={'packages': sources}), patch.object(m, 'download') as download:
            m.run(args)
            download.assert_not_called()

    def test_digest_failure_keeps_release_private(self):
        sources = [{**self.source(), 'platform': p, 'version': '1.2.3',
                    'endpoint_url': 'https://api.nrd.nie.163.com/a'} for p in m.PLATFORMS]
        args = argparse.Namespace(repo='owner/repo', publish=True, audit=True, probe_only=False)
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            def download(source):
                name = source['platform'] + '--uuyc.exe'
                (dist / name).write_bytes(b'MZ' + b'x' * 2046)
                return {**{k: v for k, v in source.items() if not k.startswith('_')},
                        'asset_name': name, 'size': 2048, 'sha256': m.file_sha256(dist / name)}
            def api(_):
                return {'id': 1, 'assets': [{'name': f.name, 'size': f.stat().st_size, 'digest': 'sha256:wrong'} for f in dist.iterdir()], 'html_url': 'https://github.com/owner/repo/releases/tag/test'}
            with patch.object(m, 'DIST', dist), patch.object(m, 'request', return_value=Response(b'page', m.HOME)), patch.object(m, 'probe', side_effect=lambda p, _: next(s for s in sources if s['platform'] == p)), patch.object(m, 'latest', return_value=None), patch.object(m, 'download', side_effect=download), patch.object(m, 'find_release', return_value={'id': 1, 'draft': True}), patch.object(m, 'api', side_effect=api), patch.object(m, 'gh', side_effect=lambda *a, **kw: calls.append(a)):
                with self.assertRaisesRegex(ValueError, 'digest verification failed'):
                    m.run(args)
        self.assertTrue(any(c[:2] == ('release', 'upload') for c in calls))
        self.assertFalse(any(c[:2] == ('release', 'edit') for c in calls))

    def test_draft_lookup_uses_paginated_list(self):
        draft = {'tag_name': 'uuyc-test', 'draft': True, 'id': 123}
        with patch.object(m, 'optional_api', return_value=None), patch.object(m, 'api', return_value=[[], [draft]]) as api:
            self.assertEqual(m.find_release('owner/repo', 'uuyc-test'), draft)
            self.assertIn('--paginate', api.call_args.args)


if __name__ == '__main__':
    unittest.main()
