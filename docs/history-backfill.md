# Wayback 一次性历史回溯

[历史 Release](https://github.com/2873tr6x/uuyc-app-mirror/releases/tag/uuyc-history-2026-11-27) · [一次性工作流](https://github.com/2873tr6x/uuyc-app-mirror/actions/workflows/history.yml) · [冻结的来源计划](../data/wayback-2026-11-27.json)

## 来源与范围

从 Wayback CDX 索引追溯 `https://uuyc.163.com/download/`、网易 ADL 分发页、`api.nrd.nie.163.com/api/v1/release/dl/` 的历史 302，以及 `a56.gdl.netease.com` 上 UU 远程 / GameViewer 的历史包。GameViewer 是旧安装包名称，保留原始文件名，不能只检索 UURemote。查询截止日期为 2026-11-27，不指定起始日期，允许发现比官网下载页更早的 API 证据。

从快照中提取原始链接，不执行归档脚本，不推算十位时间戳。另按用户提供的方法，对不含时间戳的 Android/macOS 简单文件名，用“归档中实际出现的版本号 + 归档中实际出现的文件名模板”组合候选，先用官方 CDN HEAD 验证可用性。只尝试这两个有证据的有限集合，不枚举任意数字版本。历史包只允许 UU 远程 / GameViewer 的 EXE、PKG、DMG、APK，域名限制为网易 `*.gdl.netease.com`。iOS 商店包不在范围内。

## 两步执行

1. `python scripts/history.py --discover` 查询 CDX，读取历史页面 / 响应头，并将候选与证据冻结到 `data/wayback-2026-11-27.json`。`dist/history-discovery-cache.json` 保存本地断点。证据缺口不会被隐藏，记录在计划的 `coverage_errors`。Wayback 会限速或临时不可用，重跑会复用已成功读取的证据。
2. `python scripts/history.py --expand` 按证据中的简单模板补充 Android/macOS 候选，也读取当前官网的模板，覆盖 macOS 从 DMG 改为 PKG 等命名变化。当前模板的官方分发来源另存于 `template_expansion.current_official_template_sources`。只有今天网易 CDN HEAD 正常、路径不变且包体非空的地址才能加入计划。失败组合也保存在计划中。各平台版本独立；Windows 文件名中的前三段只能作为待验证候选版本号，不能证明 Android/macOS 曾同步发版。
3. 检查并提交来源计划后，在 Actions 手动执行 **One-shot historical backfill**。执行 `python scripts/history.py --publish`，无需 secrets，使用仓库 `GITHUB_TOKEN`。此工作流没有 schedule 或 push 触发器。本次任务只手动触发一次；如果失败可重跑修复 draft，已经公开的历史 Release 拒绝修改。

源码与来源计划保存在同一提交。冻结计划让 GitHub runner 下载时无需依赖 Wayback 的实时可用性，并允许任何人复查“当时为什么认定这个 URL 是某个历史包”。

## 防止误用实时链接

回放使用 `id_` 并禁用自动重定向。只有带 `Memento-Datetime` 的响应才视为归档响应；缺失该字段的 Wayback 错误页不能当作证据。Wayback 内部的最近快照跳转可以跟随，但不会跟随到网易实时 API，防止把今天的版本误记成旧版本。记录请求与实际回放时间，保留原始响应头和页面正文 SHA-256。

历史 302 的正文常常都是空的，其 CDX digest 相同，所以**不能按 digest 折叠 302 索引**，否则会漏掉不同下载目标。网页可以按正文 digest 去重。二进制记录按 URL 路径归并，但保留各次捕获的摘要和时间。

## 下载与校验

去掉过期签名查询参数，使用证据中的网易 CDN 路径进行今天的 HEAD 与 GET。禁止重定向到不同包路径。核对 HEAD/GET 的 ETag、修改时间、长度与实际字节数；EXE 检查 MZ，PKG 检查 xar，DMG 检查 UDIF 尾部，APK 检查 ZIP、AndroidManifest.xml 和 CRC。所有成功下载计算 SHA-256，不安装或执行程序。

证据等级：

| 类型 | 能确认什么 |
| --- | --- |
| 历史二进制 CDX 索引，当前包的 SHA-1 与历史 digest 相符 | 当前官方包与归档记录的历史载荷摘要一致；manifest 标记 `archived_payload_sha1_verified: true` |
| 历史官方 API 302 或官方页面直链，无二进制摘要 | 当时官方确实指向该路径；能验证今天从官方获取的包，但不能证明其字节从未改变 |
| `version-template-derived`，版本号和模板分别有归档依据 | 该组合路径今天由网易 CDN 实际提供包；不宣称此平台的完整路径或发布日期被 Wayback 记录，manifest 指向模板与版本的原始证据 |

CDX digest 使用 Base32 SHA-1，**不是 SHA-256**。SHA-1 只作为历史一致性的补充检查，新归档与上传完整性均使用 SHA-256。若存在历史二进制摘要但今天的包全部不匹配，排除该包并在失败清单中记录。没有历史摘要不会伪造“已核对”标记。这些检查不替代厂商数字签名验证。

## 单一 Release 与失败记录

所有新补齐包集中在 `uuyc-history-2026-11-27`。先建立 draft，最多并行下载 3 个包，逐个上传并核验 GitHub size / SHA-256 digest，再清理该次运行的临时安装包；完成上传前不会继续堆积更多下载文件，避免 runner 磁盘被历史包占满。已在其他公开 Release 中具有相同文件名和 SHA-256 的包不重复上传，manifest 提供原 Release 链接。不同渠道、不同原始文件名保留各自身份。

每处理 5 个包，将 manifest 写入草稿作为断点；重跑仅在来源计划 SHA-256 相同、条目仍属于该计划、且 GitHub 资产 size / SHA-256 digest 均相符时复用已验证资产，并保留实际恢复它的原运行链接。上传失败有限重试。不要在上传期间手工修改草稿 tag；脚本只在开始时同时设置 `tag_name` 和 `target_commitish`，避免 GitHub 自动重置 draft tag。

包不可访问、内容已改变或格式校验失败时，记录 `unavailable`；成功包仍可发布，但 Release 正文明示恢复数、已归档数、失败数和来源查询缺口，不宣称覆盖全部历史。GitHub 上传或摘要校验失败则整轮保持 draft，不公开未核验的资产。最后再次核对整个资产集合，拒绝含过期或意外资产的草稿。发布使用 `--latest=false`，持续镜像工作流和当前 Latest 不受这份历史归档影响。

随 Release 提供 `historical-manifest.json`、冻结来源计划与 `SHA256SUMS.txt`。manifest 包含每个包的证据、版本、大小、SHA-256、历史 SHA-1、一致性结论、官方 HTTP metadata、运行 URL、源码提交、已归档链接和未能恢复的候选。`created_at` 是本次回溯执行时间，快照时间是证据捕获时间，都不是官方发版日期。
