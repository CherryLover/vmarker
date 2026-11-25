// 系列：列表；详情（集数排序、设定、提炼）
import { api, dialog, esc, on, toast } from "/static/ui.js";
import { go } from "/static/app.js";
import { newProject, projectCard } from "/static/views/home.js";
import { filesPanel } from "/static/views/files.js";

const fields = (s = {}) => `<label>名称<input name="name" required maxlength="120" value="${esc(s.name)}"></label>
  <label>简介<textarea name="description">${esc(s.description)}</textarea></label>`;

export async function renderList(root) {
  const list = await api("/api/v1/series");
  root.innerHTML = `<div class="row between"><h1>系列</h1><button class="btn primary" data-new>新建系列</button></div>
    <div class="grid">${list.map((s) => `<a class="card" href="/s/${esc(s.id)}"><div class="row between"><h2>${esc(s.name)}</h2>
      <span class="chip">${s.count} 集</span></div><p class="muted clamp">${esc(s.description)}</p></a>`).join("") || '<p class="muted">还没有系列。</p>'}</div>`;
  on(root, "[data-new]", "click", () => dialog("新建系列", fields(), "创建", async (f) => {
    go(`/s/${(await api("/api/v1/series", { method: "POST", body: f })).id}`);
  }));
}

export async function renderOne(root, id) {
  const s = await api(`/api/v1/series/${id}`);
  const n = s.episodes.length;
  root.innerHTML = `<div class="row between"><div><h1>${esc(s.name)}</h1><p class="muted">${esc(s.description)}</p></div>
    <div class="row"><button class="btn" data-edit>编辑</button><button class="btn" data-distill>AI 提炼设定</button>
      <button class="btn danger" data-del>删除</button><button class="btn primary" data-new>新增一集</button></div></div>
    <div class="bench"><section class="col"><h2>集数</h2>${s.episodes.map((p, i) => `<div class="row" style="flex-wrap:nowrap">
      <div class="grow">${projectCard(p, `第 ${p.position} 集 · `)}</div><div class="col">
      <button class="btn sm" data-move="${i}" data-by="-1" aria-label="上移" ${i ? "" : "disabled"}>↑</button>
      <button class="btn sm" data-move="${i}" data-by="1" aria-label="下移" ${i < n - 1 ? "" : "disabled"}>↓</button></div></div>`).join("") || '<p class="muted">还没有视频。</p>'}</section>
      <section class="card" data-files></section></div>`;
  const reload = () => go(`/s/${id}`);
  const files = filesPanel(root.querySelector("[data-files]"), id);
  on(root, "[data-new]", "click", () => newProject(id));
  on(root, "[data-edit]", "click", () => dialog("编辑系列", fields(s), "保存", async (f) => {
    await api(`/api/v1/series/${id}`, { method: "PUT", body: f });
    reload();
  }));
  on(root, "[data-move]", "click", async (b) => {
    const ids = s.episodes.map((p) => p.id), i = +b.dataset.move, j = i + +b.dataset.by;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    await api(`/api/v1/series/${id}/order`, { method: "PUT", body: { ids } });
    reload();
  });
  on(root, "[data-distill]", "click", async () => {
    toast("正在提炼…");
    const { content } = await api(`/api/v1/series/${id}/distill`, { method: "POST", body: {} });
    files.edit("设定.md", content);  // 放进编辑框，由人确认后保存
  });
  on(root, "[data-del]", "click", async () => {
    if (!confirm(`删除系列「${s.name}」？会移到服务器的 data/trash。`)) return;
    await api(`/api/v1/series/${id}`, { method: "DELETE" });
    go("/series");
  });
}
