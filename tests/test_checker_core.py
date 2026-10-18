import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(ROOT, ".core", "checker_core.py")
SPEC = importlib.util.spec_from_file_location("soundcloud_checker_core", CORE_PATH)
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)


class TypeParserTests(unittest.TestCase):
    def test_default_is_four_character_permalink(self):
        lengths, alphabet, label = CORE.parse_type("")
        self.assertEqual(lengths, [4])
        self.assertEqual(alphabet, CORE.PERMALINK_CHARS)
        self.assertIn("4 permalink characters", label)

    def test_supported_character_sets(self):
        self.assertEqual(CORE.parse_type("3L")[1], CORE.LETTERS)
        self.assertEqual(CORE.parse_type("4C")[1], CORE.ALNUM)
        self.assertEqual(CORE.parse_type("5P")[1], CORE.PERMALINK_CHARS)

    def test_ranges_and_lists(self):
        self.assertEqual(CORE.parse_type("3-5P")[0], [3, 4, 5])
        self.assertEqual(CORE.parse_type("3,5L")[0], [3, 5])
        self.assertIsNone(CORE.parse_type("3-4,6P"))

    def test_lengths_outside_soundcloud_limits_are_rejected(self):
        self.assertIsNone(CORE.parse_type("2P"))
        self.assertIsNone(CORE.parse_type("26P"))


class CandidateTests(unittest.TestCase):
    def test_validation_matches_permalink_rules(self):
        self.assertTrue(CORE.validate_username("beat_maker-2"))
        self.assertFalse(CORE.validate_username("ab"))
        self.assertFalse(CORE.validate_username("UpperCase"))
        self.assertFalse(CORE.validate_username("my_soundcloud"))
        self.assertFalse(CORE.validate_username("has space"))
        self.assertFalse(CORE.validate_username("a" * 26))

    def test_stream_yields_every_candidate_once(self):
        candidates = list(CORE.stream((3,), "ab"))
        self.assertEqual(len(candidates), 8)
        self.assertEqual(len(set(candidates)), 8)
        self.assertTrue(all(len(name) == 3 and set(name) <= set("ab")
                            for name in candidates))

    def test_stream_handles_multiple_lengths(self):
        candidates = list(CORE.stream((2, 3), "ab"))
        self.assertEqual(len(candidates), 12)
        self.assertEqual(len(set(candidates)), 12)
        self.assertEqual({len(name) for name in candidates}, {2, 3})


class ResponseClassificationTests(unittest.TestCase):
    def test_http_not_found_means_no_public_profile(self):
        self.assertEqual(
            CORE.classify_profile_response(404, "not found", "freshname", "https://soundcloud.com/freshname"),
            "available",
        )

    def test_profile_metadata_is_taken(self):
        html = (
            '<meta property="og:type" content="profile">'
            '<meta property="og:url" content="https://soundcloud.com/artist_name">'
        )
        self.assertEqual(
            CORE.classify_profile_response(
                200, html, "artist_name", "https://soundcloud.com/artist_name"
            ),
            "taken",
        )

    def test_unknown_success_page_is_not_claimed_available(self):
        self.assertEqual(
            CORE.classify_profile_response(
                200, "<html><title>SoundCloud</title></html>",
                "freshname", "https://soundcloud.com/freshname",
            ),
            "error",
        )

    def test_explicit_not_found_page_is_available(self):
        self.assertEqual(
            CORE.classify_profile_response(
                200, "<html>We couldn't find that page</html>",
                "freshname", "https://soundcloud.com/freshname",
            ),
            "available",
        )


class AsyncCheckTests(unittest.IsolatedAsyncioTestCase):
    class Response:
        def __init__(self, status, url, body=""):
            self.status = status
            self.url = url
            self.headers = {}
            self.body = body

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def text(self, **_kwargs):
            return self.body

    class Session:
        def __init__(self, response):
            self.response = response
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return self.response

    async def test_invalid_candidate_is_filtered_without_a_request(self):
        session = self.Session(self.Response(404, "https://soundcloud.com/"))
        result = await CORE.check(session, "UPPER", {"ratelimit": 0, "ratelimit_at": 0.0})
        self.assertEqual(result, "invalid")
        self.assertEqual(session.calls, [])

    async def test_profile_url_is_checked_with_a_get(self):
        session = self.Session(self.Response(404, "https://soundcloud.com/newname"))
        result = await CORE.check(session, "newname", {"ratelimit": 0, "ratelimit_at": 0.0})
        self.assertEqual(result, "available")
        self.assertEqual(session.calls[0][0], "https://soundcloud.com/newname")


if __name__ == "__main__":
    unittest.main()
