# Coding Standards

Python3.11，完整公共类型，ruff格式/lint与mypy strict。TypeScript strict，函数组件，禁止any掩盖接口错误。服务端UTC，页面Asia/Shanghai。JSON API统一错误与request_id；日志不得记录原文、密码或令牌。

新增业务先写并运行失败测试，后实现，再跑通过。事务、权限、幂等、版本及封存由后端保证；禁止用前端隐藏字段替代访问控制。真实PostgreSQL测试不以SQLite替代。角色冲突和专项未定规则必须可见阻塞。

每文件只保留一类职责；不改其他代理拥有的文件。Conventional Commits，实际Git作者sign-off，不伪造远端、评审或生产证据。不提交var、.env、node_modules、.venv、.tools和真实题目。
