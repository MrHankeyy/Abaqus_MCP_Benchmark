# ABAQUS-MCP Benchmark

**English** · [中文](#中文)

A classification benchmark for evaluating an LLM agent that drives Abaqus through an
**ABAQUS-MCP** server (an MCP whose main tool executes Abaqus/Python in a live CAE kernel).

📄 Design doc — **ABAQUS-MCP Validation Benchmark**: [English](BENCHMARK_v1_en.md) · [中文](BENCHMARK_v1.md)

---

<a id="english"></a>
## English

**Contents:** [Overview](#overview) · [Coverage](#coverage) · [Scoring](#five-scoring-dimensions) ·
[Layout](#repository-layout) · [Case format](#case-format) · [Usage](#usage) ·
[Evaluation loop](#evaluation-loop) · [Validating](#validating-the-case-set) ·
[Docs](#documentation) · [References](#references)

### Overview

Each case is described in plain engineering language. The agent must make all the modelling
decisions itself (element type, mesh, BCs, solver) — the prompt never hints at them. Reference
answers come from **closed-form solutions** or **published NAFEMS targets**, so accuracy can be
graded automatically against ground truth instead of against another simulation.

The prompt the agent receives is [`instructions_en.md`](instructions_en.md) (global rules: prefer
MCP tools over Bash, put all files under the scratch directory, the missing-info protocol, etc.)
followed by the case-specific problem statement. Edit `instructions_en.md` once to change the
rules for every case.

### Coverage

22 cases spanning the matrix **5 analyses × 5 geometries × 4 materials** (covering sampling, not
the full 100-cell cross product):

- **Analyses:** S static · M modal · B buckling · D dynamics · T thermal-mechanical
- **Geometries:** Tr truss · Pl plane · Ax axisymmetric · Sh plate/shell · 3D solid
- **Materials:** LE linear-elastic · HE hyperelastic · EP elastoplastic · VE viscoelastic

### Five scoring dimensions

| Dim | Meaning | Source |
|-----|---------|--------|
| D1 | Information-gap identification (does it ask / declare assumptions instead of fabricating?) | transcript + drop record |
| D2 | Result accuracy vs the reference value | the produced `.odb` (per `extract`) |
| D3 | Hallucinated API calls | transcript (failed `run_python`, `error_type`) |
| D4 | Token cost (cost-weighted) | transcript `usage` |
| D5 | Solver cost | Abaqus `.dat` JOB TIME SUMMARY + DOF |

### Repository layout

```
schema.yaml              Field definitions for a case (the contract every case follows)
cases/NN.yaml            22 benchmark cases (templated)
instructions_en.md       Global operating instructions (preamble) prepended to every prompt
generate.py              Build a prompt instance from a case (+ random information-gap)
requirements.txt         PyYAML
BENCHMARK_v1_en.md       Design doc (English)
BENCHMARK_v1.md         Design doc (Chinese)
NOTES.md                 Open questions / observations log
```

### Case format

A case stores the prompt as **ordered segments**, some gated by a parameter. Only the `prompt`
(assembled from segments) is ever shown to the agent; `inputs`, `expected` and `reference` (the
answers) are **never** sent to it. `expected[].extract` tells the grader where to read the
ground-truth value from the `.odb`, bypassing whatever the agent says in prose.

Information gaps are generated **at run time, not fixed**: `drop_policy.eligible` lists the
parameters that may be randomly removed, and the generator records exactly which were dropped —
that record is the D1 ground truth. Each eligible parameter lives in its own segment so it can be
removed independently.

### Usage

```bash
pip install -r requirements.txt

# Full-information prompt for a case:
python generate.py cases/03.yaml --full

# A reproducible random information-gap instance (records what it dropped):
python generate.py cases/03.yaml --seed 7 --json

# Force exactly one dropped parameter:
python generate.py cases/09.yaml --seed 1 --n-drop 1

# Bare problem statement, without the global operating instructions:
python generate.py cases/03.yaml --full --no-preamble
```

By default the generated `prompt` is `instructions_en.md` + the case problem. Use
`--preamble <path>` to swap in a different instruction file, or `--no-preamble` to omit it.
`--json` also emits `dropped` / `expected_missing` (the D1 ground truth).

### Evaluation loop

1. `generate.py` produces a prompt instance (full or gapped).
2. Feed the `prompt` to the agent in a **fresh session** (one session = one run). The agent runs
   Abaqus via ABAQUS-MCP and produces an `.odb`.
3. Grade — **D2** from the `.odb` per `extract`; **D1/D3/D4** from the session transcript;
   **D5** from the Abaqus `.dat` JOB TIME SUMMARY + DOF.
4. Repeat each case over several seeds; report mean ± variance per dimension.

> The grading scripts (`grade_d2.py`, `parse_transcript.py`) are the next deliverable; the case
> set, schema and prompt generator are complete and validated.

### Validating the case set

`validate_case` (in `generate.py`) enforces that every droppable parameter sits in its own gated
segment, so a malformed case fails loudly instead of only on an unlucky random seed:

```bash
python -c "import glob; from generate import load_case, validate_case; \
[print(f, validate_case(load_case(f))) for f in glob.glob('cases/*.yaml') if validate_case(load_case(f))] or print('all clean')"
```

### Documentation

- **ABAQUS-MCP Validation Benchmark** (full design doc): [English](BENCHMARK_v1_en.md) · [中文](BENCHMARK_v1.md)
- Case field contract: [`schema.yaml`](schema.yaml)
- Open questions: [`NOTES.md`](NOTES.md)

### References

NAFEMS standard benchmarks (LE1, LE10, FV series); Abaqus Benchmarks Manual; Timoshenko
(*Plates and Shells*, *Elastic Stability*, *Elasticity*, *Thermal Stresses*); Hill
(*Mathematical Theory of Plasticity*); Blevins (*Formulas for Natural Frequency*).

---

<a id="中文"></a>
## 中文

[English](#english) · **中文**

用于评测"驱动 Abaqus 做仿真的 LLM Agent"的分类基准。Agent 通过 **ABAQUS-MCP** 服务器
（其主工具在常驻 CAE 内核中执行 Abaqus/Python）完成建模与求解。

📄 设计文档 —— **ABAQUS-MCP 验证算例评测基准**：[English](BENCHMARK_v1_en.md) · [中文](BENCHMARK_v1.md)

**目录：** [概述](#概述) · [覆盖范围](#覆盖范围) · [五维评分](#五维评分) ·
[目录结构](#目录结构) · [算例格式](#算例格式) · [使用方法](#使用方法) ·
[评测流程](#评测流程) · [校验](#校验算例集) · [文档](#文档) · [来源](#来源)

### 概述

每个算例用工程语言描述问题，**不提示**单元类型、网格、边界或求解器——这些建模决策全部由
Agent 自主完成。参考解来自**闭式解析解**或**公认 NAFEMS 标准值**，因此准确性可以对照真值
自动评分，而非"对照另一次仿真"。

Agent 收到的 prompt = 全局指令 [`instructions_en.md`](instructions_en.md)（优先用 MCP 工具而非
Bash、所有文件放 scratch 目录、信息缺失协议等）+ 该算例的题面。改一处 `instructions_en.md`，
22 个算例的全局规则同时生效。

### 覆盖范围

22 个算例覆盖矩阵 **5 类分析 × 5 类几何 × 4 类材料**（覆盖式抽样，而非 100 个全交叉）：

- **分析：** S 静力 · M 模态 · B 屈曲 · D 动力学 · T 热力耦合
- **几何：** Tr 桁架 · Pl 平面 · Ax 轴对称 · Sh 板壳 · 3D 三维
- **材料：** LE 线弹 · HE 超弹 · EP 弹塑性 · VE 粘弹

### 五维评分

| 维度 | 含义 | 数据来源 |
|-----|---------|--------|
| D1 | 信息缺失识别（缺信息时是追问/显式假设，还是编造？） | transcript + 缺失记录 |
| D2 | 结果相对参考值的准确性 | 产出的 `.odb`（按 `extract`） |
| D3 | 幻觉 API 调用 | transcript（失败的 `run_python`、`error_type`） |
| D4 | token 开销（成本加权） | transcript 的 `usage` |
| D5 | 求解开销 | Abaqus `.dat` 的 JOB TIME SUMMARY + DOF |

### 目录结构

```
schema.yaml              算例字段定义（每个算例遵循的契约）
cases/NN.yaml            22 个算例（模板化）
instructions_en.md       全局操作指令（preamble），拼接在每个 prompt 前
generate.py              从算例生成 prompt 实例（含随机信息缺失）
requirements.txt         PyYAML
BENCHMARK_v1_en.md       设计文档（英文）
BENCHMARK_v1.md         设计文档（中文）
NOTES.md                 开放问题 / 观察记录
```

### 算例格式

算例把 prompt 存成**有序片段**，部分片段由参数控制开关。只有拼装出的 `prompt` 会发给 Agent；
`inputs`、`expected`、`reference`（即答案）**绝不**发给它。`expected[].extract` 告诉评分脚本去
`.odb` 的哪里取真值，从而绕开 Agent 自报的数字。

信息缺失是**运行时随机生成、非固定**：`drop_policy.eligible` 列出可随机删除的参数，生成器会
**记录到底删了哪些**——这份记录就是 D1 的标准答案。每个可删参数独占一段，可被独立删除。

### 使用方法

```bash
pip install -r requirements.txt

# 某算例的满信息 prompt：
python generate.py cases/03.yaml --full

# 可复现的随机信息缺失实例（并记录删了什么）：
python generate.py cases/03.yaml --seed 7 --json

# 强制只删一个参数：
python generate.py cases/09.yaml --seed 1 --n-drop 1

# 纯题面，不带全局操作指令：
python generate.py cases/03.yaml --full --no-preamble
```

默认 `prompt` = `instructions_en.md` + 题面。用 `--preamble <路径>` 换指令文件，`--no-preamble`
省略它。`--json` 还会输出 `dropped` / `expected_missing`（D1 标准答案）。

### 评测流程

1. `generate.py` 生成一个 prompt 实例（满信息或残缺）。
2. 在**全新会话**里把 `prompt` 喂给 Agent（一会话=一次运行）。Agent 经 ABAQUS-MCP 跑出 `.odb`。
3. 打分 —— **D2** 按 `extract` 从 `.odb` 取值；**D1/D3/D4** 解析会话 transcript；**D5** 读
   Abaqus `.dat` 的 JOB TIME SUMMARY + DOF。
4. 每例多个 seed 重复，报告各维度的均值 ± 方差。

> 评分脚本（`grade_d2.py`、`parse_transcript.py`）为下一步交付物；算例集、schema 与 prompt
> 生成器已完成并通过校验。

### 校验算例集

`generate.py` 里的 `validate_case` 强制"每个可删参数独占一段"，配置错了会**明确报错**，而不是
靠运气在某个随机种子才暴露：

```bash
python -c "import glob; from generate import load_case, validate_case; \
[print(f, validate_case(load_case(f))) for f in glob.glob('cases/*.yaml') if validate_case(load_case(f))] or print('all clean')"
```

### 文档

- **ABAQUS-MCP 验证算例评测基准**（完整设计文档）：[English](BENCHMARK_v1_en.md) · [中文](BENCHMARK_v1.md)
- 算例字段契约：[`schema.yaml`](schema.yaml)
- 开放问题：[`NOTES.md`](NOTES.md)

### 来源

NAFEMS 标准基准（LE1、LE10、FV 系列）；Abaqus Benchmarks Manual；Timoshenko（《板壳理论》
《弹性稳定性》《弹性力学》《热应力》）；Hill（《塑性数学理论》）；Blevins（《固有频率公式》）。
