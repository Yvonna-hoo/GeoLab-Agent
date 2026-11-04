# 任务路由：规则引擎 vs 大模型引擎

> 由 `eval/compare_engines.py` 自动生成于 2026-11-04 21:27；数据集见 `eval/tasks.jsonl` 与 `eval/heldout.jsonl`。

同一套判据、同一批任务，只替换「谁在理解这句话」。

## 为什么分成两个任务集

| 任务集 | 说明 |
|---|---|
| **A（18 条）** | 规则引擎的关键词表就是照着这批问题写的。它在这里接近满分是**必然的**，但这不能证明泛化能力——这就是过拟合 |
| **B（12 条）** | 换成学生真实的口语说法（「修了梯田比不修能少流失多少土」），规则引擎的关键词表没见过这些句式，这一组才反映真实能力 |

只报 A 是自欺欺人；只报 B 又不公平（规则引擎本来也没打算覆盖所有说法）。两个并排摆出来，才能说明两种引擎各自守哪一段。

## 结果总览

| 指标 | A·规则 | A·大模型 | B·规则 | B·大模型 |
|---|---|---|---|---|
| 路由准确率 | 100.0% | 100.0% | 33.3% | 91.7% |
| 执行符合预期 | 100.0% | 100.0% | 91.7% | 100.0% |
| 平均延迟 | 0 ms | 1196 ms | 0 ms | 1013 ms |
| token 消耗（入/出） | 0 / 0 | 26595 / 1244 | 0 / 0 | 17670 / 765 |
| 成本估算 | 0 元 | 0.0316 元 | 0 元 | 0.0207 元 |

成本按 deepseek-flash 空闲时段价格（输入 1 元/百万、输出 4 元/百万）估算，只代表量级。


## 任务集 A · 设计同源（规则引擎据此调优）

| 任务 | 期望 | 规则引擎 | 大模型 | 备注 |
|---|---|---|---|---|
| T01 在其他条件不变时，植被覆盖变化会怎样影响土壤 | soil_erosion_rusle / sweep | ✅ soil_erosion_rusle / sweep | ✅ soil_erosion_rusle / sweep |  |
| T02 弯曲河道的哪些部位更容易发生侵蚀或沉积？ | river_bend_erosion / run | ✅ river_bend_erosion / run | ✅ river_bend_erosion / run |  |
| T03 同一块坡地，改成梯田或退耕还林之后，土壤流失 | soil_erosion_rusle / compare | ✅ soil_erosion_rusle / compare | ✅ soil_erosion_rusle / compare |  |
| T04 对这块坡地的土壤流失来说，覆盖度和坡度哪个因 | soil_erosion_rusle / analyze | ✅ soil_erosion_rusle / analyze | ✅ soil_erosion_rusle / analyze |  |
| T05 河宽不变的情况下，弯道半径变小，凹岸的冲刷会 | river_bend_erosion / sweep | ✅ river_bend_erosion / sweep | ✅ river_bend_erosion / sweep |  |
| T06 坡面产生的泥沙与河流的搬运、沉积有什么联系？ | - / cross_module | ✅ - / cross_module | ✅ - / cross_module |  |
| T07 把植被覆盖度设成 130%，看看土壤流失量是 | soil_erosion_rusle / run | ✅ soil_erosion_rusle / run | ✅ soil_erosion_rusle / run |  |
| T08 坡度从 3% 增加到 25%，土壤流失量会增 | soil_erosion_rusle / sweep | ✅ soil_erosion_rusle / sweep | ✅ soil_erosion_rusle / sweep |  |
| T09 如果河道流速变大，凹岸的冲刷风险会怎样变化？ | river_bend_erosion / sweep | ✅ river_bend_erosion / sweep | ✅ river_bend_erosion / sweep |  |
| T10 砂岸和黏土岸在同样的水流条件下，冲刷风险差别 | river_bend_erosion / compare | ✅ river_bend_erosion / compare | ✅ river_bend_erosion / compare |  |
| T11 坡长从 10 米延长到 100 米，土壤流失 | soil_erosion_rusle / sweep | ✅ soil_erosion_rusle / sweep | ✅ soil_erosion_rusle / sweep |  |
| T12 降雨侵蚀力从 2000 增加到 6000，土 | soil_erosion_rusle / sweep | ✅ soil_erosion_rusle / sweep | ✅ soil_erosion_rusle / sweep |  |
| T13 帮我写一首关于春天的小诗。 | - / - | ✅ - / - | ✅ - / - |  |
| T14 坡度 15%、坡长 80 米的坡耕地，水土流 | soil_erosion_rusle / run | ✅ soil_erosion_rusle / run | ✅ soil_erosion_rusle / run |  |
| T15 退耕还林和等高耕作相比，哪个保土效果更好？ | soil_erosion_rusle / compare | ✅ soil_erosion_rusle / compare | ✅ soil_erosion_rusle / compare |  |
| T16 弯道转角从 30 度变到 180 度，最大冲 | river_bend_erosion / sweep | ✅ river_bend_erosion / sweep | ✅ river_bend_erosion / sweep |  |
| T17 河宽 30 米、半径 60 米的急弯，凹岸剪 | river_bend_erosion / run | ✅ river_bend_erosion / run | ✅ river_bend_erosion / run |  |
| T18 植被覆盖度对水土流失的影响是不是线性的？请用 | soil_erosion_rusle / sweep | ✅ soil_erosion_rusle / sweep | ✅ soil_erosion_rusle / sweep |  |

## 任务集 B · 未见过的新问法

| 任务 | 期望 | 规则引擎 | 大模型 | 备注 |
|---|---|---|---|---|
| H01 植被覆盖率提高之后，土壤流失量是线性下降的吗 | soil_erosion_rusle / sweep | ✅ soil_erosion_rusle / sweep | ✅ soil_erosion_rusle / sweep |  |
| H02 弯道的内侧和外侧，哪边淤哪边冲？ | river_bend_erosion / run | ✅ river_bend_erosion / run | ✅ river_bend_erosion / run |  |
| H03 同样一块坡，修了梯田比不修能少流失多少土？ | soil_erosion_rusle / compare | ❌ soil_erosion_rusle / run | ✅ soil_erosion_rusle / compare | 分歧 |
| H04 覆盖度和坡长，哪个对流失量更关键？ | soil_erosion_rusle / analyze | ❌ soil_erosion_rusle / compare | ✅ soil_erosion_rusle / analyze | 分歧 |
| H05 河湾转得更急一些，冲刷会加重吗？ | river_bend_erosion / sweep | ❌ river_bend_erosion / run | ✅ river_bend_erosion / sweep | 分歧 |
| H06 降雨多的年份，坡地流失量会差多少？ | soil_erosion_rusle / sweep | ❌ soil_erosion_rusle / run | ✅ soil_erosion_rusle / sweep | 分歧 |
| H07 坡越陡越容易流失吗？ | soil_erosion_rusle / sweep | ❌ - / - | ✅ soil_erosion_rusle / sweep | 分歧 |
| H08 坡面冲下来的土，最后堆在河道的什么位置？ | - / cross_module | ❌ soil_erosion_rusle / run | ✅ - / cross_module | 分歧 |
| H09 把覆盖度写成 150% 会怎么样？ | soil_erosion_rusle / run | ❌ soil_erosion_rusle / sweep | ✅ soil_erosion_rusle / run | 分歧 |
| H10 今天天气怎么样？ | - / - | ✅ - / - | ✅ - / - |  |
| H11 如果把这面坡的树砍了，流失量会翻几倍？ | soil_erosion_rusle / sweep | ❌ soil_erosion_rusle / run | ❌ soil_erosion_rusle / compare | 分歧 |
| H12 河道从直变弯，凹岸的泥沙是被冲走还是堆起来？ | river_bend_erosion / run | ✅ river_bend_erosion / run | ✅ river_bend_erosion / run |  |

## 结论

1. **规则引擎**确定性、零成本、零延迟，在 A 集几乎全中；但 B 集暴露了它的本质——只认写死的说法，换个问法就掉。
2. **大模型**在 A 集与规则引擎基本持平，在 B 集明显更稳；代价是每条多约一千多 token 和约 1 秒。
3. 因此项目默认策略是 `auto`：配了 key 就走大模型；模型调用失败（网络、额度、输出不合法）时**静默回退**到规则引擎。用户永远拿得到结果，且能从返回的 `engine` 字段看出这次是谁答的。

这不是「哪个更好」的问题，而是**两种引擎各守一段**：规则兜底保证可用性，模型负责泛化。为了几个百分点的准确率而拆掉兜底，在真实课堂里并不划算。
