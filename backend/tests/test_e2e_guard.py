"""The test-only user endpoint must be impossible to enable by accident in a normal run."""

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NORMAL_RUN_FILES = ["docker-compose.yml", "Dockerfile", ".env.example", "README.md"]


@pytest.mark.parametrize("name", NORMAL_RUN_FILES)
def test_tidy_e2e_is_not_in_any_file_a_normal_run_uses(name):
    assert "TIDY_E2E" not in (ROOT / name).read_text(encoding="utf-8"), f"{name} must not mention TIDY_E2E"


@pytest.mark.parametrize("script", sorted((ROOT / "scripts").glob("*.*")), ids=lambda p: p.name)
def test_the_start_and_stop_scripts_never_set_it(script):
    assert "TIDY_E2E" not in script.read_text(encoding="utf-8")


def test_your_own_env_file_does_not_set_it():
    env = ROOT / ".env"  # not in git; checked when it exists on this machine
    if env.exists():
        assert "TIDY_E2E" not in env.read_text(encoding="utf-8")


def test_only_the_test_override_file_sets_it():
    override = (ROOT / "docker-compose.e2e.yml").read_text(encoding="utf-8")
    assert 'TIDY_E2E: "1"' in override
    others = [p for p in ROOT.glob("docker-compose*.yml") if p.name != "docker-compose.e2e.yml"]
    assert others and all("TIDY_E2E" not in p.read_text(encoding="utf-8") for p in others)


def test_the_variable_is_not_set_in_the_process_running_these_tests():
    assert os.environ.get("TIDY_E2E") in (None, "")


def test_the_test_only_endpoint_is_404_for_every_method_in_a_normal_run(me):
    for method in ("get", "post", "put", "patch", "delete"):
        response = getattr(me, method)("/api/e2e/users")
        assert response.status_code == 404, method
    assert me.post("/api/e2e/users", json={"username": "someone", "today": "2026-11-08"}).status_code == 404
    assert not [path for path in me.get("/openapi.json").json()["paths"] if "e2e" in path]


def test_it_is_404_even_when_signed_out(client):
    assert client.post("/api/e2e/users", json={"username": "someone"}).status_code == 404


def test_any_unknown_api_path_is_a_json_404_not_a_405_or_a_web_page(me):
    for method in ("get", "post", "delete"):
        response = getattr(me, method)("/api/no/such/thing")
        assert response.status_code == 404 and response.json() == {"detail": "Not found"}
