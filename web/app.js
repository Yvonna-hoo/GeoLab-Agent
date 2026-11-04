/* GeoLab Agent — 前端交互
 * 纯原生 JS，无框架、无打包。与 Python 内核通过 5 个 JSON 接口通信。
 *
 * 结构：落地页（提问 + 四张示例卡）→ 结果页（方案 → 结论 → 图表 → 参数抽屉）
 */
(function () {
  "use strict";

  var MODES = [
    { id: "run", label: "单次计算" },
    { id: "sweep", label: "参数扫描" },
    { id: "compare", label: "对照实验" },
    { id: "analyze", label: "敏感性" },
  ];

  var ICONS = {
    drop: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.2s5.6 6 5.6 10a5.6 5.6 0 1 1-11.2 0c0-4 5.6-10 5.6-10z"/><path d="M9.2 14.6a2.9 2.9 0 0 0 2.8 2.4"/></svg>',
    curve: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 19c3.4 0 5.2-4 7.4-7.6C12.4 8 14.4 5 18 5"/><path d="M15.6 5H18v2.4"/><circle cx="7" cy="19" r="1.5"/></svg>',
    layers: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9h7M15.5 9H20"/><circle cx="13.2" cy="9" r="2.2"/><path d="M4 15h3M11.5 15H20"/><circle cx="9.2" cy="15" r="2.2"/></svg>',
    chart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19V6"/><path d="M4 19h16"/><path d="M8 19v-6M12.5 19V9M17 19v-8"/></svg>',
  };

  var CARD_META = [
    { icon: "drop", tone: "c-blue", desc: "扫描 0–100% 覆盖度，看流失量怎么变" },
    { icon: "curve", tone: "c-violet", desc: "算断面流速与剪应力，找出冲刷带" },
    { icon: "layers", tone: "c-teal", desc: "梯田、等高耕作、退耕还林分别减多少" },
    { icon: "chart", tone: "c-amber", desc: "弹性系数排序，谁在放大流失" },
  ];

  var state = {
    catalog: [],
    presets: { sweep: {}, compare: {} },
    tasks: [],
    expId: null,
    mode: "run",
    params: {},
    sweepParam: null,
    sweepValues: null,
    compareKey: null,
    compareVariants: null,
    busy: false,
    log: [],
  };

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s === undefined || s === null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function num(v, digits) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return Number(v).toLocaleString("zh-CN", {
      maximumFractionDigits: digits === undefined ? 2 : digits,
    });
  }

  /** 表格用：保留固定小数位，避免一列里 93.39 和 139.321 参差不齐 */
  function fixed(v, digits) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return Number(v).toFixed(digits);
  }

  /* ---------------- 网络 ---------------- */

  function logCall(method, path, status, ms, payload) {
    state.log.unshift({
      t: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
      method: method, path: path, status: status, ms: Math.round(ms), payload: payload,
    });
    if (state.log.length > 30) state.log.pop();
    var el = $("logBody");
    if (el) {
      el.textContent = state.log.map(function (x) {
        var line = x.t + "  " + x.method + " " + x.path + "  " + x.status + "  " + x.ms + "ms";
        if (x.payload) line += "\n    " + JSON.stringify(x.payload);
        return line;
      }).join("\n");
    }
  }

  async function api(path, body) {
    var t0 = performance.now();
    var opts = body ? {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    } : undefined;
    var res = await fetch(path, opts);
    var data = await res.json();
    logCall(body ? "POST" : "GET", path, res.status, performance.now() - t0, body);
    return data;
  }

  /* ---------------- 初始化 ---------------- */

  async function boot() {
    var results = await Promise.all([
      api("/api/health"), api("/api/catalog"), api("/api/tasks"), api("/api/presets"),
    ]);
    var health = results[0];
    state.catalog = results[1].experiments || [];
    state.tasks = results[2].tasks || [];
    state.presets = { sweep: results[3].sweep || {}, compare: results[3].compare || {} };
    state.llm = (health && health.llm) || { configured: false };

    renderCards();
    bindComposer();
    renderEngineBadge();

    $("homeLink").addEventListener("click", function () {
      $("result").classList.add("hidden");
      $("landing").classList.remove("hidden");
      renderEngineBadge();
      $("taskInput").value = "";
      syncSend();
      $("scroll").scrollTop = 0;
      if (location.hash) history.replaceState(null, "", location.pathname);
    });

    // 深链接：/ #q=问题 可以直接打开某个结果，方便演示与截图
    var m = /[#&]q=([^&]*)/.exec(location.hash);
    if (m) {
      var text = decodeURIComponent(m[1]);
      $("taskInput").value = text;
      syncSend();
      ask(text);
    }
  }

  function renderCards() {
    var cards = CARD_META.map(function (meta, i) {
      var task = state.tasks[i];
      if (!task) return "";
      var title = (task.title || "").split("｜").pop() || task.title;
      return '<button class="card" data-i="' + i + '">' +
        '<span class="ico ' + meta.tone + '">' + ICONS[meta.icon] + "</span>" +
        '<span class="txt"><span class="t">' + esc(title) + "</span>" +
        '<span class="d">' + esc(meta.desc) + "</span></span></button>";
    }).join("");

    $("cards").innerHTML = cards;
    Array.prototype.forEach.call(document.querySelectorAll("[data-i]"), function (btn) {
      btn.addEventListener("click", function () {
        var t = state.tasks[+btn.getAttribute("data-i")];
        if (!t) return;
        $("taskInput").value = t.text;
        syncSend();
        ask(t.text);
      });
    });
  }

  function renderEngineBadge() {
    var el = $("barNote");
    if (!el) return;
    if (state.llm && state.llm.configured) {
      el.textContent = "大模型已接入 · " + (state.llm.model || "") + " · 失败自动回退规则引擎";
    } else {
      el.textContent = "规则引擎 · 未配置模型服务（见 .env）";
    }
  }

  function engineLabel(e) {
    if (!e) return "";
    if (e.indexOf("llm") === 0) return "大模型";
    if (e.indexOf("rule") >= 0) return e.indexOf("回退") >= 0 || e.indexOf("失败") >= 0 ? "规则（回退）" : "规则";
    return e;
  }

  /* ---------------- 输入框 ---------------- */

  function bindComposer() {
    var ta = $("taskInput");

    ta.addEventListener("input", function () {
      ta.style.height = "auto";
      ta.style.height = Math.min(ta.scrollHeight, 150) + "px";
      syncSend();
    });

    ta.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
        ev.preventDefault();
        $("composer").requestSubmit();
      }
    });

    $("composer").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var text = ta.value.trim();
      if (!text || state.busy) return;
      ask(text);
    });
  }

  function syncSend() {
    var has = $("taskInput").value.trim().length > 0;
    $("sendBtn").classList.toggle("on", has);
    $("sendBtn").disabled = state.busy;
  }

  /* ---------------- 提问 ---------------- */

  async function ask(text) {
    state.busy = true;
    syncSend();
    showResult(text);
    try {
      history.replaceState(null, "", "#q=" + encodeURIComponent(text));
    } catch (e) { /* file:// 下可能受限，忽略 */ }
    var ta = $("taskInput");
    ta.value = "";
    ta.style.height = "auto";

    var agent = $("agent");
    agent.innerHTML = '<div class="chips"><span class="chip">正在理解问题…</span></div>';

    var plan;
    try {
      plan = await api("/api/agent/route", { text: text });
    } catch (err) {
      agent.innerHTML = '<div class="errors"><div class="et">服务不可用</div>' + esc(String(err)) + "</div>";
      state.busy = false; syncSend(); return;
    }

    if (!plan.ok) {
      renderClarify(agent, plan);
      state.busy = false; syncSend(); return;
    }

    if (plan.intent === "cross_module") {
      renderCross(agent, plan);
      state.busy = false; syncSend(); return;
    }

    applyPlan(plan);
    await execute();
    state.busy = false;
    syncSend();
  }

  function showResult(text) {
    $("landing").classList.add("hidden");
    $("result").classList.remove("hidden");
    $("result").innerHTML =
      '<div class="turn">' +
      '  <div class="ask">' + esc(text) + "</div>" +
      '  <div class="agent" id="agent"></div>' +
      "</div>";
    $("scroll").scrollTop = 0;
  }

  function renderClarify(agent, plan) {
    agent.innerHTML =
      '<div class="chips"><span class="chip">暂时无法执行</span></div>' +
      '<div class="headline">' + esc(plan.clarify || plan.error || "没能理解这个问题") + "</div>";
  }

  function renderCross(agent, plan) {
    agent.innerHTML =
      '<div class="chips"><span class="chip accent">跨模块关联探究</span>' +
      '<span class="chip">只做概念串联</span></div>' +
      '<div class="headline"><div class="cross">' + esc(plan.explanation || "") + "</div></div>" +
      '<div class="note">两个模型的输出口径不同（坡面为 t/(ha·a)，河道为 Pa），' +
      "系统不会把它们拼成一个预测结果。</div>";
  }

  function applyPlan(plan) {
    state.expId = plan.experiment;
    state.params = Object.assign({}, plan.params || {});
    state.mode = plan.intent;
    state.sweepValues = null;
    state.compareVariants = null;

    var exp = currentExp();
    state.sweepParam = (plan.plan && plan.plan.parameter) || firstNumeric(exp);
    if (plan.plan && plan.plan.values) state.sweepValues = plan.plan.values;
    if (plan.plan && plan.plan.variants) state.compareVariants = plan.plan.variants;
    state.compareKey = availableCompareKeys(exp)[0] || null;
    state.plan = plan;
  }

  /* ---------------- 执行与渲染 ---------------- */

  async function execute() {
    var exp = currentExp();
    if (!exp) return;

    var payload = { experiment: state.expId, mode: state.mode, params: collectParams() };
    if (state.mode === "sweep") {
      payload.sweep = { parameter: state.sweepParam, values: valuesFor(state.sweepParam) };
    } else if (state.mode === "compare") {
      payload.compare = { variants: variantsFor(state.compareKey) || [] };
    } else if (state.mode === "analyze") {
      payload.analyze = { outputs: [exp.outputs[0] && exp.outputs[0].key].filter(Boolean) };
    }

    var r = await api("/api/execute", payload);
    renderResult(r, exp);
  }

  function renderResult(r, exp) {
    var agent = $("agent");
    if (!agent) return;

    var plan = state.plan || {};
    var chips = '<div class="chips">' +
      '<span class="chip accent">' + esc(r.experiment ? r.experiment.title : exp.title) + "</span>" +
      '<span class="chip"><b>' + esc(modeLabel(state.mode)) + "</b></span>" +
      (plan.engine ? '<span class="chip">' + esc(engineLabel(plan.engine)) + "</span>" : "") +
      (plan.confidence ? '<span class="chip">置信度 ' + Math.round(plan.confidence * 100) + "%</span>" : "") +
      (r.trace ? '<span class="chip">' + r.trace.duration_ms + " ms</span>" : "") +
      "</div>";

    if (!r.ok) {
      agent.innerHTML = chips +
        '<div class="errors"><div class="et">参数未通过校验，工具拒绝执行</div>' +
        (r.errors || []).map(function (e) {
          return "<div>· <code>" + esc(e.field || "") + "</code> " + esc(e.message) + "</div>";
        }).join("") +
        '<div class="etip">数值只能由工具计算，模型无权编造。修正参数后可重新计算。</div></div>' +
        paramPanel(exp);
      bindParamPanel(exp);
      return;
    }

    var body = chips;

    if (r.mode === "run") body += headline(r.outputs.headline || "计算完成", r.outputs);
    if (r.mode === "sweep") body += sweepHeadline(r);
    if (r.mode === "compare") body += compareHeadline(r);
    if (r.mode === "analyze") body += analyzeHeadline(r);

    body += '<div class="charts" id="charts"></div>';
    body += paramPanel(exp);
    body += metaPanel(r);
    body += logPanel();

    agent.innerHTML = body;
    bindParamPanel(exp);

    var charts = $("charts");
    if (r.mode === "run") renderRun(exp, r, charts);
    else if (r.mode === "sweep") renderSweep(r, charts);
    else if (r.mode === "compare") renderCompare(exp, r, charts);
    else if (r.mode === "analyze") renderAnalyze(r, charts);
  }

  function headline(text, outputs) {
    var badge = "";
    if (outputs && outputs.intensity_class) {
      badge = '<span class="verdict" style="background:' + esc(outputs.intensity_color || "#8b95a1") + '">' +
        esc(outputs.intensity_class) + "</span>";
    }
    return '<div class="headline">' + esc(text) + badge + "</div>";
  }

  function sweepHeadline(r) {
    var sw = r.sweep || {};
    var ok = (r.points || []).filter(function (p) { return p.ok; });
    if (ok.length < 2) return '<div class="headline">扫描完成，有效采样点不足。</div>';
    var a = ok[0], b = ok[ok.length - 1];
    var y1 = a.outputs[r.primary_output], y2 = b.outputs[r.primary_output];
    var pct = y1 ? ((y2 - y1) / Math.abs(y1) * 100) : 0;
    return '<div class="headline">「' + esc(sw.label) + "」从 " + num(a.value) + esc(sw.unit) +
      " 变到 " + num(b.value) + esc(sw.unit) + " 时，" + esc(r.primary_label) + " 由 " +
      num(y1, 2) + " 变为 " + num(y2, 2) + "（" + (pct >= 0 ? "+" : "") + num(pct, 1) + "%）。" +
      "<br>共 " + ok.length + " 个采样点，全部计算成功。</div>";
  }

  function compareHeadline(r) {
    var cmp = r.compare || {};
    var ok = (r.rows || []).filter(function (x) { return x.ok; });
    var baseVal = r.baseline && r.baseline.outputs ? r.baseline.outputs[cmp.primary_key] : null;
    if (!ok.length) return '<div class="headline">对照计算完成。</div>';
    var best = ok.slice().sort(function (a, b) {
      return (a.delta_pct === null ? 9e9 : a.delta_pct) - (b.delta_pct === null ? 9e9 : b.delta_pct);
    })[0];
    var bl = cmp.baseline_label || "基准组";
    var baseText = bl === "基准组" ? "基准组" : "基准组（" + bl + "）";
    return '<div class="headline">' + esc(baseText) + "的" + esc(cmp.primary_label) +
      "为 " + num(baseVal, 2) + "。共比较 " + ok.length + " 组方案，变化最大的是「" + esc(best.label) +
      "」，相对基准 " + (best.delta_pct >= 0 ? "+" : "") + num(best.delta_pct, 1) + "%（" +
      num(best.primary, 2) + "）。</div>";
  }

  function analyzeHeadline(r) {
    var items = ((r.analysis || {}).elasticities) || [];
    if (!items.length) return '<div class="headline">敏感性分析完成。</div>';
    var top = items[0];
    return '<div class="headline">对「' + esc(r.primary_label) + "」影响最大的是「" + esc(top.label) +
      "」，弹性系数 " + num(top.elasticity, 2) + "：它变化 1%，结果变化约 " +
      num(Math.abs(top.elasticity), 2) + "%（" + (top.elasticity > 0 ? "同向" : "反向") + "）。</div>";
  }

  /* ---------------- 图表区块 ---------------- */

  function card(title, inner) {
    var d = document.createElement("div");
    d.className = "chart-card";
    d.innerHTML = "<h3>" + esc(title) + "</h3>" + inner;
    return d;
  }

  function factorGrid(items) {
    return '<div class="factor-grid">' + items.map(function (it) {
      return '<div class="factor"><div class="k">' + esc(it.k) + '</div><div class="v">' +
        it.v + '</div><div class="u">' + esc(it.u || "") + "</div></div>";
    }).join("") + "</div>";
  }

  function renderRun(exp, r, charts) {
    var o = r.outputs;

    if (exp.id === "soil_erosion_rusle") {
      charts.appendChild(card("结果分解", factorGrid([
        { k: "预测流失量 A", v: num(o.soil_loss_t_ha_yr, 1), u: "t/(ha·a)" },
        { k: "面积负荷", v: num(o.soil_loss_t_km2_yr, 0), u: "t/(km²·a)" },
        { k: "坡度坡长因子 LS", v: num(o.ls_components.LS, 3), u: "L×S" },
        { k: "覆盖管理因子 C", v: num(o.factors.C, 4), u: "0–1" },
        { k: "保持措施因子 P", v: num(o.factors.P, 2), u: o.practice_label },
        { k: "坡度换算", v: num(o.ls_components.theta_deg, 1) + "°", u: "坡长指数 m=" + num(o.ls_components.m, 2) },
      ])));
      charts.appendChild(card("这个数是怎么来的",
        '<div class="param-desc" style="margin:0">A = R·K·LS·C·P = ' +
        num(o.factors.R, 0) + " × " + num(o.factors.K, 3) + " × " + num(o.factors.LS, 3) +
        " × " + num(o.factors.C, 4) + " × " + num(o.factors.P, 2) + " = <b>" +
        num(o.soil_loss_t_ha_yr, 1) + " t/(ha·a)</b><br>C 因子来源：" + esc(o.cover_factor_source) + "</div>"));
      return;
    }

    charts.appendChild(card("弯道平面冲淤格局（悬停看逐格数值）", '<div id="fieldHolder"></div>'));
    GLChart.bendField($("fieldHolder"), o);

    charts.appendChild(card("凹岸沿程床面剪应力", '<div id="profileHolder"></div>'));
    GLChart.line($("profileHolder"), {
      points: (o.outer_bank_profile || []).map(function (p) { return [p.phi_pct, p.tau_pa]; }),
    }, { xLabel: "沿弯道进程（%）", yLabel: "床面剪应力 τ（Pa）", color: "#cf3b2e" });

    charts.appendChild(card("结果分解", factorGrid([
      { k: "弯道半径比 Rc/B", v: num(o.rc_over_b, 2), u: "" },
      { k: "环流幅度 A0", v: num(o.circulation_amplitude, 2), u: "弯道曲率效应" },
      { k: "最大剪应力", v: num(o.tau_max_pa, 2), u: "Pa" },
      { k: "岸坡起动剪应力", v: num(o.bank_tau_c_pa, 1), u: o.bank_material_label },
      { k: "超过起动条件", v: num(o.stress_exceed_ratio, 2) + "×", u: ">1 才真的能冲" },
    ])));

    charts.appendChild(card("判断",
      '<div class="param-desc" style="margin:0;font-size:12.5px">' +
      esc(o.material_verdict) + "<br>侵蚀带：" + esc(o.erosion_zone || "—") +
      "　沉积带：" + esc(o.deposition_zone || "—") + "</div>"));
  }

  function renderSweep(r, charts) {
    var sw = r.sweep || {};
    var series = (r.series || []).filter(function (s) { return s.key === r.primary_output; })[0] ||
      (r.series || [])[0];

    charts.appendChild(card(sw.label + " → " + r.primary_label, '<div id="sweepHolder"></div>'));
    if (series) {
      GLChart.line($("sweepHolder"), series, {
        xLabel: sw.label + (sw.unit ? "（" + sw.unit + "）" : ""),
        yLabel: r.primary_label,
      });
    } else {
      $("sweepHolder").textContent = "无可用曲线";
    }

    var ok = (r.points || []).filter(function (p) { return p.ok; });
    charts.appendChild(card("逐点结果", "<table class='data'><thead><tr><th>" + esc(sw.label) +
      "</th><th class='num'>" + esc(r.primary_label) + "</th></tr></thead><tbody>" +
      ok.map(function (p) {
        return "<tr><td>" + fixed(p.value, 0) + "</td><td class='num'>" +
          fixed(p.outputs[r.primary_output], 3) + "</td></tr>";
      }).join("") + "</tbody></table>"));
  }

  function renderCompare(exp, r, charts) {
    var cmp = r.compare || {};
    var rows = r.rows || [];
    var ok = rows.filter(function (x) { return x.ok; });
    var baseVal = r.baseline && r.baseline.outputs ? r.baseline.outputs[cmp.primary_key] : null;

    var items = ok.map(function (x) {
      return { label: x.label, value: x.primary, display: num(x.primary, 2) };
    });
    if (baseVal !== null && baseVal !== undefined) {
      items.unshift({ label: cmp.baseline_label, value: baseVal, display: num(baseVal, 2), color: "#b9c1c9" });
    }
    charts.appendChild(card(cmp.primary_label + " 对照", '<div id="cmpHolder"></div>'));
    GLChart.bars($("cmpHolder"), items, { labelWidth: 150 });

    charts.appendChild(card("对照明细", "<table class='data'><thead><tr><th>方案</th>" +
      "<th class='num'>" + esc(cmp.primary_label) + "</th><th class='num'>相对基准</th></tr></thead><tbody>" +
      rows.map(function (x) {
        if (!x.ok) {
          return "<tr><td>" + esc(x.label) + "</td><td colspan='2' style='color:#c0392b'>" +
            esc((x.errors || []).map(function (e) { return e.message; }).join("；")) + "</td></tr>";
        }
        var d = x.delta_pct;
        var cls = d === null ? "delta-flat" : d < 0 ? "delta-down" : d > 0 ? "delta-up" : "delta-flat";
        var dtxt = d === null ? "—" : (d > 0 ? "+" : "") + num(d, 1) + "%";
        return "<tr><td>" + esc(x.label) + "</td><td class='num'>" + fixed(x.primary, 3) +
          "</td><td class='num " + cls + "'>" + dtxt + "</td></tr>";
      }).join("") + "</tbody></table>"));
  }

  function renderAnalyze(r, charts) {
    var items = ((r.analysis || {}).elasticities) || [];

    charts.appendChild(card("各因子弹性系数（d lnY / d lnX）", '<div id="elHolder"></div>'));
    GLChart.bars($("elHolder"), items.map(function (x) {
      return {
        label: x.label, value: x.elasticity, display: fixed(x.elasticity, 2),
        color: x.elasticity >= 0 ? "#0e7c6f" : "#4b93d1",
      };
    }), { labelWidth: 170 });

    charts.appendChild(card("排序明细", "<table class='data'><thead><tr><th>#</th><th>因子</th>" +
      "<th class='num'>弹性系数</th></tr></thead><tbody>" +
      items.map(function (x) {
        return "<tr><td>" + x.rank + "</td><td>" + esc(x.label) + "</td><td class='num'>" +
          num(x.elasticity, 3) + "</td></tr>";
      }).join("") + "</tbody></table>"));
  }

  /* ---------------- 面板 ---------------- */

  function paramPanel(exp) {
    return '<details class="panel"><summary>调整参数并重新计算</summary>' +
      '<div id="modes" class="modes"></div><div id="modeConfig"></div>' +
      '<div id="paramForm" class="params"></div>' +
      '<button class="btn primary wide" id="rerunBtn">重新计算</button></details>';
  }

  function metaPanel(r) {
    var html = "";
    if (r.assumptions && r.assumptions.length) {
      html += '<div class="sub">模型假设</div><ul>' + r.assumptions.map(function (s) {
        return "<li>" + esc(s) + "</li>";
      }).join("") + "</ul>";
    }
    if (r.limitations && r.limitations.length) {
      html += '<div class="sub">适用范围与限制</div><ul>' + r.limitations.map(function (s) {
        return "<li>" + esc(s) + "</li>";
      }).join("") + "</ul>";
    }
    return '<details class="panel"><summary>模型假设与适用范围</summary>' + html + "</details>";
  }

  function logPanel() {
    return '<details class="panel"><summary>调用日志（可复现）</summary>' +
      '<pre id="logBody"></pre></details>';
  }

  function bindParamPanel(exp) {
    if (!exp) return;
    renderModes();
    renderModeConfig();
    renderParams();
    $("rerunBtn").addEventListener("click", async function () {
      var btn = $("rerunBtn");
      btn.disabled = true;
      btn.textContent = "计算中…";
      await execute();
      btn.disabled = false;
      btn.textContent = "重新计算";
    });
  }

  function currentExp() {
    for (var i = 0; i < state.catalog.length; i++) {
      if (state.catalog[i].id === state.expId) return state.catalog[i];
    }
    return null;
  }

  function firstNumeric(exp) {
    if (!exp) return null;
    var p = exp.parameters.filter(function (q) { return q.kind === "number" && !q.optional; })[0];
    return p ? p.name : null;
  }

  function renderModes() {
    var box = $("modes");
    if (!box) return;
    box.innerHTML = MODES.map(function (m) {
      return '<button class="mode' + (m.id === state.mode ? " active" : "") +
        '" data-mode="' + m.id + '">' + m.label + "</button>";
    }).join("");
    Array.prototype.forEach.call(box.querySelectorAll("[data-mode]"), function (b) {
      b.addEventListener("click", function () {
        state.mode = b.getAttribute("data-mode");
        renderModes();
        renderModeConfig();
      });
    });
  }

  function sweepableParams(exp) {
    return exp.parameters.filter(function (p) {
      return !p.optional && (p.kind === "number" || p.kind === "enum");
    });
  }

  function availableCompareKeys(exp) {
    if (!exp) return [];
    var names = exp.parameters.map(function (p) { return p.name; });
    return Object.keys(state.presets.compare || {}).filter(function (k) {
      return names.indexOf(k) >= 0;
    });
  }

  function renderModeConfig() {
    var box = $("modeConfig");
    var exp = currentExp();
    if (!box || !exp) return;

    if (state.mode === "run" || state.mode === "analyze") { box.innerHTML = ""; return; }

    if (state.mode === "sweep") {
      var vals = valuesFor(state.sweepParam);
      box.innerHTML = '<label class="param-label"><span>扫描自变量</span>' +
        '<span class="unit">' + vals.length + " 个采样点</span></label>" +
        '<select id="sweepSelect">' + sweepableParams(exp).map(function (p) {
          return '<option value="' + esc(p.name) + '"' + (p.name === state.sweepParam ? " selected" : "") +
            ">" + esc(p.label) + "</option>";
        }).join("") + "</select>" +
        '<div class="param-desc" style="margin-bottom:14px">按该参数取一系列值分别计算，得到对照曲线。</div>';
      $("sweepSelect").addEventListener("change", function () {
        state.sweepParam = $("sweepSelect").value;
        state.sweepValues = null;
        renderModeConfig();
      });
      return;
    }

    if (state.mode === "compare") {
      var keys = availableCompareKeys(exp);
      var variants = variantsFor(state.compareKey);
      box.innerHTML = '<label class="param-label"><span>对照维度</span>' +
        '<span class="unit">' + (variants ? variants.length : 0) + " 组</span></label>" +
        '<select id="compareSelect">' + keys.map(function (k) {
          var p = exp.parameters.filter(function (q) { return q.name === k; })[0];
          return '<option value="' + esc(k) + '"' + (k === state.compareKey ? " selected" : "") +
            ">" + esc(p ? p.label : k) + "</option>";
        }).join("") + "</select>" +
        '<div class="param-desc" style="margin-bottom:14px">其余参数保持一致，只改变这一项。</div>';
      $("compareSelect").addEventListener("change", function () {
        state.compareKey = $("compareSelect").value;
        state.compareVariants = null;
        renderModeConfig();
      });
    }
  }

  function valuesFor(name) {
    if (state.sweepValues && state.sweepValues.length) return state.sweepValues;
    if (name && state.presets.sweep && state.presets.sweep[name]) return state.presets.sweep[name];
    var exp = currentExp();
    if (!exp) return [];
    var p = exp.parameters.filter(function (q) { return q.name === name; })[0];
    if (!p) return [];
    if (p.kind === "enum") return (p.choices || []).map(function (c) { return c.value; });
    var out = [];
    for (var i = 0; i < 10; i++) out.push(+(p.min + (p.max - p.min) * i / 9).toFixed(4));
    return out;
  }

  function variantsFor(key) {
    if (state.compareVariants && state.compareVariants.length) return state.compareVariants;
    if (key && state.presets.compare && state.presets.compare[key]) return state.presets.compare[key];
    return null;
  }

  function collectParams() {
    var exp = currentExp();
    var out = {};
    if (!exp) return out;
    exp.parameters.forEach(function (p) {
      var v = state.params[p.name];
      if (p.optional && (v === null || v === undefined || v === "")) { out[p.name] = null; return; }
      out[p.name] = v;
    });
    return out;
  }

  function renderParams() {
    var exp = currentExp();
    var box = $("paramForm");
    if (!exp || !box) return;

    box.innerHTML = exp.parameters.map(function (p) {
      var val = state.params[p.name];
      var head = '<div class="param-label"><span>' + esc(p.label) +
        '</span><span class="unit">' + esc(p.unit || "") + "</span></div>";

      if (p.kind === "enum") {
        return '<div class="param-block">' + head + '<select data-param="' + esc(p.name) + '">' +
          (p.choices || []).map(function (c) {
            return '<option value="' + esc(c.value) + '"' + (c.value === val ? " selected" : "") +
              ">" + esc(c.label) + "</option>";
          }).join("") + "</select></div>";
      }

      if (p.optional) {
        return '<div class="param-block optional">' + head +
          '<input type="number" class="solo" data-param="' + esc(p.name) + '" step="' + (p.step || 0.001) +
          '" value="' + (val === null || val === undefined ? "" : val) + '" placeholder="留空则由覆盖度换算">' +
          "</div>";
      }

      return '<div class="param-block">' + head + '<div class="range-row">' +
        '<input type="range" data-param="' + esc(p.name) + '" min="' + p.min + '" max="' + p.max +
        '" step="' + (p.step || 1) + '" value="' + val + '">' +
        '<input type="number" data-param="' + esc(p.name) + '" min="' + p.min + '" max="' + p.max +
        '" step="' + (p.step || 1) + '" value="' + val + '">' +
        "</div></div>";
    }).join("");

    Array.prototype.forEach.call(box.querySelectorAll("[data-param]"), function (inp) {
      inp.addEventListener("input", function () {
        var name = inp.getAttribute("data-param");
        var v = inp.type === "number" ? (inp.value === "" ? null : parseFloat(inp.value)) : inp.value;
        state.params[name] = v;
        Array.prototype.forEach.call(box.querySelectorAll('[data-param="' + name + '"]'), function (o) {
          if (o !== inp) o.value = v === null ? "" : v;
        });
      });
    });
  }

  function modeLabel(id) {
    for (var i = 0; i < MODES.length; i++) if (MODES[i].id === id) return MODES[i].label;
    return id;
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
