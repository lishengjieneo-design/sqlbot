#!/usr/bin/env python3
"""Deploy to ECS test env (8000) from Windows via paramiko (no rsync/pexpect)."""

from __future__ import annotations

import os
import sys
import tarfile
import tempfile
from pathlib import Path

import paramiko

HOST = os.environ.get("DEPLOY_HOST", "47.83.2.158")
USER = os.environ.get("DEPLOY_USER", "root")
PASSWORD = os.environ.get("DEPLOY_PASSWORD", "")
REMOTE_DIR = os.environ.get("DEPLOY_REMOTE_DIR", "/opt/sqlbot_dev")
LOCAL_DIR = Path(os.environ.get("DEPLOY_LOCAL_DIR", Path(__file__).resolve().parent.parent))

TAR_MEMBERS = [
    "backend",
    "frontend/dist",
    "Dockerfile.ecs",
    "docker-compose.ecs-test.yaml",
]

EXCLUDE_DIRS = {"__pycache__", ".venv", "node_modules", ".git"}
EXCLUDE_SUFFIXES = {".pyc"}


def _should_add(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDE_DIRS:
        return False
    if path.suffix in EXCLUDE_SUFFIXES:
        return False
    return True


def build_tarball(tar_path: Path) -> None:
    with tarfile.open(tar_path, "w:gz") as tar:
        for member in TAR_MEMBERS:
            src = LOCAL_DIR / member
            if not src.exists():
                raise FileNotFoundError(f"Missing deploy artifact: {src}")
            if src.is_file():
                tar.add(src, arcname=member)
                continue
            for file in src.rglob("*"):
                if not file.is_file() or not _should_add(file.relative_to(src)):
                    continue
                arcname = Path(member) / file.relative_to(src)
                tar.add(file, arcname=str(arcname).replace("\\", "/"))


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 7200) -> str:
    print(f">>> {cmd[:120]}...")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out:
        print(out[-4000:] if len(out) > 4000 else out)
    if code != 0:
        print(err[-2000:] if err else "", file=sys.stderr)
        raise RuntimeError(f"Command failed ({code}): {cmd[:80]}")
    return out


def main() -> None:
    if not PASSWORD:
        print("Set DEPLOY_PASSWORD env var", file=sys.stderr)
        sys.exit(1)

    dist = LOCAL_DIR / "frontend" / "dist"
    if not dist.is_dir():
        print("Run: cd frontend && npm run build", file=sys.stderr)
        sys.exit(1)

    with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as tmp:
        tar_path = Path(tmp.name)
    try:
        print("=== Pack deploy tarball ===")
        build_tarball(tar_path)
        print(f"Created {tar_path} ({tar_path.stat().st_size // 1024} KB)")

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(HOST, username=USER, password=PASSWORD, timeout=30)

        print("=== Pre-check ===")
        run(client, "docker ps --format '{{.Names}} {{.Ports}}' | grep -E 'sqlbot|8000|8004' || true")

        remote_tar = "/tmp/sqlbot-deploy-win.tgz"
        print("=== Upload ===")
        sftp = client.open_sftp()
        sftp.put(str(tar_path), remote_tar)
        sftp.close()

        print("=== Extract (preserve data/) ===")
        run(
            client,
            f"cd {REMOTE_DIR} && tar xzf {remote_tar} && "
            f"cp -f docker-compose.ecs-test.yaml docker-compose.yaml && rm -f {remote_tar}",
        )

        print("=== Build image sqlbot-local:ecs ===")
        run(
            client,
            f"cd {REMOTE_DIR} && docker build -f Dockerfile.ecs -t sqlbot-local:ecs . 2>&1 | tail -40",
            timeout=7200,
        )

        print("=== Recreate sqlbot_dev only ===")
        run(
            client,
            f"cd {REMOTE_DIR} && docker-compose -p sqlbotdev up -d --force-recreate --no-deps sqlbot",
            timeout=600,
        )

        print("=== Post-check ===")
        run(client, "docker ps --format '{{.Names}} {{.Status}} {{.Ports}}' | grep sqlbot || true")
        run(
            client,
            "curl -sS -m 10 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ && echo",
        )
        client.close()
        print("Done.")
    finally:
        tar_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
