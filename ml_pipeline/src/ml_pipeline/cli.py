import argparse
import json
from pathlib import Path

from neo4j import GraphDatabase

from ml_pipeline.config import GraphSettings
from ml_pipeline.evaluation.baseline import evaluate
from ml_pipeline.features.pipeline import features
from ml_pipeline.generator.dataset import generate
from ml_pipeline.neo4j_store.loader import load


def main() -> None:
    parser = argparse.ArgumentParser(prog="mule")
    parser.add_argument("command", choices=["generate", "load", "features", "baseline"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label-noise", type=float, default=0)
    args = parser.parse_args()
    settings = GraphSettings()
    if args.command == "baseline":
        evaluate(args.output)
        return
    if args.command == "features":
        frame = features(args.output, settings.seed, settings.reporting_threshold)
        frame.to_parquet(args.output / "features.parquet", index=False)
        print(json.dumps({"accounts": len(frame), "communities": int(frame.community.nunique())}))
        return
    if args.command == "load":
        user, password = settings.neo4j_auth.get_secret_value().split("/", 1)
        with GraphDatabase.driver(settings.neo4j_uri, auth=(user, password)) as driver:
            print(json.dumps(load(driver, args.output)))
        return
    generate(
        args.output,
        settings.mule_scale,
        settings.seed,
        settings.reporting_threshold,
        args.label_noise,
    )
