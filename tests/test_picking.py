import random
import unittest

from readwise_bundler.picking import (
    Picker, Rule, eligible, order, parse_minutes, tidy_author, tidy_title, to_article,
)

from helpers import make_doc


class ParseMinutes(unittest.TestCase):
    def test_readwise_labels(self):
        self.assertEqual(parse_minutes("12 mins", None), 12)
        self.assertEqual(parse_minutes("1 min", None), 1)
        self.assertEqual(parse_minutes("1 hr 5 mins", None), 65)
        self.assertEqual(parse_minutes("5 hrs 48 mins", None), 348)

    def test_falls_back_to_word_count(self):
        self.assertEqual(parse_minutes(None, 2380), 10)
        self.assertIsNone(parse_minutes(None, None))


class Tidying(unittest.TestCase):
    def test_titles(self):
        self.assertEqual(tidy_title("A Pilgrimage in Pakistan - The New York Times", "New York Times"),
                         "A Pilgrimage in Pakistan")
        self.assertEqual(tidy_title("Empire | The New Yorker", "The New Yorker"), "Empire")
        self.assertEqual(tidy_title("Growth - Why It Stalled", "Some Blog"), "Growth - Why It Stalled")
        self.assertEqual(tidy_title("THE CONTINUING RESONANCE OF THE MCKEOWN THESIS"),
                         "The Continuing Resonance Of The Mckeown Thesis")
        self.assertEqual(tidy_title("NATO at 75"), "NATO at 75")

    def test_authors(self):
        self.assertEqual(tidy_author("Naomi Klein, Astra Taylor"), "Naomi Klein and Astra Taylor")
        self.assertEqual(tidy_author("A One, B Two, C Three"), "A One, B Two and C Three")
        self.assertEqual(tidy_author("A, B, C, D, E"), "A, B and others")
        self.assertEqual(tidy_author("By Victoria Guida and Ian Ward"), "Victoria Guida and Ian Ward")
        self.assertEqual(tidy_author("https://www.nytimes.com/by/kim-tingley"), "Kim Tingley")
        self.assertEqual(tidy_author("https://github.com/someone/"), "")
        self.assertEqual(tidy_author("Latest News , Breaking News Today | Frontline"), "")


class Eligibility(unittest.TestCase):
    def test_rules(self):
        docs = [
            make_doc(1),
            make_doc(2, tags=["Interactive"]),
            make_doc(3, tags=["bundled"]),
            make_doc(4, tags=["listen-bundle"]),
            make_doc(5, minutes=40),
            make_doc(6, minutes=39),
            make_doc(7, category="pdf"),
            make_doc(8, category="rss"),
            make_doc(9, category="email"),
            make_doc(10, words=100),
            make_doc(11, parent_id="doc0001"),
            make_doc(12, location="archive"),
            make_doc(13, tags=["India", "history"]),
            make_doc(14, tags=["jobpost"]),
            make_doc(15, tags=["Job post"]),
            make_doc(16, minutes=1, words=300),
            make_doc(17, minutes=2),
        ]
        pool, skipped = eligible(docs, exclude_ids={"doc0013"})
        self.assertEqual(sorted(a.id for a in pool),
                         ["doc0001", "doc0006", "doc0008", "doc0009", "doc0017"])
        self.assertEqual(skipped["tagged interactive"], 1)
        self.assertEqual(skipped["tagged jobpost"], 2)
        self.assertEqual(skipped["40+ minutes"], 1)
        self.assertEqual(skipped["under 2 minutes"], 1)
        self.assertEqual(skipped["already in a bundle"], 1)


class Picking(unittest.TestCase):
    def pool(self, n=300, seed=1):
        rng = random.Random(seed)
        docs = [make_doc(i, minutes=rng.choice([3, 5, 7, 12, 18, 25, 35]), days=rng.randint(0, 900))
                for i in range(n)]
        pool, _ = eligible(docs)
        return pool

    def test_every_bundle_follows_the_rule(self):
        rule = Rule()
        picker = Picker(self.pool(), rule, random.Random(3))
        seen = set()
        for _ in range(40):
            bundle = picker.pick()
            self.assertIsNotNone(bundle)
            self.assertTrue(2 <= len(bundle) <= 4)
            total = sum(a.minutes for a in bundle)
            self.assertTrue(40 <= total <= 80, total)
            dates = [a.saved_at for a in bundle]
            # all within 30 days of the anchor, so at most 60 days apart
            self.assertLessEqual((max(dates) - min(dates)).days, 60)
            ids = {a.id for a in bundle}
            self.assertFalse(ids & seen, "an article was reused")
            seen |= ids

    def test_returns_none_when_nothing_fits(self):
        docs = [make_doc(i, minutes=3, days=i * 100) for i in range(5)]  # far apart and short
        pool, _ = eligible(docs)
        self.assertIsNone(Picker(pool, Rule(anchor_tries=20), random.Random(1)).pick())

    def test_order_is_oldest_published_first(self):
        a = to_article(make_doc(1, published="2024-05-01"))
        b = to_article(make_doc(2, published="2023-01-01"))
        c = to_article(make_doc(3, published=None, days=-1500))  # saved in 2021
        self.assertEqual([x.id for x in order([a, b, c])], ["doc0003", "doc0002", "doc0001"])


if __name__ == "__main__":
    unittest.main()
