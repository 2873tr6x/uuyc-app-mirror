# uuyc-app-mirror

[![Mirror UU Remote](https://github.com/2873tr6x/uuyc-app-mirror/actions/workflows/mirror.yml/badge.svg)](https://github.com/2873tr6x/uuyc-app-mirror/actions/workflows/mirror.yml)
[![CI](https://github.com/2873tr6x/uuyc-app-mirror/actions/workflows/ci.yml/badge.svg)](https://github.com/2873tr6x/uuyc-app-mirror/actions/workflows/ci.yml)

自动保存 **网易 UU 远程** 官网安装包到 **GitHub Releases**，保留每次发现的不同内容快照及其来源、版本和校验信息。仅使用 GitHub Actions 与 Releases，无 R2、Cloudflare、服务器或额外存储凭据。

**[下载最新快照](https://github.com/2873tr6x/uuyc-app-mirror/releases/latest) · [全部历史归档](https://github.com/2873tr6x/uuyc-app-mirror/releases) · [运行记录](https://github.com/2873tr6x/uuyc-app-mirror/actions/workflows/mirror.yml) · [UU 远程官网](https://uuyc.163.com/)**

## 下载

| 平台 | Release 资产 | 覆盖范围 |
| --- | --- | --- |
| Windows | `windows--*.exe` | 官网默认安装包 |
| macOS | `macos--*.pkg` | 官网默认安装包 |
| Android | `android--*.apk` | 官网渠道 APK |
| Android TV | `android-tv--*.apk` | 官网 TV 渠道 APK |
| iOS / iPadOS | [官方 App Store](https://apps.apple.com/cn/app/id1642306791) | 商店分发，不镜像 IPA |

平台版本号彼此独立，一份快照可能同时包含不同版本。安装包名称添加平台前缀以避免重名，**文件内容不修改、不重打包**。官网未明确标注架构时，metadata 记录为未指定，不能据文件扩展名推断 x64 / ARM64 / Universal。

每个 Release 附带：

- 四个平台的官方安装包。
- `release-manifest.json`：平台版本、来源链路、官方原始文件名、HTTP 指纹、字节数、SHA-256、运行与源码链接。
- `SHA256SUMS.txt`：安装包及证据文件的 SHA-256。
- `probe.json`：本次探测结果；`official-download-page.html`：官网来源页面快照（作为证据下载，不是镜像网站）。

### 校验

Linux：下载本 Release 的全部资产，在同一目录运行：

```bash
sha256sum -c SHA256SUMS.txt
```

macOS：`shasum -a 256 -c SHA256SUMS.txt`。Windows PowerShell：

```powershell
Get-FileHash .\windows--UURemote_Setup_*.exe -Algorithm SHA256
```

将结果与该 Release 的 `SHA256SUMS.txt` 比较。如果只下载一个安装包，只比较对应一行，其他文件缺失不代表该安装包损坏。SHA-256 用于验证归档一致性，**不替代厂商数字签名或安全审计**。本项目不会安装或执行下载的程序。

## 自动化

1. 每小时第 17 分钟解析[官网下载页](https://uuyc.163.com/download/)，找到网易 ADL 分发配置，再请求官方 API 的 HEAD 重定向。
2. 比较包 URL 路径、ETag、Last-Modified、Content-Length 和版本；忽略会变化的 CDN 临时签名参数。无变化时结束。
3. 有变化则完整下载四个包，检查长度、文件头及 APK ZIP 完整性，并计算 SHA-256。每天 UTC 03:43（台北 / 北京 11:43）强制执行完整内容校验，捕捉 HTTP 指纹不变的同版本换包。
4. 若整组 SHA-256 与最近归档相同，不重复发布。不同则先上传到 draft Release，校验 GitHub 返回的每个资产 SHA-256 与字节数，全部通过才公开并设为 Latest。
5. 相同版本不同内容会得到不同 tag；已公开的历史快照不会被覆盖。任一必需平台失败，本轮不发布不完整快照；错误体现在 Actions，上传中断则保留 draft 供重跑修复。

tag 为 `uuyc-<整组内容指纹前20位>`，Release 标题列出各平台版本。以内容作为身份，避免平台异步更新和同版本换包冲突。首次推送、脚本变更和手动运行也会触发。

完整说明：[工作原理](docs/how-it-works.md) · [维护与排错](docs/operations.md) · [metadata 契约](docs/metadata.md) · [设计决策](docs/design.md)。

## 自行部署

Fork 或创建仓库并推送这些文件，启用 Actions，在 **Actions → Mirror UU Remote → Run workflow** 执行。无需手动配置 secrets：工作流仅使用仓库自身的 `GITHUB_TOKEN`，发布 job 声明 `contents: write`。Fork 的定时任务可能需要手动启用。

本地仅探测（Python 3.12+）：

```bash
python scripts/mirror.py --probe-only
```

本地完整验证：`python scripts/mirror.py --audit`。本地发布需安装并登录 `gh`：`python scripts/mirror.py --publish --repo OWNER/REPO`。下载目录 `dist/` 被 Git 忽略，二进制只进入 Releases。

## 历史与限制

另提供 [Windows 签名时间线索回溯](https://github.com/2873tr6x/uuyc-app-mirror/releases/tag/uuyc-windows-history-2026-11-27)：以第三方文件的内部版本和签名时间作为线索，有界探测网易官方地址，再由 Windows Actions 重新下载并核对网易 Authenticode 签名、内部版本与 SHA-256。[执行方法与限制](docs/windows-signature-recovery.md)。第三方文件本体不上传。

[Windows 第二批补充归档](https://github.com/2873tr6x/uuyc-app-mirror/releases/tag/uuyc-windows-history-2026-11-27-batch2) 沿用同一验证流程，各批次的来源计划、运行日志与 Release 独立保留。

除持续镜像外，提供一份 [Wayback 历史回溯归档](https://github.com/2873tr6x/uuyc-app-mirror/releases/tag/uuyc-history-2026-11-27)：从历史官网、ADL 分发页、官方 API 302 和 CDN 索引恢复旧包地址，再直接从网易官方 CDN 下载。它是独立的一次性 Release，不推进 Latest；[来源与执行方法](docs/history-backfill.md)记录证据等级、历史摘要校验及覆盖缺口。

**不能恢复没有公开来源或官方 CDN 已失效的所有旧版**。常规镜像每次归档的是官网当前四个平台的组合，不是官方统一版本声明；版本取自官方文件名，未提取包内版本或验证厂商签名。

GitHub 计划任务可能排队、延迟或跳过，不能保证小时级 SLA，也无法保证捕获两次探测之间短暂出现又撤回的包。公开仓库长期没有活动时 GitHub 可能自动停用计划任务，需要仓库维护者恢复。Actions 日志按 GitHub 的保留策略清理，诊断 artifact 保留 30 天；已发布 Release 的 metadata 与来源页面持续保留，直至维护者删除。GitHub Releases 是唯一长期归档位置，并不构成异地备份。

仅追踪官网公开渠道，不枚举隐藏测试版、不绕过认证。若官方分发结构改变、下载来源离开允许域名、包格式变化、GitHub 限额或网络故障，工作流会失败而不是发布错误文件。

## 致谢与许可

自动化归档、可校验资产和完整文档的设计参考了 [Wangnov/codex-app-mirror](https://github.com/Wangnov/codex-app-mirror)，本项目针对 UU 远程独立实现。

本仓库脚本与文档采用 [MIT](LICENSE)。UU 远程安装包、商标及相关权利属于网易及相应权利人，MIT 不适用于被镜像的第三方软件；使用软件仍受官方协议约束。本项目非官方，与网易无隶属或背书关系。如有分发权利问题，请通过仓库 Issue 联系维护者。
