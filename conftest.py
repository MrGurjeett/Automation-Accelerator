"""Root pytest configuration.

This repo contains a mix of:
- local/unit-style tests (e.g. security utilities)
- integration tests that require a reachable UI/API environment

To keep `pytest` runnable out-of-the-box, UI/API tests are skipped unless
explicitly enabled.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from utils.config_loader import get_config


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-ui",
        action="store_true",
        default=False,
        help="Run UI tests (requires a live BASE_URL and usually credentials).",
    )
    parser.addoption(
        "--run-api",
        action="store_true",
        default=False,
        help="Run API tests (requires a live API_URL or configured api_url).",
    )
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run E2E tests (generated flows; requires stable target environment).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_ui = bool(config.getoption("--run-ui")) or _truthy_env("RUN_UI_TESTS")
    run_api = bool(config.getoption("--run-api")) or _truthy_env("RUN_API_TESTS")
    run_e2e = bool(config.getoption("--run-e2e")) or _truthy_env("RUN_E2E_TESTS")

    for item in items:
        if item.get_closest_marker("ui") and not run_ui:
            item.add_marker(
                pytest.mark.skip(
                    reason="UI tests are disabled by default. Use --run-ui or RUN_UI_TESTS=1 (and set BASE_URL)."
                )
            )
        if item.get_closest_marker("api") and not run_api:
            item.add_marker(
                pytest.mark.skip(
                    reason="API tests are disabled by default. Use --run-api or RUN_API_TESTS=1 (and set API_URL)."
                )
            )
        if item.get_closest_marker("e2e") and not run_e2e:
            item.add_marker(
                pytest.mark.skip(
                    reason="E2E tests are disabled by default. Use --run-e2e or RUN_E2E_TESTS=1."
                )
            )


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for UI tests.

    Resolution order:
    1) env var BASE_URL
    2) config/config.yaml environments[environment].base_url

    Note: many repos default this to example.com; UI tests are skipped unless enabled.
    """
    env = os.environ.get("BASE_URL")
    if env and env.strip():
        return env.strip().rstrip("/")

    cfg = get_config()
    env_cfg: dict[str, Any] = cfg.get_environment_config()
    url = str(env_cfg.get("base_url", "")).strip()
    return url.rstrip("/")
