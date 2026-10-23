#!/usr/bin/python3

import argparse
import os
import re
import shlex
import subprocess
import sys
from collections import defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from operator import attrgetter

TIME_PATTERNS = {
    "s": "%Y-%m-%d %H:%M:%S",
    "min": "%Y-%m-%d %H:%M",
    "h": "%Y-%m-%d %H",
    "d": "%Y-%m-%d",
    "w": "%G-%V",
    "mon": "%Y-%m",
    "y": "%Y",
}

KEEP_SPEC_PATTERN = re.compile(r"(\d+)(" + "|".join(TIME_PATTERNS) + ")")
NAME_RE = re.compile(r"(.+)-([0-9]{8}-[0-9]{6})")


@dataclass
class Archive:
    """An archive with a naive timestamp representing UTC."""

    name: str
    timestamp: datetime


@dataclass
class KeepSpec:
    """Keep the newest archive in each of the latest occupied UTC periods.

    Applied separately to each archive series. Empty periods do not count;
    multiple keep specifications retain the union of their selected archives.
    """

    # strftime format identifying a period, e.g. "%Y-%m-%d" for a day.
    timepattern: str
    # Maximum number of occupied periods to keep; zero keeps no archives.
    num: int


class Tarsnap:
    def __init__(self, keyfile: str | None) -> None:
        self._base_command = ["tarsnap"]
        if keyfile is not None:
            self._base_command += ["--keyfile", keyfile]

    def _run(
        self,
        *args: str,
        stdout: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [*self._base_command, *args]
        return subprocess.run(  # noqa: S603
            command, stdout=stdout, env=env, check=True, text=True
        )

    def list_archives(self) -> str:
        env = os.environ.copy()
        env["TZ"] = "UTC"
        result = self._run("--list-archives", "-v", stdout=subprocess.PIPE, env=env)
        return result.stdout

    def delete(self, filenames: Iterable[str]) -> None:
        file_args: list[str] = []
        for name in filenames:
            file_args.extend(("-f", name))
        self._run("-d", *file_args)


def arc_names_to_keep(arcs: Sequence[Archive], ks: KeepSpec) -> Iterator[str]:
    """Precondition: 'arcs' is sorted in descending order by timestamp."""
    n = 0
    prev_ts = None
    for arc in arcs:
        if n == ks.num:
            return
        ts = arc.timestamp.strftime(ks.timepattern)
        if ts != prev_ts:
            yield arc.name
            n += 1
            prev_ts = ts


def arc_names_to_delete(
    arcs: Sequence[Archive], kss: Iterable[KeepSpec]
) -> Iterator[str]:
    arcs = sorted(arcs, key=attrgetter("timestamp"), reverse=True)
    keep = {name for ks in kss for name in arc_names_to_keep(arcs, ks)}
    for arc in arcs:
        if arc.name not in keep:
            yield arc.name


def parse_arcs(listing: str) -> dict[str, list[Archive]]:
    """Group matching archive names; listing timestamps must be in UTC."""
    result: defaultdict[str, list[Archive]] = defaultdict(list)
    for line in listing.splitlines():
        name, ts_str = line.split("\t")
        match = NAME_RE.fullmatch(name)
        if match is not None:
            try:
                datetime.strptime(match.group(2), "%Y%m%d-%H%M%S")
            except ValueError:
                match = None
        if match is None:
            print(
                f"Warning: ignoring archive {name!r}: "
                "expected <something>-YYYYmmdd-HHMMSS with a valid date and time",
                file=sys.stderr,
            )
            continue
        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        result[match.group(1)].append(Archive(name, ts))
    return dict(result)


def parse_keep_specs(spec: str) -> list[KeepSpec]:
    result = []
    for s in spec.split(","):
        match = KEEP_SPEC_PATTERN.fullmatch(s)
        if match is None:
            raise ValueError(f"invalid keep spec: {s!r}")
        result.append(KeepSpec(TIME_PATTERNS[match.group(2)], int(match.group(1))))
    return result


def print_arcs(arc_names: Iterable[str]) -> None:
    for name in sorted(arc_names):
        print(f"  {name}")


def remaining_arc_names(
    arcs_dict: Mapping[str, Sequence[Archive]], to_delete: Iterable[str]
) -> set[str]:
    return {arc.name for arcs in arcs_dict.values() for arc in arcs} - set(to_delete)


def plural_s(c: Collection[object]) -> str:
    return "" if len(c) == 1 else "s"


def report_action(
    arcs_dict: Mapping[str, Sequence[Archive]],
    to_delete: Collection[str],
    dry_run: bool,
) -> None:
    action = "Would" if dry_run else "Will"
    print(
        f"{action} delete the following {len(to_delete)} archive{plural_s(to_delete)}:"
    )
    print_arcs(to_delete)
    remaining = remaining_arc_names(arcs_dict, to_delete)
    print(
        f"Leaving the following {len(remaining)} "
        f"remaining archive{plural_s(remaining)}:"
    )
    print_arcs(remaining)


def run(keep_specs: Iterable[KeepSpec], keyfile: str | None, dry_run: bool) -> None:
    tarsnap = Tarsnap(keyfile)
    # Each backup series needs to apply every retention rule.
    keep_specs = list(keep_specs)
    arcs_dict = parse_arcs(tarsnap.list_archives())
    to_delete = [
        name
        for arcs in arcs_dict.values()
        for name in arc_names_to_delete(arcs, keep_specs)
    ]
    report_action(arcs_dict, to_delete, dry_run)
    if not dry_run:
        if to_delete:
            print(f"Deleting {len(to_delete)} archive{plural_s(to_delete)}...")
            tarsnap.delete(to_delete)
        else:
            print("Nothing to delete.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prune old tarsnap backups",
        epilog=(
            "Only archive names matching <something>-YYYYmmdd-HHMMSS with a "
            "valid date and time are considered. Other archives are ignored "
            "with a warning. Retention uses UTC archive creation times."
        ),
    )
    parser.add_argument(
        "keep_spec",
        metavar="KEEP_SPEC",
        type=parse_keep_specs,
        help=(
            "Comma-separated counts and units, e.g. 7d,4w,12mon. "
            "Units: s, min, h, d, w, mon, y. "
            "Keep the newest archive per occupied period, up to each count."
        ),
    )
    parser.add_argument("--keyfile", metavar="PATH", help="Tarsnap key file to use")
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Only show what would be done, don't actually delete any archives",
    )
    args = parser.parse_args(argv)
    try:
        run(args.keep_spec, args.keyfile, args.dry_run)
    except subprocess.CalledProcessError as error:
        cmd_str = shlex.join(error.cmd)
        print(
            f"Command {cmd_str!r} failed with exit status {error.returncode}",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
