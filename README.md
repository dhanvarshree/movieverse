# MovieVerse

MovieVerse is a Flask application for discovering movies, TV shows, and anime
with data from [The Movie Database (TMDB)](https://www.themoviedb.org/).

## Setup

1. Create and activate a Python virtual environment.
2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Create `.env` in the project root:

   ```text
   TMDB_API_KEY=your_tmdb_api_key
   ```

4. Start the app:

   ```powershell
   python app.py
   ```

## Routes

- `/` — trending movies and an anime collection
- `/explore` — popular movies and TV shows
- `/search?q=...` — movie, TV, and anime search
- `/details/<movie|tv>/<id>` — title details, cast, trailer, and recommendations

Explore and Search support `?page=` navigation (bounded to TMDB's first 500
pages). Recommendation sections merge TMDB recommendations and similar titles,
remove duplicates, and show up to 18 safe suggestions.

## Content behavior

Restricted titles are filtered from Home, Explore, and normal recommendation
sections using TMDB's adult flag, international age certifications, and mature
content keywords. This also applies to anime and TV shows. Titles with unknown
advisory metadata are hidden from passive discovery.

TMDB adult search is enabled only after a user submits a non-empty search, so a
restricted title can appear as a direct search result. Restricted recommendations
are allowed only when that explicit search's first matching title is itself
restricted. The interface does not display Adult or `18+` badges.
