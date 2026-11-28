// ============================================================================
//  app —— 启动 + 路由
//
//  URL 是页面状态的唯一真相：标签页、打开的文件都在路径里，刷新 / 分享 / 后退都对。
//  视图签名：async render(root, params) → 可选 { update(params) }
//    同一视图同一 id 之间跳转（换标签、开文件）只调 update，不重建（对话流、轮询不断）。
//  三种跳转：go 前进一步 · go(…, {replace}) 原地换 · refresh 重画当前页（不留历史）
// ============================================================================
import { api, esc } from "/static/ui.js";
import * as home from "/static/views/home.js";
import * as project from "/static/views/project.js";
import * as series from "/static/views/series.js";
import * as settings from "/static/views/settings.js";

const ROUTES = [
  [/^\/p\/(?<id>[^/]+)(?:\/(?<tab>chat|files|make))?(?:\/(?<file>[^/]+))?$/, project.render, "/"],
  [/^\/s\/(?<id>[^/]+)(?:\/files\/(?<file>[^/]+))?$/, series.renderOne, "/series"],
  [/^\/series$/, series.renderList, "/series"],
  [/^\/settings$/, settings.render, "/settings"],
  [/^\/$/, home.render, "/"],
];
const root = document.getElementById("root");
const here = () => location.pathname;
let mounted = null, seq = 0;
history.scrollRestoration = "manual";

// ---------------------------------------------------------------- 跳转
export function go(url, { replace = false } = {}) {
  history.replaceState({ ...history.state, y: scrollY }, "");
  const prev = replace ? history.state?.prev : here();
  history[replace ? "replaceState" : "pushState"]({ prev }, "", url);
  render(replace ? scrollY : 0);
}

// 页内的「返回」：上一步还在 scope（同一个项目 / 系列）里就真后退，
// 否则原地换到 fallback —— 从外部直接打开的链接，点返回不会退出站点
export function back(fallback, scope = fallback) {
  const prev = history.state?.prev || "";
  if (prev === scope || prev.startsWith(`${scope}/`)) history.back();
  else go(fallback, { replace: true });
}

export function refresh() { mounted = null; render(scrollY); }

// 视图拿到数据后声明自己：标题、属于哪个主导航、上级路径
export function page({ title, section, crumbs = [] }) {
  document.title = title ? `${title} · vmarker` : "vmarker";
  document.querySelectorAll("[data-nav]").forEach((a) => a.dataset.nav === section
    ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  document.getElementById("crumbs").innerHTML = crumbs.map(([label, href]) => `<a href="${esc(href)}">${esc(label)}</a>`).join("");
}

// ---------------------------------------------------------------- 渲染
function match() {
  for (const [re, view, section] of ROUTES) {
    const m = here().match(re);
    if (!m) continue;
    const params = Object.fromEntries(Object.entries(m.groups || {}).map(([k, v]) => [k, v && decodeURIComponent(v)]));
    return { view, section, params };
  }
  return { view: home.render, section: "/", params: {} };
}

async function render(y) {
  const { view, section, params } = match();
  if (mounted?.view === view && mounted.id === params.id && mounted.update) {
    mounted.update(params);
    return scrollTo(0, y);
  }
  const token = ++seq;
  mounted = null;
  page({ section });
  // 每次换一个新容器：旧视图的异步回调只会写到已移除的节点上
  const el = Object.assign(document.createElement("div"), { className: "col" });
  root.replaceChildren(el);
  try {
    const out = await view(el, params);
    if (token === seq) mounted = { view, id: params.id, update: out?.update };
  } catch (e) {
    el.innerHTML = `<section class="card"><h2>出错了</h2><p class="bad">${esc(e.message)}</p></section>`;
  }
  if (token === seq) scrollTo(0, y);
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[href^='/']");
  if (!a || a.target || a.hasAttribute("download") || e.metaKey || e.ctrlKey || e.shiftKey) return;
  if (/^\/(api|auth|mcp)/.test(a.getAttribute("href"))) return;
  e.preventDefault();
  if (a.getAttribute("href") !== here()) go(a.getAttribute("href"), { replace: a.hasAttribute("data-replace") });
});
window.addEventListener("popstate", () => render(history.state?.y || 0));

const me = await api("/api/v1/me");
document.getElementById("user").innerHTML = `<span class="muted small">${esc(me.name)}</span>
  <form method="post" action="/auth/logout"><button class="btn sm">退出</button></form>`;
render(0);
