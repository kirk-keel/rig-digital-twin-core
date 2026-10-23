"""Portfolio compliance and configuration verification tests."""

import json
import os
import subprocess
import pytest


def test_required_directories_exist():
    """Verify that all standard portfolio directories exist."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    required_dirs = ["src", "tests", "configs", "docker", "docs"]
    for d in required_dirs:
        dir_path = os.path.join(base_dir, d)
        assert os.path.isdir(dir_path), f"Required directory '{d}' is missing from {base_dir}"


def test_required_config_files_exist():
    """Verify that standard deployment and configuration files exist."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    required_files = [
        ".env.example",
        ".gitignore",
        "Dockerfile",
        "docker-compose.yml",
        os.path.join("configs", "twin_config.yaml"),
        os.path.join("configs", "rig_sample.json"),
        os.path.join("configs", "logging.yaml"),
        os.path.join("docker", "Dockerfile"),
        os.path.join("docker", "entrypoint.sh"),
        os.path.join("docs", "architecture.md"),
        os.path.join("docs", "physics_formulation.md"),
        os.path.join("docs", "api_reference.md"),
        os.path.join("docs", "deployment.md"),
    ]
    for f in required_files:
        file_path = os.path.join(base_dir, f)
        assert os.path.isfile(file_path), f"Required file '{f}' is missing from {base_dir}"


def test_env_example_contents():
    """Ensure .env.example contains necessary operational keys."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(base_dir, ".env.example")
    with open(env_path, "r") as f:
        content = f.read()
    
    assert "DATABASE_URL" in content
    assert "SERVER_PORT" in content
    assert "WITS0_PORT" in content
    assert "POSTGRES_USER" in content


def test_rig_sample_json_validity():
    """Verify that sample rig JSON is valid JSON and contains required keys."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sample_path = os.path.join(base_dir, "configs", "rig_sample.json")
    with open(sample_path, "r") as f:
        data = json.load(f)
    
    assert data["well_id"] == "DEEPWATER-NAVI-01"
    assert "geometry" in data
    assert "drillstring" in data
    assert "bit" in data
    assert "mud" in data
    assert "geopressure" in data


def test_cli_subcommands_registered():
    """Verify that rig-twin CLI subcommands are available and functional."""
    from rig_twin.cli import build_parser

    parser = build_parser()
    # Check that main subcommands are present in choices
    subparsers_actions = [
        action for action in parser._actions 
        if action.dest == "subcommand"
    ]
    assert len(subparsers_actions) == 1
    subcommands = list(subparsers_actions[0].choices.keys())
    
    expected = [
        "serve",
        "sim",
        "kill-sheet",
        "trajectory",
        "geopressure",
        "wits0-server",
        "vibrations",
        "waterhammer",
        "what-if"
    ]
    for cmd in expected:
        assert cmd in subcommands, f"Subcommand '{cmd}' not found in CLI"
