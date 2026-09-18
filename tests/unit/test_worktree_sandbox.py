"""Unit tests for LocalWorktreeSandbox lifecycle, execution, and isolation boundaries."""

from pathlib import Path
import subprocess
import uuid
import pytest

from auto_pr.sandbox.worktree import LocalWorktreeSandbox
from auto_pr.sandbox.models import ProtectedBranchError


@pytest.fixture
def local_git_repo(tmp_path: Path) -> Path:
    """Initialize a clean local Git repository with an initial commit on 'main'."""
    repo_dir = tmp_path / "origin_repo"
    repo_dir.mkdir()

    # git init
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Runner"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_dir), check=True)

    # Initial file and commit
    readme = repo_dir / "README.md"
    readme.write_text("# Initial Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(repo_dir), check=True)

    return repo_dir


@pytest.mark.asyncio
async def test_worktree_creation_and_metadata(local_git_repo: Path) -> None:
    """Verify that a dedicated worktree is created on a non-protected branch."""
    run_id = uuid.uuid4()
    sandbox = LocalWorktreeSandbox(run_id=run_id, repo_path=local_git_repo)

    worktree_path = await sandbox.create(base_branch="main")
    assert worktree_path.is_dir()
    assert (worktree_path / "README.md").is_file()

    meta = sandbox.get_metadata()
    assert meta["sandbox_type"] == "worktree"
    assert meta["isolation_level"] == "source_control_isolation"
    assert "Not a container/process jail" in meta["description"]

    # Verify worktree list via git
    res = subprocess.run(["git", "worktree", "list"], cwd=str(local_git_repo), capture_output=True, text=True, check=True)
    assert str(worktree_path).replace("\\", "/") in res.stdout.replace("\\", "/")

    await sandbox.cleanup()


@pytest.mark.asyncio
async def test_protected_branch_prevention(local_git_repo: Path) -> None:
    """Verify that targeting protected branches (main, master, etc.) raises ProtectedBranchError."""
    run_id = uuid.uuid4()
    for protected in ("main", "master", "prod", "release"):
        sandbox = LocalWorktreeSandbox(run_id=run_id, repo_path=local_git_repo, branch_name=protected)
        with pytest.raises(ProtectedBranchError):
            await sandbox.create()


@pytest.mark.asyncio
async def test_stdout_stderr_and_exit_code_capture(local_git_repo: Path) -> None:
    """Verify that command execution accurately captures stdout, stderr, and exit codes."""
    run_id = uuid.uuid4()
    sandbox = LocalWorktreeSandbox(run_id=run_id, repo_path=local_git_repo)
    await sandbox.create()

    # Execute python writing to stdout and stderr with specific exit code
    py_cmd = [
        "python",
        "-c",
        "import sys; sys.stdout.write('hello_stdout'); sys.stderr.write('hello_stderr'); sys.exit(42)",
    ]
    result = await sandbox.execute_command(py_cmd)

    assert result.exit_code == 42
    assert "hello_stdout" in result.stdout
    assert "hello_stderr" in result.stderr
    assert not result.timed_out
    assert result.duration_ms >= 0

    await sandbox.cleanup()


@pytest.mark.asyncio
async def test_timeout_enforcement_and_process_termination(local_git_repo: Path) -> None:
    """Verify that commands exceeding timeout are terminated cleanly."""
    run_id = uuid.uuid4()
    sandbox = LocalWorktreeSandbox(run_id=run_id, repo_path=local_git_repo)
    await sandbox.create()

    # Run sleep command with 1s timeout
    py_sleep = ["python", "-c", "import time; time.sleep(10)"]
    result = await sandbox.execute_command(py_sleep, timeout_seconds=1)

    assert result.timed_out is True
    assert result.exit_code == -1

    await sandbox.cleanup()


@pytest.mark.asyncio
async def test_worktree_cleanup(local_git_repo: Path) -> None:
    """Verify that cleanup removes the worktree directory and branch."""
    run_id = uuid.uuid4()
    sandbox = LocalWorktreeSandbox(run_id=run_id, repo_path=local_git_repo)
    worktree_path = await sandbox.create()
    assert worktree_path.exists()

    await sandbox.cleanup()
    assert not worktree_path.exists()

    # Verify branch was deleted
    res = subprocess.run(["git", "branch"], cwd=str(local_git_repo), capture_output=True, text=True, check=True)
    assert sandbox.branch_name not in res.stdout
