(function(){
  function qs(sel, root){ return (root || document).querySelector(sel); }
  function drawer(){
    var el = qs('[data-opp-drawer]');
    if (!el) return null;
    var close = qs('[data-opp-close]', el);
    if (close && !close.dataset.bound) {
      close.dataset.bound = '1';
      close.addEventListener('click', function(){ el.hidden = true; });
    }
    return el;
  }

  function clear(el){
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function node(tag, className, text){
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined && text !== null) el.textContent = String(text);
    return el;
  }

  function appendKV(parent, label, value){
    if (value === undefined || value === null || value === '') return;
    var dt = node('dt', null, label);
    var dd = node('dd', null, value);
    parent.appendChild(dt);
    parent.appendChild(dd);
  }

  function formatValue(record){
    if (!record) return '';
    var unit = record.unit ? ' ' + record.unit : '';
    if (record.value_num !== undefined && record.value_num !== null) return String(record.value_num) + unit;
    if (record.value_text) return String(record.value_text) + unit;
    return '';
  }

  function displayLabel(value){
    var labels = window.OPP_DISPLAY_LABELS || {};
    return labels[value] || value;
  }

  function objectLabel(payload){
    var type = payload && (payload.canonical_object_type || payload.object_type || payload.table || payload.scheme);
    var labels = {
      'research.industry_data_point': 'A/B 行研数据点',
      'research.source': 'A/B 行研来源',
      'source': '机会透镜来源',
      'data_point': '机会透镜数据点',
      'metric_slot': '指标槽',
      'factor_score': '因子评分',
      'external_url': '外部 URL'
    };
    return labels[type] || type || '证据对象';
  }

  function appendLink(parent, label, href){
    if (!href) return;
    var a = node('a', 'opp-evidence-link', label);
    a.href = href;
    if (/^https?:\/\//.test(href)) {
      a.target = '_blank';
      a.rel = 'noopener';
    }
    parent.appendChild(a);
  }

  function appendExcerpt(parent, title, text){
    if (!text) return;
    var wrap = node('div', 'opp-evidence-excerpt');
    wrap.appendChild(node('h4', null, title));
    wrap.appendChild(node('blockquote', null, text));
    parent.appendChild(wrap);
  }

  function appendTranslation(parent, title, text){
    if (!text) return;
    var wrap = node('div', 'opp-translation');
    wrap.appendChild(node('b', null, title));
    wrap.appendChild(node('span', null, text));
    parent.appendChild(wrap);
  }

  function appendWarning(parent, text){
    if (!text) return;
    parent.appendChild(node('div', 'opp-stale-warning', text));
  }

  function appendRecordSummary(card, payload){
    var record = payload && payload.record ? payload.record : {};
    var linkedSource = payload && payload.linked_source ? payload.linked_source : null;
    var type = payload && (payload.canonical_object_type || payload.object_type);
    var dl = node('dl', 'opp-evidence-kv');

    if (type === 'research.industry_data_point' || type === 'data_point') {
      appendKV(dl, '指标', record.metric);
      appendKV(dl, '期间/时点', record.period || record.as_of_date);
      appendKV(dl, '数值', formatValue(record));
      appendKV(dl, '抽取方法', record.extraction_method_display || record.calculation_review_status_display || displayLabel(record.extraction_method || record.calculation_review_status));
      appendKV(dl, '证据角色', record.policy_evidence_role_display || displayLabel(record.policy_evidence_role));
      appendKV(dl, '核心评分资格', record.scoring_eligibility_display || displayLabel(record.scoring_eligibility));
      if (linkedSource) {
        appendKV(dl, '来源标题', linkedSource.title);
        appendKV(dl, '来源中文标题', linkedSource.title_zh);
        appendKV(dl, '发布方', linkedSource.publisher);
        appendKV(dl, '发布时间', linkedSource.publish_date);
        appendKV(dl, '来源质量', linkedSource.source_credibility || linkedSource.quality_tier);
      }
      card.appendChild(dl);
      appendWarning(card, record.freshness_warning || (linkedSource && linkedSource.freshness_warning));
      appendExcerpt(card, '引用的原文摘录', record.source_excerpt_display || record.source_excerpt);
      appendTranslation(card, '中文译意', record.source_excerpt_zh);
      appendLink(card, '查看主行研 source 详情', payload.deep_link);
      return;
    }

    if (type === 'research.source' || type === 'source' || payload.scheme === 'url') {
      appendKV(dl, '标题', record.title);
      appendKV(dl, '中文标题', record.title_zh);
      appendKV(dl, '发布方', record.publisher);
      appendKV(dl, '发布时间', record.publish_date);
      appendKV(dl, '来源等级', record.source_tier || record.quality_tier || record.source_credibility);
      appendKV(dl, '复核状态', record.source_review_status_display || displayLabel(record.source_review_status));
      appendKV(dl, '证据角色', record.policy_evidence_role_display || displayLabel(record.policy_evidence_role));
      appendKV(dl, '核心评分资格', record.scoring_eligibility_display || displayLabel(record.scoring_eligibility));
      card.appendChild(dl);
      appendWarning(card, record.freshness_warning);
      appendExcerpt(card, '本轮使用的原文摘录', record.excerpt_display || record.excerpt);
      appendTranslation(card, '中文译意', record.excerpt_zh);
      appendLink(card, '查看来源详情', payload.deep_link);
      appendLink(card, '打开原始 URL', record.url || record.source_url);
      return;
    }

    appendKV(dl, '对象类型', objectLabel(payload));
    appendKV(dl, '记录 ID', payload && payload.id);
    appendKV(dl, '表', payload && payload.table);
    card.appendChild(dl);
  }

  function normalizedText(value){
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function semanticKind(header, maxLen){
    var h = normalizedText(header);
    if (/代码|ticker|Ticker|证券|合约|标识|代码\/标识/.test(h)) {
      return maxLen > 14 ? 'code' : 'medium';
    }
    if (/^(ID|id)$/.test(h) || /排名|优先级|分数|核心分|状态|证据$|观测|观测数|方向|权重|类型|成熟度|覆盖度|置信度|验证债|已评分|早期信号|来源$/.test(h)) {
      return maxLen > 24 && /来源/.test(h) ? 'medium' : 'short';
    }
    if (/期间|日期|时间|财务日期|发布时间/.test(h)) return 'date';
    if (/核心判断|证实|证伪|交易操作框架|研究响应|投资研究建议|条件|来源和原文|引用的原文|原文|摘录|说明|分析|风险|暴露|比较|公式|含义|指标含义|业务摘要|研究问题|监控信号|预计变化|后续监控/.test(h)) {
      return 'long';
    }
    if (maxLen >= 42) return 'long';
    if (maxLen <= 12) return 'short';
    return 'medium';
  }

  function columnWidth(kind, header, maxLen){
    var headerLen = normalizedText(header).length;
    if (kind === 'short') return Math.max(72, Math.min(132, 34 + Math.max(headerLen, maxLen) * 9));
    if (kind === 'code') return Math.max(180, Math.min(420, 72 + Math.max(headerLen, maxLen) * 7));
    if (kind === 'date') return Math.max(128, Math.min(190, 74 + Math.max(headerLen, maxLen) * 6));
    if (kind === 'long') return Math.max(340, Math.min(720, 150 + Math.max(headerLen, maxLen) * 5));
    return Math.max(160, Math.min(320, 86 + Math.max(headerLen, maxLen) * 5));
  }

  function autoSizeTable(table){
    if (!table || table.dataset.oppAutosized === '1') return;
    var headerCells = Array.prototype.slice.call(table.querySelectorAll('thead th'));
    if (!headerCells.length) {
      var firstRow = table.querySelector('tr');
      headerCells = firstRow ? Array.prototype.slice.call(firstRow.children) : [];
    }
    if (!headerCells.length) return;
    var colCount = headerCells.length;
    var rows = Array.prototype.slice.call(table.querySelectorAll('tr'));
    var widths = [];
    var kinds = [];
    for (var i = 0; i < colCount; i += 1) {
      var header = normalizedText(headerCells[i] && headerCells[i].textContent);
      var codeColumn = /代码|ticker|Ticker|证券|合约|标识|代码\/标识/.test(header);
      var maxLen = header.length;
      rows.forEach(function(row){
        var cell = row.children[i];
        if (!cell) return;
        var text = normalizedText(cell.textContent);
        var weighted = codeColumn
          ? text.length
          : text.replace(/[A-Za-z0-9_.:/%-]+/g, function(token){
            return token.length > 12 ? token.slice(0, 12) : token;
          }).length;
        maxLen = Math.max(maxLen, Math.min(weighted, 120));
      });
      var kind = semanticKind(header, maxLen);
      kinds.push(kind);
      widths.push(columnWidth(kind, header, maxLen));
    }
    var minWidth = widths.reduce(function(total, width){ return total + width; }, 0);
    var colgroup = table.querySelector('colgroup');
    if (colgroup) colgroup.remove();
    colgroup = document.createElement('colgroup');
    widths.forEach(function(width, index){
      var col = document.createElement('col');
      col.style.width = Math.round(width) + 'px';
      col.className = 'opp-auto-col opp-auto-col-' + kinds[index];
      colgroup.appendChild(col);
    });
    table.insertBefore(colgroup, table.firstChild);
    rows.forEach(function(row){
      Array.prototype.forEach.call(row.children, function(cell, index){
        cell.classList.remove('opp-col-kind-short', 'opp-col-kind-date', 'opp-col-kind-medium', 'opp-col-kind-long');
        cell.classList.add('opp-col-kind-' + (kinds[index] || 'medium'));
      });
    });
    table.classList.add('opp-autosized-table');
    table.style.tableLayout = 'fixed';
    table.style.minWidth = Math.max(minWidth, 720) + 'px';
    table.dataset.oppAutosized = '1';
  }

  function updateScrollMirror(wrapper){
    if (!wrapper || !wrapper._oppScrollMirror) return;
    var table = wrapper.querySelector('table');
    var mirror = wrapper._oppScrollMirror;
    var inner = wrapper._oppScrollMirrorInner;
    if (!table || !inner) return;
    var width = Math.max(table.scrollWidth, table.offsetWidth, wrapper.scrollWidth, wrapper.clientWidth + 1);
    inner.style.width = width + 'px';
    var needsMirror = width > wrapper.clientWidth + 8;
    mirror.hidden = !needsMirror;
    wrapper.classList.toggle('opp-wide-scroll-with-mirror', needsMirror);
    if (needsMirror) mirror.scrollLeft = wrapper.scrollLeft;
  }

  function installScrollMirror(wrapper){
    if (!wrapper || wrapper.dataset.oppScrollMirror === '1') {
      updateScrollMirror(wrapper);
      return;
    }
    var table = wrapper.querySelector('table');
    if (!table) return;
    var mirror = node('div', 'opp-scroll-mirror');
    mirror.setAttribute('aria-hidden', 'true');
    var inner = node('div', 'opp-scroll-mirror-inner');
    mirror.appendChild(inner);
    wrapper.parentNode.insertBefore(mirror, wrapper);
    wrapper.dataset.oppScrollMirror = '1';
    wrapper._oppScrollMirror = mirror;
    wrapper._oppScrollMirrorInner = inner;
    var syncing = false;
    function sync(source, target){
      if (syncing) return;
      syncing = true;
      target.scrollLeft = source.scrollLeft;
      syncing = false;
    }
    wrapper.addEventListener('scroll', function(){ sync(wrapper, mirror); });
    mirror.addEventListener('scroll', function(){ sync(mirror, wrapper); });
    updateScrollMirror(wrapper);
  }

  function installScrollMirrors(root){
    Array.prototype.forEach.call((root || document).querySelectorAll('.opp-wide-scroll'), installScrollMirror);
  }

  function refreshScrollMirrors(root){
    Array.prototype.forEach.call((root || document).querySelectorAll('.opp-wide-scroll'), updateScrollMirror);
  }

  function autoSizeTables(root){
    Array.prototype.forEach.call((root || document).querySelectorAll('.opp-page table'), autoSizeTable);
    installScrollMirrors(root || document);
    window.setTimeout(function(){ refreshScrollMirrors(root || document); }, 0);
  }

  function initRequestGenerator(){
    var root = qs('[data-opp-request-generator]');
    if (!root || root.dataset.oppRequestBound === '1') return;
    root.dataset.oppRequestBound = '1';

    function field(id){
      var el = qs('#' + id, root);
      return el ? String(el.value || '').trim() : '';
    }

    function checked(name){
      var el = qs('input[name="' + name + '"]:checked', root);
      return el ? el.value : '';
    }

    function codeBlock(value){
      return '```text\n' + (value || '') + '\n```';
    }

    function section(title, body){
      return '## ' + title + '\n\n' + body;
    }

    function materialPathValue(choice){
      var value = field('oppReqMaterialPath');
      if (choice === 'B' && !value) {
        return '资料为本地研报或附件包：请将研报资料压缩打包发送给张正泽，并通过企业微信同步任务名称、资料范围、文件数量、重点说明和需要特别关注的问题。本栏无需填写本机路径。';
      }
      if (choice === 'A' && !value) return '';
      return value;
    }

    function materialNoteValue(choice){
      var value = field('oppReqMaterialNote');
      if (choice === 'B') {
        var submitNote = '如资料为研报、PDF、Excel 或会议纪要，资料交付以压缩包发送和企业微信同步为准；系统仍需独立做公开资料检索、source review 和证据核验，不能直接继承研报结论。';
        return value ? value + '\n\n' + submitNote : submitNote;
      }
      if (choice === 'A' && !value) return '无';
      return value;
    }

    function constraintsValue(){
      var items = [];
      var free = field('oppReqConstraints');
      var requiredData = field('oppReqRequiredData');
      var minDataPoints = field('oppReqMinDataPoints');
      var minWords = field('oppReqMinWords');
      if (free) items.push(free);
      if (requiredData) items.push('必须收集的信息 / 数据：\n' + requiredData);
      if (minDataPoints) items.push('可信数据点最低要求：' + minDataPoints);
      if (minWords) items.push('分析文字最低要求：' + minWords);
      return items.join('\n\n');
    }

    function buildMarkdown(){
      var material = checked('oppReqMaterial') || 'A';
      var policy = checked('oppReqPolicy') || 'B';
      var timeDefault = checked('oppReqTimeDefault') || '是';
      var scopeDefault = checked('oppReqScopeDefault') || '是';
      var constraintDefault = checked('oppReqConstraintDefault') || '是';
      var parts = [
        '# Opportunity Lens 研究请求（正式填写模板）',
        section('必填 1：研究问题', codeBlock(field('oppReqQuestion'))),
        section('必填 2：可用资料状态',
          'A. 无资料  \n' +
          'B. 有 papers / 研报文件夹  \n' +
          'C. 有可以参考的行研库行业  \n\n' +
          '选择（A / B / C）：\n\n' + codeBlock(material) + '\n\n' +
          '资料路径 / 行研库行业名称：\n\n' + codeBlock(materialPathValue(material)) + '\n\n' +
          '补充说明：\n\n' + codeBlock(materialNoteValue(material))
        ),
        section('必填 3：证据策略',
          'A. freshness_first / 时效优先  \n' +
          'B. balanced / 平衡  \n' +
          'C. accuracy_first / 准确优先  \n\n' +
          '选择（A / B / C）：\n\n' + codeBlock(policy)
        ),
        section('选填 1：时间窗口',
          '默认：核心窗口为未来 12 个月；长期背景为未来 3 年。\n\n' +
          '是否使用默认（是 / 否）：\n\n' + codeBlock(timeDefault) + '\n\n' +
          '核心窗口：\n\n' + codeBlock(field('oppReqCoreWindow')) + '\n\n' +
          '长期背景：\n\n' + codeBlock(field('oppReqLongWindow'))
        ),
        section('选填 2：研究范围',
          '默认：全球多语言搜索；不预设候选池；系统可以自行扩展候选。\n\n' +
          '是否使用默认（是 / 否）：\n\n' + codeBlock(scopeDefault) + '\n\n' +
          '地理范围：\n\n' + codeBlock(field('oppReqGeo')) + '\n\n' +
          '行业 / 环节：\n\n' + codeBlock(field('oppReqSegments')) + '\n\n' +
          '公司 / 材料候选：\n\n' + codeBlock(field('oppReqCandidates')) + '\n\n' +
          '必须包含：\n\n' + codeBlock(field('oppReqMustInclude')) + '\n\n' +
          '必须排除：\n\n' + codeBlock(field('oppReqMustExclude'))
        ),
        section('选填 3：特殊约束',
          '默认：无。\n\n' +
          '是否使用默认（是 / 否）：\n\n' + codeBlock(constraintDefault) + '\n\n' +
          '特殊约束：\n\n' + codeBlock(constraintsValue())
        )
      ];
      return parts.join('\n\n---\n\n') + '\n';
    }

    function status(text){
      var el = qs('[data-opp-request-status]', root);
      if (el) el.textContent = text || '';
    }

    function output(){
      var el = qs('#oppReqOutput', root);
      if (!el) return '';
      el.value = buildMarkdown();
      var missing = [];
      if (!field('oppReqQuestion')) missing.push('研究问题');
      if (!checked('oppReqPolicy')) missing.push('证据策略');
      status(missing.length ? '已生成，但仍缺少：' + missing.join('、') + '。' : '已生成标准 Markdown request。');
      return el.value;
    }

    function updateMaterialNote(){
      var note = qs('[data-material-note="B"]', root);
      if (note) note.hidden = checked('oppReqMaterial') !== 'B';
    }

    function filename(){
      var title = field('oppReqTitle') || 'Opportunity_Lens_研究请求';
      title = title.replace(/[\\/:*?"<>|]+/g, '_').replace(/\s+/g, '_').slice(0, 80);
      if (!/^Opportunity_Lens/.test(title)) title = 'Opportunity_Lens_' + title;
      return title + '.md';
    }

    var generateBtn = qs('[data-opp-generate-request]', root);
    if (generateBtn) generateBtn.addEventListener('click', output);

    var copyBtn = qs('[data-opp-copy-request]', root);
    if (copyBtn) copyBtn.addEventListener('click', function(){
      var text = output();
      if (!text) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function(){ status('已复制生成结果。'); }).catch(function(){ status('复制失败，请手动全选输出框内容。'); });
      } else {
        var el = qs('#oppReqOutput', root);
        if (el) {
          el.focus();
          el.select();
          try { document.execCommand('copy'); status('已复制生成结果。'); }
          catch(e) { status('复制失败，请手动全选输出框内容。'); }
        }
      }
    });

    var downloadBtn = qs('[data-opp-download-request]', root);
    if (downloadBtn) downloadBtn.addEventListener('click', function(){
      var text = output();
      if (!text) return;
      var blob = new Blob([text], {type: 'text/markdown;charset=utf-8'});
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename();
      document.body.appendChild(a);
      a.click();
      setTimeout(function(){ URL.revokeObjectURL(a.href); a.remove(); }, 0);
      status('已生成下载文件：' + a.download);
    });

    Array.prototype.forEach.call(root.querySelectorAll('input, textarea'), function(el){
      el.addEventListener('input', function(){ if (el.name === 'oppReqMaterial') updateMaterialNote(); });
      el.addEventListener('change', function(){ updateMaterialNote(); });
    });
    updateMaterialNote();
    output();
  }

  function appendExplanation(card, explanation){
    if (!explanation) return;
    if (explanation.plain_steps && explanation.plain_steps.length) {
      var section = node('section', 'opp-evidence-section');
      section.appendChild(node('h4', null, '字段和口径说明'));
      var ul = node('ul', null);
      explanation.plain_steps.forEach(function(step){ ul.appendChild(node('li', null, step)); });
      section.appendChild(ul);
      card.appendChild(section);
    }
    if (explanation.json_guide && explanation.json_guide.length) {
      var details = node('details', 'opp-evidence-details');
      details.appendChild(node('summary', null, '审计字段说明'));
      var guide = node('ul', null);
      explanation.json_guide.forEach(function(step){ guide.appendChild(node('li', null, step)); });
      details.appendChild(guide);
      card.appendChild(details);
    }
  }

  function renderEvidence(data, body){
    var payload = data && data.data ? data.data : data;
    var explanation = payload && payload.human_explanation ? payload.human_explanation : null;
    clear(body);
    var card = node('article', 'opp-evidence-card');
    var head = node('header', 'opp-evidence-head');
    head.appendChild(node('span', 'opp-evidence-pill', objectLabel(payload)));
    head.appendChild(node('h3', null, (explanation && explanation.headline) || '证据说明'));
    card.appendChild(head);
    appendRecordSummary(card, payload || {});
    appendExplanation(card, explanation);
    body.appendChild(card);
  }

  document.addEventListener('click', function(ev){
    var btn = ev.target.closest('[data-opp-evidence]');
    if (!btn) return;
    var ref = btn.getAttribute('data-opp-evidence');
    var el = drawer();
    if (!el) return;
    var body = qs('[data-opp-drawer-body]', el);
    el.hidden = false;
    body.textContent = '正在加载 ' + ref + ' ...';
    fetch('/api/opportunity-lens/evidence/resolve?ref=' + encodeURIComponent(ref))
      .then(function(r){ return r.json(); })
      .then(function(data){ renderEvidence(data, body); })
      .catch(function(err){ body.textContent = String(err); });
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function(){
      autoSizeTables(document);
      initRequestGenerator();
    });
  } else {
    autoSizeTables(document);
    initRequestGenerator();
  }
  var mirrorResizePending = false;
  window.addEventListener('resize', function(){
    if (mirrorResizePending) return;
    mirrorResizePending = true;
    window.requestAnimationFrame(function(){
      mirrorResizePending = false;
      refreshScrollMirrors(document);
    });
  });
})();
