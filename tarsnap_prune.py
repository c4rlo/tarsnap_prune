#!/usr/bin/python3

import argparse
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from operator import attrgetter
from typing import Dict, DefaultDict, Iterator, Iterable, Collection, List, \
                   Optional

TIME_PATTERNS = {
    's': '%Y-%m-%d %H:%M:%S',
    'min': '%Y-%m-%d %H:%M',
    'h': '%Y-%m-%d %H',
    'd': '%Y-%m-%d',
    'w': '%G-%V',
    'mon': '%Y-%m',
    'y': '%Y'
}

KEEP_SPEC_PATTERN = \
        re.compile(r'(\d+)(' + '|'.join(TIME_PATTERNS.keys()) + ')')

NAME_RE = re.compile(r'(.*?)(?:-[0-9-]*)?')


@dataclass
class Archive:
    name: str
    timestamp: datetime


@dataclass
class KeepSpec:
    timepattern: str
    num: int


class Tarsnap:
    def __init__(self, keyfile: Optional[str]) -> None:
        self._base_command = ['tarsnap']
        if keyfile is not None:
            self._base_command += ['--keyfile', keyfile]

    def _run(self, *args: str, **kwargs) -> subprocess.CompletedProcess:
        command = self._base_command.copy()
        command += args
        return subprocess.run(command, **kwargs)

    def list_archives(self) -> str:
        env = os.environ.copy()
        env['TZ'] = 'UTC'
        result = self._run('--list-archives', '-v', stdout=subprocess.PIPE,
                           env=env, check=True, text=True)
        return result.stdout

    def delete(self, filenames: Iterable[str]) -> None:
        file_args: List[str] = []
        for fn in filenames:
            file_args += ['-f', fn]
        self._run('-d', *file_args)


def arc_names_to_keep(arcs: List[Archive], ks: KeepSpec) -> Iterator[str]:
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


def arc_names_to_delete(arcs: List[Archive], kss: Iterable[KeepSpec]) \
        -> Iterator[str]:
    arcs.sort(key=attrgetter('timestamp'), reverse=True)
    keep = set()
    for ks in kss:
        for name in arc_names_to_keep(arcs, ks):
            keep.add(name)
    for arc in arcs:
        n = arc.name
        if n not in keep:
            yield n


def parse_arcs(listing: str) -> Dict[str, List[Archive]]:
    result: DefaultDict[str, List[Archive]] = defaultdict(list)
    for line in listing.splitlines():
        line = line.rstrip('\n')
        name, ts_str = line.split('\t')
        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        m = NAME_RE.fullmatch(name)
        if m is None:
            raise RuntimeError("failed to parse line '{}'".format(line))
        base = m.group(1)
        result[base].append(Archive(name, ts))
    return result


def parse_keep_specs(spec: str) -> List[KeepSpec]:
    result = []
    for s in spec.split(','):
        m = KEEP_SPEC_PATTERN.fullmatch(s)
        if m:
            result.append(KeepSpec(TIME_PATTERNS[m.group(2)], int(m.group(1))))
        else:
            raise RuntimeError("invalid keep spec: '{}'".format(s))
    return result


def print_arcs(arc_names: Iterable[str]) -> None:
    for name in sorted(arc_names):
        print("  {}".format(name))


def remaining_arc_names(arcs_dict: Dict[str, List[Archive]],
                        to_delete: Iterable[str]) -> Collection[str]:
    all_arc_names = set()
    for arcs in arcs_dict.values():
        for arc in arcs:
            all_arc_names.add(arc.name)
    for name in to_delete:
        all_arc_names.remove(name)
    return all_arc_names


def plural_s(c: Collection) -> str:
    if len(c) == 1:
        return ''
    else:
        return 's'


def report_action(arcs_dict, to_delete, dry_run) -> None:
    print("{} delete the following {} archive{}:"
          .format('Would' if dry_run else 'Will',
                  len(to_delete), plural_s(to_delete)))
    print_arcs(to_delete)
    remaining = remaining_arc_names(arcs_dict, to_delete)
    print("Leaving the following {} remaining archive{}:"
          .format(len(remaining), plural_s(remaining)))
    print_arcs(remaining)


def run(keep_specs_str: str, keyfile: Optional[str], dry_run: bool) -> None:
    tarsnap = Tarsnap(keyfile)
    keep_specs = parse_keep_specs(keep_specs_str)
    arcs_str = tarsnap.list_archives()
    arcs_dict = parse_arcs(arcs_str)
    to_delete: List[str] = []
    for arcs in arcs_dict.values():
        to_delete += arc_names_to_delete(arcs, keep_specs)
    report_action(arcs_dict, to_delete, dry_run)
    if not dry_run:
        if len(to_delete) > 0:
            print("Deleting {} archive{}...".format(len(to_delete),
                                                    plural_s(to_delete)))
            tarsnap.delete(to_delete)
        else:
            print("Nothing to delete.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Prune old tarsnap backups')
    parser.add_argument('keep_spec', metavar='KEEP_SPEC',
                        help='Specification for what archives to keep')
    parser.add_argument('--keyfile', metavar='PATH',
                        help='Tarsnap key file to use')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help="Only show what would be done, don't actually "
                             "delete any archives")
    args = parser.parse_args()
    try:
        run(args.keep_spec, args.keyfile, args.dry_run)
    except RuntimeError as e:
        print(e)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        cmd_str = ' '.join(e.cmd)
        print("Command '{}' failed with exit status {}".format(cmd_str,
                                                               e.returncode))
        sys.exit(1)
