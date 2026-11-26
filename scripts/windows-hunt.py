"""Bounded HEAD discovery using untrusted local signature timestamp hints; never executes EXEs."""
import concurrent.futures
import argparse
from datetime import datetime, timedelta, timezone
import json
import re
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT = 'https://a56.gdl.netease.com/'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def candidates(hint, radius=100):
    version = hint['version']
    for stamp in hint['timestamp_hints']:
        dt = datetime.strptime(stamp.split('.')[0].rstrip('Z'), '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
        # Recent official filename uses UTC (4.49.0 is independently known), older ones UTC+8.
        zones = (0, 8) if tuple(map(int, version.split('.')[:2])) >= (4, 39) else (8, 0)
        for hours in zones:
            local = dt.astimezone(timezone(timedelta(hours=hours)))
            for delta in [0] + [n for i in range(1, radius + 1) for n in (-i, i)]:
                name = f"UURemote_Setup_{version}_{(local + timedelta(seconds=delta)):%m%d%H%M%S}_gwqd.exe"
                yield ROOT + name, delta


def probe(item):
    url, delta = item
    time.sleep(.1)
    try:
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'uuyc-app-mirror historical recovery', 'Accept-Encoding': 'identity'}), timeout=12) as response:
            length = int(response.headers.get('Content-Length', 0))
            if response.status != 200 or length < 1024:
                return {'url': url, 'error': 'Unexpected HEAD response'}
            return {'url': url, 'offset_seconds': delta, 'size': length, 'headers': dict(response.headers.items())}
    except urllib.error.HTTPError as error:
        return None if error.code == 404 else {'url': url, 'error': str(error)}
    except (OSError, ValueError) as error:
        return {'url': url, 'error': str(error)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--radius', type=int, default=100, choices=(100, 300))
    args = parser.parse_args()
    hints = json.loads(Path('dist/windows-hints.json').read_text(encoding='utf-8-sig'))
    known = json.loads(Path('data/wayback-2026-11-27.json').read_text(encoding='utf-8'))
    versions = {p['version'] for p in known['packages'] if p['platform'] == 'windows'}
    output = Path('dist/windows-hunt.json')
    results = json.loads(output.read_text(encoding='utf-8')) if output.exists() else []
    results = [r for r in results if r.get('matches') or (r.get('skipped') and not r['hint']['version'].startswith('0.')) or r.get('radius_seconds', 0) >= args.radius]
    seen = {r['hint']['version'] for r in results}
    for hint in hints:
        if hint['version'] in seen:
            continue
        seen.add(hint['version'])
        if hint['version'] in versions:
            results.append({'hint': hint, 'skipped': 'Version already archived'})
            continue
        result = {'hint': hint, 'radius_seconds': args.radius, 'timezone_candidates': ['UTC', 'UTC+08:00'], 'attempts': 0, 'errors': [], 'matches': []}
        if re.fullmatch(r'UURemote_Setup_\d+\.\d+\.\d+\.\d+_\d{10}_[A-Za-z0-9_.-]+\.exe', hint['name']):
            response = probe((ROOT + hint['name'], None))
            result['attempts'] += 1
            if response and 'error' not in response:
                response['discovery'] = 'retained-original-filename'
                result['matches'].append(response)
        # Batches bound concurrency and avoid eagerly submitting all requests after a match.
        items = list(candidates(hint, args.radius))
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            for start in range(0, len(items), 6):
                if result['matches']:
                    break
                for response in pool.map(probe, items[start:start + 6]):
                    result['attempts'] += 1
                    if response and 'error' in response:
                        result['errors'].append(response)
                    elif response:
                        for stamp in hint['timestamp_hints']:
                            dt = datetime.strptime(stamp.split('.')[0].rstrip('Z'), '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
                            for hours in (0, 8):
                                token = (dt + timedelta(hours=hours, seconds=response['offset_seconds'])).strftime('%m%d%H%M%S')
                                if '_' + token + '_' in response['url']:
                                    response['filename_timezone'] = 'UTC' if hours == 0 else 'UTC+08:00'
                        result['matches'].append(response)
                if result['matches']:
                    break
        results.append(result)
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(hint['version'], 'matches', len(result['matches']), 'attempts', result['attempts'], 'errors', len(result['errors']), flush=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
