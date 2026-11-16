import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import io
import zipfile

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


if __name__ == '__main__':
    unittest.main()
