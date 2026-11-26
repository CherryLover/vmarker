# vmarker

视频策划与制作平台：在网页里和 AI 梳理文案，确认后由 Claude（或任何支持 MCP / REST 的 AI）领任务制作、上传，你在网页上审片。

- 登录：Pocket ID（OIDC）；第一个登录的账号成为所有者
- AI：任何兼容 OpenAI 格式的接口，可拉取最新模型、真实测试、按对话切换
- 文件：内容是 Markdown，元信息是 JSON，其余在 SQLite，全部位于 `data/`
- 视频：网页播放、下载、打回、通过

## 部署

```bash
mkdir vmarker && cd vmarker
curl -O https://raw.githubusercontent.com/CherryLover/vmarker/main/deploy/docker-compose.yml
curl -O https://raw.githubusercontent.com/CherryLover/vmarker/main/deploy/update.sh && chmod +x update.sh
vi .env && chmod 600 .env   # 参照 .env.example
./update.sh                 # 首次和以后更新都只跑这一句
```

服务监听 `127.0.0.1:8710`，用反向代理提供 HTTPS。反向代理要允许大文件上传，并关闭 `/api` 的响应缓冲。
经过 Cloudflare 代理时，单次上传受套餐限制（免费版 100 MB）。

## 接入 Claude

在「设置」生成带「制作」权限的 Key：

```bash
claude mcp add --scope user --transport http vmarker https://你的域名/mcp --header "Authorization: Bearer vmk_..."
```

工具：`claim_task` `report_progress` `submit_video` `fail_task` `list_projects` `get_project` `create_project` `save_file`。
视频用 HTTP 上传：`curl -fsS -T 成片.mp4 -H "Authorization: Bearer $KEY" -H "X-Claim: $CLAIM" https://你的域名/api/v1/tasks/ID/video`
封面（可选，JPG/PNG ≤ 10 MB，审片页做 poster；须在 submit 之前上传，重传即替换）：`curl -fsS -T 封面.jpg -H "Authorization: Bearer $KEY" -H "X-Claim: $CLAIM" https://你的域名/api/v1/tasks/ID/cover`

REST 文档在 `/api/docs`。

## 开发

```bash
cp .env.example .env && make setup && make dev   # http://localhost:8710
make ci                                          # 防泄密 → ruff → 测试 → docker build
```
