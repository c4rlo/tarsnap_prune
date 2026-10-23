#!/usr/bin/python3

import contextlib
import io
import subprocess
import unittest
from datetime import datetime
from unittest.mock import patch

from tarsnap_prune import (
    TIME_PATTERNS,
    Archive,
    KeepSpec,
    Tarsnap,
    arc_names_to_delete,
    arc_names_to_keep,
    main,
    parse_arcs,
    parse_keep_specs,
)


def arc(name, year, month, day):
    return Archive(name, datetime(year, month, day))


def ks(patname, num):
    return KeepSpec(TIME_PATTERNS[patname], num)


class TestTimePatterns(unittest.TestCase):
    @staticmethod
    def _fmt(key, d1, d2):
        pattern = TIME_PATTERNS[key]
        return d1.strftime(pattern), d2.strftime(pattern)

    def _assert_same(self, key, d1, d2):
        f1, f2 = self._fmt(key, d1, d2)
        self.assertEqual(f1, f2)

    def _assert_different(self, key, d1, d2):
        f1, f2 = self._fmt(key, d1, d2)
        self.assertNotEqual(f1, f2)

    def test_seconds(self):
        self._assert_different(
            "s",
            datetime(2018, 1, 2, 3, 4, 5),
            datetime(2018, 1, 2, 3, 4, 6),
        )

    def test_minutes(self):
        self._assert_same(
            "min",
            datetime(2018, 1, 2, 3, 4, 5),
            datetime(2018, 1, 2, 3, 4, 6),
        )
        self._assert_different(
            "min",
            datetime(2018, 1, 2, 3, 4, 0),
            datetime(2018, 1, 2, 3, 5, 0),
        )

    def test_hours(self):
        self._assert_same(
            "h",
            datetime(2018, 1, 2, 3, 4, 5),
            datetime(2018, 1, 2, 3, 45, 0),
        )
        self._assert_different(
            "h",
            datetime(2018, 1, 2, 3, 4, 59),
            datetime(2018, 1, 2, 4, 4, 59),
        )

    def test_days(self):
        self._assert_same(
            "d",
            datetime(2018, 1, 2, 3, 0, 5),
            datetime(2018, 1, 2, 23, 0, 4),
        )
        self._assert_different(
            "d",
            datetime(2018, 1, 2, 3, 4, 59),
            datetime(2018, 1, 3, 3, 4, 59),
        )

    def test_weeks(self):
        self._assert_same(
            "w",
            datetime(2008, 12, 29, 3, 4, 5),
            datetime(2008, 12, 30, 4, 5, 6),
        )
        self._assert_different("w", datetime(2008, 12, 28), datetime(2008, 12, 29))

    def test_months(self):
        self._assert_same(
            "mon",
            datetime(2009, 12, 29, 3, 4, 5),
            datetime(2009, 12, 30, 4, 5, 6),
        )
        self._assert_different(
            "mon",
            datetime(2009, 11, 29),
            datetime(2009, 12, 29),
        )

    def test_years(self):
        self._assert_same(
            "y",
            datetime(2009, 11, 29, 3, 4, 5),
            datetime(2009, 12, 30, 4, 5, 6),
        )
        self._assert_different("y", datetime(2008, 12, 29), datetime(2009, 12, 29))


class TestLogic(unittest.TestCase):
    def test_arc_names_to_keep(self):
        r1 = arc_names_to_keep(
            [
                arc("1", 2000, 3, 15),
                arc("2", 2000, 3, 1),
                arc("3", 2000, 2, 15),
                arc("4", 2000, 2, 1),
                arc("5", 2000, 1, 15),
            ],
            ks("mon", 2),
        )
        self.assertEqual(list(r1), ["1", "3"])

        r2 = arc_names_to_keep(
            [arc("1", 2010, 2, 15), arc("2", 2000, 2, 1), arc("3", 2000, 1, 15)],
            ks("mon", 2),
        )
        self.assertEqual(list(r2), ["1", "2"])

        r3 = arc_names_to_keep([arc("1", 2010, 2, 15)], ks("mon", 2))
        self.assertEqual(list(r3), ["1"])

        r4 = arc_names_to_keep([], ks("mon", 2))
        self.assertEqual(list(r4), [])

    def test_arc_names_to_delete(self):
        r1 = arc_names_to_delete(
            [
                arc("4", 1999, 1, 2),
                arc("5", 1999, 1, 1),
                arc("6", 1998, 1, 1),
                arc("1", 2000, 1, 31),
                arc("2", 2000, 1, 30),
                arc("3", 2000, 1, 29),
            ],
            [ks("d", 2), ks("y", 2)],
        )
        self.assertEqual(list(r1), ["3", "5", "6"])

        r2 = arc_names_to_delete([arc("1", 2000, 1, 1)], [])
        self.assertEqual(list(r2), ["1"])

        r3 = arc_names_to_delete([], [])
        self.assertEqual(list(r3), [])


class TestParsing(unittest.TestCase):
    def test_parse_arcs(self):
        r1 = parse_arcs("")
        self.assertEqual(r1, {})

        r2 = parse_arcs(
            "foo-20000101-000000\t2000-01-01 00:00:00\n"
            "foo-19990202-030000\t1999-02-02 03:00:00\n"
            "bar-19990202-030000\t1999-02-02 03:00:00\n"
        )
        self.assertEqual(
            r2,
            {
                "foo": [
                    Archive("foo-20000101-000000", datetime(2000, 1, 1)),
                    Archive("foo-19990202-030000", datetime(1999, 2, 2, 3)),
                ],
                "bar": [
                    Archive("bar-19990202-030000", datetime(1999, 2, 2, 3)),
                ],
            },
        )

        with self.assertRaises(ValueError):
            parse_arcs("\n")

        with self.assertRaises(ValueError):
            parse_arcs("foo-20000101-000000\tbar")

    def test_numbered_prefixes_remain_separate(self):
        groups = parse_arcs(
            "db-1-20261023-000000\t2026-10-23 00:00:00\n"
            "db-2-20261022-000000\t2026-10-22 00:00:00\n"
        )
        self.assertEqual(set(groups), {"db-1", "db-2"})
        for arcs in groups.values():
            self.assertEqual(list(arc_names_to_delete(arcs, [ks("d", 1)])), [])

    def test_invalid_names_warn_and_are_ignored(self):
        names = [
            "foo",
            "foo-123",
            "-20261023-000000",
            "foo-2026-10-23T00:00:00",
            "foo-20261023-000000.part",
            "foo-20260230-000000",
            "foo-20261023-240000",
            "foo-2026102-000000",
            "foo-２０２６１０２３-000000",  # noqa: RUF001 -- reject Unicode digits
        ]
        for name in names:
            with (
                self.subTest(name=name),
                contextlib.redirect_stderr(io.StringIO()) as stderr,
            ):
                self.assertEqual(parse_arcs(f"{name}\t2026-10-23 00:00:00\n"), {})
                self.assertIn(repr(name), stderr.getvalue())
                self.assertIn("Warning: ignoring archive", stderr.getvalue())

    def test_retention_uses_creation_time(self):
        groups = parse_arcs(
            "foo-20261023-000000\t2026-10-22 00:00:00\n"
            "foo-20261022-000000\t2026-10-23 00:00:00\n"
        )
        self.assertEqual(
            list(arc_names_to_delete(groups["foo"], [ks("d", 1)])),
            ["foo-20261023-000000"],
        )

    def test_parse_keep_specs(self):
        r1 = parse_keep_specs("1d")
        self.assertEqual(r1, [KeepSpec(TIME_PATTERNS["d"], 1)])

        r2 = parse_keep_specs("2d,5w,4mon")
        self.assertEqual(
            r2,
            [
                KeepSpec(TIME_PATTERNS["d"], 2),
                KeepSpec(TIME_PATTERNS["w"], 5),
                KeepSpec(TIME_PATTERNS["mon"], 4),
            ],
        )

        with self.assertRaises(ValueError):
            parse_keep_specs("2x")

        with self.assertRaises(ValueError):
            parse_keep_specs("d")

        with self.assertRaises(ValueError):
            parse_keep_specs("")


class TestTarsnap(unittest.TestCase):
    def test_subprocess_failures_raise(self):
        tarsnap = Tarsnap("key file")
        for args in [("--list-archives", "-v"), ("-d", "-f", "foo-20261023-000000")]:
            with (
                self.subTest(args=args),
                patch(
                    "tarsnap_prune.subprocess.run",
                    side_effect=subprocess.CalledProcessError(7, ["tarsnap", *args]),
                ) as mocked,
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    if args[0] == "-d":
                        tarsnap.delete(["foo-20261023-000000"])
                    else:
                        tarsnap.list_archives()
                self.assertEqual(
                    mocked.call_args.args[0],
                    ["tarsnap", "--keyfile", "key file", *args],
                )
                self.assertTrue(mocked.call_args.kwargs["check"])
                if args[0] == "--list-archives":
                    self.assertEqual(mocked.call_args.kwargs["env"]["TZ"], "UTC")


class TestCli(unittest.TestCase):
    listing = (
        "foo-20261023-000000\t2026-10-23 00:00:00\n"
        "foo-20261022-000000\t2026-10-22 00:00:00\n"
        "unrelated\t2026-10-21 00:00:00\n"
    )

    def test_invalid_keep_spec_is_an_argparse_error(self):
        with (
            patch("tarsnap_prune.Tarsnap") as tarsnap,
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            with self.assertRaises(SystemExit) as error:
                main(["2x"])
            self.assertEqual(error.exception.code, 2)
            self.assertIn("KEEP_SPEC", stderr.getvalue())
            self.assertIn("error:", stderr.getvalue())
            tarsnap.assert_not_called()

    def test_dry_run_does_not_delete(self):
        with (
            patch.object(Tarsnap, "list_archives", return_value=self.listing),
            patch.object(Tarsnap, "delete") as delete,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            self.assertEqual(main(["1d", "--dry-run"]), 0)
            delete.assert_not_called()
            self.assertIn("Would delete the following 1 archive:", stdout.getvalue())
            self.assertNotIn("unrelated", stdout.getvalue())
            self.assertIn("unrelated", stderr.getvalue())

    def test_only_matching_archives_are_deleted(self):
        with (
            patch.object(Tarsnap, "list_archives", return_value=self.listing),
            patch.object(Tarsnap, "delete") as delete,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main(["0d"]), 0)
            delete.assert_called_once_with(
                ["foo-20261023-000000", "foo-20261022-000000"]
            )

    def test_delete_failure_returns_error_status(self):
        with (
            patch.object(Tarsnap, "list_archives", return_value=self.listing),
            patch.object(
                Tarsnap,
                "delete",
                side_effect=subprocess.CalledProcessError(7, ["tarsnap", "-d"]),
            ),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            self.assertEqual(main(["1d"]), 1)
            self.assertIn("exit status 7", stderr.getvalue())

    def test_list_failure_returns_error_status(self):
        with (
            patch.object(
                Tarsnap,
                "list_archives",
                side_effect=subprocess.CalledProcessError(
                    8, ["tarsnap", "--list-archives"]
                ),
            ),
            patch.object(Tarsnap, "delete") as delete,
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            self.assertEqual(main(["1d"]), 1)
            self.assertIn("exit status 8", stderr.getvalue())
            delete.assert_not_called()

    def test_missing_executable_returns_error_status(self):
        with (
            patch.object(
                Tarsnap, "list_archives", side_effect=FileNotFoundError("tarsnap")
            ),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            self.assertEqual(main(["1d"]), 1)
            self.assertIn("tarsnap", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
