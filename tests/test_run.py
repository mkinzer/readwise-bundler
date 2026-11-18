import random
import unittest
from datetime import date

from readwise_bundler.run import TARGET_OPEN, Run, original_ids

from readwise_bundler.labels import title_label

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
    kw.setdefault("labeler", lambda arts: [title_label(a.title) for a in arts])
    kw.setdefault("thumbnails", "none")
    return Run(client, **kw).go()


class FakeHost:
    def __init__(self, fail=False):
        self.files, self.fail = {}, fail

    def put(self, path, data, message):
        if self.fail:
            raise RuntimeError("GitHub is down")
        self.files[path] = data
        return f"https://host.example/{path}"


class FillingTheShelf(unittest.TestCase):
    def test_fills_the_shelf_and_tags_originals_keeping_their_tags(self):
        client = FakeClient(library())
        made = run(client)
        self.assertEqual(TARGET_OPEN, 10)
        self.assertEqual([b.number for b in made], list(range(1, TARGET_OPEN + 1)))
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
        self.assertEqual([b.number for b in made], [TARGET_OPEN + 1])

    def test_dry_run_changes_nothing(self):
        client = FakeClient(library())
        made = run(client, dry_run=True)
        self.assertEqual(len(made), TARGET_OPEN)
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


class LabelsAndThumbnails(unittest.TestCase):
    topics = staticmethod(lambda arts: [f"Topic {i}" for i in range(len(arts))])

    def test_new_bundles_get_labels_and_alternating_thumbnails(self):
        client, host = FakeClient(library()), FakeHost()
        made = run(client, target=2, labeler=self.topics, thumbnails="alternate", host=host,
                   fetch_image=lambda url: None)
        self.assertRegex(made[0].title, r"^Bundle 1 \(\d{4}(–\d{4})?\) \| Topic 0 \| Topic 1")
        self.assertEqual(sorted(p.rsplit("-", 1)[-1] for p in host.files), ["collage.jpg", "list.jpg"])
        self.assertTrue(all(p["image_url"].startswith("https://host.example/bundles/") for p in client.saved))

    def test_a_failed_upload_does_not_stop_the_bundle(self):
        client, log = FakeClient(library()), []
        made = run(client, target=1, thumbnails="list", host=FakeHost(fail=True), log=log.append)
        self.assertEqual(len(made), 1)
        self.assertNotIn("image_url", client.saved[0])
        self.assertTrue(any("uploading it failed" in line for line in log))

    def test_refresh_renames_only_waiting_bundles(self):
        client = FakeClient(library())
        run(client, target=2)
        first, second = sorted((d for d in client.docs.values() if d["id"].startswith("bundle")),
                               key=lambda d: d["title"])
        first["location"] = "archive"
        archived_title = first["title"]
        host = FakeHost()
        done = Run(client, labeler=lambda arts: [f"Fresh {i}" for i in range(len(arts))],
                   thumbnails="list", host=host, log=lambda *_: None,
                   made_on=date(2026, 11, 18)).refresh()
        self.assertEqual(done, 1)
        self.assertIn("| Fresh 0 | Fresh 1", client.docs[second["id"]]["title"])
        self.assertTrue(client.docs[second["id"]]["image_url"].startswith("https://host.example/"))
        self.assertEqual(client.docs[first["id"]]["title"], archived_title)

    def test_refresh_dry_run_changes_nothing(self):
        client = FakeClient(library())
        run(client, target=1)
        before = len(client.updates)
        Run(client, labeler=self.topics, thumbnails="none", dry_run=True, log=lambda *_: None).refresh()
        self.assertEqual(len(client.updates), before)


if __name__ == "__main__":
    unittest.main()
