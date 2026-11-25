// ============================================================================
//  ui —— 请求、转义、对话框、SSE。所有数据字符串进 innerHTML 前必须 esc()
// ============================================================================
export async function request(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method, credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) { location.href = "/login"; throw new Error("登录已过期"); }
  if (!res.ok) throw new Error(describe(await res.json().catch(() => null), res.status));
  return res;
}

function describe(data, status) {
  const d = data?.detail;
  return Array.isArray(d) ? d.map((x) => `${x.loc?.at(-1)}：${x.msg}`).join("；") : d || `HTTP ${status}`;
}

export async function api(path, opts) {
  const res = await request(path, opts);
  return res.status === 204 ? null : res.json();
}

// 读 SSE：每个 data 事件回调一次
export async function readEvents(res, onEvent) {
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    const parts = (buf + value).split("\n\n");
    buf = parts.pop();
    for (const p of parts) if (p.startsWith("data: ")) onEvent(JSON.parse(p.slice(6)));
  }
}

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
export const seg = encodeURIComponent;
export const size = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
export const when = (iso) => (iso ? new Date(iso).toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" }) : "—");

export const STATUS = {
  planning: "策划中", queued: "等待制作", working: "制作中", review: "待审片",
  done: "已完成", rejected: "已打回", failed: "失败", canceled: "已取消",
};
export const chip = (s) => `<span class="chip ${esc(s)}">${esc(STATUS[s] || s)}</span>`;

export function toast(msg, kind = "") {
  const el = Object.assign(document.createElement("div"), { className: `toast ${kind}`, textContent: msg });
  el.setAttribute("role", "status");
  document.body.append(el);
  setTimeout(() => el.remove(), 3500);
}

// 统一的事件绑定：出错弹提示，执行期间禁用按钮
export function on(root, selector, event, fn) {
  root.querySelectorAll(selector).forEach((el) => el.addEventListener(event, async (e) => {
    if (event !== "change") e.preventDefault();
    const btn = event === "submit" ? el.querySelector("[type=submit]") : el.matches("button") ? el : null;
    if (btn) btn.disabled = true;
    try { await fn(el, e); } catch (err) { toast(err.message, "error"); }
    if (btn) btn.disabled = false;
  }));
}

export const formData = (form) => Object.fromEntries(new FormData(form));

// 弹窗表单：onSubmit 抛错则留在弹窗里显示原因
export function dialog(title, fields, submitText, onSubmit) {
  const d = document.createElement("dialog");
  d.innerHTML = `<form class="col"><h2>${esc(title)}</h2>${fields}<p class="bad small" role="alert"></p>
    <div class="row"><button class="btn primary" type="submit">${esc(submitText)}</button><button class="btn" type="button" data-close>取消</button></div></form>`;
  d.querySelector("[data-close]").onclick = () => d.close();
  d.addEventListener("close", () => d.remove());
  d.querySelector("form").onsubmit = async (e) => {
    e.preventDefault();
    const btn = d.querySelector("[type=submit]");
    btn.disabled = true;
    try { await onSubmit(formData(e.target), d); d.close(); } catch (err) { d.querySelector("[role=alert]").textContent = err.message; }
    btn.disabled = false;
  };
  document.body.append(d);
  d.showModal();
  return d;
}
