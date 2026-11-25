# vmarker

视频策划与制作平台：网页里和 AI 把文案梳理成文件 → 确认 → Claude 通过 MCP 领任务做片 → 上传 → 审片。
一个 Python 进程、一个 data 目录、一个无构建步骤的单页前端。单人使用。

## 骨架

```
vmarker/
├── app/
│   ├── main.py          装配：配置 → 存储 → AI/任务 → 路由 → MCP → 页面
│   ├── config.py        环境变量（只放登录前必须知道的）
│   ├── db.py            SQLite：对话、任务、视频记录、AI 供应商、API Key
│   ├── auth/            oidc 登录 · keys API Key · deps 身份判定
│   ├── core/            store 磁盘文件 · providers AI 上游 · chat 对话 · tasks 任务状态机
│   ├── api/             settings / project / chat / task 路由 · mcp_server
│   └── web/             ui 工具 · md 渲染 · views/ 各页面
├── tests/               fakes 假上游 · unit 接口与 MCP · e2e 浏览器全链路
├── deploy/              docker-compose + update.sh
├── scripts/ci.sh        本地 CI = GitHub Actions 跑的同一个脚本
└── Dockerfile           只有代码；容器只读，数据全在挂载的 /data
```

```
data/                          docker-compose 同级，唯一可写目录
├── vmarker.db                 SQLite
├── projects/<id>/project.json 元信息   *.md 内容   .history/ 旧版   releases/vN/ 快照   video/vN.mp4
├── series/<id>/series.json    元信息   设定.md
├── trash/                     删除的项目和系列
└── tmp/                       上传中的临时文件
```

## 架构决策

- **每种数据只有一份真相**：元信息在 JSON，内容在 Markdown，过程（对话、任务）在 SQLite。状态从任务推导，不存。
- **确认即快照**：制作端只看 releases/vN，确认后改文件不影响进行中的任务。
- **AI 用 `<file>` 标签写文件**，不依赖函数调用；没写完整的不落盘，旧版进 .history。
- **生成跑在后台任务里**：浏览器断线照样保存，回来能续看。
- **AI 不能给自己放行**：确认、审片、设置只认会话；MCP 没有对应工具。
- **领取 = 原子 UPDATE + claim 凭证 + 租约**：过期可被抢走，旧 worker 的写入会被拒绝。
- **第一个登录者是所有者**，其他 Pocket ID 账号拒绝。

## 开发规范

- `make setup` 一次；`make dev` 开发；`make ci` 是 push 前必过的检查。
- 仓库公开，真实凭证不能进 git。前端所有数据字符串先 `esc()`。
- 每文件 ≤ 800 行，每目录 ≤ 8 个文件。

## 变更日志

- 2026-11-25 初版。
