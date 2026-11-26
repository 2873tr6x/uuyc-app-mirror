#!/usr/bin/env python3
"""One-shot Wayback evidence discovery and official-CDN historical backfill."""
import argparse
import base64
import concurrent.futures
from collections import deque
from datetime import datetime, timezone
import email.utils
import gzip
import hashlib
import html
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import mirror

ARCHIVE = 'https://web.archive.org'
PLAN = Path('data/wayback-2026-11-27.json')
OUT = Path('dist/history')
TAG = 'uuyc-history-2026-11-27'
PAGE = 'https://uuyc.163.com/download/'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


ARCHIVE_OPENER = urllib.request.build_opener(NoRedirect())


def archive_get(url):
    if urllib.parse.urlsplit(url).netloc != 'web.archive.org' or not url.startswith('https://'):
        raise ValueError('Archive requests must stay on web.archive.org')
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'uuyc-app-mirror historical research', 'Accept-Encoding': 'gzip'})
            try:
                response = ARCHIVE_OPENER.open(req, timeout=40)
            except urllib.error.HTTPError as error:
                if error.code not in (301, 302, 303, 307, 308):
                    raise
                response = error
            with response:
                body = response.read(12_000_001)
                if len(body) > 12_000_000:
                    raise ValueError('Oversized archive response')
                if body.startswith(b'\x1f\x8b'):
                    body = gzip.decompress(body)
                return response.status, dict(response.headers.items()), body
        except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError):
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def header(headers, key):
    return next((v for k, v in headers.items() if k.lower() == key.lower()), None)


def cdx(url, until, prefix=False, collapse=None, status=None):
    params = {'url': url, 'output': 'json', 'fl': 'timestamp,original,statuscode,digest',
              'to': until, 'filter': 'statuscode:' + (status or '(200|301|302|307|308)')}
    if prefix:
        params['matchType'] = 'prefix'
    if collapse:
        params['collapse'] = collapse
    query = ARCHIVE + '/cdx/search/cdx?' + urllib.parse.urlencode(params)
    code, _, body = archive_get(query)
    if code != 200:
        raise ValueError('CDX status ' + str(code))
    rows = json.loads(body)
    if not rows:
        return query, []
    if rows[0] != ['timestamp', 'original', 'statuscode', 'digest']:
        raise ValueError('Unexpected CDX columns')
    if len(rows) > 20000:
        raise ValueError('Index unexpectedly large; review before processing')
    return query, [dict(zip(rows[0], row)) for row in rows[1:]]


def unwrap(url):
    url = html.unescape(url).replace('\\/', '/')
    for _ in range(4):
        match = re.match(r'(?:https?://web\.archive\.org)?/web/\d+(?:[a-z]+_)?/(https?://.+)', url)
        if not match:
            break
        url = match[1]
    return url


def package_url(url):
    url = unwrap(url)
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ''
    if p.scheme not in ('http', 'https') or not host.endswith('.gdl.netease.com') or p.username or p.password or p.port not in (None, 80, 443):
        return None
    filename = urllib.parse.unquote(p.path.rsplit('/', 1)[-1])
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', filename):
        return None
    if not re.match(r'(?i)(?:uuremote|uuyc|gameviewer)[_-]', filename):
        return None
    version = re.search(r'\d+\.\d+\.\d+(?:\.\d+)?', filename)
    if not version:
        return None
    if filename.lower().endswith('.exe') and '_setup_' in filename.lower():
        platform = 'windows'
    elif filename.lower().endswith(('.pkg', '.dmg')):
        platform = 'macos'
    elif filename.lower().endswith('.apk'):
        platform = 'android-tv' if re.search(r'(?i)(?:[-_]tv|tvProduction)', filename) else 'android'
    else:
        return None
    return {'url': urllib.parse.urlunsplit(('https', p.hostname, p.path, '', '')),
            'platform': platform, 'version': version[0], 'filename': filename}


def replay(record):
    replay_url = ARCHIVE + '/web/' + record['timestamp'] + 'id_/' + record['original']
    current = replay_url
    for _ in range(5):
        status, headers, body = archive_get(current)
        location = header(headers, 'location')
        memento = header(headers, 'memento-datetime')
        if memento:
            stamp = email.utils.parsedate_to_datetime(memento).strftime('%Y%m%d%H%M%S')
            return {'requested_replay_url': replay_url, 'replay_url': current,
                    'requested_timestamp': record['timestamp'], 'actual_timestamp': stamp,
                    'original': record['original'], 'status': status,
                    'archived_response_date': header(headers, 'x-archive-orig-date'),
                    'location': header(headers, 'x-archive-orig-location') or location,
                    'response_headers': {k: v for k, v in headers.items() if k.lower().startswith('x-archive-orig-') or k.lower() in ('memento-datetime', 'location', 'link')},
                    'body_sha256': hashlib.sha256(body).hexdigest()}, body
        if location:
            new_url = urllib.parse.urljoin(current, location)
            if urllib.parse.urlsplit(new_url).netloc == 'web.archive.org':
                current = new_url
                continue
        raise ValueError('Replay is not an archived response (missing Memento-Datetime)')
    raise ValueError('Too many archive navigation redirects')


def discover(args):
    PLAN.parent.mkdir(exist_ok=True)
    cache = Path('dist/history-discovery-cache.json')
    cache.parent.mkdir(exist_ok=True)
    state = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {'indexes': {}, 'replays': {}}
    queries = [(PAGE, False, 'digest', '200'),
               ('https://api.nrd.nie.163.com/api/v1/release/dl/', True, None, '302'),
               ('https://adl.netease.com/d/g/uuremote/c/', True, 'digest', '200')]
    for prefix in ('UURemote_', 'UURemote-', 'GameViewer_', 'GameViewer-', 'uuyc_', 'gameviewer_'):
        queries.append(('https://a56.gdl.netease.com/' + prefix, True, None, '200'))
    errors = []
    candidates = {}

    def add(url, evidence):
        package = package_url(url)
        if not package:
            return
        item = candidates.setdefault(package['url'], {**package, 'evidence': []})
        if evidence not in item['evidence']:
            item['evidence'].append(evidence)

    records = []
    for url, prefix, collapse, status in queries:
        key = json.dumps([url, prefix, collapse, status, args.until])
        try:
            if key not in state['indexes']:
                query, rows = cdx(url, args.until, prefix, collapse, status)
                state['indexes'][key] = {'query': query, 'records': rows}
                mirror.write_json(cache, state)
            result = state['indexes'][key]
            mirror.summary(f"Indexed {url}: {len(result['records'])} captures")
            for row in result['records']:
                if package_url(row['original']) and row['statuscode'] == '200':
                    add(row['original'], {'kind': 'archived-binary-index', 'index_query': result['query'], **row,
                                         'replay_url': ARCHIVE + '/web/' + row['timestamp'] + 'id_/' + row['original']})
                else:
                    records.append(row)
        except Exception as error:
            errors.append({'phase': 'index', 'url': url, 'error': str(error)})
            mirror.summary('Index unavailable: ' + url + ' · ' + str(error))

    records = list({(r['timestamp'], r['original']): r for r in records}.values())

    def read_record(row):
        key = row['timestamp'] + '/' + row['original']
        if key in state['replays']:
            return key, state['replays'][key]
        evidence, body = replay(row)
        links = re.findall(r'https?[^\s<>"\']+', html.unescape(body.decode('utf-8', errors='replace')).replace('\\/', '/'))
        urls = [evidence['location']] if evidence['location'] else []
        urls += [u.rstrip(');,') for u in links]
        # Store relevant literals, never execute JavaScript or fetch archived binaries.
        return key, {'evidence': evidence, 'links': list(dict.fromkeys(urls))}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {pool.submit(read_record, r): r for r in records}
        for future in concurrent.futures.as_completed(jobs):
            row = jobs[future]
            try:
                key, result = future.result()
                state['replays'][key] = result
                mirror.write_json(cache, state)
                evidence = result['evidence']
                if evidence['actual_timestamp'][:8] > args.until:
                    raise ValueError('Replay drifted past discovery cutoff')
                for url in result['links']:
                    add(url, {'kind': 'archived-redirect' if evidence['location'] and url == evidence['location'] else 'archived-page-link', **evidence})
                mirror.summary(f"Read archived response {row['timestamp']} · {row['original']}")
            except Exception as error:
                errors.append({'phase': 'replay', **row, 'error': str(error)})
                mirror.summary('Replay unavailable: ' + row['timestamp'] + ' · ' + str(error))

    packages = sorted(candidates.values(), key=lambda x: (x['platform'], tuple(map(int, x['version'].split('.'))), x['filename']))
    if not packages:
        raise ValueError('No archive-supported official packages found')
    plan = {'schema_version': 1, 'discovered_at': mirror.now(), 'capture_until': args.until,
            'method': 'Wayback CDX + archived HTTP redirects/page links; binaries downloaded only from live official NetEase CDN',
            'indexes': list(state['indexes'].values()), 'coverage_errors': errors, 'packages': packages}
    mirror.write_json(PLAN, plan)
    mirror.summary('Frozen historical source plan: ' + str(PLAN) + f' · {len(packages)} packages · {len(errors)} coverage errors')


def source_for(package):
    parsed = package_url(package['url'])
    if not parsed or any(parsed[k] != package[k] for k in ('platform', 'version', 'filename', 'url')):
        raise ValueError('Candidate identity does not match official URL')
    if not package.get('evidence'):
        raise ValueError('Candidate lacks archived evidence')
    with mirror.request(package['url'], 'HEAD') as response:
        if mirror.stable_url(response.url) != package['url']:
            raise ValueError('Historical CDN path redirects to a different package')
        headers = {k.lower(): response.headers.get(k) for k in mirror.HEADERS}
    return {'platform': package['platform'], 'version': package['version'], 'version_source': 'official-filename',
            'architecture': 'unspecified-by-download-page', 'resolved_url': package['url'],
            '_download_url': package['url'], 'upstream_filename': package['filename'], 'http': headers}


def expand_plan():
    """Try only archive-observed versions against archive-observed simple templates."""
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    direct = [p for p in plan['packages'] if not any(e['kind'] == 'version-template-derived' for e in p['evidence'])]
    versions = {}
    templates = {}
    for package in direct:
        version = '.'.join(package['version'].split('.')[:3])
        versions.setdefault(version, []).append(package['url'])
    template_sources = list(direct)
    current_templates = []
    template_errors = []
    try:
        with mirror.request(mirror.HOME) as response:
            current_page = response.read(3_000_000).decode('utf-8')
        for platform in ('android', 'macos'):
            current = mirror.probe(platform, current_page)
            current_templates.append({k: v for k, v in current.items() if not k.startswith('_')})
            template_sources.append({'platform': platform, 'url': current['resolved_url'],
                                     'version': current['version'], 'filename': current['upstream_filename']})
    except (OSError, ValueError, urllib.error.URLError) as error:
        template_errors.append(str(error))
    for package in template_sources:
        filename = package['filename']
        if package['platform'] == 'android' and re.fullmatch(r'uuyc_\d+\.\d+\.\d+\.apk', filename, re.I):
            templates[package['url'].replace(package['version'], '{version}')] = package['url']
        if package['platform'] == 'macos' and re.fullmatch(r'(?:uuyc_|UURemote-|GameViewer-)\d+\.\d+\.\d+(?:[-_][A-Za-z][A-Za-z0-9_-]*)?\.(?:pkg|dmg)', filename, re.I):
            templates[package['url'].replace(package['version'], '{version}')] = package['url']
    known = {p['url'] for p in plan['packages']}
    candidates = {}
    cache_path = Path('dist/history-expansion-cache.json')
    cached_heads = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
    for template, template_source in templates.items():
        for version, version_sources in versions.items():
            url = template.format(version=version)
            if url in known:
                continue
            item = package_url(url)
            item['evidence'] = [{'kind': 'version-template-derived', 'template': template,
                                 'template_source_url': template_source,
                                 'version_source_urls': version_sources,
                                 'archive_evidence_is_direct': False,
                                 'note': 'Version observed in archived sources, possibly another platform; template observed in an archived or current official download. This platform-specific URL is inferred and validated against live official CDN.'}]
            candidates[url] = item

    def head(item):
        if item['url'] in cached_heads:
            previous = cached_heads[item['url']]
            if previous['error']:
                return None, previous['error']
            return {**item, **previous['verification']}, None
        for attempt in range(2):
            try:
                req = urllib.request.Request(mirror.allowed(item['url']), method='HEAD', headers={'User-Agent': 'uuyc-app-mirror history discovery'})
                with mirror.OPENER.open(req, timeout=20) as response:
                    if mirror.stable_url(response.url) != item['url']:
                        raise ValueError('Derived URL redirects to a different path')
                    if int(response.headers.get('Content-Length', '0')) < 1024:
                        raise ValueError('Derived URL does not expose a nonempty package')
                    item['derived_url_verified_at'] = mirror.now()
                    item['http_at_discovery'] = {k.lower(): response.headers.get(k) for k in mirror.HEADERS}
                return item, None
            except urllib.error.HTTPError as error:
                if error.code in (403, 404, 410) or attempt == 1:
                    return None, {'url': item['url'], 'error': 'HTTP ' + str(error.code)}
            except (OSError, ValueError, urllib.error.URLError) as error:
                if attempt == 1:
                    return None, {'url': item['url'], 'error': str(error)}
            time.sleep(1)

    accepted, rejected = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for item, error in pool.map(head, candidates.values()):
            if item:
                accepted.append(item)
                cached_heads[item['url']] = {'error': None, 'verification': {k: item[k] for k in ('derived_url_verified_at', 'http_at_discovery')}}
                mirror.summary('Verified derived official URL: ' + item['url'])
            else:
                rejected.append(error)
                cached_heads[error['url']] = {'error': error}
            mirror.write_json(cache_path, cached_heads)
    plan['packages'] += accepted
    plan['packages'].sort(key=lambda p: (p['platform'], tuple(map(int, p['version'].split('.'))), p['filename']))
    plan['template_expansion'] = {'created_at': mirror.now(), 'templates': templates,
                                  'current_official_template_sources': current_templates,
                                  'current_template_errors': template_errors,
                                  'version_source': 'Only versions observed in directly archived package URLs; platform versions remain independent',
                                  'accepted': len(accepted), 'rejected': rejected}
    mirror.write_json(PLAN, plan)
    mirror.summary(f'Derived URL expansion: {len(accepted)} available, {len(rejected)} rejected; {len(plan["packages"])} total candidates')


def fetch_package(package):
    source = source_for(package)
    name = package['platform'] + '--' + package['filename']
    path = OUT / name
    digest = hashlib.sha256()
    size = 0
    with mirror.request(package['url']) as response, path.open('wb') as stream:
        if mirror.stable_url(response.url) != package['url']:
            raise ValueError('Historical package redirected during download')
        for key in ('etag', 'last-modified', 'content-length'):
            if source['http'].get(key) and source['http'][key] != response.headers.get(key):
                raise ValueError('CDN metadata changed during historical download: ' + key)
        while block := response.read(1024 * 1024):
            size += len(block)
            if size >= 2_000_000_000:
                raise ValueError('Historical package exceeds asset size guard')
            stream.write(block)
            digest.update(block)
    if size < 1024 or (source['http'].get('content-length') and size != int(source['http']['content-length'])):
        raise ValueError('Incomplete historical package')
    with path.open('rb') as stream:
        magic = stream.read(4)
        suffix = path.suffix.lower()
        expected = {'.exe': b'MZ', '.pkg': b'xar!', '.apk': b'PK'}
        if suffix in expected and not magic.startswith(expected[suffix]):
            raise ValueError('Historical package has invalid format magic')
        if suffix == '.dmg':
            stream.seek(-512, 2)
            if stream.read(4) != b'koly':
                raise ValueError('Historical DMG missing UDIF trailer')
    if suffix == '.apk':
        with zipfile.ZipFile(path) as apk:
            if 'AndroidManifest.xml' not in apk.namelist() or apk.testzip():
                raise ValueError('Invalid historical APK archive')
    downloaded = {**{k: v for k, v in source.items() if not k.startswith('_')},
                  'asset_name': name, 'size': size, 'sha256': digest.hexdigest()}
    with path.open('rb') as stream:
        sha1 = base64.b32encode(hashlib.file_digest(stream, 'sha1').digest()).decode('ascii')
    historical_digests = sorted({e['digest'] for e in package['evidence'] if e['kind'] == 'archived-binary-index' and re.fullmatch('[A-Z2-7]{32}', e.get('digest', ''))})
    if historical_digests and sha1 not in historical_digests:
        path.unlink()
        raise ValueError('Live CDN payload differs from all archived binary SHA-1 digests')
    return {**downloaded, 'payload_sha1_base32': sha1,
            'archived_payload_sha1_verified': bool(historical_digests),
            'archived_payload_sha1_candidates': historical_digests,
            'evidence': package['evidence']}


def fetch_with_retry(package):
    for attempt in range(3):
        try:
            return fetch_package(package)
        except (OSError, urllib.error.URLError, http.client.HTTPException):
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))
        except ValueError as error:
            transient = str(error).startswith(('Incomplete historical package', 'CDN metadata changed during historical download'))
            if not transient or attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def prefetched_packages(packages):
    """Keep at most three temporary binaries while serializing upload/verification."""
    iterator = iter(enumerate(packages, 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        pending = deque()
        for _ in range(3):
            item = next(iterator, None)
            if item:
                number, package = item
                pending.append((number, package, pool.submit(fetch_with_retry, package)))
        while pending:
            yield pending.popleft()
            item = next(iterator, None)
            if item:
                number, package = item
                pending.append((number, package, pool.submit(fetch_with_retry, package)))


def upload(repo, *paths):
    for attempt in range(3):
        try:
            return mirror.gh('release', 'upload', TAG, '--repo', repo, '--clobber', *map(str, paths))
        except subprocess.CalledProcessError as error:
            mirror.summary('GitHub upload retry: ' + error.stderr.decode('utf-8', errors='replace'))
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def checkpoint_packages(saved, plan, assets, plan_hash):
    if saved.get('source_plan_sha256') != plan_hash or saved.get('tag') != TAG:
        return []
    candidates = {p['url']: p for p in plan['packages']}
    restored = []
    for package in saved.get('packages', []):
        candidate = candidates.get(package.get('resolved_url'))
        if not candidate:
            continue
        name = candidate['platform'] + '--' + candidate['filename']
        asset = assets.get(name, {})
        if (package.get('asset_name') == name and asset.get('size') == package.get('size')
                and asset.get('digest') == 'sha256:' + package.get('sha256', '')):
            restored.append({**package, 'recovered_by_run_url': package.get('recovered_by_run_url', saved.get('run_url'))})
    return restored


def execute(args):
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    OUT.mkdir(parents=True, exist_ok=True)
    report_path = OUT / 'historical-manifest.json'
    result = {'schema_version': 1, 'kind': 'one-shot-historical-backfill', 'tag': TAG,
              'created_at': mirror.now(), 'capture_until': plan['capture_until'],
              'source_plan_sha256': mirror.file_sha256(PLAN), 'source_commit': os.environ.get('GITHUB_SHA'),
              'run_url': 'https://github.com/' + args.repo + '/actions/runs/' + os.environ.get('GITHUB_RUN_ID', 'local'),
              'coverage_errors': plan['coverage_errors'], 'packages': [], 'unavailable': [], 'already_archived': []}
    release = mirror.find_release(args.repo, TAG) if args.publish else None
    if release and not release['draft']:
        mirror.summary('Historical release is already published; refusing to change it: ' + release['html_url'])
        return
    if args.publish and not release:
        release = mirror.api(f'repos/{args.repo}/releases', '--method', 'POST', '-f', 'tag_name=' + TAG,
                             '-f', 'name=UU 远程历史版本一次性回溯 · 2026-11-27', '-F', 'draft=true',
                             '-f', 'target_commitish=' + os.environ.get('GITHUB_SHA', 'main'))
    elif args.publish:
        # Always include tag_name: GitHub may reset a draft tag when only target changes.
        release = mirror.api(f'repos/{args.repo}/releases/{release["id"]}', '--method', 'PATCH',
                             '-f', 'tag_name=' + TAG, '-f', 'target_commitish=' + os.environ.get('GITHUB_SHA', 'main'))
    if args.publish:
        assets = {a['name']: a for a in release['assets']}
        checkpoint = assets.get('historical-manifest.json')
        if checkpoint:
            saved = json.loads(mirror.gh('api', f'repos/{args.repo}/releases/assets/{checkpoint["id"]}', '-H', 'Accept: application/octet-stream'))
            result['packages'] = checkpoint_packages(saved, plan, assets, result['source_plan_sha256'])
            mirror.summary(f"Restored {len(result['packages'])} verified assets from draft checkpoint")
    existing = {}
    if args.publish:
        pages = mirror.api(f'repos/{args.repo}/releases?per_page=100', '--paginate', '--slurp')
        for page in pages:
            for prior in page:
                if prior['draft']:
                    continue
                for asset in prior['assets']:
                    if asset.get('digest'):
                        existing[(asset['name'], asset['digest'])] = prior['html_url']

    restored_urls = {p['resolved_url'] for p in result['packages']}
    pending_packages = [p for p in plan['packages'] if p['url'] not in restored_urls]
    for number, package, future in prefetched_packages(pending_packages):
        mirror.summary(f"Historical download {number}/{len(plan['packages'])}: {package['filename']}")
        path = OUT / (package['platform'] + '--' + package['filename'])
        try:
            recovered = future.result()
            recovered['recovered_by_run_url'] = result['run_url']
            digest = 'sha256:' + recovered['sha256']
            prior = existing.get((recovered['asset_name'], digest))
            if prior:
                result['already_archived'].append({**recovered, 'existing_release_url': prior})
                path.unlink()
            else:
                if args.publish:
                    upload(args.repo, path)
                    remote = mirror.api(f'repos/{args.repo}/releases/{release["id"]}/assets?per_page=100', '--paginate', '--slurp')
                    asset = next(a for page in remote for a in page if a['name'] == recovered['asset_name'])
                    if asset['size'] != recovered['size'] or asset.get('digest') != digest:
                        raise RuntimeError('Uploaded asset digest mismatch; stop before publishing')
                    path.unlink()  # Only this run's verified temporary package; prevents disk exhaustion.
                result['packages'].append(recovered)
        except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException) as error:
            result['unavailable'].append({**package, 'error': str(error)})
            mirror.summary('Historical package unavailable: ' + package['filename'] + ' · ' + str(error))
            if path.exists():
                path.unlink()
        mirror.write_json(report_path, result)
        if args.publish and number % 5 == 0:
            upload(args.repo, report_path)
    if not result['packages']:
        raise ValueError('No new historical packages recovered; refusing empty publication')
    result['completed_at'] = mirror.now()
    mirror.write_json(report_path, result)
    (OUT / PLAN.name).write_bytes(PLAN.read_bytes())
    notes = f"""## 一次性历史回溯

通过 Wayback 的官方网页、官方 API 302 与网易 CDN 索引追溯来源，**所有安装包均直接从今天仍可用的网易官方 CDN 下载**，未使用 Wayback 托管的二进制。

- 本 Release 新补齐 **{len(result['packages'])}** 个安装包；已在本仓库归档 **{len(result['already_archived'])}** 个，不重复上传。
- 无法恢复 **{len(result['unavailable'])}** 个候选；另有 **{len(result['coverage_errors'])}** 项索引/页面读取缺口，详见 manifest。
- 快照查询截止：`{plan['capture_until']}`。最早证据时间不是官方发布日期，不代表覆盖全部历史版本。
- 候选也包括按“归档中出现的版本号 + 历史或当前官方下载的简单文件名模板”推导、且今天网易 CDN 确认可访问的 Android/macOS 地址；这些包标记 `version-template-derived`，不宣称其具体路径曾被 Wayback 捕获。
- 已核对历史二进制 SHA-1 的包在 manifest 中标记 `archived_payload_sha1_verified: true`；其余仅具历史页面/302 来源证据。全部成功资产均有当前 SHA-256 与上传后 GitHub digest 验证。
- 版本号来自官方文件名；渠道差异保留原名。未执行安装包，也未验证厂商数字签名。

| 平台 | 版本 | 原始文件名 | 历史二进制摘要已核对 |
| --- | --- | --- | --- |
"""
    notes += '\n'.join(f"| {p['platform']} | {p['version']} | `{p['upstream_filename']}` | {'是' if p['archived_payload_sha1_verified'] else '无可用历史二进制摘要'} |" for p in result['packages'])
    notes += '\n\n`historical-manifest.json` 记录每个包的来源证据、大小、SHA-256、历史 SHA-1 和失败清单；`' + PLAN.name + '` 是执行前冻结的完整候选计划。`SHA256SUMS.txt` 包含新补齐安装包和 metadata 的校验和。\n\n[本次 Actions 日志](' + result['run_url'] + ')。这是独立历史归档，不推进 Latest，也不修改现有定时镜像。\n'
    (OUT / 'historical-notes.md').write_text(notes, encoding='utf-8')
    sums = [p['sha256'] + '  ' + p['asset_name'] for p in result['packages']]
    for name in ('historical-manifest.json', PLAN.name):
        sums.append(mirror.file_sha256(OUT / name) + '  ' + name)
    (OUT / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n', encoding='utf-8')
    if args.publish:
        metadata = ['historical-manifest.json', PLAN.name, 'SHA256SUMS.txt']
        upload(args.repo, *[OUT / n for n in metadata])
        remote = mirror.api(f'repos/{args.repo}/releases/{release["id"]}/assets?per_page=100', '--paginate', '--slurp')
        assets = {a['name']: a for page in remote for a in page}
        expected = {p['asset_name']: (p['size'], p['sha256']) for p in result['packages']}
        expected.update({n: ((OUT / n).stat().st_size, mirror.file_sha256(OUT / n)) for n in metadata})
        if set(assets) != set(expected):
            raise ValueError('Draft contains stale/unexpected assets; manual review required')
        for name, (size, digest) in expected.items():
            if assets[name]['size'] != size or assets[name].get('digest') != 'sha256:' + digest:
                raise ValueError('Final historical asset verification failed: ' + name)
        mirror.gh('release', 'edit', TAG, '--repo', args.repo, '--draft=false', '--latest=false',
                  '--notes-file', str(OUT / 'historical-notes.md'))
    mirror.summary(f"Historical recovery complete: {len(result['packages'])} new, {len(result['already_archived'])} existing, {len(result['unavailable'])} unavailable")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discover', action='store_true')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--expand', action='store_true', help='Validate Android/macOS URL combinations using archive-observed versions and filename templates')
    parser.add_argument('--until', default='20261127')
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', '2873tr6x/uuyc-app-mirror'))
    args = parser.parse_args()
    if sum((args.discover, args.publish, args.expand)) > 1:
        parser.error('Discovery and publishing are separate steps')
    if not re.fullmatch(r'\d{8}', args.until):
        parser.error('--until must be YYYYMMDD')
    if args.discover:
        discover(args)
    elif args.expand:
        expand_plan()
    else:
        execute(args)
