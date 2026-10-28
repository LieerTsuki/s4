import { useState } from "react";
import { ArrowRight, LockKeyhole, UserRound } from "lucide-react";

export function LoginForm({
  onLogin,
}: {
  onLogin: (username: string, password: string) => Promise<void>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  return (
    <form
      className="login-form"
      onSubmit={async (event) => {
        event.preventDefault();
        setError("");
        setPending(true);
        try {
          await onLogin(username.trim(), password);
          setPassword("");
        } catch (failure) {
          setError(
            failure instanceof Error ? failure.message : "登录失败，请重试。",
          );
        } finally {
          setPending(false);
        }
      }}
    >
      <label htmlFor="username">账号</label>
      <div className="input-icon">
        <UserRound size={18} />
        <input
          id="username"
          name="username"
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          required
          maxLength={80}
          placeholder="输入你的工作账号"
        />
      </div>
      <label htmlFor="password">密码</label>
      <div className="input-icon">
        <LockKeyhole size={18} />
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
          maxLength={200}
          placeholder="输入密码"
        />
      </div>
      {error && (
        <div className="notice danger" role="alert">
          {error}
        </div>
      )}
      <button
        className="button primary login-submit"
        disabled={pending}
        type="submit"
      >
        {pending ? "正在验证身份…" : "登录工作台"}
        <ArrowRight size={18} />
      </button>
      <p className="muted login-help">
        账号由项目管理员创建。如需重置密码，请联系管理员。
      </p>
    </form>
  );
}
