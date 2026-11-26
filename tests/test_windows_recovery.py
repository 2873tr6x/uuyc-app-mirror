import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('windows_recover', Path(__file__).parents[1] / 'scripts/windows-recover.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class WindowsRecoveryTests(unittest.TestCase):
    def test_reject_signature_failure_before_package_is_returned_for_upload(self):
        downloaded = {'asset_name': 'windows--official.exe', 'sha256': 'a' * 64}
        error = subprocess.CalledProcessError(1, ['pwsh'])
        with patch.object(w, 'original_fetch', return_value=downloaded), patch.object(w.subprocess, 'run', side_effect=error):
            with self.assertRaises(subprocess.CalledProcessError):
                w.verified_fetch({'version': '4.1.2.3'})

    def test_channel_hash_difference_is_recorded_without_substituting_local_file(self):
        downloaded = {'asset_name': 'windows--official.exe', 'sha256': 'a' * 64}
        package = {'version': '4.1.2.3', 'evidence': [{'kind': 'signature-time-derived', 'hint': {'sha256': 'b' * 64}}]}
        with patch.object(w, 'original_fetch', return_value=downloaded), patch.object(w.subprocess, 'run', return_value=SimpleNamespace(stdout='{"status":"Valid"}')) as verify:
            result = w.verified_fetch(package)
        self.assertFalse(result['matches_untrusted_hint_sha256'])
        self.assertEqual(result['sha256'], 'a' * 64)
        self.assertIn('windows--official.exe', verify.call_args.args[0][-3])
        self.assertTrue(verify.call_args.kwargs['check'])
