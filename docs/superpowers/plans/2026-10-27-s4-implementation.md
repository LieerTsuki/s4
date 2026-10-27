# OpenKB-Eval S4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

2026-10-27完成记录：五个工作包已实现并完成本地验证，证据见`docs/acceptance.md`。任务1—3按共同后端/契约依赖合并为受验证的组件提交9faf057，前端为f83138d；部署、E2E与手册单独提交。外部联调、专项规则与真人验收不在已完成项内。下列复选框表示工程活动已完成，不代表生产验收。

**Goal:** 在用户指定s4目录交付可运行、可测试的独立双盲标注系统，并如实区分本地验证与外部/生产验收。

**Architecture:** React工作台调用FastAPI同源接口，PostgreSQL事务约束权限和封存，数据库任务由独立worker执行。纯领域模块负责输入、profile、抽样与κ，外部S3/S5保留版本化待对齐契约。

**Tech Stack:** Python3.11、FastAPI/pydantic2、SQLAlchemy2/asyncpg/Alembic、PostgreSQL17、React19/TypeScript/Vite、pytest/Vitest/Playwright。

---

执行方式：沿用已启用的buddy分工；领域、后端和前端分别拥有文件，主代理负责环境、部署、集成和复核。用户已指定开发目录，直接在该目录的新Git工程开发；不创建其他位置的worktree，不接触旧工程或语源。

## Task 1: 领域规则与版本化契约

**Files:** `backend/src/openkb_s4/domain/{errors,profiles,contracts,sampling,statistics}.py`；`backend/tests/test_domain.py`；`contracts/`。

- [x] 先写行为测试：缺正式证据拒绝、原始95/100不被清洗、分层抽样≥8且不漏层、pe=1不填1、0.6/0.7门正确、缺配对阻塞。
- [x] 运行 `..\.venv\Scripts\python -m pytest tests/test_domain.py -q`，记录缺实现失败。
- [x] 实现纯函数 `validate_import(payload)->dict`、`sample_units(units, seed)->dict`、`calculate_agreement(a,b)->dict`、`list_profiles()->list[dict]`，错误统一`DomainError(code,message)`。输入输出详见接口协作约定。
- [x] 重新运行上述测试并核对独立推导期望值。
- [x] 只提交该任务文件，Conventional Commit与实际作者sign-off；不生成或提交真实题目和凭据。

最小统计回归示例：
```python
def test_constant_labels_are_undefined():
    result = calculate_agreement(["correct"] * 8, ["correct"] * 8)
    assert result["kappa"] is None
    assert result["verdict"] == "BLOCKED"
```

## Task 2: PostgreSQL、认证、权限与API

**Files:** `backend/pyproject.toml`、`backend/src/openkb_s4/{config,db,models,schemas,security,cli,main}.py`、`backend/src/openkb_s4/api/`、`backend/src/openkb_s4/services/`、`backend/alembic/`、`backend/tests/test_api.py`。

- [x] 测试先覆盖401、失效会话、CSRF、管理员非业务超管、同人双席拒绝、A不可读B详情、BLIND不含草案、未齐禁止解锁、重复提交幂等和草稿版本冲突。
- [x] 在真实PostgreSQL运行 `..\.venv\Scripts\python -m pytest tests/test_api.py -q`，确认失败由能力缺失引起。
- [x] Alembic迁移建表，应用不自动create_all；API按协作约定实现，身份从会话取；所有提交和解锁锁定批次，写审计，禁止覆盖封存。
- [x] 账号通过交互式CLI初始化，密码由getpass/环境输入，存Argon2id，数据库仅存会话令牌摘要；Cookie与CSRF保护写请求。
- [x] 重跑迁移、认证和权限测试，再测试参与者权限收缩、停用账号撤销会话、阶段越权与正文枚举验证。
- [x] 只提交后端此工作包文件，记录验证命令与结果。

## Task 3: 持久任务、质量、人工闭环与导出

**Files:** `backend/src/openkb_s4/{worker,services/{jobs,workflow,handoffs}}.py`、`backend/tests/test_workflow.py`、`backend/tests/test_handoffs.py`。

- [x] 先测试缺配对/规则未确认不能算有效κ；灰区未闭环拒绝导出；低κ新轮保留旧结果；未抽检N−n不丢失；导出篡改拒绝；worker重启不重复发布。
- [x] 运行对应pytest，保存预期失败摘要。
- [x] worker用PostgreSQL SKIP LOCKED、租约、有限重试和幂等业务键；导入、统计、导出在事务内登记任务，文件全部核对才发布manifest。
- [x] 实现第三人裁决与独立负责人确认；ACCEPT也需逐单元内容定稿；全量与抽检分离，demo导出明确标识，外部回执默认未对齐。
- [x] 重跑测试及并发提交/解锁/重复领取测试，核对原始标签和κ未被仲裁覆盖。
- [x] 只提交该任务文件及证据。

## Task 4: React工作台

**Files:** `frontend/package.json`及锁文件、`frontend/src/{api,types,App,main}.tsx/ts`、`frontend/src/pages/`、`frontend/src/components/`、`frontend/src/styles.css`、`frontend/src/tests/`。

- [x] 先写登录错误、未登录不读业务、阶段表单、字典2/1/0和退出清缓存的组件行为测试。
- [x] 运行 `npm test -- --run`，确认缺能力失败。
- [x] 实现中文导航与错误/等待/空状态；所有页面调用真实API；轮询202任务，不用静态假数据替代持久化。BLIND只展示阶段投影，REVIEW按point_key/doc_id绑定多项。
- [x] 接通账号、profile、导入、批次排班、我的任务、质量仲裁、轮次、导出、审计与健康页，角色仅控制展示，最终权限由API决定。
- [x] 运行 `npm test -- --run`、`npm run build`、`npm run lint`。
- [x] 只提交前端此任务文件。

## Task 5: 部署、整体验证与操作手册

**Files:** `deploy/`、`scripts/`、`.github/workflows/ci.yml`、`tests/e2e/`、`README.md`、`docs/{OPERATIONS,ACCEPTANCE,API_ALIGNMENT}.md`。

- [x] 在合成demo及专用测试库写E2E：运营导入/派发→A/B分别盲答→拒绝提前解锁→统一解锁→复核→批次κ→定稿或人工仲裁→N/n导出。
- [x] 首次运行真实API/浏览器流程，记录尚未接通的失败并逐项修复。
- [x] 提供Compose四类服务、迁移命令、环境示例、备份恢复脚本、依赖锁和CI；服务不含预置通用凭据。
- [x] 执行pytest覆盖率≥80%、ruff、mypy strict、前端测试/构建/lint、浏览器E2E、备份恢复核对；各项仅据实际输出登记。
- [x] 更新手册真实启动入口和已验证范围，外部联调、专项确认及真人演练保留未完成状态，不伪造生产验收。
- [x] 审查所有改动和忽略规则，提交本工程变更，不推送未知远端。

## 协作接口约定

API前缀`/api/s4/v1`，JSON错误`{error_code,message,request_id}`。认证`POST /auth/login {username,password}`返回`{user,csrf_token}`并设Cookie；`GET /auth/me`返回同形；写请求带`X-CSRF-Token`；`POST /auth/logout`撤销。用户字段`id,username,display_name,person_id,roles,active`，roles为admin/lead/annotator/arbitrator/auditor。业务ID均字符串。

`GET/POST /users`管理账号；`GET /profiles`返回数组；`GET/POST /imports`导入payload并返回202 job_id；`GET /jobs/{id}`查询任务。输入为`{contract_version,mode,batch_id,source_revision,units,s3_report?,source_manifest?,checksums?}`，unit有`unit_id,dataset,difficulty,question?/payload?,gold?/expected_behavior?,contexts:[{doc_id,text}],metadata?`。demo也禁止无范围原文的普通QA作业。

`GET/POST /annotation-batches`，创建体`{import_id,dataset,annotator_a,annotator_b,seed}`；详情`GET /annotation-batches/{id}`；解锁`POST /annotation-batches/{id}/release-review`；统计`POST /annotation-batches/{id}/agreement`返回job_id；定稿`POST /annotation-batches/{id}/finalize {decisions:[{unit_id,final_gold,reason}]}`。列表响应统一`{items:[...],total}`，profile仍为数组。

`GET /me/tasks`；`GET /assignments/{id}`；`PATCH /assignments/{id}/draft {phase,version,payload}`；`POST /assignments/{id}/submit {phase,content_revision,profile_version,payload}`带`Idempotency-Key`。BLIND payload`{answer,reason}`；REVIEW payload`{point_labels:{P001:correct},evidence_labels:{doc_id:2},answerable,reason,suggested_points?,evidence_changes?}`。

`GET /agreements`；`GET/POST /arbitrations {batch_id,unit_id,final_gold,reason}`；`POST /arbitrations/{id}/confirm {reason}`；`POST /rounds {batch_id,annotator_a,annotator_b,reason,seed}`；`GET/POST /handoffs {import_id}`；`GET /handoffs/{id}`；文件`GET /handoffs/{id}/files/{filename}`；`GET /audit`；`GET /health/live`、`GET /health/ready`。前后端若需新增字段，双方同步修改本约定与测试。

领域函数约定：sample_units返回`{selected_ids, strata, blocked_reasons}`；calculate_agreement返回`{kappa,po,pe,n,verdict,blocked_reasons}`；validate_import返回归一化payload字典，额外`blocked_reasons`记录formal专项与外部确认依赖；list_profiles返回含`dataset,quota,kind,version,formal_enabled,blocked_reasons`的数组。内容摘要统一UTF-8、sort_keys、紧凑JSON SHA256。

## 设计自查

所有实施项覆盖已确认设计；依赖按领域→后端/前端→集成顺序，独立模块并行有明确文件所有权。测试来自权限、状态、质量门和交接的用户可观察结果。环境准备失败时如实记录，不用SQLite或模拟截图代替真实验证；正式外部证据缺失只阻塞对应出口，不改业务阈值。
