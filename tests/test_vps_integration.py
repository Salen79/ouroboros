"""VPS integration tests for Ouroboros v6.2.0.

Validates that the Colab→VPS migration is complete:
- .env loading, secrets, paths
- No residual Colab imports or paths
- Data directories, branch config
- VendorLens structure
- OpenRouter API key validity

Run: pytest tests/test_vps_integration.py -v
"""
import ast
import os
import pathlib
import re

import pytest
import requests

REPO = pathlib.Path(__file__).resolve().parent.parent
HOME = pathlib.Path.home()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_dotenv() -> dict[str, str]:
    """Parse .env the same way colab_launcher.py does."""
    env_path = REPO / ".env"
    result: dict[str, str] = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                result[k] = v
    return result


# ---------------------------------------------------------------------------
# a) .env loading — all required keys present
# ---------------------------------------------------------------------------

class TestEnvLoading:
    REQUIRED_KEYS = [
        "OPENROUTER_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TOTAL_BUDGET",
        "GITHUB_TOKEN",
    ]

    def test_env_file_exists(self):
        assert (REPO / ".env").is_file(), ".env file missing from repo root"

    @pytest.mark.parametrize("key", REQUIRED_KEYS)
    def test_required_key_present(self, key):
        env = _load_dotenv()
        assert key in env, f"{key} missing from .env"
        assert len(env[key]) > 0, f"{key} is empty in .env"


# ---------------------------------------------------------------------------
# b) Agent import
# ---------------------------------------------------------------------------

def test_agent_import():
    from ouroboros.agent import OuroborosAgent
    assert OuroborosAgent is not None


# ---------------------------------------------------------------------------
# c) Consciousness import
# ---------------------------------------------------------------------------

def test_consciousness_import():
    from ouroboros.consciousness import BackgroundConsciousness
    assert BackgroundConsciousness is not None


# ---------------------------------------------------------------------------
# d) Supervisor imports
# ---------------------------------------------------------------------------

SUPERVISOR_MODULES = [
    "supervisor.state",
    "supervisor.telegram",
    "supervisor.queue",
    "supervisor.workers",
    "supervisor.git_ops",
    "supervisor.events",
]

@pytest.mark.parametrize("module", SUPERVISOR_MODULES)
def test_supervisor_import(module):
    __import__(module)


# ---------------------------------------------------------------------------
# e) DRIVE_ROOT points to ~/ouroboros-data/, not /content/drive/
# ---------------------------------------------------------------------------

def test_drive_root_is_local():
    """Verify module-level DRIVE_ROOT defaults are VPS paths, not Colab."""
    colab_path = "/content/drive"
    files_to_check = [
        REPO / "supervisor" / "state.py",
        REPO / "supervisor" / "queue.py",
        REPO / "supervisor" / "workers.py",
        REPO / "supervisor" / "git_ops.py",
    ]
    for fpath in files_to_check:
        content = fpath.read_text()
        # Check that the Colab path does NOT appear as a default value
        # (it's ok if it appears in comments)
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert colab_path not in node.value, (
                    f"{fpath.name} still has Colab path '{node.value}'"
                )


# ---------------------------------------------------------------------------
# f) REPO_DIR points to ~/ouroboros/, not /content/ouroboros_repo
# ---------------------------------------------------------------------------

def test_repo_dir_is_local():
    """Verify REPO_DIR defaults are VPS paths, not Colab."""
    colab_path = "/content/ouroboros_repo"
    files_to_check = [
        REPO / "supervisor" / "workers.py",
        REPO / "supervisor" / "git_ops.py",
        REPO / "ouroboros" / "tools" / "evolution_stats.py",
    ]
    for fpath in files_to_check:
        content = fpath.read_text()
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert colab_path not in node.value, (
                    f"{fpath.name} still has Colab REPO_DIR '{node.value}'"
                )


# ---------------------------------------------------------------------------
# g) Branch is "main", not "ouroboros"
# ---------------------------------------------------------------------------

def test_branch_is_main():
    """colab_launcher.py must set BRANCH_DEV = 'main'."""
    content = (REPO / "colab_launcher.py").read_text()
    match = re.search(r'^BRANCH_DEV\s*=\s*["\'](.+?)["\']', content, re.MULTILINE)
    assert match, "BRANCH_DEV assignment not found in colab_launcher.py"
    assert match.group(1) == "main", f"BRANCH_DEV is '{match.group(1)}', expected 'main'"


# ---------------------------------------------------------------------------
# h) No active google.colab imports in any .py file
# ---------------------------------------------------------------------------

def test_no_colab_imports():
    """No .py file (except colab_bootstrap_shim.py) should have active Colab imports."""
    pattern = re.compile(r"^\s*from\s+google\.colab\s+import", re.MULTILINE)
    violations = []
    for pyfile in REPO.rglob("*.py"):
        # Skip the Colab-only shim and venvs
        rel = pyfile.relative_to(REPO)
        if "colab_bootstrap_shim" in str(rel):
            continue
        if "venv" in str(rel) or "site-packages" in str(rel):
            continue
        content = pyfile.read_text()
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.lstrip()
            # Skip comments
            if stripped.startswith("#"):
                continue
            if pattern.search(line):
                violations.append(f"{rel}:{i}: {line.strip()}")
    assert not violations, (
        "Active google.colab imports found:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# i) Data directories exist
# ---------------------------------------------------------------------------

DATA_ROOT = HOME / "ouroboros-data"
EXPECTED_SUBDIRS = ["state", "logs", "memory", "locks"]

def test_data_root_exists():
    assert DATA_ROOT.is_dir(), f"{DATA_ROOT} does not exist"

@pytest.mark.parametrize("subdir", EXPECTED_SUBDIRS)
def test_data_subdir_exists(subdir):
    path = DATA_ROOT / subdir
    assert path.is_dir(), f"{path} does not exist"


# ---------------------------------------------------------------------------
# j) VendorLens structure
# ---------------------------------------------------------------------------

VENDORLENS_ROOT = REPO / "company" / "vendor-lens"

def test_vendorlens_has_backend():
    assert (VENDORLENS_ROOT / "backend").is_dir()

def test_vendorlens_has_frontend():
    assert (VENDORLENS_ROOT / "frontend").is_dir()

def test_vendorlens_has_readme():
    assert (VENDORLENS_ROOT / "README.md").is_file()


# ---------------------------------------------------------------------------
# k) OpenRouter API key is valid
# ---------------------------------------------------------------------------

def test_openrouter_api_key_valid():
    """Call OpenRouter /auth/key endpoint and verify limit_remaining > 0."""
    env = _load_dotenv()
    api_key = env.get("OPENROUTER_API_KEY", "")
    assert api_key, "OPENROUTER_API_KEY not found in .env"

    resp = requests.get(
        "https://openrouter.ai/api/v1/auth/key",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    assert resp.status_code == 200, f"OpenRouter API returned {resp.status_code}: {resp.text}"
    data = resp.json().get("data", {})
    limit_remaining = data.get("limit_remaining")
    assert limit_remaining is not None, f"No limit_remaining in response: {data}"
    assert float(limit_remaining) > 0, (
        f"API key exhausted: limit_remaining={limit_remaining}"
    )
