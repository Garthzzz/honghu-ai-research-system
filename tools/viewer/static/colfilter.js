/* colfilter.js — Excel 式列头多选 dropdown filter + 列排序(纯原生,无依赖)
 * 渐进增强:表格由 Jinja SSR 渲染,本脚本只接管交互(禁用 JS 仍可看内容)。
 *
 * 用法(模板侧):
 *   <table class="colfilter" data-cf-group="dp">
 *     <thead><tr>
 *       <th data-cf-sort="text">指标</th>            ← 排序(字母)
 *       <th data-cf-sort="date">时点</th>             ← 排序(日期,默认无)
 *       <th data-cf-sort="num">数值</th>              ← 排序(数值)
 *       <th data-cf-filter="consensus" data-cf-filter2="em">共识</th>  ← 单/双 facet dropdown
 *       <th data-cf-filter="forecast">性质</th>
 *       ...
 *     </tr></thead>
 *     <tbody>
 *       <tr data-cf-consensus="主流" data-cf-em="pdf_direct" data-cf-forecast="实际"
 *           data-cf-sentiment="看涨" data-cf-tier="2"
 *           data-cf-sortkey-text="CR5" data-cf-sortkey-date="2026-03-31" data-cf-sortkey-num="80.2"> ...
 *   同一 data-cf-group 的多张表联动筛选(distinct 值取并集,筛选作用于全部表)。
 *   facet 内多选 = OR;facet 之间 = AND。关键字搜索由外部 input[data-cf-search] 控制(匹配 data-cf-text)。
 */
(function () {
  "use strict";

  const FACET_LABEL = {
    consensus: "共识", em: "抽取", forecast: "性质",
    sentiment: "倾向", tier: "tier",
    stype: "类型", vlayer: "价值层", pub: "publisher",
  };

  function byGroup() {
    const groups = {};
    document.querySelectorAll("table.colfilter").forEach((tbl) => {
      const g = tbl.dataset.cfGroup || "default";
      (groups[g] = groups[g] || []).push(tbl);
    });
    return groups;
  }

  function allRows(tables) {
    const rows = [];
    tables.forEach((t) => t.querySelectorAll("tbody tr").forEach((r) => rows.push(r)));
    return rows;
  }

  function distinctValues(rows, facet) {
    const set = new Set();
    rows.forEach((r) => {
      const v = r.dataset["cf" + cap(facet)];
      if (v !== undefined && v !== "") set.add(v);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b, "zh"));
  }
  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  // 每个 group 的筛选状态:{ facet: Set(selected) }(空 Set = 不筛该 facet)
  function makeState() { return { facets: {}, keyword: "" }; }

  function applyFilter(tables, state) {
    const kw = (state.keyword || "").trim().toLowerCase();
    tables.forEach((tbl) => {
      let visibleInTbl = 0;
      tbl.querySelectorAll("tbody tr").forEach((r) => {
        let show = true;
        for (const facet in state.facets) {
          const sel = state.facets[facet];
          if (sel && sel.size > 0) {
            const v = r.dataset["cf" + cap(facet)];
            if (!sel.has(v)) { show = false; break; }
          }
        }
        if (show && kw) {
          const hay = (r.dataset.cfText || r.textContent || "").toLowerCase();
          if (hay.indexOf(kw) === -1) show = false;
        }
        r.style.display = show ? "" : "none";
        if (show) visibleInTbl++;
      });
      // 隐藏空表所在的 section/panel(以及它前面的分组标题,如 sources 的 tier 头)
      const section = tbl.closest("section");
      if (section) {
        section.style.display = visibleInTbl === 0 ? "none" : "";
        let prev = section.previousElementSibling;
        if (prev && prev.classList.contains("source-group-header")) {
          prev.style.display = visibleInTbl === 0 ? "none" : "";
        }
      }
      const cnt = tbl.parentElement && tbl.parentElement.querySelector("[data-cf-rowcount]");
      if (cnt) cnt.textContent = visibleInTbl;
    });
  }

  function renderChips(state, chipBar, onClear) {
    if (!chipBar) return;
    chipBar.innerHTML = "";
    let any = false;
    for (const facet in state.facets) {
      const sel = state.facets[facet];
      if (sel && sel.size > 0) {
        sel.forEach((v) => {
          any = true;
          const chip = document.createElement("span");
          chip.className = "cf-chip";
          chip.innerHTML = (FACET_LABEL[facet] || facet) + ":" + v + " ×";
          chip.onclick = () => { sel.delete(v); onClear(); };
          chipBar.appendChild(chip);
        });
      }
    }
    if (state.keyword) {
      any = true;
      const chip = document.createElement("span");
      chip.className = "cf-chip";
      chip.innerHTML = "搜索:" + state.keyword + " ×";
      chip.onclick = () => { state.keyword = ""; const si = document.querySelector("[data-cf-search]"); if (si) si.value = ""; onClear(); };
      chipBar.appendChild(chip);
    }
    chipBar.style.display = any ? "" : "none";
  }

  function buildDropdown(facet, rows, state, refresh) {
    const values = distinctValues(rows, facet);
    const wrap = document.createElement("div");
    wrap.className = "cf-dd";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "cf-funnel";
    btn.title = "筛选 " + (FACET_LABEL[facet] || facet);
    btn.innerHTML = "⏷";
    const panel = document.createElement("div");
    panel.className = "cf-dd-panel";
    panel.hidden = true;

    // 搜索框(facet 值多时有用,如 publisher)
    const search = document.createElement("input");
    search.type = "text";
    search.className = "cf-dd-search";
    search.placeholder = "搜索…";
    panel.appendChild(search);

    const actions = document.createElement("div");
    actions.className = "cf-dd-actions";
    const selAll = document.createElement("button"); selAll.type = "button"; selAll.textContent = "全选";
    const clr = document.createElement("button"); clr.type = "button"; clr.textContent = "清空";
    actions.appendChild(selAll); actions.appendChild(clr);
    panel.appendChild(actions);

    const list = document.createElement("div");
    list.className = "cf-dd-list";
    panel.appendChild(list);

    state.facets[facet] = state.facets[facet] || new Set();
    const sel = state.facets[facet];

    values.forEach((v) => {
      const lab = document.createElement("label");
      lab.className = "cf-dd-item";
      const cb = document.createElement("input");
      cb.type = "checkbox"; cb.value = v; cb.checked = sel.has(v);
      cb.onchange = () => { if (cb.checked) sel.add(v); else sel.delete(v); btn.classList.toggle("cf-funnel-on", sel.size > 0); refresh(); };
      lab.appendChild(cb);
      const sp = document.createElement("span"); sp.textContent = v; lab.appendChild(sp);
      list.appendChild(lab);
    });

    search.oninput = () => {
      const q = search.value.toLowerCase();
      list.querySelectorAll(".cf-dd-item").forEach((it) => {
        it.style.display = it.textContent.toLowerCase().indexOf(q) === -1 ? "none" : "";
      });
    };
    selAll.onclick = () => { list.querySelectorAll('input[type=checkbox]').forEach((cb) => { if (cb.parentElement.style.display !== "none") { cb.checked = true; sel.add(cb.value); } }); btn.classList.add("cf-funnel-on"); refresh(); };
    clr.onclick = () => { list.querySelectorAll('input[type=checkbox]').forEach((cb) => { cb.checked = false; }); sel.clear(); btn.classList.remove("cf-funnel-on"); refresh(); };

    btn.onclick = (e) => {
      e.stopPropagation();
      document.querySelectorAll(".cf-dd-panel").forEach((p) => { if (p !== panel) p.hidden = true; });
      // 打开时同步勾选态(同一 facet 在多张表表头有多个 dropdown,共享同一选择集)
      list.querySelectorAll('input[type=checkbox]').forEach((cb) => { cb.checked = sel.has(cb.value); });
      panel.hidden = !panel.hidden;
    };
    document.addEventListener("click", (e) => { if (!wrap.contains(e.target)) panel.hidden = true; });

    btn.classList.toggle("cf-funnel-on", sel.size > 0);
    wrap.appendChild(btn);
    wrap.appendChild(panel);
    return wrap;
  }

  function sortTables(tables, facet, kind, dir) {
    tables.forEach((tbl) => {
      const tb = tbl.querySelector("tbody");
      if (!tb) return;
      const rows = Array.from(tb.querySelectorAll("tr"));
      rows.sort((a, b) => {
        let va = a.dataset["cfSortkey" + cap(facet)] || "";
        let vb = b.dataset["cfSortkey" + cap(facet)] || "";
        if (kind === "num") { va = parseFloat(va); vb = parseFloat(vb); if (isNaN(va)) va = -Infinity; if (isNaN(vb)) vb = -Infinity; return dir * (va - vb); }
        return dir * String(va).localeCompare(String(vb), "zh");
      });
      rows.forEach((r) => tb.appendChild(r));
    });
  }

  function init() {
    const groups = byGroup();
    for (const g in groups) {
      const tables = groups[g];
      const rows = allRows(tables);
      const state = makeState();
      const chipBar = document.querySelector('[data-cf-chips="' + g + '"]');
      const refresh = () => { applyFilter(tables, state); renderChips(state, chipBar, refresh); };

      // 用第一张表的 thead 作为列定义(各表结构相同)
      const headRow = tables[0].querySelector("thead tr");
      if (!headRow) continue;
      const ths = Array.from(headRow.children);
      // 对所有表的同位置 th 都装 UI(避免只第一张表有)
      tables.forEach((tbl) => {
        const hrs = tbl.querySelector("thead tr");
        if (!hrs) return;
        Array.from(hrs.children).forEach((th) => {
          if (th.querySelector(".cf-head-ui")) return;
          const facets = [th.dataset.cfFilter, th.dataset.cfFilter2].filter(Boolean);
          const sortKind = th.dataset.cfSort;
          if (!facets.length && !sortKind) return;
          const ui = document.createElement("span");
          ui.className = "cf-head-ui";
          facets.forEach((f) => ui.appendChild(buildDropdown(f, rows, state, refresh)));
          if (sortKind) {
            const sb = document.createElement("button");
            sb.type = "button"; sb.className = "cf-sort"; sb.innerHTML = "↕";
            let dir = 0;
            sb.onclick = () => { dir = dir === 1 ? -1 : 1; sb.innerHTML = dir === 1 ? "↑" : "↓";
              document.querySelectorAll(".cf-sort").forEach((o) => { if (o !== sb) o.innerHTML = "↕"; });
              sortTables(tables, f2camel(sortKind, th), sortKind, dir); };
            ui.appendChild(sb);
          }
          th.appendChild(ui);
        });
      });

      // 关键字搜索(共享 input)
      const search = document.querySelector('[data-cf-search="' + g + '"]');
      if (search) { search.addEventListener("input", () => { state.keyword = search.value; refresh(); }); }
      // 清空所有
      const clearAll = document.querySelector('[data-cf-clearall="' + g + '"]');
      if (clearAll) clearAll.addEventListener("click", (e) => {
        e.preventDefault();
        for (const f in state.facets) state.facets[f].clear();
        state.keyword = "";
        if (search) search.value = "";
        document.querySelectorAll('table.colfilter[data-cf-group="' + g + '"] input[type=checkbox]').forEach((cb) => cb.checked = false);
        document.querySelectorAll('table.colfilter[data-cf-group="' + g + '"] .cf-funnel').forEach((b) => b.classList.remove("cf-funnel-on"));
        refresh();
      });
    }
  }
  // sortkey 字段名 = sort kind 不直接对应,th 用 data-cf-sortfield 指定;回退用 kind
  function f2camel(kind, th) { return th.dataset.cfSortfield || kind; }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
