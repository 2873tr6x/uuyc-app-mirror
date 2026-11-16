# Metadata 契约（schema_version = 1）

`release-manifest.json` 随每次新内容 Release 发布，UTF-8 JSON。机器结构见 [JSON Schema](../schemas/release-manifest.schema.json)。新增字段向后兼容；修改已有字段含义或类型时提高 schema_version。

| 字段 | 含义 |
| --- | --- |
| `observed_at` | 本镜像观察到完整快照的 UTC 时间，非官方发版时间 |
| `tag` / `snapshot_sha256` | 内容寻址 tag / 整组平台及哈希的完整指纹 |
| `run_url` / `source_commit` | Actions 运行与所用源码提交；本地执行时 commit 可为空 |
| `packages[].platform` | windows / macos / android / android-tv |
| `version` / `version_source` | 官方文件名中的数字版本；固定来源标记 official-filename，非包内验签结论 |
| `architecture` | 未明确标注时为 unspecified-by-download-page |
| `landing_url` / `endpoint_url` | 官网 ADL 入口与动态解析得到的官方分发 API |
| `resolved_url` | 最终 CDN URL 去除查询与 fragment；审计线索，不保证可直接下载 |
| `upstream_filename` / `asset_name` | 官方原名 / 加平台前缀后的 GitHub 资产名 |
| `http` | HEAD 返回的 ETag、Last-Modified、Content-Length、Content-Type；可能为空 |
| `size` / `sha256` | 实际下载字节数 / 安装包 SHA-256，小写十六进制 |
| `store_only` | 只能从官方商店获取的平台入口 |

`SHA256SUMS.txt` 覆盖安装包、manifest、probe 与官网 HTML；不包含它自己，避免自引用。GitHub 自己生成的 Source code zip/tar.gz 不是 UU 安装包，也不在校验和中。`probe.json` 是同次运行的无临时 CDN 签名探测记录，`release-notes.md` 只用于 Release 正文和诊断 artifact。
