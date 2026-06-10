import pytest

from app.services.job_service import JobService


def test_job_save_keeps_existing_state_when_replace_fails(tmp_path, monkeypatch) -> None:
    service = JobService(tmp_path / "jobs")
    job = service.create_job(["drawing.pdf"])
    service.update(job.job_id, status="running", stage="flow_generating", progress=20)

    def fail_replace(source, target):
        raise OSError("replace failed")

    monkeypatch.setattr("app.services.job_service.os.replace", fail_replace)
    with pytest.raises(OSError):
        service.update(job.job_id, progress=40)

    stored = service.get(job.job_id)
    assert stored.status == "running"
    assert stored.stage == "flow_generating"
    assert stored.progress == 20
