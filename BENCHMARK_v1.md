# ABAQUS-MCP 验证算例评测基准 v1

> 目的：为 ABAQUS-MCP（让 Agent 调用 MCP 工具驱动 Abaqus 做仿真）建立一套**分类评测基准**。
> 每个算例的"问题描述"作为 prompt 喂给 Agent，参考解用于自动/半自动打分。
> 首批 22 个算例，覆盖 5 类分析 × 5 类几何 × 4 类材料；配 5 维评分体系与"信息缺失"评测。
>
> **English version:** [BENCHMARK_v1_en.md](BENCHMARK_v1_en.md) ·
> **算例的权威定义在** [`cases/NN.yaml`](cases)，本文档给设计原理与参考值总览。

---

## 1. 设计原则

1. **参考解可审计**：优先选用有**闭式解析解**或**公认 NAFEMS 标准解**的经典问题。每个算例给出公式 + 代入数值，便于自动比对，不依赖"另一次仿真"做真值。
2. **分类正交**：每个算例打三个标签 `分析类型 / 几何类型 / 材料类型`，整体保证 5×5×4 三个维度上每一类都被覆盖（非全交叉 100 个，而是覆盖式抽样 22 个）。
3. **prompt 拟真**：问题描述用工程语言写，而非"FEA 操作步骤"，考察 Agent 能否自行完成建模决策（单元类型、网格、边界、求解器选择）。
4. **难度梯度**：从静力线弹问题，到屈曲、超弹、粘弹、热力耦合等强约束、强非线性问题，覆盖不同难度层级。
5. **信息缺失为运行时随机生成**：见 §5。每轮随机删去若干关键参数，考察 Agent 是否"识别缺失并追问/显式假设"而非静默编造。

---

## 2. 五维评分体系

| 维度 | 含义 | 量化方式（建议 0–5 分） | 数据来源 |
|---|---|---|---|
| **D1 信息缺失识别** | 描述不全时能否识别并追问/合理假设并显式声明，而非默默编造 | 5=识别全部缺失项；3=部分识别或假设但显式标注；0=静默编造 | transcript + 生成器记录的 `expected_missing` |
| **D2 结果准确性** | 关键输出量相对参考解的误差 | ≤2%→5；≤5%→4；≤10%→3；≤20%→2；>20% 或定性错→0 | 产出的 `.odb`（按 `extract`） |
| **D3 幻觉调用数** | 调用不存在的 MCP 工具 / 编造参数 / 虚构 Abaqus API | 0 次→5；每次 −1，封底 0 | transcript：失败的 `run_python` 的 `error_type` |
| **D4 token 开销** | 完成任务消耗的总 token（成本加权） | 同类算例内分位归一：最优 25%→5，最差 25%→1 | transcript 的 `usage` |
| **D5 求解开销** | 求解器 CPU/wall-clock（及网格规模合理性） | 在达到 D2 精度前提下，时间/自由度分位归一 | Abaqus `.dat` 的 JOB TIME SUMMARY + DOF |

> D4 成本加权：`effective = input×1 + cache_creation×1.25 + cache_read×0.1 + output×5`。
> D4/D5 为相对指标，需在同一批算例内横向比较，首批跑完后再定分位阈值。
> 建议每个算例跑 **多个随机 seed 取均值 + 方差**，反映 Agent 稳定性。

---

## 3. 覆盖矩阵

标签缩写：分析 `S静力 / M模态 / B屈曲 / D动力学 / T热力耦合`；几何 `Tr桁架 / Pl平面 / Ax轴对称 / Sh板壳 / 3D三维`；材料 `LE线弹 / HE超弹 / EP弹塑性 / VE粘弹`。

**维度覆盖核对（按 cases/ 标签统计）**
- 分析：S×10、M×3、B×3、D×3、T×3 ✔（5 类全覆盖）
- 几何：Tr×1、Pl×3、Ax×4、Sh×4、3D×10 ✔（5 类全覆盖；另有 #11/#14/#17/#18 等以一维线/梁单元建模）
- 材料：LE×15、HE×2、EP×3、VE×2 ✔（4 类全覆盖）

---

## 4. 算例总览

> 每个算例的完整定义（prompt 模板、`extract` 取值规则、可随机缺失的参数）以及关键输出量与参考值，见对应的 [`cases/NN.yaml`](cases)。物性默认：钢 E=200 GPa、ν=0.3、ρ=7850 kg/m³、α=12e-6 /℃。

| # | 名称 | 分析/几何/材料 | 来源 |
|---|---|---|---|
| 01 | 两杆平面桁架 | S/Tr/LE | 静定桁架 |
| 02 | NAFEMS LE1 椭圆膜 | S/Pl/LE | NAFEMS LE1 |
| 03 | 厚壁圆筒内压 (Lamé) | S/Ax/LE | Lamé 解 |
| 04 | 四边简支方板均布压力 | S/Sh/LE | Timoshenko |
| 05 | NAFEMS LE10 厚板受压 | S/3D/LE | NAFEMS LE10 |
| 06 | 橡胶块单轴拉伸 | S/3D/HE | Neo-Hookean |
| 07 | O 形密封圈压缩 | S/Ax/HE | 密封件基准（待标定） |
| 08 | 带孔板拉伸弹塑性 | S/Pl/EP | Peterson + 极限分析 |
| 09 | 厚壁圆筒弹塑性内压 | S/Ax/EP | Hill |
| 10 | 粘弹性杆松弛 | S/3D/VE | Prony 松弛 |
| 11 | 悬臂梁固有频率 | M/3D/LE | Euler-Bernoulli |
| 12 | 四边简支方板模态 | M/Sh/LE | 薄板振动 |
| 13 | 简支实体方板模态 (FV52) | M/3D/LE | NAFEMS FV52 / 薄板基线 |
| 14 | 欧拉柱屈曲 | B/3D/LE | Euler 屈曲 |
| 15 | 轴压薄板屈曲 | B/Sh/LE | Timoshenko (k=4) |
| 16 | 轴压圆柱壳屈曲 | B/Sh/LE | 经典壳屈曲 |
| 17 | 杆中应力波传播 | D/3D/LE | 一维波理论 |
| 18 | 梁阶跃载荷瞬态响应 | D/3D/LE | SDOF 阶跃 |
| 19 | 粘弹性梁阻尼自由衰减 | D/Pl/VE | 粘弹阻尼（待标定） |
| 20 | 约束杆均匀升温热应力 | T/3D/LE | σ=−EαΔT |
| 21 | 受热厚壁圆筒热应力 | T/Ax/LE | 热弹性厚壁筒 |
| 22 | 约束杆升温诱发塑性 | T/3D/EP | 约束热-塑性 |

> 趋势类（#07/#19，及 #08/#16/#21 的部分项）无简单闭式解，按"符号 + 量级区间/单调性"评分，不计入 D2 严格误差。

---

## 5. 信息缺失评测（D1）：运行时随机生成

不再使用固定"删参变体"，而是**每轮随机生成**：每个算例的 prompt 由"可选片段 + 参数"组成，`drop_policy.eligible` 列出允许随机删除的关键参数；生成器（`generate.py`）每轮随机丢弃 0–N 个并**记录丢了哪些**——这份记录就是 D1 的标准答案（`expected_missing`）。

- 每个参数带 `on_drop`：`ask`（无合理默认，应追问）或 `assume_ok`（有行业默认，如钢密度，可假设并显式声明）。
- 全局指令（[`instructions_en.md`](instructions_en.md)）要求 Agent 缺信息时输出 `NEED_INFO:[...]` 或 `ASSUMED: name=value`，使 D1 可机器判定（集合比对）。
- **失败模式联动 D3**：若某缺失参数既未追问/声明，又在 `run_python` 代码里被硬编码 → 判"静默编造"，D1 该项 0 分且联动扣 D3。
- 信息缺失轮建议**单独无人值守跑**：正确行为是"停下追问"，故约定 Agent 输出 `NEED_INFO` 后即终止本例，否则它会自行假设着继续，反而测不出 D1。

---

## 6. 执行与记录

1. **生成 prompt**：`python generate.py cases/NN.yaml [--full | --seed S | --n-drop K]`，默认在题面前拼接全局指令（preamble）。
2. **喂给 Agent**：每次运行用**全新会话**（一会话=一次运行，token 账与 transcript 才干净）。Agent 经 ABAQUS-MCP 跑出 `.odb`。
3. **打分**：
   - D2：按 `expected[].extract` 从 `.odb` 取值，与 `reference` 在 `tol` 内比对。
   - D1/D3/D4：解析会话 transcript（`~/.claude/projects/.../*.jsonl`）。
   - D5：读 Abaqus `.dat` 的 JOB TIME SUMMARY + 模型 DOF。
4. **重复与统计**：每例多个随机 seed，报告 D1–D5 的均值 ± 方差。
5. **回归基线**：本表参考值固化为"金标准"，后续 MCP/模型升级做回归对比。

> 评分脚本（`grade_d2.py` 读 odb 比对；`parse_transcript.py` 出 D1/D3/D4）为下一步交付物；算例集、schema 与 prompt 生成器已完成并通过校验。

---

## 7. 来源

- NAFEMS, *The Standard NAFEMS Benchmarks*（LE1、LE10）
- NAFEMS R0015, *Selected Benchmarks for Natural Frequency Analysis*（FV 系列）
- Abaqus Benchmarks Manual §4.2（LE1=92.7 MPa / LE10=−5.38 MPa）
- Timoshenko, *Theory of Plates and Shells* / *Theory of Elastic Stability* / *Theory of Elasticity* / *Theory of Thermal Stresses*
- Hill, *The Mathematical Theory of Plasticity*（厚壁筒弹塑性）
- Boley & Weiner, *Theory of Thermal Stresses*（热应力）
- Holzapfel, *Nonlinear Solid Mechanics*（超弹本构）
- Blevins, *Formulas for Natural Frequency and Mode Shape*（梁/板频率）

> v1 待办：① 收紧 #07/#19 等趋势项的量级区间（文献/收敛解标定）；② 核对 #21 热应力闭式系数；③ 补 1–2 个粘弹+热（TTS 时温等效）与显式冲击大变形算例，进一步均衡 HE/VE 维度；④ 实现 `grade_d2.py` 与 `parse_transcript.py`。
