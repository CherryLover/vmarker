// 设置：AI 模型（OpenAI 格式）、API Key、MCP 接入
import { api, dialog, esc, formData, on, toast, when } from "/static/ui.js";
import { page, refresh } from "/static/app.js";

const PRESETS = {
  OpenAI: "https://api.openai.com/v1",
  Claude: "https://api.anthropic.com/v1",
  DeepSeek: "https://api.deepseek.com/v1",
  Gemini: "https://generativelanguage.googleapis.com/v1beta/openai",
};

function providerDialog(p = {}) {
  const d = dialog(p.id ? "编辑 AI" : "添加 AI", `<div class="row">${Object.keys(PRESETS).map((k) => `<button type="button" class="btn sm" data-preset="${k}">${k}</button>`).join("")}</div>
    <label>名称<input name="name" required maxlength="60" value="${esc(p.name)}"></label>
    <label>Base URL<input name="base_url" required value="${esc(p.base_url)}" placeholder="https://…/v1"></label>
    <label>API Key<input name="api_key" type="password" autocomplete="off" placeholder="${p.id ? "留空则不变" : ""}"></label>
    <div class="row"><button type="button" class="btn sm" data-models>获取最新模型</button><span class="small muted" data-hint>也可以直接手填模型名</span></div>
    <label>模型<input name="model" required list="model-list" value="${esc(p.model)}"></label><datalist id="model-list"></datalist>
    <select data-pick class="hidden" aria-label="从列表选择模型"></select>`, "保存并测试", async (f) => {
    const { test } = await api(p.id ? `/api/v1/providers/${p.id}` : "/api/v1/providers", { method: p.id ? "PUT" : "POST", body: f });
    toast(test.ok ? `测试通过（${test.ms} ms）：${test.detail}` : `已保存，但测试失败：${test.detail}`, test.ok ? "" : "error");
    refresh();
  });
  const form = d.querySelector("form");
  on(d, "[data-preset]", "click", (b) => { form.base_url.value = PRESETS[b.dataset.preset]; form.elements.name.value ||= b.dataset.preset; });
  on(d, "[data-models]", "click", async () => {
    const f = formData(form);
    const saved = p.id && !f.api_key && f.base_url.replace(/\/+$/, "") === p.base_url;
    const ids = saved ? await api(`/api/v1/providers/${p.id}/models`)
      : await api("/api/v1/providers/models", { method: "POST", body: { base_url: f.base_url, api_key: f.api_key } });
    const opts = ids.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("");
    d.querySelector("datalist").innerHTML = opts;
    const pick = d.querySelector("[data-pick]");
    pick.innerHTML = `<option value="">从 ${ids.length} 个模型里选…</option>${opts}`;
    pick.classList.remove("hidden");
    d.querySelector("[data-hint]").textContent = `拿到 ${ids.length} 个模型，能按发布时间排的排最新在前`;
  });
  on(d, "[data-pick]", "change", (s) => { if (s.value) form.model.value = s.value; });
}

const providerRow = (p) => `<div class="item"><div class="grow"><div class="row"><b>${esc(p.name)}</b>${p.is_default ? '<span class="chip ok">默认</span>' : ""}
    ${p.test_ok === null ? '<span class="chip">未测试</span>' : `<span class="chip ${p.test_ok ? "ok" : "err"}">${p.test_ok ? "可用" : "不可用"}</span>`}</div>
    <p class="muted small">${esc(p.model)} · ${esc(p.base_url)}</p>${p.test_detail ? `<p class="small">${esc(p.test_detail)}（${when(p.tested_at)}）</p>` : ""}</div>
  <div class="row"><button class="btn sm" data-test="${p.id}">测试</button>${p.is_default ? "" : `<button class="btn sm" data-def="${p.id}">设为默认</button>`}
    <button class="btn sm" data-edit="${p.id}">编辑</button><button class="btn sm danger" data-delp="${p.id}">删除</button></div></div>`;

const scopesOf = (k) => k.scopes.split(",").filter(Boolean);
const keyRow = (k) => {
  const admin = scopesOf(k).includes("admin");
  const ops = k.revoked_at ? '<span class="chip">已吊销</span>'
    : `<div class="row"><button class="btn sm" data-admin="${k.id}">${admin ? "取消全部权限" : "给全部权限"}</button><button class="btn sm danger" data-revoke="${k.id}">吊销</button></div>`;
  return `<div class="item"><div class="grow"><b>${esc(k.name)}</b> <code>${esc(k.prefix)}…</code>${admin ? ' <span class="chip err">全部权限</span>' : ""}
    <p class="muted small">${esc(["read", ...scopesOf(k)].join(" / "))} · 最近使用 ${when(k.last_used_at)}</p></div>${ops}</div>`;
};

export async function render(root) {
  const [me, providers, keys] = await Promise.all(["me", "providers", "keys"].map((x) => api(`/api/v1/${x}`)));
  page({ title: "设置", section: "/settings" });
  root.innerHTML = `<h1>设置</h1>
    <section class="card"><div class="row between"><h2>AI 模型</h2><button class="btn primary" data-add>添加 AI</button></div>
      <p class="muted">任何兼容 OpenAI 格式的接口都可以。保存时会真实对话一次来验证。</p><div>${providers.map(providerRow).join("") || '<p class="muted">还没有配置。</p>'}</div></section>
    <section class="card"><div class="row between"><h2>API Key</h2><button class="btn primary" data-key>生成 Key</button></div><div data-fresh></div>
      <div>${keys.map(keyRow).join("") || '<p class="muted">还没有。</p>'}</div></section>
    <section class="card"><h2>接入 Claude（MCP）</h2><p class="muted">生成一个带「制作」权限的 Key，然后在本机执行：</p>
      <div class="secret">claude mcp add --scope user --transport http vmarker ${esc(me.base_url)}/mcp --header "Authorization: Bearer vmk_你的Key"</div>
      <p class="muted">MCP 里的 api_index / call_api 能调用全部 REST 接口；人的动作（确认、审片、设置）需要 Key 有「全部权限」。其他 AI 可以直接用 REST，文档在 <a href="/api/docs" target="_blank">/api/docs</a>。</p></section>
    <section class="card"><h2>账号</h2><div class="row between"><span>${esc(me.name)}</span>
      <form method="post" action="/auth/logout"><button class="btn sm">退出登录</button></form></div></section>`;
  const reload = refresh;
  on(root, "[data-add]", "click", () => providerDialog());
  on(root, "[data-edit]", "click", (b) => providerDialog(providers.find((p) => p.id === +b.dataset.edit)));
  on(root, "[data-test]", "click", async (b) => {
    const r = await api(`/api/v1/providers/${b.dataset.test}/test`, { method: "POST" });
    toast(r.ok ? `可用（${r.ms} ms）：${r.detail}` : r.detail, r.ok ? "" : "error");
    reload();
  });
  on(root, "[data-def]", "click", async (b) => { await api(`/api/v1/providers/${b.dataset.def}/default`, { method: "POST" }); reload(); });
  on(root, "[data-delp]", "click", async (b) => {
    if (!confirm("删除这个 AI 配置？")) return;
    await api(`/api/v1/providers/${b.dataset.delp}`, { method: "DELETE" });
    reload();
  });
  on(root, "[data-admin]", "click", async (b) => {
    const k = keys.find((x) => x.id === +b.dataset.admin), on = !scopesOf(k).includes("admin");
    if (on && !confirm("全部权限等同你本人：能确认文案、通过/打回审片、改设置和 Key。只给你信任的程序。继续？")) return;
    const scopes = on ? [...scopesOf(k), "admin"] : scopesOf(k).filter((s) => s !== "admin");
    await api(`/api/v1/keys/${k.id}`, { method: "PUT", body: { scopes } });
    reload();
  });
  on(root, "[data-revoke]", "click", async (b) => {
    if (!confirm("吊销后，使用它的程序会立即失效。继续？")) return;
    await api(`/api/v1/keys/${b.dataset.revoke}`, { method: "DELETE" });
    reload();
  });
  on(root, "[data-key]", "click", () => dialog("生成 API Key", `<label>名称<input name="name" required maxlength="60" placeholder="Claude 制作端"></label>
    <label class="check"><input type="checkbox" name="plan"> 策划：新建项目、写文件</label>
    <label class="check"><input type="checkbox" name="produce" checked> 制作：领任务、上传视频</label>
    <label class="check"><input type="checkbox" name="admin"> 全部权限：等同你本人，能确认文案、审片、改设置</label><p class="muted small">所有 Key 都能读取项目内容；没有「全部权限」的 Key 不能确认文案、审片或改设置。</p>`, "生成", async (f) => {
    const scopes = ["plan", "produce", "admin"].filter((s) => f[s]);
    const { key } = await api("/api/v1/keys", { method: "POST", body: { name: f.name, scopes } });
    root.querySelector("[data-fresh]").innerHTML = `<p class="note warn">只显示这一次，请现在复制：</p><div class="secret" data-secret>${esc(key)}</div>`;
  }));
}
