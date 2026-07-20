"""Build an ignored, curated evidence workspace for the hackathon demo."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import shutil

from .repository import JourneyRepository


SHOWCASE_VERSION = "1.0.0"


@dataclass(frozen=True)
class ShowcaseResult:
    output_root: Path
    fixture_revisions: int
    real_revision: tuple[str, str] | None


def _copy_revision(source_root: Path, output_root: Path, job_id: str, revision_id: str) -> None:
    source = source_root / job_id / "revisions" / revision_id
    destination = output_root / job_id / "revisions" / revision_id
    if not source.is_dir():
        raise FileNotFoundError(f"showcase source revision is missing: {job_id}/{revision_id}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def prepare_showcase(
    runtime_root: Path,
    fixture_root: Path,
    output_root: Path,
) -> ShowcaseResult:
    runtime = runtime_root.expanduser().resolve(strict=True)
    fixture = fixture_root.expanduser().resolve(strict=True)
    output = output_root.expanduser().resolve()
    if output == runtime or output == fixture or not output.is_relative_to(runtime):
        raise ValueError(
            "showcase output must differ from its evidence sources and remain inside runtime root"
        )
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    fixture_count = 0
    for job in sorted(fixture.glob("job_*"), key=lambda item: item.name.casefold()):
        revisions = job / "revisions"
        if not revisions.is_dir():
            continue
        for revision in sorted(revisions.glob("rev_*"), key=lambda item: item.name.casefold()):
            if not revision.is_dir():
                continue
            _copy_revision(fixture, output, job.name, revision.name)
            fixture_count += 1

    selected: tuple[str, str] | None = None
    repository = JourneyRepository(runtime)
    listing = repository.list_revisions(offset=0, limit=200)
    for summary in listing.revisions:
        if (
            summary.availability == "available"
            and summary.source is not None
            and summary.source.kind == "runtime_revision"
            and summary.achieved_evidence_level == "R4"
        ):
            repository.get_revision(summary.job_id, summary.revision_id)
            selected = (summary.job_id, summary.revision_id)
            _copy_revision(runtime, output, *selected)
            break

    manifest = {
        "showcase_version": SHOWCASE_VERSION,
        "fixture_revisions": fixture_count,
        "real_revision": (
            {"job_id": selected[0], "revision_id": selected[1]} if selected else None
        ),
        "hardware_actions": False,
        "claim_boundary": (
            "Curated copies only; fixture evidence remains fixture and the optional real R4 "
            "revision retains its persisted digital claim boundary."
        ),
    }
    (output / "showcase.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return ShowcaseResult(output, fixture_count, selected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, default=Path("runs"))
    parser.add_argument("--fixture-root", type=Path, default=Path("benchmarks/interface"))
    parser.add_argument("--output-root", type=Path, default=Path("runs/showcase"))
    arguments = parser.parse_args()
    result = prepare_showcase(
        arguments.runtime_root,
        arguments.fixture_root,
        arguments.output_root,
    )
    print(f"Showcase workspace: {result.output_root}")
    print(f"Fixture revisions: {result.fixture_revisions}")
    print(
        "Real R4 revision: "
        + ("/".join(result.real_revision) if result.real_revision else "unavailable")
    )
    print("Hardware actions: disabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
