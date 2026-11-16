#!/usr/bin/env python3
"""Mirror official UU Remote packages; Python standard library + GitHub CLI only."""
import argparse
import concurrent.futures
import hashlib
import html
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
from datetime import datetime, timezone

HOME = 'https://uuyc.163.com/download/'
PLATFORMS = {
    'windows': ('pc', '.exe', 'MZ'),
    'macos': ('mac', '.pkg', 'xar!'),
    'android': ('android', '.apk', 'PK'),
    'android-tv': ('androidtv', '.apk', 'PK'),
}
HEADERS = ('ETag', 'Last-Modified', 'Content-Length', 'Content-Type')
DIST = Path('dist')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def allowed(url):
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ''
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
        raise ValueError('Only official HTTPS sources are accepted')
    if not any(host == d or host.endswith('.' + d) for d in ('netease.com', '163.com')):
        raise ValueError('Unexpected source host: ' + host)
    return url


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(OfficialRedirect())


def request(url, method='GET'):
    allowed(url)
    for attempt in range(4):
        try:
            return OPENER.open(urllib.request.Request(url, method=method, headers={
                'User-Agent': 'uuyc-app-mirror/1.0 (+https://github.com/2873tr6x/uuyc-app-mirror)',
                'Accept-Encoding': 'identity',
            }), timeout=120)
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def gh(*args, binary=False):
    result = subprocess.run(['gh', *args], check=True, capture_output=True)
    return result.stdout if binary else result.stdout.decode('utf-8')


def api(path, *args):
    return json.loads(gh('api', path, *args))


def optional_api(path):
    try:
        return api(path)
    except subprocess.CalledProcessError as error:
        if b'HTTP 404' in error.stderr:
            return None
        raise


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def stable_url(url):
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, '', ''))


def probe(platform, page):
    kind, extension, _ = PLATFORMS[platform]
    match = re.search(r'data-adl-type="' + kind + r'"[^>]*', page)
    # Download buttons point to the same ADL links exposed in JSON-LD.
    expected = '/c/adtv' if platform == 'android-tv' else '/c/gw_mac' if platform == 'macos' else '/c/gw?type=' + kind
    urls = re.findall(r'https://adl\.netease\.com/d/g/uuremote/c/[^\s<>"\']+', html.unescape(page))
    landing = next((u for u in urls if urllib.parse.urlsplit(u).path + ('?' + urllib.parse.urlsplit(u).query if urllib.parse.urlsplit(u).query else '') == '/d/g/uuremote' + expected), None)
    if not match or not landing:
        raise ValueError('Official download page no longer exposes ' + platform)
    with request(landing) as response:
        adl = response.read(2_000_000).decode('utf-8')
    # Parse literal official configuration; never execute remote JavaScript.
    field = 'android_link' if platform in ('android', 'android-tv') else 'pc_link'
    pattern = r'var\s+' + field + r'\s*=\s*(?:\w+\s*\?\s*)?["\'](https://api\.nrd\.nie\.163\.com/[^"\']+)["\']'
    found = re.search(pattern, adl)
    if not found:
        raise ValueError('Cannot resolve official ADL configuration: ' + platform)
    endpoint = html.unescape(found[1])
    with request(endpoint, 'HEAD') as response:
        final_url = response.url
        filename = urllib.parse.unquote(urllib.parse.urlsplit(final_url).path.rsplit('/', 1)[-1])
        headers = {key.lower(): response.headers.get(key) for key in HEADERS}
    if not filename.lower().endswith(extension) or not re.fullmatch(r'[A-Za-z0-9_.-]+', filename):
        raise ValueError('Unexpected package filename: ' + filename)
    version = re.search(r'(\d+\.\d+\.\d+(?:\.\d+)?)', filename)
    if not version:
        raise ValueError('No version in official filename')
    return {'platform': platform, 'version': version[1], 'version_source': 'official-filename',
            'architecture': 'unspecified-by-download-page', 'landing_url': landing,
            'endpoint_url': endpoint, 'resolved_url': stable_url(final_url),
            'upstream_filename': filename, 'http': headers, '_download_url': final_url}


def fingerprint(source):
    return {k: source[k] for k in ('resolved_url', 'http', 'version', 'endpoint_url')}


def download(source):
    platform = source['platform']
    name = platform + '--' + source['upstream_filename']
    target = DIST / name
    for attempt in range(3):
        try:
            digest = hashlib.sha256()
            size = 0
            with request(source['_download_url']) as response, target.open('wb') as output:
                # A rollout between HEAD and GET must not mix two package generations.
                if stable_url(response.url) != source['resolved_url']:
                    raise ValueError('Source changed during download; rerun')
                for header in ('etag', 'last-modified', 'content-length'):
                    expected = source['http'].get(header)
                    if expected and response.headers.get(header) != expected:
                        raise ValueError('Source metadata changed during download: ' + header)
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size >= 2_000_000_000:
                        raise ValueError('Package exceeds configured GitHub asset size guard')
                    digest.update(chunk)
                    output.write(chunk)
            expected_size = source['http'].get('content-length')
            if size < 1024 or (expected_size and size != int(expected_size)):
                raise ValueError('Incomplete or empty package')
            with target.open('rb') as file:
                magic = file.read(4)
            if not magic.startswith(PLATFORMS[platform][2].encode()):
                raise ValueError('Invalid package magic; refusing HTML/error response')
            if name.endswith('.apk'):
                with zipfile.ZipFile(target) as apk:
                    if 'AndroidManifest.xml' not in apk.namelist() or apk.testzip():
                        raise ValueError('Invalid APK archive')
            return {**{k: v for k, v in source.items() if not k.startswith('_')},
                    'asset_name': name, 'size': size, 'sha256': digest.hexdigest()}
        except (OSError, ValueError, urllib.error.URLError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def latest(repo):
    # Distinguish an empty repository from authentication/network/API failures.
    release = optional_api(f'repos/{repo}/releases/latest')
    if release is None:
        api(f'repos/{repo}')  # Validate access instead of treating a missing repo as empty.
        return None
    if not release['tag_name'].startswith('uuyc-'):
        raise ValueError('Latest Release is not a managed UU Remote snapshot')
    asset = next(a for a in release['assets'] if a['name'] == 'release-manifest.json')
    return json.loads(gh('api', f'repos/{repo}/releases/assets/{asset["id"]}', '-H', 'Accept: application/octet-stream'))


def summary(message):
    print(message, flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as output:
            output.write(message + '\n')


def run(args):
    DIST.mkdir(exist_ok=True)
    with request(HOME) as response:
        page = response.read(3_000_000).decode('utf-8')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        sources = list(pool.map(lambda p: probe(p, page), PLATFORMS))
    public_sources = [{k: v for k, v in s.items() if not k.startswith('_')} for s in sources]
    write_json(DIST / 'probe.json', {'observed_at': now(), 'sources': public_sources})
    previous = latest(args.repo) if args.publish else None
    if previous and not args.audit and [fingerprint(s) for s in public_sources] == [fingerprint(s) for s in previous['packages']]:
        summary('上游指纹未变化；跳过下载和发布。')
        return
    if args.probe_only:
        summary(json.dumps(public_sources, indent=2, ensure_ascii=False))
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        packages = list(pool.map(download, sources))
    identity = hashlib.sha256(json.dumps([(p['platform'], p['sha256']) for p in packages], separators=(',', ':')).encode()).hexdigest()
    if previous and identity == previous['snapshot_sha256']:
        summary('完整 SHA-256 校验完成，安装包内容未变化；不创建重复 Release。')
        return
    tag = 'uuyc-' + identity[:20]
    manifest = {'schema_version': 1, 'product': 'UU Remote', 'observed_at': now(),
                'tag': tag, 'snapshot_sha256': identity, 'official_download_page': HOME,
                'run_url': os.environ.get('GITHUB_SERVER_URL', 'https://github.com') + '/' + args.repo + '/actions/runs/' + os.environ.get('GITHUB_RUN_ID', 'local'),
                'source_commit': os.environ.get('GITHUB_SHA'), 'packages': packages,
                'store_only': {'ios': 'https://apps.apple.com/cn/app/id1642306791'}}
    write_json(DIST / 'release-manifest.json', manifest)
    # Preserve the source page as evidence; no transient signed CDN query parameters.
    (DIST / 'official-download-page.html').write_text(page, encoding='utf-8')
    checksums = [f'{p["sha256"]}  {p["asset_name"]}' for p in packages]
    for name in ('release-manifest.json', 'official-download-page.html', 'probe.json'):
        checksums.append(hashlib.sha256((DIST / name).read_bytes()).hexdigest() + '  ' + name)
    (DIST / 'SHA256SUMS.txt').write_text('\n'.join(checksums) + '\n', encoding='utf-8')
    rows = '\n'.join(f'| {p["platform"]} | {p["version"]} | {p["size"]:,} | `{p["sha256"]}` |' for p in packages)
    body = f'''官方安装包原样归档 · 检测时间：{manifest['observed_at']}

| 平台 | 官方文件名版本 | 字节数 | SHA-256 |
| --- | --- | ---: | --- |
{rows}

下载对应平台的安装包，并用 `SHA256SUMS.txt` 校验。平台版本独立发布，版本号可能不同；架构未由官网明确标注。

`release-manifest.json` 记录来源、版本、HTTP metadata、大小和哈希；`official-download-page.html` 是官网来源快照，`probe.json` 是探测记录。

上游版本号取自官方文件名，未宣称是包内验证版本。SHA-256 证明归档一致性，不等于厂商签名验证。iOS 请前往官方 App Store。本项目与网易无隶属关系。

[官方来源]({HOME}) · [本次 Actions 日志]({manifest['run_url']}) · 快照 `{identity}`
'''
    (DIST / 'release-notes.md').write_text(body, encoding='utf-8')
    if not args.publish:
        summary('本地验证完成，未发布：' + tag)
        return
    release = optional_api(f'repos/{args.repo}/releases/tags/{tag}')
    if release and not release['draft']:
        # Includes upstream rollbacks: never mutate an already published archive.
        summary('该内容快照已归档，保留原 Release：' + release['html_url'])
        return
    title = 'UU 远程 · ' + ' / '.join(p['platform'] + ' ' + p['version'] for p in packages)
    if not release:
        gh('release', 'create', tag, '--repo', args.repo, '--draft', '--title', title,
           '--notes-file', str(DIST / 'release-notes.md'), '--target', os.environ.get('GITHUB_SHA', 'main'))
    names = [p['asset_name'] for p in packages] + ['release-manifest.json', 'official-download-page.html', 'probe.json', 'SHA256SUMS.txt']
    # Only drafts may be repaired. Never replace a published archive.
    gh('release', 'upload', tag, '--repo', args.repo, '--clobber', *[str(DIST / n) for n in names])
    release = api(f'repos/{args.repo}/releases/tags/{tag}')
    assets = {a['name']: a for a in release['assets']}
    for name in names:
        local = DIST / name
        asset = assets[name]
        digest = 'sha256:' + hashlib.sha256(local.read_bytes()).hexdigest()
        if asset['size'] != local.stat().st_size or asset.get('digest') != digest:
            raise ValueError('GitHub asset digest verification failed: ' + name)
    gh('release', 'edit', tag, '--repo', args.repo, '--draft=false', '--latest', '--title', title, '--notes-file', str(DIST / 'release-notes.md'))
    summary('已发布并验证全部 GitHub 资产：' + release['html_url'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', '2873tr6x/uuyc-app-mirror'))
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--audit', action='store_true', help='Download and hash even when HEAD metadata is unchanged')
    parser.add_argument('--probe-only', action='store_true')
    arguments = parser.parse_args()
    if arguments.publish and arguments.probe_only:
        parser.error('--publish and --probe-only are mutually exclusive')
    run(arguments)
