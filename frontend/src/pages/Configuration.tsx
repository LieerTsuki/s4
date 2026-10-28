import { ProfileRevisions } from "./Governance";

import { useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { Plus, ShieldCheck, UserRoundPlus } from "lucide-react";

import { api } from "../api";

import { useCommand, useList } from "../hooks";

import type { Profile, Role, User } from "../types";

import {
  Badge,
  BlockedReasons,
  Empty,
  ErrorNotice,
  PageHeader,
  Panel,
  QueryState,
  RefreshButton,
} from "../components/Common";

const roleNames: Record<Role, string> = {
  admin: "系统管理员",
  lead: "标注运营",
  annotator: "标注员",
  arbitrator: "仲裁员",
  auditor: "QA / 审计",
  verifier: "独立复验员",
};

export function UsersPage() {
  const query = useList<User>("/users");
  const command = useCommand();

  const [showCreate, setShowCreate] = useState(false);
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [person, setPerson] = useState("");
  const [password, setPassword] = useState("");
  const [roles, setRoles] = useState<Role[]>(["annotator"]);
  const [editing, setEditing] = useState<User | null>(null);
  const [newPassword, setNewPassword] = useState("");

  async function create() {
    const result = await command.run<User>("/users", {
      username,
      display_name: name,
      person_id: person,
      password,
      roles,
    });
    if (result) {
      setShowCreate(false);
      setPassword("");
      setUsername("");
      setName("");
      setPerson("");
      command.setSuccess("账号已创建。请通过受控方式向本人交付初始密码。");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="IDENTITY & ACCESS"
        title="账号与角色"
        description="使用个人账号和实际人员标识排班；角色能力仍受对象和阶段条件约束。"
        action={
          <button
            className="button primary"
            onClick={() => setShowCreate(!showCreate)}
          >
            <UserRoundPlus size={17} />
            创建账号
          </button>
        }
      />
      <ErrorNotice error={command.error} />
      {command.success && (
        <div className="notice success" role="status">
          {command.success}
        </div>
      )}

      {showCreate && (
        <Panel
          title="创建工作账号"
          description="一个人员标识对应同一实际人员，不可通过两个账号占用双席。"
        >
          <form
            className="form-grid"
            onSubmit={(event) => {
              event.preventDefault();
              void create();
            }}
          >
            <label>
              账号
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
                maxLength={80}
                autoComplete="off"
              />
            </label>
            <label>
              显示名称
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                maxLength={100}
              />
            </label>
            <label>
              人员标识
              <input
                value={person}
                onChange={(event) => setPerson(event.target.value)}
                required
                maxLength={100}
                placeholder="使用稳定的员工 / 项目人员编号"
              />
            </label>
            <label>
              初始密码
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                minLength={12}
                maxLength={200}
                autoComplete="new-password"
                required
              />
            </label>
            <fieldset className="span-all">
              <legend>角色</legend>
              <div className="checkbox-row">
                {(Object.keys(roleNames) as Role[]).map((role) => (
                  <label className="checkbox-label" key={role}>
                    <input
                      type="checkbox"
                      checked={roles.includes(role)}
                      onChange={(event) =>
                        setRoles(
                          event.target.checked
                            ? [...roles, role]
                            : roles.filter((item) => item !== role),
                        )
                      }
                    />
                    {roleNames[role]}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="button-row span-all">
              <button
                className="button primary"
                disabled={command.pending || !roles.length}
              >
                <Plus size={16} />
                确认创建
              </button>
              <button
                className="button"
                type="button"
                onClick={() => setShowCreate(false)}
              >
                取消
              </button>
            </div>
          </form>
        </Panel>
      )}

      <Panel
        title="工作账号"
        action={<RefreshButton onClick={() => void query.refetch()} />}
      >
        <QueryState pending={query.isPending} error={query.error}>
          {query.data?.items.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>人员</th>
                    <th>账号 / 人员标识</th>
                    <th>角色</th>
                    <th>状态</th>
                    <th>管理</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.items.map((user) => (
                    <tr key={user.id}>
                      <td>
                        <strong>{user.display_name}</strong>
                      </td>
                      <td>
                        <span>{user.username}</span>
                        <div className="muted tiny mono">{user.person_id}</div>
                      </td>
                      <td>
                        <div className="tag-list">
                          {user.roles.map((role) => (
                            <span key={role} className="plain-tag">
                              {roleNames[role]}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td>
                        <Badge
                          value={user.active ? "READY" : "CANCELLED"}
                          label={user.active ? "已启用" : "已停用"}
                        />
                      </td>
                      <td>
                        <div className="button-row">
                          <button
                            className="text-button"
                            disabled={command.pending}
                            onClick={() => {
                              setEditing(user);
                              setNewPassword("");
                            }}
                          >
                            管理
                          </button>
                          <button
                            className="text-button"
                            disabled={command.pending}
                            onClick={() =>
                              void command.run(
                                `/users/${user.id}`,
                                { active: !user.active },
                                "PATCH",
                              )
                            }
                          >
                            {user.active ? "停用" : "启用"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="尚无可展示账号" />
          )}
        </QueryState>
      </Panel>

      {editing && (
        <div className="dialog-backdrop">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="account-dialog"
            className="dialog"
          >
            <h2 id="account-dialog">管理 {editing.display_name}</h2>
            <form
              className="form-stack"
              onSubmit={async (event) => {
                event.preventDefault();
                const result = await command.run(
                  `/users/${editing.id}`,
                  {
                    roles: editing.roles,
                    ...(newPassword ? { password: newPassword } : {}),
                  },
                  "PATCH",
                );
                if (result) {
                  setEditing(null);
                  setNewPassword("");
                  command.setSuccess("账号设置已保存。");
                }
              }}
            >
              <div className="checkbox-row">
                {(Object.keys(roleNames) as Role[]).map((role) => (
                  <label className="checkbox-label" key={role}>
                    <input
                      type="checkbox"
                      checked={editing.roles.includes(role)}
                      onChange={(event) =>
                        setEditing({
                          ...editing,
                          roles: event.target.checked
                            ? [...editing.roles, role]
                            : editing.roles.filter((item) => item !== role),
                        })
                      }
                    />
                    {roleNames[role]}
                  </label>
                ))}
              </div>
              <label>
                重置密码（不修改则留空）
                <input
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  minLength={12}
                  maxLength={200}
                  onChange={(event) => setNewPassword(event.target.value)}
                />
              </label>
              <p className="muted">停用或重置密码后，原会话将由服务端撤销。</p>
              <ErrorNotice error={command.error} />
              <div className="button-row">
                <button
                  className="button primary"
                  disabled={command.pending || !editing.roles.length}
                >
                  保存设置
                </button>
                <button
                  className="button"
                  type="button"
                  onClick={() => setEditing(null)}
                >
                  取消
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </>
  );
}

export function ProfilesPage() {
  const query = useQuery({
    queryKey: ["/profiles"],
    queryFn: () => api<Profile[]>("/profiles"),
  });

  return (
    <>
      <PageHeader
        eyebrow="DATASET PROFILES"
        title="任务配置与规则"
        description="十二类评测单元使用各自的材料与表单；正式统计需要已确认的量表和配对单位。"
      />
      <div className="notice info">
        <ShieldCheck size={20} />
        <div>
          <strong>规则版本随批次冻结</strong>
          <p>
            通用QA逐要点三分类；D4、D6与SEC专项规则未冻结时明确阻塞，不生成虚构κ。
          </p>
        </div>
      </div>
      <ProfileRevisions />
      <QueryState pending={query.isPending} error={query.error}>
        <div className="profile-grid">
          {query.data?.map((profile) => (
            <Panel key={profile.dataset} className="profile-card">
              <div className="profile-heading">
                <span className="dataset-chip">{profile.dataset}</span>
                <Badge
                  value={profile.formal_enabled ? "READY" : "BLOCKED"}
                  label={profile.formal_enabled ? "通用统计策略" : "专项待确认"}
                />
              </div>
              <h2>{profile.title ?? profile.dataset}</h2>
              <p className="muted">
                {profile.kind} · 规则 {profile.version}
              </p>
              <div className="profile-quota">
                <strong>{profile.quota}</strong>
                <span>项目配额 / 评测单元</span>
              </div>
              <BlockedReasons reasons={profile.blocked_reasons} />
            </Panel>
          ))}
        </div>
      </QueryState>
    </>
  );
}
