"""Freeze verified HEAD matches and all unsuccessful hint searches for review."""
import json
import argparse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import history
import mirror


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', default='2026-11-27')
    parser.add_argument('--hints', type=Path, default=Path('dist/windows-hints.json'))
    parser.add_argument('--searches', type=Path, default=Path('dist/windows-hunt.json'))
    args = parser.parse_args()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:-batch[1-9]\d*)?', args.batch):
        parser.error('Invalid batch identifier')
    searches = json.loads(args.searches.read_text(encoding='utf-8'))
    packages = []
    for search in searches:
        if search.get('skipped'):
            search['skipped'] = 'Version already archived'
        search['timezone_candidates'] = search.pop('timezones_tested', search.get('timezone_candidates', ['UTC', 'UTC+08:00']))
        for match in search.get('matches', []):
            if match['offset_seconds'] is not None:
                for stamp in search['hint']['timestamp_hints']:
                    dt = datetime.strptime(stamp.split('.')[0].rstrip('Z'), '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
                    for hours in (0, 8):
                        token = (dt + timedelta(hours=hours, seconds=match['offset_seconds'])).strftime('%m%d%H%M%S')
                        if '_' + token + '_' in match['url']:
                            match['filename_timezone'] = 'UTC' if hours == 0 else 'UTC+08:00'
            package = history.package_url(match['url'])
            if not package or package['version'] != search['hint']['version']:
                raise ValueError('Invalid candidate identity')
            package['evidence'] = [{'kind': 'signature-time-derived', 'hint': search['hint'],
                                    'radius_seconds': search['radius_seconds'], 'offset_seconds': match['offset_seconds'],
                                    'timezone_candidates': search.get('timezone_candidates', search.get('timezones_tested', ['UTC+08:00'])),
                                    'official_head': match}]
            packages.append(package)
    plan = {'schema_version': 1, 'discovered_at': mirror.now(), 'capture_until': args.batch[:10].replace('-', ''),
            'method': 'Untrusted local files provide version and signed timestamp hints only. Bounded official CDN HEAD search in UTC and UTC+8; no untrusted binary uploaded.',
            'release_title': 'UU 远程 Windows 历史版本 · 签名时间线索回溯 · ' + args.batch,
            'release_intro': '## Windows 历史版本补充归档\n\n第三方 EXE 仅提供内部版本、签名时间与 SHA-256 线索，不上传第三方文件。以签名时间附近 ±100 秒（未命中扩大至 ±300 秒），按 UTC / UTC+8 尝试有官方证据的文件名模板。所有发布安装包均由本次 Actions 直接从网易官方 CDN 下载，逐包核对 Windows Authenticode 状态 Valid、网易发布者、内部版本、大小、SHA-256，以及上传后的 GitHub digest。签名时间不是证书有效期，也不代表官方发布日期。\n\nmanifest 记录官方文件与第三方线索文件的 SHA-256 是否相同；不同渠道可能不同，不将第三方字节作为可信来源。完整探测记录（含未命中）保存在来源计划中。签名时间推导的路径未宣称被 Wayback 捕获；未执行任何安装包。',
            'coverage_errors': [], 'packages': packages, 'searches': searches,
            'input_hints': json.loads(args.hints.read_text(encoding='utf-8-sig'))}
    misses = [s['hint']['version'] for s in searches if not s.get('matches') and not s.get('skipped')]
    plan['search_summary'] = {'unique_versions': len(searches), 'matched_versions': len(packages),
                              'previously_archived_versions': sum(bool(s.get('skipped')) for s in searches),
                              'not_found_versions': misses}
    plan['release_intro'] += f"\n\n检索覆盖：{len(plan['input_hints'])} 个线索文件、{len(searches)} 个内部版本；{len(packages)} 个版本命中官方地址，{plan['search_summary']['previously_archived_versions']} 个版本先前已有归档。未命中版本：{', '.join(misses) or '无'}。未命中不证明该版本从未发布或不存在其他官方文件名；各搜索的窗口、请求数与错误详见来源计划。"
    mirror.write_json(Path(f'data/windows-signature-recovery-{args.batch}.json'), plan)
    print(f'Frozen {len(packages)} official candidates, {len(searches)} unique version searches')


if __name__ == '__main__':
    main()
