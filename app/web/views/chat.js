// 项目对话：历史、模型选择、流式回复、断线续看
import { api, esc, on, readEvents, request, toast } from "/static/ui.js";
import { mdMessage } from "/static/md.js";

const QUICK = {
  "梳理需求": "先帮我把这支视频的受众、一句话目标、要讲和不讲的内容理清楚，信息不够就问我最关键的问题。",
  "整理成文件": "把目前聊定的内容整理成文件：规划.md、文字稿.md（旁白 | 画面 两列表格）、准备清单.md。",
  "检查能否开工": "检查现有文件是否足够让制作端直接开工，列出缺口，先不要改文件。",
};

export async function chatPanel(root, pid, onFiles) {
  const [providers, convs] = await Promise.all([api("/api/v1/providers"), api(`/api/v1/projects/${pid}/conversations`)]);
  root.innerHTML = `<div class="chat-head"><div class="row"><select data-conv aria-label="对话"></select>
      <button class="btn sm" data-new>新对话</button><button class="btn sm danger" data-del>删除</button></div>
    <div class="row"><select data-prov aria-label="AI 供应商">${providers.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>
      <select data-model aria-label="模型"></select></div></div>
    <div class="log" data-log aria-live="polite"></div>
    <form class="chat-foot" data-send><div class="row">${Object.keys(QUICK).map((k) => `<button type="button" class="btn sm" data-quick="${k}">${k}</button>`).join("")}</div>
      <textarea name="text" aria-label="消息" placeholder="说说你想做什么视频（⌘/Ctrl + Enter 发送）"></textarea>
      <div class="row"><button class="btn primary" type="submit">发送</button><button class="btn hidden" type="button" data-stop>停止</button></div></form>`;
  const $ = (s) => root.querySelector(s);
  const log = $("[data-log]"), input = $("textarea"), stop = $("[data-stop]");
  let cid = null, busy = false;

  // ------------------------------------------------------------ 模型
  async function loadModels() {
    const p = providers.find((x) => x.id === +$("[data-prov]").value);
    if (!p) return;
    const draw = (ids) => {
      const keep = $("[data-model]").value;
      $("[data-model]").innerHTML = ids.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("");
      $("[data-model]").value = ids.includes(keep) ? keep : p.model;
    };
    draw([p.model]);  // 默认模型立刻可用，列表拿到后再补全
    const ids = await api(`/api/v1/providers/${p.id}/models`).catch(() => []);
    draw([p.model, ...ids.filter((m) => m !== p.model)]);
  }

  // ------------------------------------------------------------ 渲染
  const bottom = () => { log.scrollTop = log.scrollHeight; };
  function bubble(role, text) {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    paint(el, role, text);
    log.append(el);
    return el;
  }
  const paint = (el, role, text) => {
    if (role === "user") el.textContent = text;
    else el.innerHTML = `<div class="md">${mdMessage(text)}</div>`;
  };
  function footnote(el, { error, files = [], model }) {
    if (files.length) el.insertAdjacentHTML("beforeend", `<p class="note ok small">已写入：${files.map(esc).join("、")}</p>`);
    if (error) el.insertAdjacentHTML("beforeend", `<p class="note err small">${esc(error)}</p>`);
    if (model) el.insertAdjacentHTML("beforeend", `<p class="muted small">${esc(model)}</p>`);
  }
  const setBusy = (v) => { busy = v; stop.classList.toggle("hidden", !v); };

  // ------------------------------------------------------------ 对话
  async function open(id) {
    cid = id;
    log.innerHTML = "";
    const c = await api(`/api/v1/conversations/${id}`);
    for (const m of c.messages) footnote(bubble(m.role, m.content), m.role === "user" ? {} : m);
    bottom();
    setBusy(false);
    if (c.running) watch(id, request(`/api/v1/conversations/${id}/stream`)).catch((e) => toast(e.message, "error"));
  }

  async function watch(id, pending) {
    setBusy(true);
    const el = bubble("assistant", "…");
    let text = "", end = null;
    try {
      await readEvents(await pending, (ev) => {
        if (ev.type === "done") { end = ev; return; }
        text += ev.text;
        const stick = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
        paint(el, "assistant", text);
        if (stick) bottom();
      });
      if (!end) throw new Error("连接断开；后台仍在生成，稍后刷新查看");
    } catch (e) {
      if (!text) el.remove();
      throw e;
    } finally {
      if (cid === id) setBusy(false);
    }
    paint(el, "assistant", text);
    footnote(el, end);
    bottom();
    if (end.files.length) onFiles();
  }

  async function send(text) {
    if (busy || !text.trim()) return;
    if (!providers.length) throw new Error("还没有配置 AI，请先到「设置」添加");
    setBusy(true);
    try {
      if (!cid) await create();
    } catch (e) { setBusy(false); throw e; }
    bubble("user", text);
    bottom();
    input.value = "";
    const body = { text, provider_id: +$("[data-prov]").value, model: $("[data-model]").value };
    try {
      await watch(cid, request(`/api/v1/conversations/${cid}/messages`, { method: "POST", body }));
    } catch (e) { if (!input.value) input.value = text; throw e; }
  }

  function options() {
    $("[data-conv]").innerHTML = convs.map((c) => `<option value="${c.id}" ${c.id === cid ? "selected" : ""}>${esc(c.title)}</option>`).join("") || "<option>还没有对话</option>";
  }
  async function create() {
    const c = await api(`/api/v1/projects/${pid}/conversations`, { method: "POST" });
    convs.unshift(c);
    cid = c.id;
    options();
  }

  on(root, "[data-prov]", "change", loadModels);
  on(root, "[data-conv]", "change", (el) => open(+el.value));
  on(root, "[data-new]", "click", async () => { await create(); await open(cid); });
  on(root, "[data-del]", "click", async () => {
    if (!cid || !confirm("删除这个对话？已写入的文件不受影响。")) return;
    await api(`/api/v1/conversations/${cid}`, { method: "DELETE" });
    convs.splice(convs.findIndex((c) => c.id === cid), 1);
    cid = null;
    log.innerHTML = "";
    options();
    if (convs.length) await open(convs[0].id);
  });
  on(root, "[data-quick]", "click", (b) => send(QUICK[b.dataset.quick]));
  on(root, "[data-send]", "submit", () => send(input.value));
  on(root, "[data-stop]", "click", () => api(`/api/v1/conversations/${cid}/stop`, { method: "POST" }));
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("[data-send]").requestSubmit(); });

  if (!providers.length) log.innerHTML = '<p class="note warn">还没有配置 AI。<a href="/settings">去设置添加</a></p>';
  loadModels();
  options();
  if (convs.length) { cid = convs[0].id; options(); await open(cid); }
}
