import { GovernancePage } from "./pages/Governance";
import { V13Overview, V13Imports, V13ImportDetail, V13Batches, V13BatchDetail, V13Tasks, V13Profiles } from "./v13/Pages";
import { V13TaskPage } from "./v13/Workspace";
import { V13Handoffs } from "./v13/Handoffs";
import { V13Governance } from "./v13/Governance";

import { NotificationsPage } from "./pages/CompletionOperations";

import { useEffect, useState } from "react";

import type { ReactNode } from "react";

import { NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { useQueryClient } from "@tanstack/react-query";

import {
  Activity,
  BookOpenCheck,
  ClipboardCheck,
  FileInput,
  FileOutput,
  LayoutDashboard,
  Layers3,
  LogOut,
  Scale,
  ScrollText,
  Settings2,
  ShieldCheck,
  UsersRound,
} from "lucide-react";

import { api, ApiError, setCsrfToken } from "./api";

import type { Role, Session } from "./types";

import { LoginForm } from "./components/LoginForm";

import { Empty, ErrorNotice, Loading } from "./components/Common";

import { Dashboard } from "./pages/Dashboard";

import { UsersPage, ProfilesPage } from "./pages/Configuration";

import { ImportsPage } from "./pages/Imports";

import { BatchesPage, BatchPage } from "./pages/Batches";

import { TasksPage, TaskPage } from "./pages/Tasks";

import { QualityPage, ArbitrationPage } from "./pages/Quality";

import {
  AuditPage,
  HandoffPage,
  HandoffsPage,
  HealthPage,
} from "./pages/Operations";

const roleNames: Record<Role, string> = {
  admin: "系统管理员",
  lead: "标注运营",
  annotator: "标注员",
  arbitrator: "仲裁员",
  auditor: "QA / 审计",
  verifier: "独立复验员",
};

const navigation = [
  { to: "/", label: "工作概览", icon: LayoutDashboard, roles: [] },
  { to: "/v13/imports", label: "新版候选接入", icon: FileInput, roles: ["lead", "auditor"] },
  { to: "/v13/batches", label: "全量核实与观测", icon: Layers3, roles: ["lead", "auditor"] },
  { to: "/v13/tasks", label: "我的核实任务", icon: ClipboardCheck, roles: ["annotator"] },
  { to: "/v13/handoffs", label: "新版过程交接", icon: FileOutput, roles: ["lead", "auditor"] },
  { to: "/v13/governance", label: "新版材料与复验", icon: ShieldCheck, roles: ["lead", "auditor", "annotator", "verifier", "arbitrator"] },
  { to: "/v13/profiles", label: "当前任务配置", icon: Settings2, roles: [] },

  {
    to: "/imports",
    label: "历史候选接入",
    icon: FileInput,
    roles: ["lead", "auditor"],
  },

  {
    to: "/batches",
    label: "历史双标批次",
    icon: Layers3,
    roles: ["lead", "auditor", "arbitrator"],
  },

  {
    to: "/tasks",
    label: "历史标注任务",
    icon: ClipboardCheck,
    roles: ["annotator"],
  },

  {
    to: "/quality",
    label: "历史质量与定稿",
    icon: BookOpenCheck,
    roles: ["lead", "auditor", "arbitrator"],
  },

  {
    to: "/arbitrations",
    label: "历史人工仲裁",
    icon: Scale,
    roles: ["lead", "auditor", "arbitrator"],
  },

  {
    to: "/handoffs",
    label: "历史导出与交接",
    icon: FileOutput,
    roles: ["lead", "auditor"],
  },

  {
    to: "/governance",
    label: "历史材料与复验",
    icon: ShieldCheck,
    roles: ["lead", "auditor", "verifier"],
  },

  { to: "/notifications", label: "站内提醒", icon: Activity, roles: [] },

  { to: "/profiles", label: "历史任务配置", icon: Settings2, roles: [] },

  { to: "/users", label: "账号与角色", icon: UsersRound, roles: ["admin"] },

  { to: "/audit", label: "审计记录", icon: ScrollText, roles: ["auditor"] },

  { to: "/health", label: "系统健康", icon: Activity, roles: [] },
];

export function App() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const legacy = /^\/(?:legacy|imports|batches|tasks|quality|arbitrations|handoffs|governance|profiles)(?:\/|$)/.test(location.pathname);

  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    let current = true;
    const controller = new AbortController();

    void api<Session>("/auth/me", { signal: controller.signal })
      .then((result) => {
        if (current) {
          setCsrfToken(result.csrf_token);
          setSession(result);
        }
      })
      .catch((failure) => {
        if (current && !(failure instanceof ApiError && failure.status === 401))
          setError(failure);
      })
      .finally(() => {
        if (current) setLoading(false);
      });

    return () => {
      current = false;
      controller.abort();
    };
  }, []);

  useEffect(() => {
    const expire = () => {
      setSession(null);
      setCsrfToken(null);
      void client.cancelQueries();
      client.clear();
      setError(new Error("会话已失效，请重新登录。"));
    };
    window.addEventListener("s4-session-expired", expire);
    return () => window.removeEventListener("s4-session-expired", expire);
  }, [client]);

  async function login(username: string, password: string) {
    const result = await api<Session>("/auth/login", {
      method: "POST",
      body: { username, password },
    });
    await client.cancelQueries();
    client.clear();
    setCsrfToken(result.csrf_token);
    setSession(result);
    setError(null);
    navigate("/");
  }

  async function logout() {
    setLoggingOut(true);
    setError(null);
    try {
      await api("/auth/logout", { method: "POST", body: {} });
      await client.cancelQueries();
      client.clear();
      setCsrfToken(null);
      setSession(null);
      navigate("/");
    } catch (failure) {
      setError(
        failure instanceof Error ? failure : new Error("退出失败，请重试"),
      );
    } finally {
      setLoggingOut(false);
    }
  }

  if (loading)
    return (
      <div className="initial-loading">
        <Loading label="正在验证工作会话…" />
      </div>
    );

  if (!session)
    return (
      <main className="login-page">
        <section className="login-story">
          <a className="brand" href="/">
            <span className="brand-mark">
              <ShieldCheck size={26} />
            </span>
            <span>
              OpenKB<span className="brand-light"> / S4</span>
            </span>
          </a>
          <div>
            <div className="section-eyebrow">
              EVIDENCE FIRST. QUALITY ALWAYS.
            </div>
            <h1>
              独立判断，
              <br />
              可信交付。
            </h1>
            <p>
              连接原文、全量核实与质量观测，
              <br />
              让每个评测单元都有清晰的依据。
            </p>
            <div className="login-principles">
              <span>全量人工核实</span>
              <span>原始记录封存</span>
              <span>独立双人观测</span>
            </div>
          </div>
          <footer>OpenKB-Eval · Verification and Observation Workspace</footer>
        </section>
        <section className="login-card">
          <div className="section-eyebrow">WELCOME TO YOUR WORKSPACE</div>
          <h2>登录核实工作台</h2>
          <p className="muted">使用项目个人账号进入你的工作空间。</p>
          <ErrorNotice error={error} />
          <LoginForm onLogin={login} />
          <div className="login-security">
            <ShieldCheck size={16} />
            材料按角色与作业阶段授权
          </div>
        </section>
      </main>
    );

  const user = session.user;
  const has = (...roles: Role[]) =>
    user.roles.some((role) => roles.includes(role));
  const guard = (roles: Role[], node: ReactNode) =>
    has(...roles) ? (
      node
    ) : (
      <Empty
        title="此账号无权访问该页面"
        description="请使用导航中属于当前角色的工作入口。"
      />
    );

  return (
    <div className="app-shell" key={user.id}>
      <aside className="sidebar">
        <NavLink to="/" className="brand">
          <span className="brand-mark">
            <ShieldCheck size={25} />
          </span>
          <span>
            OpenKB<span className="brand-light"> / S4</span>
          </span>
        </NavLink>
        <div className="workspace-label">
          人工核实与质量观测 <span>v1.3</span>
        </div>
        <nav aria-label="主导航">
          {navigation
            .filter(
              (item) =>
                !item.roles.length ||
                user.roles.some((role) => item.roles.includes(role)),
            )
            .map((item) => (
              <NavLink
                end={item.to === "/"}
                className={({ isActive }) =>
                  `nav-item ${isActive ? "active" : ""}`
                }
                to={item.to}
                key={item.to}
              >
                <item.icon size={19} strokeWidth={1.6} />
                <span>{item.label}</span>
              </NavLink>
            ))}
        </nav>
        <div className="sidebar-note">
          <span className="status-dot" />
          <strong>独立 S4 系统</strong>
          <p>保留每次判断的原始依据</p>
        </div>
      </aside>
      <div className="main-layout">
        <header className="topbar">
          <div className="breadcrumb">
            评测作业 <span>/</span> <strong>S4 人工核实与质量观测</strong>
          </div>
          <div className="user-menu">
            <div className="user-avatar">{user.display_name.slice(0, 1)}</div>
            <div>
              <strong>{user.display_name}</strong>
              <span>
                {user.roles.map((role) => roleNames[role]).join(" · ")}
              </span>
            </div>
            <button
              className="icon-button"
              aria-label="退出登录"
              onClick={() => void logout()}
              disabled={loggingOut}
            >
              <LogOut size={19} />
            </button>
          </div>
        </header>
        <main id="main-content" className="main-content">
          <ErrorNotice error={error} />
          {legacy && <p className="notice warm">历史只读：此处保留旧字段、原始封存与旧规则的记录。新任务请使用v1.3核实与观测入口。</p>}
          <fieldset className="legacy-readonly" disabled={legacy}>
          <Routes>
            <Route path="/" element={<V13Overview user={user} />} />
            <Route path="/legacy" element={<Dashboard user={user} />} />
            <Route path="/v13/imports" element={guard(["lead", "auditor"], <V13Imports canWrite={has("lead")} />)} />
            <Route path="/v13/imports/:id" element={guard(["lead", "auditor"], <V13ImportDetail canWrite={has("lead")} />)} />
            <Route path="/v13/batches" element={guard(["lead", "auditor"], <V13Batches />)} />
            <Route path="/v13/batches/:id" element={guard(["lead", "auditor"], <V13BatchDetail canWrite={has("lead")} />)} />
            <Route path="/v13/tasks" element={guard(["annotator"], <V13Tasks />)} />
            <Route path="/v13/tasks/:id" element={guard(["annotator"], <V13TaskPage />)} />
            <Route path="/v13/handoffs" element={guard(["lead", "auditor"], <V13Handoffs canWrite={has("lead")} />)} />
            <Route path="/v13/governance" element={guard(["lead", "auditor", "annotator", "verifier", "arbitrator"], <V13Governance user={user} />)} />
            <Route path="/v13/profiles" element={<V13Profiles />} />
            <Route path="/users" element={guard(["admin"], <UsersPage />)} />
            <Route path="/profiles" element={<ProfilesPage />} />
            <Route
              path="/imports"
              element={guard(
                ["lead", "auditor"],
                <ImportsPage canWrite={has("lead")} />,
              )}
            />
            <Route
              path="/batches"
              element={guard(
                ["lead", "auditor", "arbitrator"],
                <BatchesPage canWrite={has("lead")} />,
              )}
            />
            <Route
              path="/batches/:id"
              element={guard(
                ["lead", "auditor", "arbitrator"],
                <BatchPage canWrite={has("lead")} />,
              )}
            />
            <Route
              path="/tasks"
              element={guard(["annotator"], <TasksPage />)}
            />
            <Route
              path="/tasks/:id"
              element={guard(["annotator"], <TaskPage />)}
            />
            <Route
              path="/quality"
              element={guard(
                ["lead", "auditor", "arbitrator"],
                <QualityPage />,
              )}
            />
            <Route
              path="/arbitrations"
              element={guard(
                ["lead", "auditor", "arbitrator"],
                <ArbitrationPage user={user} />,
              )}
            />
            <Route
              path="/handoffs"
              element={guard(
                ["lead", "auditor"],
                <HandoffsPage canWrite={has("lead")} />,
              )}
            />
            <Route
              path="/handoffs/:id"
              element={guard(["lead", "auditor"], <HandoffPage />)}
            />
            <Route path="/audit" element={guard(["auditor"], <AuditPage />)} />
            <Route
              path="/governance"
              element={guard(
                ["lead", "auditor", "verifier"],
                <GovernancePage verifierOnly={!has("lead", "auditor")} />,
              )}
            />
            <Route path="/notifications" element={<NotificationsPage />} />
            <Route path="/health" element={<HealthPage />} />
            <Route
              path="*"
              element={
                <Empty title="页面不存在" description="请选择左侧工作入口。" />
              }
            />
          </Routes>
          </fieldset>
          <footer className="page-footer">
            <span>OpenKB-Eval / S4</span>
            <span>服务端 UTC · 界面 Asia/Shanghai</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
