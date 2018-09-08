#!/usr/bin/python3

from tarsnap_prune import TIME_PATTERNS, Archive, KeepSpec, \
        arc_names_to_delete, arc_names_to_keep, parse_arcs, parse_keep_specs

from datetime import datetime
import unittest


def arc(name, year, month, day):
    return Archive(name, datetime(year, month, day))


def ks(patname, num):
    return KeepSpec(TIME_PATTERNS[patname], num)


class TestTimePatterns(unittest.TestCase):
    @staticmethod
    def _fmt(key, d1, d2):
        pattern = TIME_PATTERNS[key]
        return d1.strftime(pattern), d2.strftime(pattern)

    def _assertSame(self, key, d1, d2):
        f1, f2 = self._fmt(key, d1, d2)
        self.assertEqual(f1, f2)

    def _assertDifferent(self, key, d1, d2):
        f1, f2 = self._fmt(key, d1, d2)
        self.assertNotEqual(f1, f2)

    def test_seconds(self):
        self._assertDifferent('s',
                              datetime(2018, 1, 2, 3, 4, 5),
                              datetime(2018, 1, 2, 3, 4, 6))

    def test_minutes(self):
        self._assertSame('min',
                         datetime(2018, 1, 2, 3, 4, 5),
                         datetime(2018, 1, 2, 3, 4, 6))
        self._assertDifferent('min',
                              datetime(2018, 1, 2, 3, 4, 0),
                              datetime(2018, 1, 2, 3, 5, 0))

    def test_hours(self):
        self._assertSame('h',
                         datetime(2018, 1, 2, 3, 4, 5),
                         datetime(2018, 1, 2, 3, 45, 0))
        self._assertDifferent('h',
                              datetime(2018, 1, 2, 3, 4, 59),
                              datetime(2018, 1, 2, 4, 4, 59))

    def test_days(self):
        self._assertSame('d',
                         datetime(2018, 1, 2, 3, 0, 5),
                         datetime(2018, 1, 2, 23, 0, 4))
        self._assertDifferent('d',
                              datetime(2018, 1, 2, 3, 4, 59),
                              datetime(2018, 1, 3, 3, 4, 59))

    def test_weeks(self):
        self._assertSame('w',
                         datetime(2008, 12, 29, 3, 4, 5),
                         datetime(2008, 12, 30, 4, 5, 6))
        self._assertDifferent('w',
                              datetime(2008, 12, 28),
                              datetime(2008, 12, 29))

    def test_months(self):
        self._assertSame('mon',
                         datetime(2009, 12, 29, 3, 4, 5),
                         datetime(2009, 12, 30, 4, 5, 6))
        self._assertDifferent('mon',
                              datetime(2009, 11, 29),
                              datetime(2009, 12, 29))

    def test_years(self):
        self._assertSame('y',
                         datetime(2009, 11, 29, 3, 4, 5),
                         datetime(2009, 12, 30, 4, 5, 6))
        self._assertDifferent('y',
                              datetime(2008, 12, 29),
                              datetime(2009, 12, 29))


class TestLogic(unittest.TestCase):
    def test_arc_names_to_keep(self):
        r1 = arc_names_to_keep([
                    arc('1', 2000, 3, 15),
                    arc('2', 2000, 3, 1),
                    arc('3', 2000, 2, 15),
                    arc('4', 2000, 2, 1),
                    arc('5', 2000, 1, 15)],
                ks('mon', 2))
        self.assertEqual(list(r1), ['1', '3'])

        r2 = arc_names_to_keep([
                    arc('1', 2010, 2, 15),
                    arc('2', 2000, 2, 1),
                    arc('3', 2000, 1, 15)],
                ks('mon', 2))
        self.assertEqual(list(r2), ['1', '2'])

        r3 = arc_names_to_keep([arc('1', 2010, 2, 15)], ks('mon', 2))
        self.assertEqual(list(r3), ['1'])

        r4 = arc_names_to_keep([], ks('mon', 2))
        self.assertEqual(list(r4), [])

    def test_arc_names_to_delete(self):
        r1 = arc_names_to_delete([
                    arc('4', 1999, 1, 2),
                    arc('5', 1999, 1, 1),
                    arc('6', 1998, 1, 1),
                    arc('1', 2000, 1, 31),
                    arc('2', 2000, 1, 30),
                    arc('3', 2000, 1, 29)],
                    [ks('d', 2), ks('y', 2)])
        self.assertEqual(list(r1), ['3', '5', '6'])

        r2 = arc_names_to_delete([arc('1', 2000, 1, 1)], [])
        self.assertEqual(list(r2), ['1'])

        r3 = arc_names_to_delete([], [])
        self.assertEqual(list(r3), [])


class TestParsing(unittest.TestCase):
    def test_parse_arcs(self):
        r1 = parse_arcs('')
        self.assertEqual(r1, {})

        r2 = parse_arcs(
                    'foo\t2000-01-01 00:00:00\n'
                    'foo-123\t1999-02-02 03:00:00\n'
                    'bar-123\t1999-02-02 03:00:00\n'
                )
        self.assertEqual(r2, {
                    'foo': [Archive('foo', datetime(2000, 1, 1)),
                            Archive('foo-123', datetime(1999, 2, 2, 3))],
                    'bar': [Archive('bar-123', datetime(1999, 2, 2, 3))]
                })

        with self.assertRaises(ValueError):
            parse_arcs('\n')

        with self.assertRaises(ValueError):
            parse_arcs('foo\tbar')

    def test_parse_keep_specs(self):
        r1 = parse_keep_specs('1d')
        self.assertEqual(r1, [KeepSpec(TIME_PATTERNS['d'], 1)])

        r2 = parse_keep_specs('2d,5w,4mon')
        self.assertEqual(r2, [
                    KeepSpec(TIME_PATTERNS['d'], 2),
                    KeepSpec(TIME_PATTERNS['w'], 5),
                    KeepSpec(TIME_PATTERNS['mon'], 4)
                ])

        with self.assertRaises(RuntimeError):
            parse_keep_specs('2x')

        with self.assertRaises(RuntimeError):
            parse_keep_specs('d')

        with self.assertRaises(RuntimeError):
            parse_keep_specs('')


if __name__ == '__main__':
    unittest.main()
