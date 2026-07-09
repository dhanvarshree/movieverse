import unittest
from unittest.mock import patch

import app as movieverse


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class MovieVerseTests(unittest.TestCase):
    def setUp(self):
        movieverse.is_restricted_media.cache_clear()
        self.client = movieverse.app.test_client()

    @patch("app.requests.get")
    def test_home_filters_adult_titles(self, get):
        get.side_effect = [
            FakeResponse(
                {
                    "results": [
                        {"id": 1, "title": "Safe Movie", "adult": False},
                        {"id": 2, "title": "Hidden Movie", "adult": True},
                    ]
                }
            ),
            FakeResponse({"results": []}),
            FakeResponse(
                {
                    "release_dates": {
                        "results": [
                            {
                                "iso_3166_1": "US",
                                "release_dates": [{"certification": "PG-13"}],
                            }
                        ]
                    },
                    "keywords": {"keywords": [{"name": "family"}]},
                }
            ),
        ]

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Safe Movie", response.data)
        self.assertNotIn(b"Hidden Movie", response.data)

    @patch("app.requests.get")
    def test_search_supports_movies_tv_anime_and_allows_direct_adult_matches(self, get):
        get.side_effect = [
            FakeResponse(
                {
                    "results": [
                        {
                            "id": 10,
                            "media_type": "movie",
                            "title": "Adult Match",
                            "adult": True,
                        },
                        {
                            "id": 11,
                            "media_type": "tv",
                            "name": "TV Match",
                            "adult": False,
                        },
                        {
                            "id": 12,
                            "media_type": "tv",
                            "name": "Anime Match",
                            "adult": False,
                            "genre_ids": [16],
                            "original_language": "ja",
                        },
                        {"id": 13, "media_type": "person", "name": "Not a title"},
                    ]
                }
            ),
            FakeResponse(
                {
                    "results": [
                        {"id": 20, "title": "Safe Recommendation", "adult": False},
                        {"id": 21, "title": "Adult Recommendation", "adult": True},
                    ]
                }
            ),
            FakeResponse({"results": []}),
        ]

        response = self.client.get("/search?q=match")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Adult Match", response.data)
        self.assertIn(b"TV Match", response.data)
        self.assertIn(b"Anime Match", response.data)
        self.assertNotIn(b"Not a title", response.data)
        self.assertIn(b"Safe Recommendation", response.data)
        self.assertIn(b"Adult Recommendation", response.data)
        self.assertNotIn(b"18+", response.data)

        search_call = get.call_args_list[0]
        self.assertTrue(search_call.args[0].endswith("/search/multi"))
        self.assertEqual(search_call.kwargs["params"]["include_adult"], "true")

    @patch("app.requests.get")
    def test_empty_search_results_do_not_request_recommendations(self, get):
        get.return_value = FakeResponse({"results": []})

        response = self.client.get("/search?q=does-not-exist")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No movies, TV shows, or anime matched", response.data)
        self.assertEqual(get.call_count, 1)

    @patch("app.requests.get")
    def test_normal_search_filters_adult_recommendations(self, get):
        get.side_effect = [
            FakeResponse(
                {
                    "results": [
                        {
                            "id": 30,
                            "media_type": "movie",
                            "title": "Normal Movie",
                            "adult": False,
                        }
                    ]
                }
            ),
            FakeResponse(
                {
                    "release_dates": {
                        "results": [
                            {
                                "iso_3166_1": "US",
                                "release_dates": [{"certification": "PG-13"}],
                            }
                        ]
                    },
                    "keywords": {"keywords": [{"name": "adventure"}]},
                }
            ),
            FakeResponse(
                {
                    "results": [
                        {
                            "id": 31,
                            "title": "Hidden Adult Recommendation",
                            "adult": True,
                        }
                    ]
                }
            ),
            FakeResponse({"results": []}),
        ]

        response = self.client.get("/search?q=normal")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Normal Movie", response.data)
        self.assertNotIn(b"Hidden Adult Recommendation", response.data)

    @patch("app.requests.get")
    def test_tv_result_uses_tv_recommendations(self, get):
        get.side_effect = [
            FakeResponse(
                {
                    "results": [
                        {
                            "id": 42,
                            "media_type": "tv",
                            "name": "Series",
                            "adult": False,
                        }
                    ]
                }
            ),
            FakeResponse(
                {
                    "content_ratings": {
                        "results": [{"iso_3166_1": "US", "rating": "TV-14"}]
                    },
                    "keywords": {"results": [{"name": "drama"}]},
                }
            ),
            FakeResponse({"results": []}),
            FakeResponse({"results": []}),
        ]

        self.client.get("/search?q=series")

        self.assertTrue(
            any(
                call.args[0].endswith("/tv/42/recommendations")
                for call in get.call_args_list
            )
        )

    @patch("app.requests.get")
    def test_details_page_renders_movie_data(self, get):
        get.side_effect = [
            FakeResponse(
                {
                    "id": 100,
                    "title": "Detail Movie",
                    "adult": False,
                    "genres": [{"id": 18, "name": "Drama"}],
                    "credits": {
                        "cast": [{"name": "Lead Actor", "character": "Hero"}]
                    },
                    "videos": {
                        "results": [
                            {
                                "site": "YouTube",
                                "type": "Trailer",
                                "official": True,
                                "key": "trailer-key",
                            }
                        ]
                    },
                    "release_dates": {
                        "results": [
                            {
                                "iso_3166_1": "US",
                                "release_dates": [{"certification": "PG-13"}],
                            }
                        ]
                    },
                    "keywords": {"keywords": [{"name": "drama"}]},
                }
            ),
            FakeResponse({"results": []}),
            FakeResponse({"results": []}),
        ]

        response = self.client.get("/details/movie/100")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Detail Movie", response.data)
        self.assertIn(b"Lead Actor", response.data)
        self.assertIn(b"trailer-key", response.data)

    @patch("app.tmdb_get")
    def test_recommendations_merge_similar_and_remove_duplicates(self, tmdb_get):
        tmdb_get.side_effect = [
            {
                "results": [
                    {"id": 201, "title": "Recommended One", "adult": False},
                    {"id": 202, "title": "Shared Title", "adult": False},
                ]
            },
            {
                "results": [
                    {"id": 202, "title": "Shared Title", "adult": False},
                    {"id": 203, "title": "Similar One", "adult": False},
                ]
            },
        ]
        seed = {
            "id": 200,
            "media_type": "movie",
            "display_title": "Seed",
            "adult": True,
        }

        results = movieverse.get_recommendations(
            seed,
            allow_restricted=True,
        )

        self.assertEqual([item["id"] for item in results], [201, 202, 203])

    @patch("app.requests.get")
    def test_search_pagination_preserves_query(self, get):
        get.return_value = FakeResponse({"results": [], "total_pages": 4})

        response = self.client.get("/search?q=naruto&page=2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(get.call_args.kwargs["params"]["page"], 2)
        self.assertIn(b"q=naruto&amp;page=1", response.data)
        self.assertIn(b"q=naruto&amp;page=3", response.data)

    @patch("app.requests.get")
    def test_explore_pagination_requests_selected_page(self, get):
        get.side_effect = [
            FakeResponse({"results": [], "total_pages": 4}),
            FakeResponse({"results": [], "total_pages": 6}),
        ]

        response = self.client.get("/explore?page=2")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            all(call.kwargs["params"]["page"] == 2 for call in get.call_args_list)
        )
        self.assertIn(b"Page 2 of 6", response.data)
        self.assertIn(b"/explore?page=3", response.data)

    def test_certification_and_keywords_detect_restricted_movies(self):
        damage = {
            "adult": False,
            "release_dates": {
                "results": [
                    {
                        "iso_3166_1": "US",
                        "release_dates": [{"certification": "R"}],
                    },
                    {
                        "iso_3166_1": "GB",
                        "release_dates": [{"certification": "18"}],
                    },
                ]
            },
            "keywords": {"keywords": [{"name": "voyeur"}]},
        }

        self.assertTrue(movieverse.metadata_is_restricted(damage, "movie"))

    def test_certification_and_keywords_detect_restricted_anime(self):
        mature_anime = {
            "adult": False,
            "content_ratings": {
                "results": [
                    {"iso_3166_1": "US", "rating": "TV-MA"},
                    {"iso_3166_1": "JP", "rating": "18+"},
                ]
            },
            "keywords": {
                "results": [
                    {"name": "anime"},
                    {"name": "ecchi"},
                    {"name": "harem"},
                ]
            },
        }

        self.assertTrue(movieverse.metadata_is_restricted(mature_anime, "tv"))

    def test_safe_certification_and_keywords_are_allowed(self):
        family_title = {
            "adult": False,
            "release_dates": {
                "results": [
                    {
                        "iso_3166_1": "US",
                        "release_dates": [{"certification": "PG-13"}],
                    }
                ]
            },
            "keywords": {"keywords": [{"name": "family"}, {"name": "adventure"}]},
        }

        self.assertFalse(movieverse.metadata_is_restricted(family_title, "movie"))


if __name__ == "__main__":
    unittest.main()
