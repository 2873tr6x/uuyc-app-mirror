"""Publish only official CDN downloads, after Windows Authenticode and version validation."""
import argparse
import json
from pathlib import Path
import subprocess

import history

original_fetch = history.fetch_package


def verified_fetch(package):
    recovered = original_fetch(package)
    path = history.OUT / recovered['asset_name']
    script = Path(__file__).with_name('verify-windows.ps1')
    check = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), '-Path', str(path.resolve()), '-Version', package['version']], check=True, capture_output=True, encoding='utf-8')
    recovered['authenticode'] = json.loads(check.stdout)
    recovered['matches_untrusted_hint_sha256'] = recovered['sha256'] in {e['hint']['sha256'] for e in package['evidence'] if e['kind'] == 'signature-time-derived'}
    return recovered


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--repo', default='2873tr6x/uuyc-app-mirror')
    args = parser.parse_args()
    history.PLAN = Path('data/windows-signature-recovery-2026-11-27.json')
    history.OUT = Path('dist/windows-recovery')
    history.TAG = 'uuyc-windows-history-2026-11-27'
    history.fetch_package = verified_fetch
    history.execute(args)
