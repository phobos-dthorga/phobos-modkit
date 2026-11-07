"""Grouping, comparison and clustering work on entries alone, with no game in them."""
import unittest

import support  # noqa: F401
from phobos_modkit.logs.model import Entry, Evidence, LogFile
from phobos_modkit.logs.triage import LINES_KEPT, build_report, clusters, compare, group, group_id


def entry(line, level, headline, evidence=(), fingerprint="", category="Game"):
    return Entry(line=line, level=level, category=category, headline=headline, evidence=list(evidence),
                 fingerprint=fingerprint, time=f"2026-01-01 10:00:{line % 60:02d}.000")


class Grouping(unittest.TestCase):
    def test_most_severe_then_most_frequent_then_earliest(self):
        groups = group([entry(1, "WARN", "w"), entry(2, "ERROR", "rare"), entry(3, "ERROR", "common 1"),
                        entry(4, "ERROR", "common 2"), entry(5, "INFO", "i")])
        self.assertEqual([(g.level, g.signature, g.count) for g in groups],
                         [("ERROR", "common #", 2), ("ERROR", "rare", 1), ("WARN", "w", 1), ("INFO", "i", 1)])

    def test_first_and_last_occurrence_are_kept(self):
        (found,) = group([entry(10, "ERROR", "x 1"), entry(20, "ERROR", "x 2"), entry(30, "ERROR", "x 3")])
        self.assertEqual((found.first_line, found.last_line, found.example.line), (10, 30, 10))

    def test_ids_are_short_stable_and_differ_by_level(self):
        self.assertEqual(group_id("ERROR", "Game", "x"), group_id("ERROR", "Game", "x"))
        self.assertNotEqual(group_id("ERROR", "Game", "x"), group_id("WARN", "Game", "x"))
        self.assertRegex(group_id("ERROR", "Game", "x"), r"^[0-9a-f]{8}$")

    def test_line_numbers_are_capped(self):
        (found,) = group([entry(n, "ERROR", "same") for n in range(1, LINES_KEPT + 20)])
        self.assertEqual(len(found.lines), LINES_KEPT)
        self.assertEqual(found.count, LINES_KEPT + 19)

    def test_each_clue_counts_once_per_message_in_the_order_found(self):
        a, b = Evidence("assembly", "First.dll"), Evidence("assembly", "Second.dll")
        (found,) = group([entry(1, "ERROR", "x", [a, b, a]), entry(2, "ERROR", "x", [a])])
        self.assertEqual(found.evidence[a], 2)
        self.assertEqual(found.evidence[b], 1)
        self.assertEqual(found.top_evidence(), [a, b])

    def test_stronger_kinds_come_first(self):
        weak, strong = Evidence("patch", "some.id"), Evidence("source", "Some Mod")
        (found,) = group([entry(1, "ERROR", "x", [weak, strong])])
        self.assertEqual(found.top_evidence(1), [strong])


class Comparing(unittest.TestCase):
    def test_new_gone_and_changed(self):
        before = group([entry(1, "ERROR", "kept"), entry(2, "ERROR", "gone"), entry(3, "WARN", "grew")])
        after = group([entry(1, "ERROR", "kept"), entry(2, "WARN", "grew"), entry(3, "WARN", "grew"),
                       entry(4, "ERROR", "new")])
        result = compare(after, before, "prev.log")
        self.assertEqual([c.group.signature for c in result.new], ["new"])
        self.assertEqual([c.group.signature for c in result.gone], ["gone"])
        self.assertEqual([(c.group.signature, c.previous, c.current) for c in result.changed], [("grew", 1, 2)])
        self.assertEqual(result.previous_name, "prev.log")


class Clustering(unittest.TestCase):
    def test_messages_sharing_an_exception_form_one_cluster(self):
        groups = group([entry(1, "ERROR", "for Alice", fingerprint="E at A < B"),
                        entry(2, "ERROR", "for Bob", fingerprint="E at A < B"),
                        entry(3, "ERROR", "for Bob", fingerprint="E at A < B"),
                        entry(4, "ERROR", "alone", fingerprint="F at C")])
        (cluster,) = clusters(groups)
        self.assertEqual(cluster.count, 3)
        self.assertEqual(sorted(g.example.headline for g in cluster.groups), ["for Alice", "for Bob"])

    def test_levels_are_not_mixed_and_unfingerprinted_messages_are_left_out(self):
        groups = group([entry(1, "ERROR", "a", fingerprint="E at A"), entry(2, "WARN", "b", fingerprint="E at A"),
                        entry(3, "ERROR", "c"), entry(4, "ERROR", "d")])
        self.assertEqual(clusters(groups), [])


class Reporting(unittest.TestCase):
    def test_counts_by_level_and_lookup_by_id_prefix(self):
        log = LogFile("now.log", "test", [entry(1, "ERROR", "a"), entry(2, "ERROR", "a"), entry(3, "WARN", "b")])
        report = build_report(log, LogFile("before.log", "test", [entry(1, "WARN", "b")]))
        self.assertEqual(report.level_counts(), {"ERROR": (2, 1), "WARN": (1, 1)})
        first = report.groups[0]
        self.assertIs(report.find(first.id[:6]), first)
        self.assertIsNone(report.find("zzzz"))
        self.assertIsNone(report.find(""))  # every ID starts with "": ambiguous
        self.assertEqual(len(report.comparison.new), 1)


if __name__ == "__main__":
    unittest.main()
