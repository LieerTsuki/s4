# 2026-11-17 麦芽平台与队列准备记录

负责人：李悦
环境：麦芽预览 264
准备范围：QA-D1/T0/W5
状态：`PREPARED_FOR_EXECUTION`

## 已核对并冻结

- QA-D1 demo import：`b5715a91-06c2-4e29-ad5d-a04ccce00ae4`
- QA-D1 batch：`B-2026-11-02`
- source_revision：`feat/dataset_pipeline_s2@ecc4441:run3_20261103+run4_r1+r2@725c882`
- manual/profile：`manual-v1.3` / `s4-v1.3`
- frozen_hash：`f606cf52279aef9440a83862616a618b921e99686b6e47cafe2af96e9d3b3e48`
- observation batch：`764f2d5e-069c-4230-b5d9-df22cee92f37`
- 7 个 unit：`QAD1-0015`—`QAD1-0021`
- 当前观测：要求 8、实际 7，A/B 独立 14/14，复核 14/14，`verification_completed=7`
- 当前模式：`demo`，不创建正式 T0/W5 交付，不计正式配额

## 队列准备动作

| 项目 | 处理结果 |
|---|---|
| 既有 QA-D1 demo 关联 | 保留原 import、batch、source_revision 和观测批次，不覆盖历史记录 |
| 独立席位 | 保留 `w3-verify/P-W3-001` 与 `ann-c/P-W3-002` 的账号映射，资格/暴露仍待核验 |
| BLIND/REVIEW 边界 | 先独立封存，再进入复核；不向首次判断席位开放草案、答案和对方结果 |
| 抽样规则 | `v13-stratified-largest-remainder.v1`，seed=42，短缺 1 题单独记录 |
| κ 记录 | `cohen-original-points.v13`，`po=1`、`pe=1`、κ=`null`，不填 1 |
| T0/W5 新队列 | 只建立计划基线，不导入候选，不生成正式分发 assignment |
| 版本屏障 | batch/source_revision/manual/profile/frozen_hash 必须同时匹配，变化时新建 revision |
| 旧写路径 | 继续保持 `LEGACY_READ_ONLY`，不启用旧写入 |

## 待李悦本人在麦芽页面完成的操作

1. 以维护者账号确认当前 preview 入口和版本回读。
2. 以 QA-D1 demo 记录核对队列、席位、BLIND/REVIEW 阶段和历史封存，不修改已封存结果。
3. 为 T0/W5 建立空的受控准备记录，保持候选数为 0，等待真实材料和 Gate。
4. 进入正式分发前再次检查 person_id、资格、暴露、manual/profile、source_revision 和候选摘要。

本记录完成的是平台和队列准备，不是正式候选分发、真人核实完成或 S5 接收通过。
