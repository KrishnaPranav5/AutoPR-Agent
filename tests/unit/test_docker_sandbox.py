"""Unit tests for DockerSandbox interface, metadata, and container isolation contract."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest

from auto_pr.sandbox.docker import DockerSandbox, is_docker_available
from auto_pr.sandbox.models import DockerUnavailableError


def test_docker_sandbox_metadata(tmp_path: Path) -> None:
    """Verify DockerSandbox reports container process isolation metadata."""
    run_id = uuid.uuid4()
    sandbox = DockerSandbox(
        run_id=run_id,
        repo_path=tmp_path,
        image_name="python:3.11-slim",
        memory_limit="2g",
        cpu_limit="2.0",
        network_mode="none",
    )

    meta = sandbox.get_metadata()
    assert meta["sandbox_type"] == "docker"
    assert meta["isolation_level"] == "container_process_isolation"
    assert meta["image"] == "python:3.11-slim"
    assert meta["memory_limit"] == "2g"
    assert meta["cpu_limit"] == "2.0"
    assert meta["network"] == "none"


@pytest.mark.asyncio
async def test_docker_sandbox_raises_when_daemon_unavailable(tmp_path: Path) -> None:
    """Verify that DockerSandbox raises DockerUnavailableError when daemon is not responsive."""
    run_id = uuid.uuid4()
    sandbox = DockerSandbox(run_id=run_id, repo_path=tmp_path)

    # Force is_docker_available to return False
    with patch("auto_pr.sandbox.docker.is_docker_available", return_value=False):
        with pytest.raises(DockerUnavailableError) as exc_info:
            await sandbox.create()
        assert "Docker daemon is not responsive" in str(exc_info.value)


@pytest.mark.asyncio
async def test_docker_sandbox_command_construction(tmp_path: Path) -> None:
    """Verify docker run arguments (memory, cpu, network none, mounts) are constructed properly."""
    run_id = uuid.uuid4()
    sandbox = DockerSandbox(run_id=run_id, repo_path=tmp_path)
    sandbox._is_prepared = True
    sandbox.sandbox_dir = tmp_path

    # Mock subprocess.Popen
    mock_process = MagicMock()
    mock_process.communicate.return_value = ("stdout_msg", "")
    mock_process.returncode = 0

    with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
        result = await sandbox.execute_command(["pytest", "tests/"])

        assert result.exit_code == 0
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]

        # Verify isolation flags passed to docker CLI
        assert "docker" == call_args[0]
        assert "run" == call_args[1]
        assert "--rm" in call_args
        assert "--memory=1g" in call_args
        assert "--cpus=1.0" in call_args
        assert "--network=none" in call_args
        assert "-v" in call_args
        assert "python:3.11-slim" in call_args
        assert "pytest" in call_args
