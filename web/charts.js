/* GeoLab Agent — 轻量 SVG 图表
 * 不依赖任何 CDN 或第三方库：离线、内网、断网都能正常显示。
 */
(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";

  function el(tag, attrs) {
    var e = document.createElementNS(NS, tag);
    if (attrs) for (var k in attrs) if (Object.prototype.hasOwnProperty.call(attrs, k)) e.setAttribute(k, attrs[k]);
    return e;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function niceTicks(min, max, target) {
    target = target || 5;
    if (!isFinite(min) || !isFinite(max)) return [0, 1];
    if (min === max) { min -= 1; max += 1; }
    var span = max - min;
    var raw = span / target;
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var norm = raw / mag;
    var step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10;
    step *= mag;
    var start = Math.ceil(min / step) * step;
    var out = [];
    for (var v = start; v <= max + step * 1e-6; v += step) out.push(+v.toFixed(10));
    return out;
  }

  function fmt(v) {
    if (v === null || v === undefined || !isFinite(v)) return "—";
    var a = Math.abs(v);
    if (a === 0) return "0";
    if (a >= 10000) return v.toExponential(1).replace("e+", "e");
    if (a >= 1000) return (v / 1000).toFixed(a >= 10000 ? 0 : 1) + "k";
    if (a >= 10) return v.toFixed(0);
    if (a >= 1) return v.toFixed(1);
    if (a >= 0.01) return v.toFixed(2);
    return v.toPrecision(2);
  }

  /* ---------------- 折线图 ---------------- */

  function line(container, series, opts) {
    opts = opts || {};
    var W = opts.width || 660, H = opts.height || 300;
    var m = { t: 14, r: 20, b: 44, l: 70 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b;

    var pts = series.points || [];
    if (!pts.length) { container.textContent = "无可用数据"; return; }

    var xs = pts.map(function (p) { return p[0]; });
    var ys = pts.map(function (p) { return p[1]; });
    var xMin = Math.min.apply(null, xs), xMax = Math.max.apply(null, xs);
    var yMin = Math.min.apply(null, ys), yMax = Math.max.apply(null, ys);
    if (yMin === yMax) { yMin -= 1; yMax += 1; }
    var padv = (yMax - yMin) * 0.12;
    yMin = Math.min(yMin - padv, yMin > 0 ? 0 : yMin - padv);
    yMax = yMax + padv;

    var X = function (v) { return m.l + (v - xMin) / (xMax - xMin || 1) * iw; };
    var Y = function (v) { return m.t + ih - (v - yMin) / (yMax - yMin || 1) * ih; };

    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "chart-svg", preserveAspectRatio: "xMidYMid meet" });

    // 网格与坐标轴
    niceTicks(yMin, yMax, 5).forEach(function (t) {
      svg.appendChild(el("line", { x1: m.l, y1: Y(t), x2: m.l + iw, y2: Y(t), class: "grid" }));
      var lb = el("text", { x: m.l - 10, y: Y(t) + 4, class: "tick", "text-anchor": "end" });
      lb.textContent = fmt(t);
      svg.appendChild(lb);
    });

    var xt = niceTicks(xMin, xMax, 6);
    xt.forEach(function (t) {
      if (t < xMin - 1e-9 || t > xMax + 1e-9) return;
      var lb = el("text", { x: X(t), y: m.t + ih + 22, class: "tick", "text-anchor": "middle" });
      lb.textContent = fmt(t);
      svg.appendChild(lb);
    });

    svg.appendChild(el("line", { x1: m.l, y1: m.t + ih, x2: m.l + iw, y2: m.t + ih, class: "axis" }));
    svg.appendChild(el("line", { x1: m.l, y1: m.t, x2: m.l, y2: m.t + ih, class: "axis" }));

    // 面积填充
    var dArea = "M" + X(pts[0][0]) + " " + Y(pts[0][1]);
    for (var i = 1; i < pts.length; i++) dArea += "L" + X(pts[i][0]) + " " + Y(pts[i][1]);
    dArea += "L" + X(pts[pts.length - 1][0]) + " " + (m.t + ih) + "L" + X(pts[0][0]) + " " + (m.t + ih) + "Z";
    var gid = "g" + Math.random().toString(36).slice(2, 8);
    var defs = el("defs", {});
    var grad = el("linearGradient", { id: gid, x1: "0", y1: "0", x2: "0", y2: "1" });
    grad.appendChild(el("stop", { offset: "0%", "stop-color": opts.color || "#0f8b7f", "stop-opacity": "0.22" }));
    grad.appendChild(el("stop", { offset: "100%", "stop-color": opts.color || "#0f8b7f", "stop-opacity": "0.02" }));
    defs.appendChild(grad);
    svg.appendChild(defs);
    svg.appendChild(el("path", { d: dArea, fill: "url(#" + gid + ")" }));

    var d = "M" + X(pts[0][0]) + " " + Y(pts[0][1]);
    for (var j = 1; j < pts.length; j++) d += "L" + X(pts[j][0]) + " " + Y(pts[j][1]);
    svg.appendChild(el("path", { d: d, class: "line-path", stroke: opts.color || "#0f8b7f" }));

    pts.forEach(function (p) {
      var c = el("circle", { cx: X(p[0]), cy: Y(p[1]), r: 3.2, fill: "#fff", stroke: opts.color || "#0f8b7f", "stroke-width": 2 });
      var t = el("title", {});
      t.textContent = (opts.xLabel || "x") + " " + fmt(p[0]) + " → " + fmt(p[1]);
      c.appendChild(t);
      svg.appendChild(c);
    });

    // 轴标题
    var xl = el("text", { x: m.l + iw / 2, y: H - 6, class: "axis-label", "text-anchor": "middle" });
    xl.textContent = opts.xLabel || "";
    svg.appendChild(xl);
    var yl = el("text", { x: 14, y: m.t + ih / 2, class: "axis-label", "text-anchor": "middle",
      transform: "rotate(-90 14 " + (m.t + ih / 2) + ")" });
    yl.textContent = opts.yLabel || "";
    svg.appendChild(yl);

    clear(container);
    container.appendChild(svg);
  }

  /* ---------------- 横向条形图（对照 / 敏感性） ---------------- */

  function bars(container, items, opts) {
    opts = opts || {};
    var W = opts.width || 660;
    var rowH = 34;
    var m = { t: 10, r: 90, b: 10, l: opts.labelWidth || 170 };
    var H = m.t + m.b + Math.max(items.length, 1) * rowH;
    var iw = W - m.l - m.r;

    var vals = items.map(function (d) { return d.value; });
    var allPos = vals.every(function (v) { return v >= 0; });
    var vMin = allPos ? 0 : Math.min.apply(null, vals.concat([0]));
    var vMax = Math.max.apply(null, vals.concat([0]));

    var X = function (v) { return m.l + (v - vMin) / (vMax - vMin || 1) * iw; };
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "chart-svg" });

    if (!allPos) svg.appendChild(el("line", { x1: X(0), y1: m.t, x2: X(0), y2: H - m.b, class: "axis" }));

    items.forEach(function (d, i) {
      var y = m.t + i * rowH + rowH * 0.16;
      var h = rowH * 0.68;
      var x0 = X(Math.min(0, d.value)), x1 = X(Math.max(0, d.value));
      svg.appendChild(el("rect", {
        x: x0, y: y, width: Math.max(1.5, x1 - x0), height: h, rx: 3,
        fill: d.color || (d.value >= 0 ? (opts.color || "#0f8b7f") : "#4b93d1"),
        opacity: 0.88,
      }));
      var lb = el("text", { x: m.l - 10, y: y + h / 2 + 4, class: "tick", "text-anchor": "end" });
      lb.textContent = d.label;
      svg.appendChild(lb);
      var vl = el("text", { x: x1 + 8, y: y + h / 2 + 4, class: "tick strong" });
      vl.textContent = d.display !== undefined ? d.display : fmt(d.value);
      svg.appendChild(vl);
    });

    clear(container);
    container.appendChild(svg);
  }

  /* ---------------- 弯道平面冲淤场 ---------------- */

  function bendField(container, outputs) {
    var field = outputs.field;
    var geo = outputs.geometry;
    var legend = outputs.tendency_legend || {};
    if (!field || !geo) { container.textContent = "无场数据"; return; }

    var W = 660, H = 400, pad = 46;
    var ri = geo.r_inner_m, ro = geo.r_outer_m;
    var half = (geo.bend_angle_deg / 2) * Math.PI / 180;

    // 计算包围盒（模型坐标：x = r·sinθ，y = -r·cosθ，θ ∈ [-half, half]）
    var xs = [], ys = [];
    [ri, ro].forEach(function (r) {
      [-half, 0, half].forEach(function (th) {
        xs.push(r * Math.sin(th));
        ys.push(-r * Math.cos(th));
      });
    });
    var xMin = Math.min.apply(null, xs), xMax = Math.max.apply(null, xs);
    var yMin = Math.min.apply(null, ys), yMax = Math.max.apply(null, ys);
    var s = Math.min((W - 2 * pad) / (xMax - xMin || 1), (H - 2 * pad) / (yMax - yMin || 1));

    function PX(x) { return pad + (x - xMin) * s + (W - 2 * pad - (xMax - xMin) * s) / 2; }
    function PY(y) { return pad + (y - yMin) * s + (H - 2 * pad - (yMax - yMin) * s) / 2; }

    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "chart-svg" });

    // 底色
    svg.appendChild(el("rect", { x: 0, y: 0, width: W, height: H, fill: "#f7fafc", rx: 8 }));

    var nPhi = field.length;
    var nS = field[0].cells.length;
    var dth = (geo.bend_angle_deg * Math.PI / 180) / (nPhi - 1) * 0.52;
    var dr = (ro - ri) / (nS - 1) * 0.52;

    for (var i = 0; i < nPhi; i++) {
      var th = -half + (field[i].phi_pct / 100) * 2 * half;
      for (var j = 0; j < nS; j++) {
        var rr = ri + (ro - ri) * j / (nS - 1);
        var cell = field[i].cells[j];
        var color = legend[cell.tendency] || "#b0b7c0";
        var quads = [];
        [[rr - dr, th - dth], [rr + dr, th - dth], [rr + dr, th + dth], [rr - dr, th + dth]].forEach(function (p) {
          quads.push(PX(p[0] * Math.sin(p[1])) + "," + PY(-p[0] * Math.cos(p[1])));
        });
        var poly = el("polygon", { points: quads.join(" "), fill: color, opacity: 0.92, stroke: color, "stroke-width": 0.4 });
        var title = el("title", {});
        title.textContent = "沿程 " + field[i].phi_pct.toFixed(0) + "%　" +
          (j > nS / 2 ? "偏凹岸" : "偏凸岸") + "　v/v̄=" + cell.v_rel.toFixed(2) +
          "　τ=" + cell.tau_pa.toFixed(2) + " Pa　" + cell.tendency;
        poly.appendChild(title);
        svg.appendChild(poly);
      }
    }

    // 河岸轮廓
    function arc(r, cls, dash) {
      var d = "";
      for (var k = 0; k <= 60; k++) {
        var a = -half + (2 * half) * k / 60;
        var x = r * Math.sin(a), y = -r * Math.cos(a);
        d += (k ? "L" : "M") + PX(x) + " " + PY(y);
      }
      svg.appendChild(el("path", { d: d, fill: "none", class: cls, "stroke-dasharray": dash || "" }));
    }
    arc(ro, "bank-outer");
    arc(ri, "bank-inner");
    arc((ri + ro) / 2, "centerline", "6 5");

    // 流向箭头
    function arrow(t) {
      var a = -half + 2 * half * t;
      var r = (ri + ro) / 2;
      var x = PX(r * Math.sin(a)), y = PY(-r * Math.cos(a));
      var nx = PX((r) * Math.sin(a + 0.04)), ny = PY(-(r) * Math.cos(a + 0.04));
      var ang = Math.atan2(ny - y, nx - x) * 180 / Math.PI;
      var g = el("polygon", {
        points: "-6,-4 7,0 -6,4",
        transform: "translate(" + x + "," + y + ") rotate(" + ang + ")",
        class: "flow-arrow",
      });
      svg.appendChild(g);
    }
    arrow(0.16); arrow(0.5); arrow(0.84);

    // 岸别标注：凹岸放在外弧上方、凸岸放在内侧空白区，都避开色带
    function bankLabel(text, radius, dy, cls) {
      var t = el("text", {
        x: PX(radius * Math.sin(0)),
        y: PY(-radius * Math.cos(0)) + dy,
        class: "bank-label " + cls,
        "text-anchor": "middle",
      });
      t.textContent = text;
      svg.appendChild(t);
    }
    bankLabel("凹岸（外侧）", ro, -12, "outer");
    bankLabel("凸岸（内侧）", ri * 0.75, 4, "inner");

    // 进口 / 出口
    var inX = PX(ro * Math.sin(-half)), inY = PY(-ro * Math.cos(-half));
    var tIn = el("text", { x: inX - 4, y: inY + 18, class: "endpoint", "text-anchor": "start" });
    tIn.textContent = "进口";
    svg.appendChild(tIn);

    var outX = PX(ro * Math.sin(half)), outY = PY(-ro * Math.cos(half));
    var tOut = el("text", { x: outX + 4, y: outY + 18, class: "endpoint", "text-anchor": "end" });
    tOut.textContent = "出口";
    svg.appendChild(tOut);

    // 图例
    var order = ["强侵蚀", "侵蚀", "冲淤平衡", "沉积", "强沉积"];
    var lx = pad, ly = H - 14;
    order.forEach(function (name) {
      if (!legend[name]) return;
      svg.appendChild(el("rect", { x: lx, y: ly - 9, width: 11, height: 11, rx: 2, fill: legend[name] }));
      var t = el("text", { x: lx + 15, y: ly, class: "legend-label" });
      t.textContent = name;
      svg.appendChild(t);
      lx += 15 + name.length * 13 + 14;
    });

    clear(container);
    container.appendChild(svg);
  }

  /* ---------------- 导出 ---------------- */

  window.GLChart = {
    line: line,
    bars: bars,
    bendField: bendField,
    clear: clear,
    niceTicks: niceTicks,
    fmt: fmt,
  };
})();
