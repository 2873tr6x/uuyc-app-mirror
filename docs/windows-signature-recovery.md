# Windows 历史版本：签名时间线索回溯

[补充归档 Release](https://github.com/2873tr6x/uuyc-app-mirror/releases/tag/uuyc-windows-history-2026-11-27) · [一次性工作流](https://github.com/2873tr6x/uuyc-app-mirror/actions/workflows/windows-history.yml) · [冻结来源计划](../data/windows-signature-recovery-2026-11-27.json)

本次 25 个文件去重后有 21 个内部版本：15 个版本命中官方地址（其中当前版先前已归档），5 个历史版本先前已有归档；最早 `0.1.5.535` 在两个时区的 ±300 秒窗口共 1,202 个候选中未命中，响应均为 404，保留为覆盖缺口。第三方名为 `uuyuancheng3.12.0.3969.exe` 的文件内部实际是 `4.4.0.5195`；名为 32 / 64 位的两份 `0.1.5.535` 文件 SHA-256 完全相同，不能据文件名认定架构不同。

第三方下载的 EXE 只作为检索线索。读取 PE 版本资源、Authenticode 时间戳和 SHA-256，不执行、不上传这些文件。Windows `Get-AuthenticodeSignature` 的状态与发布者同时记录，但第三方来源仍不会被当作官方分发来源。文件名可能写错版本；使用内部 `FileVersion`，不信任第三方改名。

## 时间与有限探测

`scripts/inspect-windows.ps1 -Source D:\uuyc_windows_untrusted` 将线索写入被 git 忽略的 `dist/windows-hints.json`。提取传统 countersignature 的 signingTime，或 RFC3161 token 的时间，时间统一为 UTC。这里不是证书的 NotBefore、NotAfter，也不是文件系统创建时间。提取器只提供线索；最终官方文件的 Windows 签名仍需独立验证。

`python scripts/windows-hunt.py` 从时间中心开始探测 ±100 秒；`python scripts/windows-hunt.py --radius 300` 复用已命中的版本，将未命中范围放宽到 ±300 秒。使用官方已有的 `https://a56.gdl.netease.com/UURemote_Setup_{version}_{MMDDHHmmss}_gwqd.exe` 模板，最多 6 个并发 HEAD，拒绝重定向，记录非 404 错误。旧版本优先北京时间，新版本优先 UTC，两个时区均可检索；相邻秒跨日、跨年用日期运算处理。命中一批后停止该版本的继续搜索。完整原始渠道文件名仍存在时优先直接验证它。

不把 ±100 / ±300 秒称作厂商保证。渠道包可能后来重新签名，版本号相同也可能具有不同构建时间。`4.49.0.6162` 的已知官方文件名使用 UTC，和线索签名时间相差 −174 秒；旧版本有多例使用北京时间，相差 +6～+10 秒。`4.40.0.1780` 保留的完整渠道文件名可直接验证，不能拿它的签名时间强行推定官网渠道的文件名。早期 `0.1.5.535` 也仅以相同 UURemote 模板测试有限窗口，不宣称它当年的模板一定相同；未命中不等于官方从未发布。

`dist/windows-hunt.json` 是本地断点，每个版本记录线索、窗口、请求数、命中与错误。为了重新探测一个失败版本，可删除该版本的断点条目；脚本不自动无限重试。错误存在的搜索不能宣称完整排除该时间窗。

## 冻结与发布

`python scripts/freeze-windows.py` 将命中地址、原始文件 hash、时间线索、官方 HEAD 响应，以及失败/跳过项冻结到 `data/windows-signature-recovery-2026-11-27.json`。这是推导证据，不能冒充 Wayback 历史链接证明。计划不含本地绝对路径或第三方文件本体。

手动运行 **One-shot Windows signature recovery**。Windows runner 从冻结计划重新下载网易官方文件，使用已有历史回溯的长度、格式、SHA-256、断点和 GitHub asset digest 核验；新增 `verify-windows.ps1`，要求 Authenticode 为 `Valid`、签名主体为网易（杭州）、内部版本等于候选版本。任何签名或版本检查失败会停止发布。manifest 记录签名主体、证书指纹、时间戳机构、内部版本，以及官方包与第三方线索 hash 是否相同。渠道不同造成的 hash 差异不会以第三方文件替代官方文件。

独立 Release `uuyc-windows-history-2026-11-27` 仅含官方重新下载的安装包与 metadata，`--latest=false`。相同名称且相同 SHA-256 已在仓库公开的资产会记录原 Release 链接。流程不执行安装包，也不将本地第三方包上传到 Actions。
