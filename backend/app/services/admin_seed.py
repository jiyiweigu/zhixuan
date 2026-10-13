"""管理端账号引导（tasks.md 8.1）。

与 C 端注册接口不同，管理端不开放自助注册——首个管理员由本脚本按环境变量创建，
避免「任何人都能注册管理员」这一越权入口。

用法：
    cd backend
    set ZHIXUAN_ADMIN_USERNAME=admin
    set ZHIXUAN_ADMIN_PASSWORD=<强口令>
    .venv/Scripts/python.exe -m app.services.admin_seed

行为：
- 用户名已存在：不修改口令，只提示（避免误覆盖线上口令）；
- 口令为空：拒绝执行并返回非零退出码；
- 幂等：重复执行结果一致。
"""

from __future__ import annotations

from app.core.config import settings
from app.services import admin_auth


def main() -> int:
    from app.db.session import SessionLocal

    username = settings.admin_username
    password = settings.admin_password

    if not password:
        print(
            "未提供管理员口令：请先设置环境变量 ZHIXUAN_ADMIN_PASSWORD 再执行本脚本。\n"
            "（口令留空时拒绝创建，避免落一个空口令的管理员账号。）"
        )
        return 2

    with SessionLocal() as db:
        admin, created = admin_auth.ensure_admin(db, username, password)

    if created:
        print(f"管理员已创建：username={admin.username} role={admin.role} admin_id={admin.id}")
    else:
        print(f"管理员已存在，未改动口令：username={admin.username} admin_id={admin.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
