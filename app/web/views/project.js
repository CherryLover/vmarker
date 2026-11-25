// 项目工作台：左边对话，右边文件 / 制作
import { api, chip, dialog, esc, on, size, toast, when } from "/static/ui.js";
import { go } from "/static/app.js";
import { md } from "/static/md.js";
import { chatPanel } from "/static/views/chat.js";
import { filesPanel } from "/static/views/files.js";

const VIDEO = { uploaded: "已上传", review: "待审", approved: "已通过", rejected: "已打回" };
const OPEN = ["queued", "working", "review"];

export async function render(root, id) {
  const [p, series] = await Promise.all([api(`/api/v1/projects/${id}`), api("/api/v1/series")]);
  root.innerHTML = `<div class="row between"><div class="grow"><div class="row"><h1>${esc(p.title)}</h1><span data-status>${chip(p.status)}</span></div>
      <p class="muted">${p.series ? `<a href="/s/${esc(p.series.id)}">${esc(p.series.name)}</a> · 第 ${p.position} 集 · ` : ""}${esc(p.brief)}</p></div>
    <div class="row"><button class="btn" data-edit>编辑</button>${p.series ? "" : '<button class="btn" data-series>转成系列</button>'}
      <button class="btn danger" data-del>删除</button></div></div>
    <div class="bench"><section class="card chat" data-chat></section>
      <section class="card side"><div class="tabs" role="tablist"><button role="tab" data-tab="files">文件</button><button role="tab" data-tab="make">制作</button></div>
        <div class="col" data-pane="files"></div><div class="col" data-pane="make"></div></section></div>`;

  const files = filesPanel(root.querySelector('[data-pane="files"]'), id);
  const tab = (name) => {
    root.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name));
    root.querySelectorAll("[data-pane]").forEach((d) => d.classList.toggle("hidden", d.dataset.pane !== name));
  };
  on(root, "[data-tab]", "click", (b) => tab(b.dataset.tab));
  tab(p.tasks.length ? "make" : "files");

  on(root, "[data-edit]", "click", () => dialog("编辑视频", `<label>标题<input name="title" required maxlength="120" value="${esc(p.title)}"></label>
    <label>需求<textarea name="brief">${esc(p.brief)}</textarea></label><label>系列<select name="series_id"><option value="">独立视频</option>
    ${series.map((s) => `<option value="${esc(s.id)}" ${s.id === p.series_id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label>`, "保存", async (f) => {
    await api(`/api/v1/projects/${id}`, { method: "PUT", body: { ...f, series_id: f.series_id || null } });
    go(`/p/${id}`);
  }));
  on(root, "[data-series]", "click", () => dialog("转成系列的第 1 集", `<label>系列名称<input name="name" required maxlength="120" value="${esc(p.title)}"></label>`, "创建系列", async (f) => {
    go(`/s/${(await api(`/api/v1/projects/${id}/to-series`, { method: "POST", body: f })).id}`);
  }));
  on(root, "[data-del]", "click", async () => {
    if (!confirm(`删除「${p.title}」？文件和视频会移到服务器的 data/trash。`)) return;
    await api(`/api/v1/projects/${id}`, { method: "DELETE" });
    go("/");
  });

  makePanel(root, id, p);
  await chatPanel(root.querySelector("[data-chat]"), id, () => files.list().then(() => tab("files")));
}

// ---------------------------------------------------------------- 制作
function makePanel(root, id, first) {
  const pane = root.querySelector('[data-pane="make"]');
  let last = "";

  function draw(p) {
    const snap = JSON.stringify([p.tasks, p.videos]);
    if (snap === last) return;  // 没变化就不重画，避免打断正在播放的视频
    last = snap;
    root.querySelector("[data-status]").innerHTML = chip(p.status);
    const open = p.tasks.find((t) => OPEN.includes(t.status));
    pane.innerHTML = `${open ? taskCard(open) : `<p class="muted">确认后会给当前所有文件拍一份快照，制作端按快照做。</p>
      <button class="btn primary" data-confirm>确认文案，提交制作</button>`}
      ${p.videos.map(videoCard).join("")}<h2>任务记录</h2>${p.tasks.filter((t) => t !== open).map(taskCard).join("") || '<p class="muted">还没有。</p>'}`;
    bind();
  }
  const reload = async () => { last = ""; draw(await api(`/api/v1/projects/${id}`)); };
  const act = (sel, path, opts = {}) => on(pane, sel, "click", async (b) => { await api(path(b), { method: "POST", ...opts }); await reload(); });

  function bind() {
    act("[data-confirm]", () => `/api/v1/projects/${id}/confirm`);
    act("[data-approve]", (b) => `/api/v1/tasks/${b.dataset.approve}/approve`);
    act("[data-retry]", (b) => `/api/v1/tasks/${b.dataset.retry}/retry`);
    act("[data-cancel]", (b) => `/api/v1/tasks/${b.dataset.cancel}/cancel`);
    on(pane, "[data-reject]", "click", (b) => dialog("打回修改", '<label>要改什么<textarea name="feedback" required></textarea></label>', "打回", async (f) => {
      await api(`/api/v1/tasks/${b.dataset.reject}/reject`, { method: "POST", body: f });
      toast("已打回，并生成了新任务");
      await reload();
    }));
    on(pane, "[data-delv]", "click", async (b) => {
      if (!confirm("永久删除这个视频文件？")) return;
      await api(`/api/v1/videos/${b.dataset.delv}`, { method: "DELETE" });
      await reload();
    });
  }

  draw(first);
  const timer = setInterval(async () => {
    if (!pane.isConnected) return clearInterval(timer);
    if (!document.hidden) draw(await api(`/api/v1/projects/${id}`).catch(() => first));
  }, 10000);
}

const BUTTONS = {
  queued: (t) => `<button class="btn sm" data-cancel="${t.id}">取消</button>`,
  working: (t) => `<button class="btn sm" data-cancel="${t.id}">取消</button>`,
  review: (t) => `<button class="btn sm primary" data-approve="${t.id}">通过</button><button class="btn sm danger" data-reject="${t.id}">打回</button>`,
  failed: (t) => `<button class="btn sm" data-retry="${t.id}">重试</button>`,
  canceled: (t) => `<button class="btn sm" data-retry="${t.id}">重试</button>`,
};

const taskCard = (t) => `<div class="note col"><div class="row between"><div class="row">${chip(t.status)}<span class="small">任务 #${t.id} · 文案 v${t.release}</span></div>
    <div class="row">${BUTTONS[t.status]?.(t) || ""}</div></div>
  ${t.progress ? `<p class="small">${esc(t.worker)}：${esc(t.progress)}</p>` : ""}${t.feedback ? `<p class="small">修改意见：${esc(t.feedback)}</p>` : ""}
  ${t.error ? `<p class="small bad">${esc(t.error)}</p>` : ""}<p class="muted small">${when(t.updated_at)}</p></div>`;

const videoCard = (v) => `<div class="col"><video controls preload="metadata" playsinline src="/api/v1/videos/${v.id}"></video>
  <div class="row between"><span class="small">v${v.version} · ${esc(VIDEO[v.status])} · ${size(v.size)} · ${when(v.created_at)}</span>
    <div class="row"><a class="btn sm" href="/api/v1/videos/${v.id}?download=1" download>下载</a>
    ${["rejected", "uploaded"].includes(v.status) ? `<button class="btn sm danger" data-delv="${v.id}">删除</button>` : ""}</div></div>
  ${v.note ? `<div class="md small">${md(v.note)}</div>` : ""}</div>`;
