# 工作原理

## 来源链路

官网 `https://uuyc.163.com/download/` 的按钮 / JSON-LD 指向网易 ADL 页面。脚本读取 ADL 中的字面量配置，不执行其中 JavaScript。

| 平台 | 官网 ADL 路径 | 建库时确认的 API |
| --- | --- | --- |
| Windows | `/d/g/uuremote/c/gw?type=pc` | `https://api.nrd.nie.163.com/api/v1/release/dl/1?channel=gwqd` |
| Android | `/d/g/uuremote/c/gw?type=android` | `https://api.nrd.nie.163.com/api/v1/release/dl/2?channel=gwqd` |
| macOS | `/d/g/uuremote/c/gw_mac` | `https://api.nrd.nie.163.com/api/v1/release/dl/4?channel=gwqd` |
| Android TV | `/d/g/uuremote/c/adtv` | `https://api.nrd.nie.163.com/api/v1/release/dl/5?channel=TV_gwqd` |

API 编号作为研究记录，不是代码中的固定下载地址。每次从官网和 ADL 重新解析；分发 API 重定向到带临时查询签名的网易 CDN。仅允许 HTTPS、标准 443 端口、`163.com` / `netease.com` 本域或子域，重定向每跳都检查。

## 变化检测与下载

所有平台先 HEAD，形成稳定指纹。CDN 查询签名随时间变化，不参与变化判断，也不会写入公开 JSON。若服务响应完整且指纹和最近发布记录相同，普通探测结束。每日 audit 不依赖 HEAD 是否变化，完整下载并比较 SHA-256。

首次运行或变化时，四个平台并行下载。HEAD 与 GET 的 URL 路径、ETag、修改时间和长度不一致时拒绝发布，避免探测期间上游换包。下载有超时、有限重试和大小门限；EXE 检查 MZ，PKG 检查 xar，APK 检查 ZIP 文件头、AndroidManifest.xml 与 ZIP CRC。它们是格式和传输检查，并非数字签名验证。

整组快照身份由有序 `(platform, sha256)` 列表的紧凑 JSON 再取 SHA-256 得到；顺序为 Windows、macOS、Android、Android TV。由此，同版本换包不会覆盖旧版；单一平台更新也有完整独立快照。代价是某个平台未变时也会出现在新 Release 中，增加存储用量，换取每份快照都可独立下载与验证。

## 发布事务

先建立 draft → 上传安装包与证据 → 调用 GitHub API 检查每个资产的 size 和 `digest` → 全部匹配才发布。GitHub 缺失 SHA-256 digest 也会阻止公开，需要维护者检查 API 行为。并发锁阻止本仓库工作流重叠；超时或失败不取消正在进行的另一次归档。

重跑同一内容时可修复 draft 资产；`--clobber` 仅用于 draft，脚本在任何上传前拒绝修改已发布的同 tag Release。上游回滚到已经归档过的内容时保留原归档，不制造重复版本，也不把旧版本提升为新发布。Latest 表示最近一次新内容归档，不能当成官方绝不回滚的版本排序 API。

日志由 Actions 展示，探测结果在 artifact 保留 30 天；成功发版将相应证据永久附在 Release 上。脚本没有向 Git 分支回写状态，归档 metadata 就是状态来源。
