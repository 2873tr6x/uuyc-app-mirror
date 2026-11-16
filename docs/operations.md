# 维护与排错

## 手动运行

打开 Actions → Mirror UU Remote → Run workflow。普通运行先比较指纹；勾选 `audit` 强制完整下载和哈希校验，内容未变仍不会发版。无自定义密钥、服务器或外部定时器。

正常小时探测为 UTC 每小时 `:17`；完整审计为 UTC 03:43（UTC+8 11:43）。GitHub schedule 不保证准点执行。首次推送和镜像脚本 / 工作流修改也会执行，README 单独修改只执行 CI。

## 查看结果

绿色运行并不一定创建 Release：Summary 会说明“指纹未变化”“内容未变化”“快照已归档”或新 Release 链接。运行详情含步骤日志；artifact 含 probe、manifest、校验和与 release notes（只有执行到相应阶段才会产生）。不要将临时 CDN 签名链接作为永久下载链接。

## 常见失败

| 情况 | 处理 |
| --- | --- |
| 无法解析 ADL / 官网不再暴露平台 | 检查官网和来源快照，更新解析器及单元测试；不要改用不明第三方下载站 |
| 403、超时、连接重置 | 确认官方仍能访问，重跑；GitHub runner 可能受到地区限制 |
| metadata changed / 长度不符 | 上游更新或传输不完整；稍后重跑，禁止跳过验证 |
| magic / APK ZIP 检查失败 | 可能拿到 HTML 错误页或格式调整，先调查真实文件格式 |
| 上传失败 / asset digest 不符 | draft 保留，重跑修复；不要手动公开未完成 draft |
| 403 Resource not accessible | 检查仓库 Actions 策略与 job 的 `contents: write` |
| 很久没有定时运行 | 检查 Actions 是否被禁用、GitHub 状态以及公开仓库无活动停用策略，手动恢复 workflow |

脚本通过 Latest API 读取最新归档，并按内容 tag 查询已有归档 / draft，不依赖 Release 列表页数。不要将仓库的 Latest 手动指向不带 manifest 的其他 Release。

## 修改与验证

Python 标准库，不安装第三方 Python 依赖；GitHub 托管 Ubuntu runner 自带 `gh`。本地：

```bash
python -m unittest discover -s tests -v
python scripts/mirror.py --probe-only
python scripts/mirror.py --audit
```

CI 使用模拟响应验证域名边界、来源解析、过期格式、换包竞争、HTML 拒绝和内容校验；真实官方下载与完整上传验证由 mirror 工作流执行。PR 工作流没有写权限，不运行不受信任的发布代码。工作流 Actions 使用官方主版本 tag，版本升级需审阅其变化。

已发布快照视为只读。维护者仍有权限手动删除 Releases；若需要强防删保证，应自行建立备份策略，本项目没有额外存储。权利人请求可在 Issue 提交，避免上传账号、设备码或个人日志。
