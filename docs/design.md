# 设计决策

- **仅 GitHub**：Actions 调度、执行、日志与失败通知，Releases 存包和来源证据；不需要 R2、Worker、对象存储或 PAT secret。
- **平台组合快照**：UU 远程 PC、移动端和 TV 版本不一致，使用统一版本号会误导。标题列各端版本，tag 使用内容指纹。
- **保留同版本换包**：稳定 URL 或文件名不足以代表字节身份；每日 audit 加 SHA-256 身份补足轻量 HEAD 探测。
- **先完整后公开**：四个平台都可用、上传后 digest 验证成功才发布。某个平台故障会阻止整个新快照，牺牲局部及时性换取完整归档。
- **历史只追加**：公开资产不覆盖；draft 可重试修复。不创建滚动 latest 资产，不清理旧 Releases。
- **来源透明**：官网 → ADL → 分发 API → CDN。保留页面、HTTP metadata 与运行提交，过滤临时 CDN 查询参数。
- **边界明确**：没有包内版本 / 架构识别、厂商签名验证、非公开渠道追踪或历史包猜测。iOS 保持商店链接。
- **受参考项目启发，独立实现**：[codex-app-mirror](https://github.com/Wangnov/codex-app-mirror) 提供了探测、可校验归档、README 与运维文档的模式。本项目不复制其 Codex / Store / Sparkle / Cloudflare 专用实现。
