# API 参考

服务默认监听 `http://127.0.0.1:8010`，全部接口返回 JSON（`application/json; charset=utf-8`）。

无需鉴权——这是本地教学服务，面向单机或局域网演示。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/catalog` | 实验清单（参数声明、假设、限制、输出定义） |
| GET | `/api/tasks` | 示例任务库 |
| GET | `/api/presets` | 扫描与对照的推荐配置 |
| POST | `/api/execute` | **核心接口**：执行实验（四种模式） |
| POST | `/api/agent/route` | 自然语言 → 结构化实验方案 |

---

## POST /api/execute

### 请求体

```json
{
  "experiment": "soil_erosion_rusle",
  "mode": "run",
  "params": { "vegetation_cover_pct": 40 },
  "sweep":   { "parameter": "vegetation_cover_pct", "values": [0, 20, 40, 60, 80, 100] },
  "compare": { "baseline_label": "基准组", "variants": [ { "label": "梯田", "params": { "practice": "terracing" } } ] },
  "analyze": { "outputs": ["soil_loss_t_ha_yr"] }
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `experiment` | 是 | 实验 ID，见 `/api/catalog` |
| `mode` | 否 | `run`（默认）/ `sweep` / `compare` / `analyze` |
| `params` | 否 | 参数对象。缺省字段用默认值；`null` 对可选参数表示"自动" |
| `sweep` | `mode=sweep` 时必填 | `parameter` + `values`，或 `start`/`stop`/`steps`；都省略时按参数量程自动取 10 点 |
| `compare` | `mode=compare` 时必填 | `variants[]`，每项 `{label, params}`，`params` 只需写与基准组不同的字段 |
| `analyze` | 否 | `outputs[]`，默认取实验的主输出 |

### 成功响应（`mode=run`）

```json
{
  "ok": true,
  "experiment": {
    "id": "soil_erosion_rusle",
    "title": "坡面水土流失（RUSLE 因子估算）",
    "version": "1.1.0",
    "domain": "水土保持 / 地貌过程"
  },
  "mode": "run",
  "params": { "rainfall_erosivity": 4500, "soil_erodibility": 0.03, "slope_percent": 8,
              "slope_length_m": 30, "vegetation_cover_pct": 40.0, "cover_decay": 0.04,
              "cover_factor": null, "practice": "none" },
  "outputs": {
    "soil_loss_t_ha_yr": 28.128,
    "soil_loss_t_km2_yr": 2812.84,
    "intensity_class": "极强烈",
    "intensity_color": "#dd4b39",
    "factors": { "R": 4500.0, "K": 0.03, "LS": 1.032006, "C": 0.201897, "P": 1.0 },
    "ls_components": { "L": 1.1579, "S": 0.8912, "LS": 1.032, "m": 0.4819, "theta_deg": 4.574 },
    "cover_factor_source": "由覆盖度 40% 与衰减系数 0.04 换算",
    "practice_label": "无措施（顺坡耕作）",
    "headline": "坡度 8%、坡长 30 m、植被覆盖 40%、无措施（顺坡耕作）条件下，估算年流失量约 28.1 t/(ha·a)，属极强烈侵蚀。"
  },
  "assumptions": ["按 RUSLE 结构 A = R·K·LS·C·P 估算多年平均年流失量，假设坡面处于长期平均状态。"],
  "limitations": ["结果为示例估算，不等同于实测输沙量，也不能用于水土保持工程设计与环评。"],
  "trace": { "engine": "geolab-core", "engine_version": "1.0.0", "duration_ms": 0.16 }
}
```

`params` 是**校验后的规范化参数**（不再是原始输入），可用于复现：
把 `params` 原样回传，结果必然一致。

`assumptions` 与 `limitations` 在每一次成功响应里都出现，不在文档里"另外说明"。

### 成功响应（`mode=sweep` 追加字段）

```json
{
  "sweep": { "parameter": "vegetation_cover_pct", "label": "植被覆盖度", "unit": "%",
             "values": [0, 50, 100] },
  "points": [
    { "value": 0.0,   "ok": true, "outputs": { "soil_loss_t_ha_yr": 139.3 } },
    { "value": 50.0,  "ok": true, "outputs": { "soil_loss_t_ha_yr": 18.9 } },
    { "value": 100.0, "ok": true, "outputs": { "soil_loss_t_ha_yr": 2.54 } }
  ],
  "series": [
    { "key": "soil_loss_t_ha_yr", "label": "预测土壤流失量 A（t/(ha·a)）",
      "points": [[0.0, 139.3], [50.0, 18.9], [100.0, 2.54]] }
  ],
  "primary_output": "soil_loss_t_ha_yr",
  "primary_label": "预测土壤流失量 A（t/(ha·a)）"
}
```

单个扫描点失败不会中断整条曲线——该点 `ok: false` 并带 `errors`。

### 成功响应（`mode=compare` 追加字段）

```json
{
  "compare": { "baseline_label": "基准组", "primary_key": "soil_loss_t_ha_yr",
               "primary_label": "预测土壤流失量 A（t/(ha·a)）" },
  "baseline": { "params": { "...": "..." }, "outputs": { "soil_loss_t_ha_yr": 12.639 } },
  "rows": [
    { "label": "梯田", "ok": true, "overrides": { "practice": "terracing" },
      "params": { "...": "..." },
      "outputs": { "soil_loss_t_ha_yr": 2.528 },
      "primary": 2.528, "delta_pct": -80.0 }
  ]
}
```

`delta_pct` 是相对基准组的百分比变化，负值表示流失量减少。

### 成功响应（`mode=analyze` 追加字段）

```json
{
  "analysis": {
    "outputs": ["soil_loss_t_ha_yr"],
    "elasticities": [
      { "output": "soil_loss_t_ha_yr", "parameter": "vegetation_cover_pct",
        "label": "植被覆盖度", "value": 60.0, "elasticity": -0.62,
        "reading": "1% 变化引起约 -0.62% 变化", "rank": 1 }
    ],
    "reading": "弹性系数 = d(ln输出)/d(ln参数)。绝对值越大，说明该参数变化 1% 对结果影响越大；正号表示同向，负号表示反向。"
  }
}
```

### 失败响应

```json
{
  "ok": false,
  "experiment": { "id": "soil_erosion_rusle", "title": "坡面水土流失（RUSLE 因子估算）" },
  "errors": [{
    "field": "vegetation_cover_pct",
    "code": "above_max",
    "message": "「植被覆盖度」不能大于 100%，收到 130",
    "allowed": { "min": 0, "max": 100, "unit": "%" }
  }],
  "assumptions": ["..."],
  "limitations": ["..."],
  "trace": { "engine": "geolab-core", "engine_version": "1.0.0", "duration_ms": 0.08 }
}
```

错误码一览：

| code | 含义 | 恢复方式 |
|---|---|---|
| `above_max` / `below_min` | 超出允许范围 | 按 `allowed` 修正 |
| `not_a_number` / `not_finite` | 类型错误 | 传数值 |
| `unknown_parameter` | 参数名不存在 | 从 `allowed` 选 |
| `bad_choice` | 枚举值不合法 | 从 `allowed` 选 |
| `required` | 缺必填参数 | 补上 |
| `unknown_experiment` | 实验 ID 不存在 | 从 `allowed` 选 |
| `unknown_mode` | 模式不合法 | 从 `allowed` 选 |
| `too_many_points` | 扫描点超过 200 | 减少采样点 |
| `too_many_variants` | 对照组超过 12 | 分批执行 |

---

## POST /api/agent/route

把一句自然语言转成可执行的实验方案。**不请求任何大模型**，纯规则实现。

请求：

```json
{ "text": "在其他条件不变时，植被覆盖变化会怎样影响土壤流失估算？" }
```

响应：

```json
{
  "ok": true,
  "intent": "sweep",
  "experiment": "soil_erosion_rusle",
  "experiment_title": "坡面水土流失（RUSLE 因子估算）",
  "confidence": 0.85,
  "params": { "vegetation_cover_pct": 60, "...": "..." },
  "plan": { "mode": "sweep", "parameter": "vegetation_cover_pct",
            "values": [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100] },
  "reasoning": ["命中「坡面水土流失（RUSLE 因子估算）」关键词：土壤侵蚀、植被覆盖 …",
                "判为「单参数扫描」：以「植被覆盖度」为自变量"],
  "steps": ["理解问题并识别实验类型", "生成变量控制方案", "校验参数范围与单位",
            "调用实验工具计算", "核对结果并生成解释"],
  "warnings": [],
  "precheck_errors": []
}
```

特例：

- `intent: "cross_module"`——问题跨越两个尺度，`explanation` 给出概念串联，**不产生合并数值**。
- `ok: false`——无法路由，`clarify` 里是追问内容，`candidates` 里是示例任务。

`precheck_errors` 用于在**调用工具之前**就指出参数问题（如覆盖度 130%），与工具侧的硬校验形成两层防护。

---

## GET /api/catalog

返回所有实验的完整声明，前端据此**动态生成**参数表单——新增实验不需要改前端。

```json
{
  "ok": true,
  "experiments": [{
    "id": "soil_erosion_rusle",
    "title": "坡面水土流失（RUSLE 因子估算）",
    "version": "1.1.0",
    "domain": "水土保持 / 地貌过程",
    "parameters": [{
      "name": "slope_percent", "label": "坡度", "kind": "number", "unit": "%",
      "min": 0, "max": 60, "default": 8, "step": 0.5,
      "description": "地表坡度（百分比）。8% 约等于 4.6°……",
      "optional": false
    }],
    "assumptions": ["..."],
    "limitations": ["..."],
    "outputs": [{ "key": "soil_loss_t_ha_yr", "label": "预测土壤流失量 A", "unit": "t/(ha·a)" }],
    "keywords": ["水土流失", "土壤侵蚀", "RUSLE", "..."]
  }]
}
```

---

## 用 curl 试一次

```bash
curl -s http://127.0.0.1:8010/api/execute \
  -H "Content-Type: application/json" \
  -d '{"experiment":"soil_erosion_rusle","mode":"run","params":{"vegetation_cover_pct":40}}'
```

Windows PowerShell：

```powershell
$b = @{experiment='soil_erosion_rusle'; mode='run'; params=@{vegetation_cover_pct=40}} | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/execute -Method Post -Body $b -ContentType 'application/json'
```
