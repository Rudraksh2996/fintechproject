import argparse
from pathlib import Path

from ml_pipeline.config import GraphSettings
from ml_pipeline.generator.dataset import generate


def main() -> None:
    parser = argparse.ArgumentParser(prog="mule")
    parser.add_argument("command", choices=["generate"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label-noise", type=float, default=0)
    args = parser.parse_args()
    settings = GraphSettings()
    generate(
        args.output,
        settings.mule_scale,
        settings.seed,
        settings.reporting_threshold,
        args.label_noise,
    )
