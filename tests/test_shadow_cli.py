from __future__ import annotations

import json
import os
import subprocess
import sys


def _env(tmp_path):
    env = os.environ.copy()
    env["DATABASE_PATH"] = str(tmp_path / "shadow_cli.db")
    return env


def test_shadow_cli_lifecycle_requires_manual_activation_confirmation(tmp_path):
    create = subprocess.run(
        [sys.executable, "-m", "football_agents.cli", "create-shadow-config", "--name", "cli-shadow"],
        cwd=".",
        env=_env(tmp_path),
        text=True,
        capture_output=True,
        check=True,
    )
    version = json.loads(create.stdout)
    config_version_id = version["config_version_id"]
    assert version["status"] == "DRAFT"

    start = subprocess.run(
        [sys.executable, "-m", "football_agents.cli", "start-shadow-validation", config_version_id],
        cwd=".",
        env=_env(tmp_path),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(start.stdout)["status"] == "SHADOW_RUNNING"

    metrics = subprocess.run(
        [sys.executable, "-m", "football_agents.cli", "shadow-metrics", config_version_id],
        cwd=".",
        env=_env(tmp_path),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(metrics.stdout)["config_version_id"] == config_version_id

    activation = subprocess.run(
        [sys.executable, "-m", "football_agents.cli", "activate-filter-only", config_version_id],
        cwd=".",
        env=_env(tmp_path),
        text=True,
        capture_output=True,
    )
    assert activation.returncode != 0
    assert "requires --confirm" in (activation.stderr + activation.stdout)
