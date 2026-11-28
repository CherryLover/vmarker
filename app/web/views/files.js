// 文件面板：列表 / 预览 / 编辑 / 历史版本（项目和系列共用）
// 打开哪个文件由 URL 决定：base 是列表地址，base/文件名 是预览；编辑和历史是页内临时状态。
import { api, dialog, esc, on, seg, size, toast, when } from "/static/ui.js";
import { back, go } from "/static/app.js";
import { md } from "/static/md.js";

export function filesPanel(root, oid, base) {
  const dir = `/api/v1/files/${oid}`;
  const url = (n) => `${dir}/${seg(n)}`;
  const owner = `/api/v1/${oid[0] === "p" ? "projects" : "series"}/${oid}`;
  let shown = null;

  const show = (name) => { shown = name || null; return (shown ? open(shown) : list()).catch((e) => toast(e.message, "error")); };

  async function list() {
    const { files } = await api(owner);
    root.innerHTML = `<div class="row between"><h2>文件</h2><button class="btn sm" data-new>新建文件</button></div>
      <div>${files.map((f) => `<div class="item"><a class="btn sm" href="${esc(base)}/${esc(seg(f.name))}">📄 ${esc(f.name)}</a>
        <span class="muted small">${size(f.size)} · ${when(f.updated_at)}</span></div>`).join("") || '<p class="muted">还没有文件。让 AI 整理，或手动新建。</p>'}</div>`;
    on(root, "[data-new]", "click", () => dialog("新建文件", '<label>文件名<input name="name" required placeholder="备注.md"></label>', "下一步", (f) => {
      const name = f.name.trim().replace(/(\.md)?$/, ".md");
      if (files.some((x) => x.name === name)) throw new Error("已有同名文件");
      edit(name, "");
    }));
  }

  async function open(name) {
    const { content } = await api(url(name));
    root.innerHTML = `<div class="row between"><h2>${esc(name)}</h2><div class="row">
      <button class="btn sm" data-back>返回</button><button class="btn sm" data-hist>历史</button>
      <button class="btn sm danger" data-del>删除</button><button class="btn sm primary" data-edit>编辑</button></div></div><div class="md">${md(content)}</div>`;
    on(root, "[data-back]", "click", () => back(base, base.replace(/\/files$/, "")));
    on(root, "[data-edit]", "click", () => edit(name, content));
    on(root, "[data-hist]", "click", () => hist(name));
    on(root, "[data-del]", "click", async () => {
      if (!confirm(`删除 ${name}？旧版会留在 .history。`)) return;
      await api(url(name), { method: "DELETE" });
      go(base, { replace: true });
    });
  }

  function edit(name, content) {
    root.innerHTML = `<h2>编辑 ${esc(name)}</h2><textarea class="editor" aria-label="文件内容"></textarea>
      <div class="row"><button class="btn primary" data-save>保存</button><button class="btn" data-back>取消</button></div>`;
    const area = root.querySelector("textarea");
    area.value = content;
    on(root, "[data-back]", "click", () => show(shown));
    on(root, "[data-save]", "click", async () => {
      await api(url(name), { method: "PUT", body: { content: area.value } });
      toast("已保存");
      if (shown === name) await open(name);
      else go(`${base}/${seg(name)}`);  // 新建的文件：保存后进入它的预览地址
    });
  }

  async function hist(name) {
    const rows = await api(`${url(name)}/history`);
    root.innerHTML = `<div class="row between"><h2>${esc(name)} 的历史版本</h2><button class="btn sm" data-back>返回</button></div>
      ${rows.map((r) => `<div class="item"><button class="btn sm" data-v="${esc(r.version)}">${esc(r.version)}（UTC）</button></div>`).join("") || '<p class="muted">没有旧版。</p>'}`;
    on(root, "[data-back]", "click", () => open(name));
    on(root, "[data-v]", "click", async (b) => edit(name, (await api(`${url(name)}/history/${b.dataset.v}`)).content));
  }

  return { show, reload: () => show(shown), edit, get shown() { return shown; } };
}
