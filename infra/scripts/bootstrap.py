"""Prepare both databases and populate missing deterministic demo artifacts."""

import hashlib
import json
import subprocess
from pathlib import Path

from edgar_pipeline.config import Settings
from ml_pipeline.config import GraphSettings
from neo4j import GraphDatabase


def main() -> None:
    settings = Settings()
    graph = GraphSettings()
    directory = Path("/artifacts")
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    with (
        GraphDatabase.driver(
            graph.neo4j_uri, auth=tuple(graph.neo4j_auth.get_secret_value().split("/", 1))
        ) as driver,
        driver.session() as session,
    ):
        for statement in Path("/platform/constraints.cypher").read_text().split(";"):
            if statement.strip():
                session.run(statement).consume()
    if settings.demo_mode:
        for command in ("seed-demo", "detect"):
            subprocess.run(["edgar", command], check=True)
    manifest = directory / "manifest.json"
    if not manifest.exists():
        subprocess.run(["mule", "generate", "--output", str(directory)], check=True)
    subprocess.run(["mule", "load", "--output", str(directory)], check=True)
    if not (directory / "model.pt").exists() or not (directory / "metrics.json").exists():
        subprocess.run(["mule", "features", "--output", str(directory)], check=True)
        subprocess.run(["python", "-m", "ml_pipeline.gnn.train", str(directory)], check=True)
    subprocess.run(["python", "/platform/verify_model.py", str(directory)], check=True)
    report_file = directory / "metrics.json"
    report = json.loads(report_file.read_text())
    reference = json.loads(Path("/platform/metrics-lite.json").read_text())
    digest = hashlib.sha256((directory / "model.pt").read_bytes()).hexdigest()
    if (
        reference["ablations"]["inductive"]["shipped_model_sha256"] == digest
        and report["fold_assignments"] == reference["fold_assignments"]
    ):
        for key in ("ablations", "cold_start"):
            report.setdefault(key, reference[key])
        report_file.write_text(json.dumps(report))
    elif "cold_start" not in report:
        subprocess.run(
            ["python", "-m", "ml_pipeline.evaluation.cold_start", str(directory)], check=True
        )


if __name__ == "__main__":
    main()
