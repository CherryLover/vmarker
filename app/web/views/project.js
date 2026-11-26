// 项目工作台：左边对话，右边文件 / 制作
import { api, chip, dialog, esc, on, size, toast, when } from "/static/ui.js";
import { go } from "/static/app.js";
import { md } from "/static/md.js";
import { chatPanel } from "/static/views/chat.js";
import { filesPanel } from "/static/views/files.js";

const VIDEO = { uploaded: "已上传", review: "待审", approved: "已通过", rejected: "已打回" };

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
// 审片就地进行：每一版视频自带状态、提交说明、打回意见；待审那一版下面直接写意见。
function makePanel(root, id, first) {
  const pane = root.querySelector('[data-pane="make"]');
  const drafts = new Map();  // 任务 id → 没提交的意见；轮询重画时原样放回
  let last = "";

  function draw(p) {
    const snap = JSON.stringify([p.tasks, p.videos]);
    if (snap === last) return;  // 没变化就不重画，避免打断正在播放的视频
    last = snap;
    root.querySelector("[data-status]").innerHTML = chip(p.status);
    const open = p.tasks.find((t) => ["queued", "working"].includes(t.status));
    const shown = new Set([open, ...p.videos.map((v) => byId(p, v.task_id))]);
    pane.innerHTML = `${open ? taskCard(open) : p.status === "review" ? "" : `<p class="muted">确认后会给当前所有文件拍一份快照，制作端按快照做。</p>
      <button class="btn primary" data-confirm>确认文案，提交制作</button>`}
      ${p.videos.map((v) => videoCard(v, byId(p, v.task_id), reworkOf(p, v.task_id))).join("")}
      <h2>任务记录</h2>${p.tasks.filter((t) => !shown.has(t)).map(taskCard).join("") || '<p class="muted">没有其他任务。</p>'}`;
    pane.querySelectorAll("textarea[data-feedback]").forEach((a) => { a.value = drafts.get(a.dataset.feedback) || ""; });
    bind();
  }
  const reload = async () => { last = ""; draw(await api(`/api/v1/projects/${id}`)); };
  const act = (sel, path, opts = {}) => on(pane, sel, "click", async (b) => { await api(path(b), { method: "POST", ...opts }); await reload(); });

  function bind() {
    act("[data-confirm]", () => `/api/v1/projects/${id}/confirm`);
    act("[data-retry]", (b) => `/api/v1/tasks/${b.dataset.retry}/retry`);
    act("[data-cancel]", (b) => `/api/v1/tasks/${b.dataset.cancel}/cancel`);
    pane.querySelectorAll("textarea[data-feedback]").forEach((a) => a.addEventListener("input", () => drafts.set(a.dataset.feedback, a.value)));
    on(pane, "[data-approve]", "click", async (b) => {
      if (!armed(b, "确定通过？")) return;
      await api(`/api/v1/tasks/${b.dataset.approve}/approve`, { method: "POST" });
      await reload();
    });
    on(pane, "[data-reject]", "click", async (b) => {
      const box = pane.querySelector(`textarea[data-feedback="${b.dataset.reject}"]`);
      if (!box.value.trim()) { box.focus(); throw new Error("先写打回意见"); }
      if (!armed(b, "确定打回？")) return;
      await api(`/api/v1/tasks/${b.dataset.reject}/reject`, { method: "POST", body: { feedback: box.value } });
      drafts.delete(b.dataset.reject);
      toast("已打回，并生成了新任务");
      await reload();
    });
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

// 二次确认：第一次点只“上膛”换文案，4 秒内再点才算数，过时自动复原。意见框不受影响。
function armed(b, label) {
  if (b.dataset.armed) return true;
  const text = b.textContent;
  b.dataset.armed = "1";
  b.textContent = label;
  setTimeout(() => { delete b.dataset.armed; b.textContent = text; }, 4000);
  return false;
}

// 打回会立刻排一个新任务并带上意见，所以某版的打回意见 = 紧随其后那个任务的 feedback（tasks 按 id 倒序）
const byId = (p, tid) => p.tasks.find((t) => t.id === tid);
const reworkOf = (p, tid) => byId(p, tid)?.status === "rejected" ? p.tasks.filter((t) => t.id > tid).at(-1) : null;

const BUTTONS = {
  queued: (t) => `<button class="btn sm" data-cancel="${t.id}">取消</button>`,
  working: (t) => `<button class="btn sm" data-cancel="${t.id}">取消</button>`,
  failed: (t) => `<button class="btn sm" data-retry="${t.id}">重试</button>`,
  canceled: (t) => `<button class="btn sm" data-retry="${t.id}">重试</button>`,
};

const taskCard = (t) => `<div class="note col"><div class="row between"><div class="row">${chip(t.status)}<span class="small">任务 #${t.id} · 文案 v${t.release}</span></div>
    <div class="row">${BUTTONS[t.status]?.(t) || ""}</div></div>
  ${t.progress ? `<p class="small">${esc(t.worker)}：${esc(t.progress)}</p>` : ""}${t.feedback ? `<p class="small">修改意见：${esc(t.feedback)}</p>` : ""}
  ${t.error ? `<p class="small bad">${esc(t.error)}</p>` : ""}<p class="muted small">${when(t.updated_at)}</p></div>`;

// 一版 = 一块：视频 → 状态行 → 本版要求 / 提交说明 → 打回意见 或 审片框
const videoCard = (v, task, rework) => `<article class="take col ${esc(v.status)}">
  <div class="row between"><div class="row"><span class="chip ${esc(v.status)}">${esc(VIDEO[v.status] || v.status)}</span>
      <strong>v${v.version}</strong><span class="muted small">${size(v.size)} · ${when(v.created_at)}</span></div>
    <div class="row"><a class="btn sm" href="/api/v1/videos/${v.id}?download=1" download>下载</a>
    ${["rejected", "uploaded"].includes(v.status) ? `<button class="btn sm danger" data-delv="${v.id}">删除</button>` : ""}</div></div>
  <video controls preload="metadata" playsinline src="/api/v1/videos/${v.id}"${v.cover ? ` poster="/api/v1/videos/${v.id}/cover?t=${v.cover}"` : ""}></video>
  ${task?.feedback ? `<p class="small muted">本版针对：${esc(task.feedback)}</p>` : ""}
  ${v.note ? `<div class="md small"><strong>提交说明</strong>${md(v.note)}</div>` : ""}
  ${rework?.feedback ? `<div class="note err small">打回意见：${esc(rework.feedback)}</div>` : ""}
  ${v.status === "review" && task?.status === "review" ? reviewBox(task) : ""}</article>`;

const reviewBox = (t) => `<label>打回意见<textarea class="feedback" data-feedback="${t.id}" placeholder="边看边写：哪一秒、要改什么"></textarea></label>
  <div class="row"><button class="btn sm danger" data-reject="${t.id}">打回</button><button class="btn sm primary" data-approve="${t.id}">通过</button></div>`;
