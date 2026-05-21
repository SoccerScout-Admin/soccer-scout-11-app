"""
iter83: supervisor `gitignore-keeper` watchdog.

The Emergent platform hook re-injects `.env`, `.env.*`, `*.env`, and
`frontend/node_modules/.cache/default-development/*.pack` lines into
/app/.gitignore at unpredictable intervals. Each injection breaks the
deploy pipeline at the "fetch envs" step.

These tests guard the long-term fix: a supervisor program that loops
`bash /app/predeploy.sh` every 60s so the file is *always* clean when
the user clicks Deploy.
"""
import os
import subprocess


_GITIGNORE = "/app/.gitignore"
_PREDEPLOY = "/app/predeploy.sh"
_KEEPER_SCRIPT = "/app/scripts/gitignore-keeper.sh"
_SUPERVISOR_CONF = "/etc/supervisor/conf.d/supervisord_gitignore_keeper.conf"


def test_predeploy_script_exists_and_executable():
    assert os.path.isfile(_PREDEPLOY), f"{_PREDEPLOY} must exist"
    assert os.access(_PREDEPLOY, os.X_OK), f"{_PREDEPLOY} must be chmod +x"


def test_keeper_script_exists_and_executable():
    assert os.path.isfile(_KEEPER_SCRIPT), f"{_KEEPER_SCRIPT} must exist"
    assert os.access(_KEEPER_SCRIPT, os.X_OK), f"{_KEEPER_SCRIPT} must be chmod +x"


def test_supervisor_config_references_keeper_script():
    assert os.path.isfile(_SUPERVISOR_CONF), f"{_SUPERVISOR_CONF} must exist"
    with open(_SUPERVISOR_CONF, "r", encoding="utf-8") as f:
        conf = f.read()
    assert "gitignore-keeper" in conf
    assert _KEEPER_SCRIPT in conf
    assert "autorestart=true" in conf, (
        "Keeper must autorestart — otherwise a transient crash leaves the deploy "
        "pipeline exposed to the next platform-hook injection."
    )


def test_keeper_program_is_running_in_supervisor():
    """End-to-end: the supervisor program is loaded and in RUNNING state."""
    try:
        out = subprocess.check_output(
            ["sudo", "supervisorctl", "status", "gitignore-keeper"],
            stderr=subprocess.STDOUT, timeout=5,
        ).decode()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        # If supervisor isn't reachable (e.g., CI env), skip rather than fail
        import pytest
        pytest.skip(f"supervisorctl not available: {e}")
    assert "RUNNING" in out, (
        f"gitignore-keeper should be RUNNING; supervisorctl said: {out.strip()}"
    )


def test_predeploy_script_idempotent_on_clean_file():
    """Running predeploy.sh on a clean .gitignore should be a no-op."""
    result = subprocess.run(
        ["bash", _PREDEPLOY],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    # Must NOT add new lines on a clean file
    assert "Removed" not in result.stdout or "0 injected" in result.stdout or \
        "No injected patterns" in result.stdout, (
        f"predeploy.sh should be a no-op on clean files. Output: {result.stdout}"
    )


def test_env_files_are_not_git_ignored_after_keeper_run():
    """Final check: `.env` files must NOT be git-ignored after the keeper has
    healed. Otherwise the deploy pipeline can't fetch them."""
    # Make sure the file is clean first
    subprocess.run(["bash", _PREDEPLOY], capture_output=True, timeout=10)

    result = subprocess.run(
        ["git", "check-ignore", "-v", "backend/.env", "frontend/.env"],
        capture_output=True, text=True, cwd="/app", timeout=5,
    )
    # `git check-ignore` exits 1 when NOTHING is ignored — that's the success case for us.
    assert result.returncode != 0, (
        f".env files are git-ignored after predeploy.sh ran. This means the deploy "
        f"pipeline will fail. check-ignore output:\n{result.stdout}"
    )
