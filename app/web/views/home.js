// 视频列表：按状态、系列筛选；新建视频
import { api, chip, dialog, esc, on, STATUS, when } from "/static/ui.js";
import { go } from "/static/app.js";

export async function newProject(sid = "") {
  const all = await api("/api/v1/series");
  const opts = all.map((s) => `<option value="${esc(s.id)}" ${s.id === sid ? "selected" : ""}>${esc(s.name)}</option>`).join("");
  dialog("新建视频", `<label>标题<input name="title" required maxlength="120"></label>
    <label>想做什么<textarea name="brief" placeholder="一两句话就行，细节和 AI 聊"></textarea></label>
    <label>系列<select name="series_id"><option value="">独立视频</option>${opts}</select></label>`, "创建", async (f) => {
    const p = await api("/api/v1/projects", { method: "POST", body: { ...f, series_id: f.series_id || null } });
    go(`/p/${p.id}`);
  });
}

export const projectCard = (p, sub = "") => `<a class="card" href="/p/${esc(p.id)}">
  <div class="row between"><h2>${esc(p.title)}</h2>${chip(p.status)}</div>
  <p class="muted clamp">${esc(p.brief || "还没写需求")}</p><p class="muted small">${sub}更新于 ${when(p.updated_at)}</p></a>`;

export async function render(root) {
  const [list, series] = await Promise.all([api("/api/v1/projects"), api("/api/v1/series")]);
  const names = Object.fromEntries(series.map((s) => [s.id, s.name]));
  const options = (m) => Object.entries(m).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("");
  root.innerHTML = `<div class="row between"><h1>视频</h1><div class="row">
      <select data-f="status" aria-label="状态" style="width:auto"><option value="">全部状态</option>${options(STATUS)}</select>
      <select data-f="series_id" aria-label="系列" style="width:auto"><option value="">全部系列</option>${options(names)}</select>
      <button class="btn primary" data-new>新建视频</button></div></div><div class="grid" data-list></div>`;
  const draw = () => {
    const f = [...root.querySelectorAll("[data-f]")].filter((s) => s.value);
    const rows = list.filter((p) => f.every((s) => p[s.dataset.f] === s.value));
    root.querySelector("[data-list]").innerHTML = rows.map((p) =>
      projectCard(p, p.series_id ? `${esc(names[p.series_id])} · 第 ${p.position} 集 · ` : "")).join("")
      || `<p class="muted">${list.length ? "没有符合条件的视频。" : "还没有视频，点「新建视频」开始。"}</p>`;
  };
  on(root, "[data-f]", "change", draw);
  on(root, "[data-new]", "click", () => newProject());
  draw();
}
