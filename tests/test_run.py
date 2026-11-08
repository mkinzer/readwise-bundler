import random
import unittest
from datetime import date

from readwise_bundler.run import Run, original_ids

from helpers import FakeClient, make_doc


def library(n=60):
    rng = random.Random(5)
    return [make_doc(i, minutes=rng.choice([4, 6, 9, 14, 22, 30]), days=rng.randint(0, 40),
                     tags=["india"] if i % 7 == 0 else ())
            for i in range(n)]


def run(client, **kw):
    kw.setdefault("rng", random.Random(2))
    kw.setdefault("made_on", date(2026, 11, 8))
    kw.setdefault("log", lambda *_: None)
    return Run(client, **kw).go()


class FillingTheShelf(unittest.TestCase):
    def test_makes_five_and_tags_originals_keeping_their_tags(self):
        client = FakeClient(library())
        made = run(client)
        self.assertEqual(len(made), 5)
        self.assertEqual([b.number for b in made], [1, 2, 3, 4, 5])
        used = [a.id for b in made for a in b.articles]
        self.assertEqual(len(used), len(set(used)))
        for doc_id in used:
            keys = set(client.docs[doc_id]["tags"])
            self.assertIn("bundled", keys)
            if int(doc_id[3:]) % 7 == 0:
                self.assertIn("india", keys, "an existing tag was dropped")

    def test_only_tops_up_and_numbers_continue(self):
        client = FakeClient(library())
        run(client)
        first = next(d for d in client.docs.values() if d["title"].startswith("Bundle 1 "))
        client.docs[first["id"]]["location"] = "archive"
        made = run(client)
        self.assertEqual([b.number for b in made], [6])

    def test_dry_run_changes_nothing(self):
        client = FakeClient(library())
        made = run(client, dry_run=True)
        self.assertEqual(len(made), 5)
        self.assertEqual(client.saved, [])
        self.assertEqual(client.updates, [])

    def test_never_reuses_articles_even_if_tagging_failed(self):
        client = FakeClient(library())
        run(client, target=1)
        bundle = next(d for d in client.docs.values() if d["title"].startswith("Bundle 1 "))
        ids = original_ids(bundle["notes"])
        for doc_id in ids:  # simulate a run that died before tagging
            client.docs[doc_id]["tags"].pop("bundled")
        made = run(client, target=2)
        self.assertFalse({a.id for a in made[0].articles} & set(ids))
        for doc_id in ids:
            self.assertIn("bundled", client.docs[doc_id]["tags"], "missing tag was not repaired")

    def test_skips_empty_saves(self):
        docs = library()
        client = FakeClient(docs)
        for d in docs[:30]:
            client.html[d["id"]] = "<p>Subscribe to keep reading.</p>"
        made = run(client)
        for b in made:
            for a in b.articles:
                self.assertGreaterEqual(int(a.id[3:]), 30)


class FinishedBundles(unittest.TestCase):
    def test_archiving_a_bundle_marks_it_and_its_originals_heard_once(self):
        client = FakeClient(library())
        run(client, target=1)
        bundle = next(d for d in client.docs.values() if d["title"].startswith("Bundle 1 "))
        bundle["location"] = "archive"
        run(client, target=1)
        self.assertIn("bundle-heard", client.docs[bundle["id"]]["tags"])
        self.assertIn("listen-bundle", client.docs[bundle["id"]]["tags"])
        for doc_id in original_ids(bundle["notes"]):
            tags = client.docs[doc_id]["tags"]
            self.assertIn("bundle-heard", tags)
            self.assertIn("bundled", tags)
            self.assertEqual(client.docs[doc_id]["location"], "later")
        before = len(client.updates)
        run(client, target=1)
        heard_updates = [u for u in client.updates[before:] if "bundle-heard" in u.get("tags", [])]
        self.assertEqual(heard_updates, [], "a settled bundle was processed again")


if __name__ == "__main__":
    unittest.main()
