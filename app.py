import os
import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, abort, redirect, render_template, request, url_for


load_dotenv(Path(__file__).parent / ".env")

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_API_URL = "https://api.themoviedb.org/3"

app = Flask(__name__)
MAX_TMDB_PAGE = 500

RESTRICTED_CERTIFICATIONS = {
    "A",
    "AO",
    "MA15+",
    "NC17",
    "R",
    "R18",
    "R18+",
    "TVMA",
    "VM18",
    "X",
    "XXX",
}

RESTRICTED_KEYWORDS = {
    "adult animation",
    "adult humor",
    "bdsm",
    "brothel",
    "ecchi",
    "erotic",
    "erotica",
    "explicit sex",
    "fan service",
    "fetish",
    "hardcore",
    "harem",
    "hentai",
    "incest",
    "nude",
    "nudity",
    "porn",
    "pornographic",
    "pornography",
    "prostitute",
    "seduction",
    "sex",
    "sexual content",
    "sexual humor",
    "sexploitation",
    "softcore",
    "strip club",
    "stripper",
}


class TMDBError(RuntimeError):
    """A user-safe wrapper for TMDB request failures."""


def tmdb_get(path, **params):
    if not TMDB_API_KEY:
        raise TMDBError("TMDB_API_KEY is not configured.")

    request_params = {"api_key": TMDB_API_KEY, "language": "en-US", **params}

    try:
        response = requests.get(
            f"{TMDB_API_URL}/{path.lstrip('/')}",
            params=request_params,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise TMDBError("Movie data is temporarily unavailable.") from exc

    if not isinstance(payload, dict):
        raise TMDBError("TMDB returned an unexpected response.")

    return payload


def prepare_media(item, fallback_type=None):
    media_type = item.get("media_type") or fallback_type
    if media_type not in {"movie", "tv"}:
        return None

    media = dict(item)
    media["media_type"] = media_type
    media["display_title"] = media.get("title") or media.get("name") or "Untitled"

    release_date = media.get("release_date") or media.get("first_air_date") or ""
    media["year"] = release_date[:4]

    genre_ids = set(media.get("genre_ids") or [])
    genre_ids.update(
        genre.get("id") for genre in media.get("genres", []) if genre.get("id")
    )
    is_anime = (
        16 in genre_ids
        and (
            media.get("original_language") == "ja"
            or "JP" in (media.get("origin_country") or [])
        )
    )
    media["media_label"] = (
        "Anime" if is_anime else "Movie" if media_type == "movie" else "TV Show"
    )
    media["adult"] = bool(media.get("adult", False))
    return media


def prepare_results(items, fallback_type=None, allow_adult=False):
    prepared = []

    for item in items or []:
        media = prepare_media(item, fallback_type)
        if media and (allow_adult or not media["adult"]):
            prepared.append(media)

    return prepared


def advisory_append(media_type):
    return "release_dates,keywords" if media_type == "movie" else "content_ratings,keywords"


def metadata_is_restricted(payload, media_type):
    if payload.get("adult"):
        return True

    certifications = []
    if media_type == "movie":
        for country in payload.get("release_dates", {}).get("results", []):
            country_code = country.get("iso_3166_1")
            for release in country.get("release_dates", []):
                certification = (release.get("certification") or "").strip()
                if certification:
                    certifications.append((country_code, certification))
    else:
        for rating in payload.get("content_ratings", {}).get("results", []):
            certification = (rating.get("rating") or "").strip()
            if certification:
                certifications.append(
                    (rating.get("iso_3166_1"), certification)
                )

    keyword_payload = payload.get("keywords", {})
    keyword_items = keyword_payload.get("keywords") or keyword_payload.get("results") or []
    keywords = {
        (keyword.get("name") or "").strip().casefold()
        for keyword in keyword_items
        if keyword.get("name")
    }

    for country_code, certification in certifications:
        compact = re.sub(r"[\s_-]", "", certification.upper())
        if compact in RESTRICTED_CERTIFICATIONS:
            # "A" is an adult-only classification in India. Other countries
            # can use the same letter differently.
            if compact != "A" or country_code == "IN":
                return True

        ages = [int(age) for age in re.findall(r"\d{2}", compact)]
        if any(age >= 18 for age in ages):
            return True

    if keywords.intersection(RESTRICTED_KEYWORDS):
        return True

    # Unknown titles are hidden from passive discovery. They can still be
    # reached through an explicit search.
    return not certifications and not keywords


@lru_cache(maxsize=2048)
def is_restricted_media(media_type, media_id):
    payload = tmdb_get(
        f"{media_type}/{media_id}",
        append_to_response=advisory_append(media_type),
    )
    return metadata_is_restricted(payload, media_type)


def media_is_restricted(media):
    if media["adult"]:
        return True

    try:
        return is_restricted_media(media["media_type"], media["id"])
    except TMDBError:
        # Discovery fails closed so an API metadata failure cannot leak a
        # restricted title onto Home or Explore.
        return True


def prepare_safe_results(items, fallback_type=None):
    prepared = prepare_results(items, fallback_type=fallback_type)
    if not prepared:
        return []

    worker_count = min(8, len(prepared))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        restricted = list(executor.map(media_is_restricted, prepared))

    return [
        media
        for media, is_restricted in zip(prepared, restricted)
        if not is_restricted
    ]


def requested_page():
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    return max(1, min(page, MAX_TMDB_PAGE))


def get_recommendations(seed, limit=18, allow_restricted=False):
    if not seed:
        return []

    media_type = seed["media_type"]
    combined = []
    for endpoint in ("recommendations", "similar"):
        try:
            payload = tmdb_get(
                f"{media_type}/{seed['id']}/{endpoint}",
                page=1,
            )
            combined.extend(payload.get("results", []))
        except TMDBError:
            continue

    unique = []
    seen_ids = {seed["id"]}
    for item in combined:
        item_id = item.get("id")
        if item_id and item_id not in seen_ids:
            seen_ids.add(item_id)
            unique.append(item)

    if allow_restricted:
        recommendations = prepare_results(
            unique,
            fallback_type=media_type,
            allow_adult=True,
        )
    else:
        recommendations = prepare_safe_results(
            unique,
            fallback_type=media_type,
        )

    return recommendations[:limit]


@app.route("/")
def home():
    error = None
    movies = []
    anime = []

    try:
        trending = tmdb_get("trending/movie/week")
        anime_results = tmdb_get(
            "discover/tv",
            with_genres=16,
            with_origin_country="JP",
            sort_by="popularity.desc",
            include_adult="false",
            page=1,
        )
        movies = prepare_safe_results(
            trending.get("results", []), fallback_type="movie"
        )
        anime = prepare_safe_results(
            anime_results.get("results", []), fallback_type="tv"
        )
    except TMDBError as exc:
        error = str(exc)

    return render_template("index.html", movies=movies, anime=anime, error=error)


@app.route("/explore")
def explore():
    page = requested_page()
    error = None
    movies = []
    shows = []
    total_pages = page

    try:
        popular_movies = tmdb_get(
            "movie/popular", include_adult="false", page=page
        )
        popular_shows = tmdb_get(
            "tv/popular", include_adult="false", page=page
        )
        movies = prepare_safe_results(
            popular_movies.get("results", []), fallback_type="movie"
        )
        shows = prepare_safe_results(
            popular_shows.get("results", []), fallback_type="tv"
        )
        total_pages = min(
            MAX_TMDB_PAGE,
            max(
                popular_movies.get("total_pages", 1),
                popular_shows.get("total_pages", 1),
            ),
        )
    except TMDBError as exc:
        error = str(exc)

    return render_template(
        "explore.html",
        movies=movies,
        shows=shows,
        page=page,
        total_pages=total_pages,
        error=error,
    )


@app.route("/search")
def search():
    query = (request.args.get("q") or "").strip()
    if not query:
        return redirect(url_for("home"))

    page = requested_page()
    error = None
    results = []
    recommendations = []
    total_pages = page

    try:
        payload = tmdb_get(
            "search/multi",
            query=query,
            include_adult="true",
            page=page,
        )
        # Adult content is intentionally allowed only in these explicit search results.
        results = prepare_results(payload.get("results", []), allow_adult=True)
        total_pages = min(MAX_TMDB_PAGE, payload.get("total_pages", 1))
        if results:
            seed_is_restricted = media_is_restricted(results[0])
            recommendations = get_recommendations(
                results[0],
                allow_restricted=seed_is_restricted,
            )
    except TMDBError as exc:
        error = str(exc)

    return render_template(
        "search.html",
        results=results,
        recommendations=recommendations,
        query=query,
        page=page,
        total_pages=total_pages,
        error=error,
    )


@app.route("/details/<media_type>/<int:media_id>")
def details(media_type, media_id):
    if media_type not in {"movie", "tv"}:
        abort(404)

    try:
        payload = tmdb_get(
            f"{media_type}/{media_id}",
            append_to_response=f"credits,videos,{advisory_append(media_type)}",
        )
        media = prepare_media(payload, media_type)
        if not media:
            abort(404)

        videos = payload.get("videos", {}).get("results", [])
        trailer = next(
            (
                video
                for video in videos
                if video.get("site") == "YouTube"
                and video.get("type") == "Trailer"
                and video.get("official")
            ),
            None,
        )
        if not trailer:
            trailer = next(
                (
                    video
                    for video in videos
                    if video.get("site") == "YouTube"
                    and video.get("type") in {"Trailer", "Teaser"}
                ),
                None,
            )

        cast = payload.get("credits", {}).get("cast", [])[:10]
        # Restricted details cannot be discovered from Home or Explore. If a
        # user reached one through explicit search, related titles are allowed.
        detail_is_restricted = metadata_is_restricted(payload, media_type)
        recommendations = get_recommendations(
            media,
            allow_restricted=detail_is_restricted,
        )
    except TMDBError as exc:
        return render_template(
            "details.html",
            media=None,
            cast=[],
            trailer=None,
            recommendations=[],
            error=str(exc),
        ), 503

    return render_template(
        "details.html",
        media=media,
        cast=cast,
        trailer=trailer,
        recommendations=recommendations,
        error=None,
    )


if __name__ == "__main__":
    app.run(debug=True)
