import unittest
from datetime import date

from readwise_bundler.compose import Bundle, clean_article_html, clean_summary, looks_complete
from readwise_bundler.picking import to_article
from readwise_bundler.run import original_ids

from helpers import make_doc


class Cleaning(unittest.TestCase):
    def test_strips_what_reads_badly(self):
        raw = (
            '<h1 class="x">Heading</h1><p style="c">Text &amp; more <a href="https://e.com" '
            'onclick="x">link</a> <a href="javascript:alert(1)">bad</a></p>'
            '<figure><img src="a.jpg"><figcaption>Photo: Getty</figcaption></figure>'
            "<script>evil()</script><p></p><h2>Sub</h2><img src='b.jpg'/><p>End</p>"
        )
        out = clean_article_html(raw).html
        self.assertIn("<h3>Heading</h3>", out)
        self.assertIn("<h3>Sub</h3>", out)
        self.assertIn('<a href="https://e.com">link</a>', out)
        self.assertIn("<a>bad</a>", out)
        self.assertIn("Text &amp; more", out)
        for gone in ("Getty", "img", "evil", "class=", "style=", "onclick", "<p></p>"):
            self.assertNotIn(gone, out)

    def test_drops_short_page_furniture_only(self):
        raw = ("<p>Subscribe now</p>"
               "<p>Image Credit: Someone via Getty Images</p>"
               "<p>Sign up to receive our biggest stories as soon as they’re published.</p>"
               "<p>Subscribe to the Big Story newsletter.</p>"
               "<p>Photo illustration by A Person; source photographs by others.</p>"
               "<p>The newsletter business boomed, and few who subscribe ever cancel.</p>"
               "<p>Photographers memorialized the murders, and the images circulated widely.</p>")
        out = clean_article_html(raw).html
        for gone in ("Subscribe now", "Getty", "biggest stories", "Big Story", "Photo illustration"):
            self.assertNotIn(gone, out)
        self.assertIn("newsletter business boomed", out)
        self.assertIn("Photographers memorialized", out)

    def test_drops_short_promotional_blocks(self):
        raw = ("<p>ProPublica is a nonprofit newsroom that investigates abuses of power. Sign up to "
               "receive our biggest stories as soon as they’re published.</p><p>On a spring day.</p>")
        out = clean_article_html(raw).html
        self.assertNotIn("nonprofit newsroom", out)
        self.assertIn("On a spring day.", out)


class Summaries(unittest.TestCase):
    def test_keeps_real_sentences_and_drops_site_boilerplate(self):
        self.assertEqual(
            clean_summary("Trump’s trade representative had one mission. The results? Trade wars. "
                          "ProPublica is a nonprofit newsroom that investigates abuses of power."),
            "Trump’s trade representative had one mission. The results? Trade wars.")
        self.assertEqual(
            clean_summary("Official websites use .gov A .gov website belongs to an official government "
                          "organization in the United States. Secure .gov websites use HTTPS A lock ( ) "
                          "or https:// means you've safely connected to the .gov website."), "")
        self.assertEqual(clean_summary("A woo-hoo heard around the world"), "A woo-hoo heard around the world.")

    def test_flags_empty_saves(self):
        article = to_article(make_doc(1, minutes=10))  # ~2,380 words promised
        self.assertFalse(looks_complete(article, clean_article_html("<p>Subscribe to read.</p>")))
        full = "<p>" + " ".join(["word"] * 2400) + "</p>"
        self.assertTrue(looks_complete(article, clean_article_html(full)))


class Assembly(unittest.TestCase):
    def setUp(self):
        docs = [make_doc(1, minutes=12, published="2025-03-03"),
                make_doc(2, minutes=30, published=None),
                make_doc(3, minutes=8, published="2024-01-15", site_name="", author="")]
        self.articles = [to_article(d) for d in docs]
        bodies = {a.id: f"<p>Body of {a.title}.</p>" for a in self.articles}
        self.bundle = Bundle(number=12, articles=self.articles, bodies=bodies, made_on=date(2026, 11, 8))

    def test_title_and_url(self):
        self.assertEqual(self.bundle.title, "Bundle 12 · 3 articles · 50 min")
        self.assertTrue(self.bundle.url.startswith("https://readwise-bundler.local/bundle/12-"))
        same = Bundle(number=12, articles=list(reversed(self.articles)), bodies={}, made_on=date.today())
        self.assertEqual(same.url, self.bundle.url)

    def test_spoken_structure(self):
        html = self.bundle.html()
        expected_in_order = [
            "Bundle 12, bundled on November 8, 2026.",
            "This bundle includes three different articles, about 50 minutes in total.",
            "First: “Article 1”, by Author 1, from Site 1, published March 3, 2025. About 12 minutes. Summary of article 1.",
            "Third: “Article 3”, published January 15, 2024. About 8 minutes.",
            "<h2>Article 1 of 3: Article 1</h2>",
            "By Author 1, from Site 1, published March 3, 2025. About 12 minutes.",
            "Body of Article 1.",
            "Ding. Ding. Ding.",
            "End of article one: “Article 1”.",
            "<h2>Article 3 of 3: Article 3</h2>",
            "<p>Published January 15, 2024. About 8 minutes.</p>",
            "End of bundle 12. That was all three articles.",
        ]
        position = -1
        for piece in expected_in_order:
            found = html.find(piece, position + 1)
            self.assertGreater(found, position, f"missing or out of order: {piece}")
            position = found

    def test_notes_lead_back_to_the_originals(self):
        self.assertEqual(original_ids(self.bundle.notes()), [a.id for a in self.articles])

    def test_payload(self):
        payload = self.bundle.payload()
        self.assertEqual(payload["location"], "later")
        self.assertEqual(payload["tags"], ["listen-bundle"])
        self.assertEqual(payload["language"], "en")
        self.assertFalse(payload["should_clean_html"])


if __name__ == "__main__":
    unittest.main()
