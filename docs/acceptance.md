# 本地工程验收记录

日期：2026-10-27，Asia/Shanghai。结论：独立工程实现与本地自动化验证完成；不是正式数据验收或真实S5接收。

## 环境与范围

- 根目录`D:\openkb-eval\liyue\s4`，独立Git分支`s4-development`；没有远端，不推送或修改旧工程。
- Windows，Python3.11.18、Node24.19、PostgreSQL17.11、Docker29.9.2；React19、FastAPI、SQLAlchemy2、Alembic及锁定依赖。
- 后端测试清理使用专用`s4_test` owner；所有API/worker操作使用实际受限`s4_app`。浏览器独立`s4_e2e`也使用运行账号，迁移账号分离。
- 本机容器入口`http://localhost:8084`；迁移0002完成；DB/API/worker/readiness正常，外部状态NOT_ALIGNED。

## 实际执行结果

| 检查 | 实际结果 | 证据 |
|---|---|---|
| pytest，真实PG权限/事务/并发/恢复 | 116 passed；覆盖率88.38%，门槛80% | `var/evidence/final-checks.log` |
| Ruff、严格mypy | clean；24个源码文件类型检查通过 | 同上 |
| 前端Vitest | 18/18，4个测试文件 | 同上 |
| 前端生产构建、ESLint | 通过，零lint警告 | 同上 |
| Edge浏览器真实表单闭环 | 1 passed；低权限数据库运行 | `var/evidence/e2e-results.json`及截图 |
| 6份JSON Schema元校验 | 通过；2个合成输入及3个真实导出快照逐行通过 | `scripts/check_contracts.py`实测 |
| 固定digest镜像构建、Compose启动 | API、worker、gateway、PG成功启动；readiness=ready | `var/evidence/container-build.log`、`container-start.log` |
| Python生产依赖漏洞库查询 | 33依赖，0已知漏洞（查询时点） | `var/evidence/backend-audit.json` |
| npm全部依赖漏洞库查询 | 0漏洞（含开发依赖，查询时点） | `var/evidence/frontend-audit-all.json` |
| 声明许可元数据 | 357依赖记录，0缺失/配置中的禁用许可命中 | `var/evidence/dependency-licenses.json` |
| Gitleaks8.30.1 | 后端/前端/集成分批暂存扫描0泄漏 | `var/evidence/gitleaks-*.json` |
| CycloneDX | 后端33生产组件；前端253完整构建组件，包含React/ReactDOM | `var/evidence/*-sbom.cdx.json` |
| 数据库+文件隔离恢复 | 行数一致，3个快照摘要/清单/单元集合一致 | 下方恢复证据 |

后端/契约本地提交9faf057，前端本地提交f83138d，均使用实际Git作者sign-off。CI配置已提供，尚无远端CI运行证据，不能把本机检查表述为远端CI通过。许可检查仅覆盖依赖声明元数据；不等于完整二进制镜像或法律审查。

## 浏览器合成闭环

最新成功轮次使用合成12题，按规则抽8题，固定A/B分别封存16份BLIND和16份REVIEW。A的一份独立作答和复核通过真实浏览器表单完成，其他重复记录由API驱动；运营统一开放复核、发起统计、修订8题最终内容、封存定稿、创建交接快照全部通过浏览器表单完成。另检验提前开放409、读取另一席位404、标注员下载交接403。

原始24个要点标签对κ=1、ACCEPT；仍逐题人工操作最终内容确认，不自动采用A/B。交接包含全量12行、抽检8行、IAA8行及其余过程文件，集合和摘要核对通过。这里的操作人员是自动化脚本，不能声称真人双盲。

最新合成批次：`5b1a6b54-9551-4e7b-9145-6bcf9367a62e`；交接：`0d096ffe-8f59-5ae3-a3d0-cfb2da68e87d`。模式demo、状态DEMO_READY、外部NOT_ALIGNED、human_acceptance=NOT_PERFORMED。清单SHA256为`a3a10b21cbf91b5ef26e1cf771ad1339bcad46def6287d5d60e3b552c1b50b16`。

截图：`var/evidence/blind-workspace.png`、`review-workspace.png`、`handoff-workbench.png`、`annotator-workbench.png`。运行证据与凭据均不提交，文档仅记录非敏感摘要及合成数量。

## 恢复演练

停写后以`backups/final-synthetic-rehearsal`备份，恢复到新数据库`s4_restore_20261027_071718_d9816f`及同名var目录；原库未被覆盖。恢复12张业务表计数一致，包含25用户、6导入、5统计批次、80分配、160封存、5统计、32定稿、912暴露、14任务、3快照、312审计；这包含历次失败回归留下的合成历史，不能累加为真实交付数量。

证据：`var/s4_restore_20261027_071718_d9816f/restore-verification.json`。3个已发布快照均与恢复数据库中的已发布manifest逐一比较，并通过摘要、N/n及集合复核；目录集合也与DB一致。目标生产环境RPO/RTO、切换和异地恢复未演练。

## 审查修复与限制

已覆盖：导入者及下载全量N的暴露记录、运营参标权限收缩、专项材料阶段投影、原文有效期/ACL元数据、磁盘manifest篡改、并发重复任务/封存/批次、租约超过3次失败、存储IO失败恢复、first-admin并发互斥、畸形输入安全422及安全500日志。

实际受限账号曾在创建批次时暴露只读SourceImport的FOR UPDATE权限冲突，现改为事务advisory lock；没有扩大原输入表权限。前端开发工具漏洞扫描曾发现旧Vitest/tinypool问题，升级Vitest5.0.5后完整审计为0，测试与构建重新通过。

仍待取得的证据：真实20题双人演练、专项量表及统计单位确认、D7可信放大规则、S3真实证据与外部传输协议、S5真实接收/验收、目标生产环境恢复。系统当前阻止formal出口，不会凭环境开关或材料自声明绕过这些待对齐项。
