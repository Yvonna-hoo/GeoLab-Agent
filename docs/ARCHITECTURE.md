# 架构说明

## 分层

```
┌─────────────────────────────────────────────────────────┐
│  交互呈现层   web/                                       │
│  原生 HTML/CSS/JS + 自绘 SVG 图表，无框架、无 CDN         │
└───────────────────────────┬─────────────────────────────┘
                            │ JSON over HTTP
┌───────────────────────────▼─────────────────────────────┐
│  服务层       geolab/server.py + geolab/service.py       │
│  路由、四种探究模式、请求校验、结果封装                   │
└───────────┬───────────────────────────────┬─────────────┘
            │                               │
┌───────────▼─────────────┐   ┌─────────────▼─────────────┐
│  智能体层  agent/router  │   │  实验层  experiments/*     │
│  自然语言 → 结构化方案    │   │  纯计算，不关心 HTTP/UI    │
└─────────────────────────┘   └─────────────┬─────────────┘
                                            │
                              ┌─────────────▼─────────────┐
                              │  协议层  protocol.py       │
                              │  参数声明 / 校验 / 封装     │
                              └───────────────────────────┘
```

依赖方向严格单向向下。实验层不知道 HTTP 的存在，协议层不知道地理学的存在。

## 一次请求的完整路径

```
用户输入「植被覆盖变化会怎样影响土壤流失？」
   │
   ├─ POST /api/agent/route
   │     router 命中「土壤侵蚀」「植被覆盖」
   │     → intent=sweep, experiment=soil_erosion_rusle,
   │       plan={parameter: vegetation_cover_pct, values: [...]}
   │
   ├─ 前端据此设置表单与模式（用户可改）
   │
   └─ POST /api/execute
         service.execute()
           ├─ registry.get()            取到实验对象
           ├─ exp.validate(params)      结构化验参 → 不通过就在这里返回
           └─ _sweep()                  对每个值调用 exp.run()
                 └─ envelope()          统一封装 + assumptions + limitations
```

关键点：**智能体只负责产生方案，不产生数值**。数值一律来自 `exp.run()`。

## 四个设计决定，以及为什么

### 1. 零第三方依赖

`numpy` 当然可以用，但会带来一个现实代价：评审要 `pip install` 才能跑起来。而本项目的参数扫描规模是 10–200 个点，纯 Python 足够，向量化没有实际收益。

换来的是：`git clone` → `python run.py` → 能看。这对开源项目的复现性评分是实打实的加分。

### 2. 模式逻辑放在服务层，不放在实验层

如果每个实验自己实现"扫描、对照、敏感性"，那么新增一个实验就要重写三遍，而且实现风格会漂移。

现在实验只需要实现 `run(params) -> dict`，四种模式对**任何**新实验自动可用——包括 `analyze` 的中心差分弹性系数，它对模型内部结构一无所知，却能给出正确的因子排序。

### 3. 校验错误结构化

```python
make_error(field, code, message, **extra)
```

`message` 给人看，`code` + `allowed` 给程序看。这样大模型可以读错误、改参数、重试，形成闭环；而不是收到一句"参数错误"就卡住或者干脆自己编一个结果。

### 4. 假设与限制随结果返回，不写死在文档里

`envelope()` 强制附加 `assumptions` 与 `limitations`。文档可以没人看，但接口响应绕不过去——任何下游（界面、报告、大模型、二次开发）都会拿到同样的边界说明。

## 新增一个实验

需要两步。

**第一步：写实验类**

```python
# geolab/experiments/wind_erosion.py
from ..protocol import Param, Experiment

class WindErosion(Experiment):
    id = "wind_erosion"
    title = "风蚀强度估算"
    summary = "……"
    domain = "风沙地貌"

    parameters = [
        Param(name="wind_speed_ms", label="近地表风速", unit="m/s",
              minimum=0, maximum=40, default=8, step=0.5),
        Param(name="surface_moisture", label="表层含水率", unit="%",
              minimum=0, maximum=40, default=5, step=1),
    ]
    assumptions = ["……"]
    limitations = ["……"]
    outputs = [{"key": "flux", "label": "输沙通量", "unit": "kg/(m·h)"}]
    primary_output = "flux"

    def run(self, params):
        # 在这里写纯计算
        return {"flux": ..., "headline": "……"}
```

**第二步：注册一行**

```python
# geolab/registry.py
from .experiments.wind_erosion import WindErosion
register(WindErosion())
```

然后 `/api/catalog` 会返回它，前端自动长出参数面板，`sweep`/`compare`/`analyze` 直接可用，`tests/` 里复制一个测试文件即可。

不需要改：`server.py`、`service.py`、`web/` 里任何一行。

## 接入 EduWork

EduWork 是构建在 DeepSeek Harness 之上的教育 Agent 工作台，扩展方式有两类：**技能（SKILL.md 目录）** 与 **原生插件（npm 包）**。

### 路线 A：技能接入（当前已具备）

`skills/` 下的三个目录已经按 EduWork 的技能约定写好（YAML frontmatter + Markdown 正文），放入 EduWork 的技能目录即可被加载。技能负责告诉模型**什么时候用工具、怎么用、解释时不能说什么**。

这一层是本项目"教学价值"的主要载体——它约束的不是计算，而是**解释纪律**。

### 路线 B：HTTP 工具桥（推荐下一步）

用一个轻量 DSH 工具包，把 `/api/execute` 包装成原生工具调用。优点是本项目的计算内核完全不动，Python 侧保持零依赖。

### 路线 C：原生插件（长期）

发布为 `@geolab/dsh-geolab` npm 包。根据 EduWork 的包维护文档，插件需注意：

- `peerDependencies` 声明支持的 DSH API 范围，用有上下界的范围而非 `*`（例如文献包声明 `>=0.2.0-rc.1 <0.3.0-0`）
- 工具通过 `tools/pre-execute` 请求审批时，除 `reason` 外应提供双语 `displayReason: { zh, en }`
- 独立 npm 包需携带 `LICENSE` 与第三方声明

> **当前状态**：路线 A 已完成；路线 B、C 未实现。README 的路线图中如实标注，不把"计划"写成"已完成"。

## 前端为什么自己画图表

ECharts 通过 CDN 引入只需一行，但会引入三个问题：断网演示失败、内网环境失败、评审环境版本不确定。

`web/charts.js` 用 SVG 实现了三种图：折线、横向条形、弯道平面场。约 300 行，无依赖，离线可用。弯道平面场是按 `(沿程 φ, 横向 s)` 网格逐格绘制的多边形，鼠标悬停可看到该格的流速、剪应力与倾向分类。

## 可复现性

- `params` 返回的是**校验后**的值，原样回传必然得到相同结果
- 所有随机成分：无（不用随机数、不用时间种子）
- `trace` 记录引擎版本与耗时
- 日志面板保留最近 40 次调用的方法与载荷
