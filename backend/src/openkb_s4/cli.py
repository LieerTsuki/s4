"""Interactive first-administrator bootstrap without shared credentials."""
import argparse
import asyncio
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select, text

from .config import get_settings
from .db import make_sessions
from .models import User
from .security import hash_password


async def bootstrap(username: str, display_name: str, person_id: str, password: str) -> None:
    """Create the first administrator only; later users use authenticated API."""
    if len(password) < 12:
        raise ValueError("管理员密码至少12位")
    engine, factory = make_sessions(get_settings().database_url)
    try:
        async with factory() as db, db.begin():
            # Row locks cannot protect the absence of the first user.
            await db.execute(text("SELECT pg_advisory_xact_lock(64341001)"))
            if await db.scalar(select(User.id).limit(1)):
                raise ValueError("已有账号，禁止重复bootstrap；请用管理员账号管理用户")
            db.add(User(username=username, display_name=display_name, person_id=person_id,
                        roles=["admin"], password_hash=hash_password(password)))
        print("管理员创建成功；请登录后创建独立运营与标注账号。")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="S4 account administration")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("bootstrap")
    command.add_argument("--username", required=True)
    command.add_argument("--display-name", required=True)
    command.add_argument("--person-id", required=True)
    for action in ("backup", "restore"):
        operation = commands.add_parser(action, help="受控本机管理：一致性备份或隔离恢复验证")
        operation.add_argument("--env-file", type=Path)
        operation.add_argument("--container")
        operation.add_argument("--database")
        operation.add_argument("--data-dir", type=Path)
        operation.add_argument("--api-container")
        operation.add_argument("--output", type=Path)
        operation.add_argument("--backup", type=Path, required=action == "restore")
    args = parser.parse_args()
    if args.command in {"backup", "restore"}:
        script = Path(__file__).resolve().parents[3] / "scripts" / "backup_restore.py"
        if not script.is_file():
            parser.error("备份/恢复仅支持受控本机管理环境，需要完整S4运维目录；API容器不提供此入口")
        if not shutil.which("docker"):
            parser.error("受控本机备份/恢复需要已安装并配置的Docker CLI")
        arguments = [sys.executable, str(script), args.command]
        for option in ("env_file", "container", "database", "data_dir", "api_container", "output", "backup"):
            value = getattr(args, option)
            if value is not None:
                arguments.extend(["--" + option.replace("_", "-"), str(value)])
        try:
            subprocess.run(arguments, check=True)
        except subprocess.CalledProcessError:
            raise SystemExit("本机备份/恢复未完成；请核对保留的运维记录与安全错误类别") from None
        return
    password = os.environ.get("S4_BOOTSTRAP_PASSWORD") or getpass.getpass("管理员密码（至少12位）：")
    asyncio.run(bootstrap(args.username, args.display_name, args.person_id, password))


if __name__ == "__main__":
    main()
