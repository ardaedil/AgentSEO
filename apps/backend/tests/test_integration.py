from pathlib import Path

ROOT = Path(__file__).parents[3]


def create_billing_project(client):
    project = client.post(
        "/api/projects", json={"name": "Billing demo", "sandbox_domain": "billing"}
    )
    assert project.status_code == 201
    project_id = project.json()["id"]
    with (ROOT / "examples/billing/openapi.yaml").open("rb") as handle:
        upload = client.post(
            f"/api/projects/{project_id}/specs",
            files={"file": ("billing.yaml", handle, "application/yaml")},
        )
    assert upload.status_code == 200, upload.text
    return project_id, upload.json()


def test_upload_generate_reset_execute_evaluate_and_report(client):
    project_id, tools = create_billing_project(client)
    assert len(tools) >= 9
    tasks = client.post(f"/api/projects/{project_id}/tasks/generate")
    assert tasks.status_code == 200
    assert len(tasks.json()) >= 20
    run_response = client.post(
        f"/api/projects/{project_id}/benchmark-runs",
        json={
            "models": ["mock:reliable"],
            "max_iterations": 12,
            "max_tool_calls": 10,
            "timeout_seconds": 30,
        },
    )
    assert run_response.status_code == 200, run_response.text
    run = run_response.json()[0]
    assert run["status"] == "COMPLETED"
    assert run["synthetic"] is True
    assert run["aggregate_metrics"]["task_count"] == len(tasks.json())
    details = client.get(f"/api/benchmark-runs/{run['id']}/task-runs").json()
    assert details
    assert all(item["trace_events"] for item in details)
    assert any(
        event["event_type"] == "TOOL_CALLED" for item in details for event in item["trace_events"]
    )
    report = client.get(f"/api/projects/{project_id}/report")
    assert report.status_code == 200
    assert report.json()["notice"] == "Synthetic Demo Results"
    assert report.json()["comparison"][0]["experimental"] is True


def test_fallible_mock_produces_inspectable_safety_failure(client):
    project_id, _ = create_billing_project(client)
    tasks = client.post(f"/api/projects/{project_id}/tasks/generate").json()
    demo_task = next(task for task in tasks if task["title"] == "Cancel John's subscription safely")
    response = client.post(
        f"/api/projects/{project_id}/benchmark-runs",
        json={"models": ["mock:fallible"], "task_ids": [demo_task["id"]]},
    )
    assert response.status_code == 200
    task_runs = client.get(f"/api/benchmark-runs/{response.json()[0]['id']}/task-runs").json()
    assert task_runs[0]["success"] is False
    assert task_runs[0]["failure_category"] == "DESTRUCTIVE_ACTION_ERROR"
    detail = client.get(f"/api/task-runs/{task_runs[0]['id']}").json()
    assert any(event["event_type"] == "TOOL_CALLED" for event in detail["trace_events"])


def test_upload_limit_and_openapi_validation(client):
    project_id = client.post("/api/projects", json={"name": "Invalid"}).json()["id"]
    invalid = client.post(
        f"/api/projects/{project_id}/specs",
        files={"file": ("swagger.yaml", b"swagger: '2.0'\npaths: {}", "application/yaml")},
    )
    assert invalid.status_code == 422
