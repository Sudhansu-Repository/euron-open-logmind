"""Command line: ``logmind <command>``."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from logmind.core.config import get_settings


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "logmind.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        workers=args.workers,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        timeout_keep_alive=settings.http_keep_alive_s,
        access_log=False,
        log_config=None,
        timeout_graceful_shutdown=30,
    )


def _migrate(_: argparse.Namespace) -> None:
    from logmind.core.clickhouse import ClickHouse
    from logmind.core.clickhouse_schema import apply
    from logmind.migrations.runner import upgrade

    settings = get_settings()
    upgrade(settings.database_url)
    print("postgres migrations applied")

    async def clickhouse() -> int:
        ch = ClickHouse(settings.clickhouse_url, timeout_s=settings.clickhouse_timeout_s)
        try:
            for attempt in range(30):
                if await ch.ping():
                    break
                await asyncio.sleep(min(1 + attempt, 5))
            return await apply(ch)
        finally:
            await ch.close()

    ran = asyncio.run(clickhouse())
    print(f"clickhouse migrations applied ({ran} new)")


def _worker(_: argparse.Namespace) -> None:
    from logmind.worker import run

    run()


async def _create_org_owner(org_name: str, email: str, name: str, password: str) -> None:
    from sqlalchemy import func, select

    from logmind.auth.models import User
    from logmind.core.db import Database
    from logmind.core.security import hash_password, password_problems
    from logmind.core.text import slugify
    from logmind.orgs.models import Organization

    if problems := password_problems(password):
        sys.exit("password needs " + ", ".join(problems))
    db = Database(get_settings().database_url, pool_size=1, max_overflow=0)
    try:
        async with db.sessionmaker() as session:
            existing = await session.scalar(
                select(User).where(func.lower(User.email) == email.lower())
            )
            if existing:
                existing.role = "owner"
                existing.password_hash = hash_password(password)
                existing.disabled = False
                existing.session_version += 1
                print(f"updated {email} (owner)")
            else:
                org = Organization(name=org_name, slug=slugify(org_name))
                session.add(org)
                await session.flush()
                session.add(
                    User(
                        org_id=org.id,
                        email=email.lower(),
                        name=name,
                        role="owner",
                        password_hash=hash_password(password),
                    )
                )
                print(f"created org {org_name!r} and owner {email}")
            await session.commit()
    finally:
        await db.dispose()


def _owner(args: argparse.Namespace) -> None:
    # The env var and subcommand name are LOGMIND_ADMIN_PASSWORD / create-admin to
    # match the infra module's Terraform secrets and Makefile (make admin, make aws-admin);
    # the person it creates is still called "owner" internally (the highest role).
    password = os.environ.get("LOGMIND_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    asyncio.run(_create_org_owner(args.org, args.email, args.name, password))


def _seed(args: argparse.Namespace) -> None:
    from logmind.demo.seed import run

    asyncio.run(run(api_url=args.api_url, mock_url=args.mock_ai_url))


def _openapi(_: argparse.Namespace) -> None:
    from logmind.openapi import spec, to_yaml

    sys.stdout.write(to_yaml(spec()))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="logmind", description="Euron Open LogMind")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="run the API")
    p.add_argument("--host", default="0.0.0.0")  # noqa: S104 the container must listen on all interfaces
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "6030")))
    p.add_argument("--workers", type=int, default=int(os.environ.get("WEB_CONCURRENCY", "2")))
    p.set_defaults(fn=_serve)

    sub.add_parser("migrate", help="apply database migrations").set_defaults(fn=_migrate)
    sub.add_parser("openapi", help="print the OpenAPI document as YAML").set_defaults(fn=_openapi)
    sub.add_parser(
        "worker",
        help="run the background worker (investigations, alert evaluation, retention)",
    ).set_defaults(fn=_worker)

    p = sub.add_parser(
        "create-admin", help="create an organization and its owner, or reset an owner's password"
    )
    p.add_argument("--org", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="Owner")
    p.set_defaults(fn=_owner)

    p = sub.add_parser("seed-demo", help="load the demo organization, projects and logs")
    p.add_argument("--api-url", default=os.environ.get("LOGMIND_API_URL", "http://localhost:6030"))
    p.add_argument(
        "--mock-ai-url",
        default=os.environ.get("LOGMIND_MOCK_AI_URL", "http://localhost:6050"),
    )
    p.set_defaults(fn=_seed)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
