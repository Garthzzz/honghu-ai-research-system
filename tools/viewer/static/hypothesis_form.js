/* Stage 4-A 假说表单:动态信号/交易行 + 搜索式多选器 + 新建/编辑提交。
    不预填任何内容(prefill 仅在 edit 模式回显研究员自己已存的数据)。 */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const PREFILL = JSON.parse(($("#hyp-prefill") || {}).textContent || "{}");
  const COMPANIES = JSON.parse(($("#hyp-companies") || {}).textContent || "[]");
  const COMP_NAME = {}; COMPANIES.forEach(c => { COMP_NAME[c.id] = c.name; });
  const MODE = PREFILL.mode || "new";
  const HID = PREFILL.id || null;
  const form = $("#hyp-form");

  // ── 搜索式多选器(source/news/voice/event/company)──
  function wirePicker(root) {
    const kind = root.dataset.kind;
    const search = $(".hyp-picker-search", root);
    const results = $(".hyp-picker-results", root);
    const chips = $(".hyp-picker-chips", root);
    const sel = new Map();           // id → label
    root._ids = () => Array.from(sel.keys());
    root._add = (id, label) => { if (!sel.has(id)) { sel.set(id, label || ("#" + id)); render(); } };
    function render() {
      chips.innerHTML = "";
      sel.forEach((label, id) => {
        const c = document.createElement("span");
        c.className = "hyp-pchip";
        c.innerHTML = `${label} <button type="button" data-id="${id}" title="移除"></button>`;
        chips.appendChild(c);
      });
    }
    chips.addEventListener("click", e => {
      const b = e.target.closest("button[data-id]");
      if (b) { sel.delete(parseInt(b.dataset.id, 10)); render(); }
    });
    let timer = null;
    search.addEventListener("input", () => {
      clearTimeout(timer);
      const q = search.value.trim();
      if (!q) { results.innerHTML = ""; return; }
      timer = setTimeout(async () => {
        try {
          const r = await fetch(`/api/hyp/search?kind=${kind}&q=${encodeURIComponent(q)}`);
          const d = await r.json();
          results.innerHTML = "";
          (d.results || []).forEach(it => {
            const row = document.createElement("div");
            row.className = "hyp-presult";
            row.textContent = it.label;
            row.addEventListener("click", () => { root._add(it.id, it.label); results.innerHTML = ""; search.value = ""; });
            results.appendChild(row);
          });
          if (!(d.results || []).length) results.innerHTML = '<div class="hyp-presult hyp-pre-empty">无匹配</div>';
        } catch (e) { results.innerHTML = ""; }
      }, 220);
    });
    document.addEventListener("click", e => { if (!root.contains(e.target)) results.innerHTML = ""; });
    return root;
  }
  $$(".hyp-picker").forEach(wirePicker);

  // ── 研究员:选「其他研究员 / 实习生」→ 显示手填姓名输入 ──
  const rSel = $("#f-researcher"), rName = $("#f-researcher-name");
  if (rSel && rName) {
    const toggleRName = () => {
      rName.style.display = (rSel.value === "__other__" || rSel.value === "__intern__") ? "" : "none";
    };
    rSel.addEventListener("change", toggleRName); toggleRName();
  }

  // ── 板块 chip 切换(假说级)──
  $$("#f-boards .fchip").forEach(ch => ch.addEventListener("click", () => ch.classList.toggle("fchip-on")));
  const boardIds = () => $$("#f-boards .fchip.fchip-on").map(c => parseInt(c.dataset.id, 10));

  // ── 信号行 ──
  const sigC = $("#signals-container");
  function addSignal(data) {
    const node = $("#tpl-signal").content.firstElementChild.cloneNode(true);
    if (data && data.id) node.dataset.signalId = data.id;
    if (data) {
      $(".srow-type", node).value = data.signal_type || "falsification";
      $(".srow-desc", node).value = data.description || "";
      $(".srow-target", node).value = data.observation_target || "";
      $(".srow-kw", node).value = (data.kw || []).join(", ");
    }
    // 删除:已入库的信号(有 signal_id)调后端删除 API,新加的仅前端移除
    $(".hyp-row-del", node).addEventListener("click", async () => {
      const sid = node.dataset.signalId;
      if (sid && HID) {
        if (!confirm("删除该监控信号?")) return;
        await postJSON(`/api/hypothesis/${HID}/signal/${sid}/delete`, {});
      }
      node.remove();
    });
    sigC.appendChild(node);
  }
  $("#add-signal").addEventListener("click", () => addSignal());

  // ── 交易行 ──
  function addTrade(scenario, data) {
    const cont = scenario === "primary" ? $("#primary-container") : $("#reverse-container");
    const node = $("#tpl-trade").content.firstElementChild.cloneNode(true);
    node.dataset.scenario = scenario;
    if (data && data.trade_id) node.dataset.tradeId = data.trade_id;
    // 删除:已入库的交易(有 trade_id)调后端删除 API,新加的(无 id)仅前端移除
    $(".hyp-row-del", node).addEventListener("click", async () => {
      const tid = node.dataset.tradeId;
      if (tid && HID) {
        if (!confirm("删除该交易方案?")) return;
        await postJSON(`/api/hypothesis/${HID}/trade/${tid}/delete`, {});
      }
      node.remove();
    });
    const picker = wirePicker($(".trow-company-picker", node));
    if (data) {
      $(".trow-dir", node).value = data.direction || "long";
      $(".trow-desc", node).value = data.target_description || "";
      $(".trow-pos", node).value = data.position_sizing || "";
      $(".trow-entry", node).value = data.entry_trigger || "";
      $(".trow-exit", node).value = data.exit_trigger || "";
      (data.industry_ids || []).forEach(id => {
        const opt = $(`.trow-boards option[value="${id}"]`, node);
        if (opt) opt.selected = true;
      });
      (data.company_ids || []).forEach(id => picker._add(id, COMP_NAME[id] || ("#" + id)));
    }
    cont.appendChild(node);
  }
  $$(".add-trade").forEach(b => b.addEventListener("click", () => addTrade(b.dataset.scenario)));

  // ── 收集行 → 数据 ──
  function collectSignals() {
    return $$(".hyp-srow", sigC).map(r => ({
      signal_type: $(".srow-type", r).value,
      description: $(".srow-desc", r).value.trim(),
      observation_target: $(".srow-target", r).value.trim(),
      ai_check_keywords: $(".srow-kw", r).value,
      _existing: !!r._existing
    })).filter(s => s.description);
  }
  function collectTrades() {
    return $$(".hyp-trow", form).map(r => ({
      trade_id: r.dataset.tradeId ? parseInt(r.dataset.tradeId, 10) : null,
      trade_scenario: r.dataset.scenario,
      direction: $(".trow-dir", r).value,
      target_description: $(".trow-desc", r).value.trim(),
      target_industry_ids: $$(".trow-boards option:checked", r).map(o => parseInt(o.value, 10)),
      target_company_ids: $(".trow-company-picker", r)._ids(),
      position_sizing: $(".trow-pos", r).value.trim(),
      entry_trigger: $(".trow-entry", r).value.trim(),
      exit_trigger: $(".trow-exit", r).value.trim()
    })).filter(t => t.target_description);
  }
  function basePayload() {
    return {
      researcher_id: $("#f-researcher").value,
      researcher_name: $("#f-researcher-name") ? $("#f-researcher-name").value.trim() : "",
      title: $("#f-title").value.trim(),
      thesis_type: (($('input[name="thesis_type"]:checked') || {}).value) || "",
      conviction_level: (($('input[name="conviction"]:checked') || {}).value) || "",
      horizon_months: $("#f-horizon").value,
      hypothesis_text: $("#f-text").value.trim(),
      related_industry_ids: boardIds(),
      related_company_ids: $("#f-companies").closest(".hyp-picker")._ids(),
      cite_source_ids: $("#f-cite-source").closest(".hyp-picker")._ids(),
      cite_news_ids: $("#f-cite-news").closest(".hyp-picker")._ids(),
      cite_voice_ids: $("#f-cite-voice").closest(".hyp-picker")._ids(),
      cite_event_ids: $("#f-cite-event").closest(".hyp-picker")._ids()
    };
  }
  const msg = $("#hyp-form-msg");
  async function postJSON(url, body) {
    return HonghuDomainMutations.postJSON('hypothesis:' + url, url, body);
  }

  async function submit(isDraft) {
    msg.textContent = "保存中…"; msg.className = "hyp-msg-pending";
    const payload = basePayload();
    payload.is_draft = isDraft ? 1 : 0;
    payload.signals = collectSignals();
    payload.trades = collectTrades();
    if (MODE === "new") {
      const { ok, data } = await postJSON("/api/hypothesis", payload);
      if (ok && data.ok) { msg.textContent = "已保存,跳转…"; location.href = "/hypothesis/" + data.hypothesis_id; }
      else { showErr(data); }
    } else {
      // 编辑:核心字段 → /edit;交易 → /trade(逐条);新信号(本次新增的)→ /signal
      payload.updated_by = payload.researcher_id;
      const { ok, data } = await postJSON(`/api/hypothesis/${HID}/edit`, payload);
      if (!(ok && data.ok)) { showErr(data); return; }
      for (const tr of payload.trades) { await postJSON(`/api/hypothesis/${HID}/trade`, tr); }
      // 仅提交"无 sid 标记"的新信号(已存信号在详情页改状态,避免重复插入)
      for (const s of payload.signals.filter(x => !x._existing)) {
        await postJSON(`/api/hypothesis/${HID}/signal`, s);
      }
      msg.textContent = "已保存,跳转…"; location.href = "/hypothesis/" + HID;
    }
  }
  function showErr(data) {
    let t = "保存失败:" + (data.error || "未知错误");
    if (data.dangling) t += " · dangling=" + JSON.stringify(data.dangling);
    msg.textContent = t; msg.className = "hyp-msg-err";
  }
  $("#save-hyp").addEventListener("click", () => submit(false));
  if ($("#save-draft")) $("#save-draft").addEventListener("click", () => submit(true));

  // ── 预填(edit 模式)──
  function prefill() {
    const h = PREFILL.h;
    if (h) {
      $("#f-researcher").value = h.researcher_id || "";
      $("#f-title").value = h.title || "";
      $("#f-text").value = h.hypothesis_text || "";
      $("#f-horizon").value = h.horizon_months || "";
      const rt = $(`input[name="thesis_type"][value="${h.thesis_type}"]`); if (rt) rt.checked = true;
      const rc = $(`input[name="conviction"][value="${h.conviction_level}"]`); if (rc) rc.checked = true;
    }
    (PREFILL.industry_ids || []).forEach(id => {
      const ch = $(`#f-boards .fchip[data-id="${id}"]`); if (ch) ch.classList.add("fchip-on");
    });
    const cites = PREFILL.cites || {};
    const fill = (kind, targetId) => (cites[kind] || []).forEach(it => {
      const p = $("#" + targetId); if (p) p.closest(".hyp-picker")._add(it.id, it.label);
    });
    fill("source", "f-cite-source"); fill("news", "f-cite-news");
    fill("voice", "f-cite-voice"); fill("event", "f-cite-event");
    (cites.company || []).forEach(it => $("#f-companies").closest(".hyp-picker")._add(it.id, it.label));
    // 信号(标记为已存,编辑提交时不重复插入)
    (PREFILL.signals || []).forEach(s => { addSignal(s); });
    $$(".hyp-srow", sigC).forEach(r => { r._existing = true; });
    // 交易
    (PREFILL.trades || []).forEach(t => addTrade(t.trade_scenario, t));
  }

  if (MODE === "edit") {
    prefill();
  } else {
    // 新建:默认给出空白脚手架 —— 1 个证伪信号行 + 正向/反向各 1 个交易行(内容全空,研究员填)
    addSignal();
    addTrade("primary");
    addTrade("falsification_reverse");
  }
})();
