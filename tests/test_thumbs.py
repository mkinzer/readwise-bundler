import io
import json
import unittest
import urllib.error

from PIL import Image

from readwise_bundler.hosting import GitHubBranchHost
from readwise_bundler.picking import to_article
from readwise_bundler.thumbs import HEIGHT, WIDTH, make_collage, make_list_card, style_for

from helpers import make_doc


def jpeg_size(data):
    image = Image.open(io.BytesIO(data))
    return image.format, image.size


class Styles(unittest.TestCase):
    def test_alternate_and_fixed(self):
        self.assertEqual([style_for("alternate", n) for n in (7, 8, 9)], ["collage", "list", "collage"])
        self.assertEqual(style_for("list", 7), "list")
        self.assertIsNone(style_for("none", 7))


class Drawing(unittest.TestCase):
    def test_list_card(self):
        data = make_list_card(6, ["FP Books", "Tunisia", "Equality Philosopher", "Mexican Cartels"])
        self.assertEqual(jpeg_size(data), ("JPEG", (WIDTH, HEIGHT)))

    def test_collage_with_and_without_pictures(self):
        arts = [to_article(make_doc(i, image_url=f"https://img/{i}")) for i in range(4)]
        picture = Image.new("RGB", (900, 600), (120, 60, 30))
        fetch = lambda url: picture if url.endswith(("0", "2")) else None
        for n in (2, 3, 4):
            data = make_collage(9, arts[:n], ["One", "Two Words", "Three Little Words", "Four"][:n], fetch=fetch)
            self.assertEqual(jpeg_size(data), ("JPEG", (WIDTH, HEIGHT)))


class FakeGitHub:
    def __init__(self, existing_sha=None):
        self.calls = []
        self.existing_sha = existing_sha

    def __call__(self, request, timeout=None):
        body = json.loads(request.data) if request.data else None
        self.calls.append((request.get_method(), request.full_url, body))
        if request.get_method() == "GET":
            if not self.existing_sha:
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
            return _Response({"sha": self.existing_sha})
        return _Response({"content": {"sha": "new"}})


class _Response(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode())
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Hosting(unittest.TestCase):
    def test_new_file(self):
        github = FakeGitHub()
        host = GitHubBranchHost("me/repo", "token", opener=github)
        url = host.put("bundles/b-7.jpg", b"jpeg", "Thumbnail")
        self.assertEqual(url, "https://raw.githubusercontent.com/me/repo/thumbnails/bundles/b-7.jpg")
        method, address, body = github.calls[-1]
        self.assertEqual((method, address), ("PUT", "https://api.github.com/repos/me/repo/contents/bundles/b-7.jpg"))
        self.assertEqual(body["branch"], "thumbnails")
        self.assertNotIn("sha", body)

    def test_replacing_a_file_sends_its_sha(self):
        github = FakeGitHub(existing_sha="abc")
        GitHubBranchHost("me/repo", "token", opener=github).put("x.jpg", b"jpeg", "Thumbnail")
        self.assertEqual(github.calls[-1][2]["sha"], "abc")


if __name__ == "__main__":
    unittest.main()
