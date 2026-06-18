#!/usr/bin/env python3
"""Deploy SQLBot source to ECS test env (sqlbot_dev on :8000) without touching POC (:8004/:8005)."""

import os
import sys
import pexpect

HOST = os.environ.get("DEPLOY_HOST", "47.83.2.158")
USER = os.environ.get("DEPLOY_USER", "root")
PASSWORD = os.environ.get("DEPLOY_PASSWORD", "")
REMOTE_DIR = os.environ.get("DEPLOY_REMOTE_DIR", "/opt/sqlbot_dev")
LOCAL_DIR = os.environ.get(
    "DEPLOY_LOCAL_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)

RSYNC_EXCLUDES = [
    "frontend/node_modules",
    "backend/.venv",
    "runtime-data",
    "data",
    ".git",
    "frontend/dist",
    ".cursor",
    "agent-transcripts",
]


def run_ssh(command: str, timeout: int = 7200) -> str:
    child = pexpect.spawn(
        f"ssh -o StrictHostKeyChecking=no {USER}@{HOST} {command!r}",
        timeout=timeout,
        encoding="utf-8",
    )
    i = child.expect(["password:", pexpect.EOF, pexpect.TIMEOUT])
    if i == 0:
        child.sendline(PASSWORD)
        child.expect(pexpect.EOF, timeout=timeout)
    output = child.before or ""
    if child.exitstatus not in (0, None):
        print(output, file=sys.stderr)
        raise RuntimeError(f"SSH failed (exit {child.exitstatus}): {command[:120]}")
    return output


def run_rsync() -> None:
    excludes = " ".join(f"--exclude={x}" for x in RSYNC_EXCLUDES)
    # rsync via ssh; password via SSH_ASKPASS helper is awkward — use pexpect on rsync+e ssh
    cmd = (
        f"rsync -az {excludes} "
        f"-e 'ssh -o StrictHostKeyChecking=no' "
        f"{LOCAL_DIR}/ {USER}@{HOST}:{REMOTE_DIR}/"
    )
    child = pexpect.spawn(cmd, timeout=3600, encoding="utf-8", cwd=LOCAL_DIR)
    i = child.expect(["password:", pexpect.EOF, pexpect.TIMEOUT], timeout=120)
    if i == 0:
        child.sendline(PASSWORD)
    child.expect(pexpect.EOF, timeout=3600)
    print(child.before or "")
    if child.exitstatus not in (0, None):
        raise RuntimeError("rsync failed")


def main() -> None:
    if not PASSWORD:
        print("Set DEPLOY_PASSWORD env var", file=sys.stderr)
        sys.exit(1)

    print("=== Pre-check: containers ===")
    print(run_ssh("docker ps --format '{{.Names}} {{.Ports}}' | grep -E 'sqlbot|8000|8004'"))

    print("=== Backup compose file ===")
    run_ssh(
        f"cp -a {REMOTE_DIR}/docker-compose.yaml {REMOTE_DIR}/docker-compose.yaml.bak.$(date +%Y%m%d%H%M) 2>/dev/null; true"
    )

    print("=== Rsync source (excluding data volumes) ===")
    run_rsync()

    print("=== Patch compose for local build ===")
    patch = r"""
python3 << 'PY'
from pathlib import Path
p = Path("/opt/sqlbot_dev/docker-compose.yaml")
text = p.read_text()
if "build:" not in text:
    text = text.replace(
        "    image: dataease/sqlbot\n",
        "    build:\n      context: .\n      dockerfile: Dockerfile\n    image: sqlbot-dev:ecs\n",
        1,
    )
    p.write_text(text)
print("compose patched")
PY
"""
    print(run_ssh(patch))

    print("=== Build image (sqlbot_dev only) ===")
    build_cmd = (
        f"cd {REMOTE_DIR} && docker compose -p sqlbotdev build --progress=plain 2>&1 | tail -80"
    )
    print(run_ssh(build_cmd, timeout=7200))

    print("=== Recreate test container only ===")
    up_cmd = (
        f"cd {REMOTE_DIR} && docker compose -p sqlbotdev up -d --force-recreate --no-deps sqlbot 2>&1"
    )
    print(run_ssh(up_cmd, timeout=600))

    print("=== Post-check ===")
    print(run_ssh("docker ps --format '{{.Names}} {{.Status}} {{.Ports}}' | grep -E 'sqlbot'"))
    print(run_ssh("curl -sS -m 10 http://127.0.0.1:8000/api/v1/system/authentication/platform/status | head -c 300"))
    print("Done.")


if __name__ == "__main__":
    main()
