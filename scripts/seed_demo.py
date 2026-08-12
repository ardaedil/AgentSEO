"""Seed a local database with the SaaS billing interface and deterministic task suite."""

from pathlib import Path

from agentseo.database import SessionLocal, create_schema
from agentseo.models import BenchmarkTask, InterfaceVersion, Project, ToolDefinition
from agentseo.openapi_parser import parse_openapi
from agentseo.task_generation import generate_template_tasks

ROOT = Path(__file__).parents[1]


def main() -> None:
    document, tools = parse_openapi((ROOT / "examples/billing/openapi.yaml").read_bytes())
    create_schema()
    with SessionLocal() as session:
        existing = session.query(Project).filter(Project.name == "AgentSEO Billing Demo").all()
        for project in existing:
            session.delete(project)
        session.flush()
        project = Project(
            name="AgentSEO Billing Demo",
            description="Resettable demo with intentionally overlapping customer and billing tools.",
            sandbox_domain="billing",
        )
        session.add(project)
        session.flush()
        session.add_all([ToolDefinition(project_id=project.id, **tool.to_dict()) for tool in tools])
        session.add(
            InterfaceVersion(
                project_id=project.id,
                tool_definitions_snapshot=[tool.to_dict() for tool in tools],
                change_description=f"Seeded {document['info']['title']}",
            )
        )
        session.add_all(
            [
                BenchmarkTask(project_id=project.id, **task.to_dict())
                for task in generate_template_tasks(tools, "billing")
            ]
        )
        session.commit()
        print(f"Seeded project {project.id} with {len(tools)} tools")


if __name__ == "__main__":
    main()
