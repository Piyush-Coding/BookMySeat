"""
Import movies from TMDB into the existing BookMySeat booking architecture.

Architecture used (unchanged):
  Movie → Theater (venue name + showtime) → Seat → Booking

Usage:
  python manage.py import_tmdb_movies --limit 10
  python manage.py import_tmdb_movies --limit 100 --skip-existing
  python manage.py import_tmdb_movies --limit 5000 --update
  python manage.py import_tmdb_movies --limit 10 --dry-run
"""

from __future__ import annotations

import random
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

from movies.models import Genre, Language, Movie, Seat, Theater


# ISO 639-1 → display name used by Language model
LANGUAGE_CODE_MAP = {
    "en": "English",
    "hi": "Hindi",
    "es": "Spanish",
    "fr": "French",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
    "ta": "Tamil",
    "te": "Telugu",
    "ml": "Malayalam",
    "kn": "Kannada",
    "bn": "Bengali",
    "mr": "Marathi",
    "pa": "Punjabi",
    "th": "Thai",
    "tr": "Turkish",
    "nl": "Dutch",
    "sv": "Swedish",
    "pl": "Polish",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "fa": "Persian",
    "he": "Hebrew",
    "uk": "Ukrainian",
    "cs": "Czech",
    "ro": "Romanian",
    "hu": "Hungarian",
    "el": "Greek",
    "da": "Danish",
    "fi": "Finnish",
    "no": "Norwegian",
}

# Demo venue names shared across movies (matches allocate_theaters_seats.py)
THEATER_NAMES = [
    "PVR Cinemas",
    "INOX Multiplex",
    "Cinepolis",
    "Piyush Complex",
    "Prashant Complex",
    "Miraj Cinemas",
    "Carnival Cinemas",
    "Wave Cinemas",
]

SHOW_HOURS = [10, 13, 16, 19, 21]
SEAT_LABELS = [f"{row}{num}" for row in ("A", "B") for num in range(1, 11)]
CAST_LIMIT = 8
REQUEST_TIMEOUT = 20
MAX_RETRIES = 5
DISCOVER_PAGE_SIZE = 20


class Command(BaseCommand):
    help = (
        "Import movies from TMDB and create Theater showtimes + Seats "
        "using the existing booking architecture."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=10,
            help="Number of unique movies to process (default: 10).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and validate data without writing to the database.",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="Update existing movies matched by tmdb_id.",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Skip movies that already exist by tmdb_id (default behavior).",
        )
        parser.add_argument(
            "--shows-per-movie",
            type=int,
            default=2,
            help="Number of Theater showtimes to create per movie (default: 2).",
        )
        parser.add_argument(
            "--start-page",
            type=int,
            default=1,
            help="TMDB discover page to start from (default: 1).",
        )
        parser.add_argument(
            "--import-target",
            type=int,
            default=None,
            help="Keep importing until this many NEW movies are added (ignores --limit).",
        )

    def _tmdb_id_exists(self, tmdb_id: int) -> bool:
        return Movie.objects.filter(tmdb_id=tmdb_id).exists()

    def handle(self, *args, **options):
        limit = options["limit"]
        dry_run = options["dry_run"]
        update = options["update"]
        skip_existing = options["skip_existing"] or not update
        shows_per_movie = max(1, options["shows_per_movie"])
        start_page = max(1, options["start_page"])
        import_target = options.get("import_target")

        if import_target is None and limit < 1:
            raise CommandError("--limit must be at least 1")
        if import_target is not None and import_target < 1:
            raise CommandError("--import-target must be at least 1")

        api_key = getattr(settings, "TMDB_API_KEY", "") or ""
        token = getattr(settings, "TMDB_API_READ_ACCESS_TOKEN", "") or ""
        if not api_key and not token:
            raise CommandError(
                "TMDB credentials missing. Set TMDB_API_KEY and/or "
                "TMDB_API_READ_ACCESS_TOKEN in your .env file."
            )

        self.base_url = getattr(
            settings, "TMDB_API_BASE_URL", "https://api.themoviedb.org/3"
        ).rstrip("/")
        self.image_base = getattr(
            settings, "TMDB_IMAGE_BASE_URL", "https://image.tmdb.org/t/p/w500"
        ).rstrip("/")
        self.api_key = api_key
        self.token = token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "BookMySeat-TMDB-Importer/1.0",
            }
        )
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

        stats = {
            "processed": 0,
            "imported": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "theaters_created": 0,
            "seats_created": 0,
        }

        existing_tmdb_ids = {
            int(tmdb_id)
            for tmdb_id in Movie.objects.exclude(tmdb_id__isnull=True).values_list(
                "tmdb_id", flat=True
            )
            if tmdb_id is not None
        }
        seen_in_run: set[int] = set()
        start_count = len(existing_tmdb_ids)

        goal_label = (
            f"import_target={import_target}"
            if import_target is not None
            else f"limit={limit}"
        )
        self.stdout.write(
            self.style.NOTICE(
                f"Starting TMDB import ({goal_label}, dry_run={dry_run}, "
                f"update={update}, skip_existing={skip_existing}, "
                f"existing_in_db={start_count})"
            )
        )

        page = start_page
        total_pages = None

        while True:
            if import_target is not None:
                if stats["imported"] >= import_target:
                    break
            elif stats["processed"] >= limit:
                break
            discover = self._request_json(
                "/discover/movie",
                params={
                    "page": page,
                    "sort_by": "popularity.desc",
                    "include_adult": "false",
                    "language": "en-US",
                },
            )
            if discover is None:
                self.stdout.write(
                    self.style.ERROR(f"Failed to fetch discover page {page}. Stopping.")
                )
                break

            results = discover.get("results") or []
            if total_pages is None:
                # TMDB caps discover at 500 pages
                total_pages = min(int(discover.get("total_pages") or 1), 500)
                self.stdout.write(f"TMDB discover total pages available: {total_pages}")

            if not results:
                self.stdout.write(self.style.WARNING(f"No results on page {page}."))
                break

            for item in results:
                if import_target is None and stats["processed"] >= limit:
                    break
                if import_target is not None and stats["imported"] >= import_target:
                    break

                tmdb_id = item.get("id")
                title = (item.get("title") or item.get("name") or "Untitled").strip()
                if tmdb_id is not None:
                    tmdb_id = int(tmdb_id)
                index = stats["processed"] + 1
                prefix = (
                    f"[{stats['imported'] + 1}/{import_target}]"
                    if import_target is not None
                    else f"[{index}/{limit}]"
                )

                if not tmdb_id:
                    self.stdout.write(f"{prefix} Failed: missing TMDB id")
                    stats["failed"] += 1
                    stats["processed"] += 1
                    continue

                if tmdb_id in seen_in_run:
                    continue
                seen_in_run.add(tmdb_id)

                already_exists = (
                    tmdb_id in existing_tmdb_ids or self._tmdb_id_exists(tmdb_id)
                )
                if already_exists:
                    existing_tmdb_ids.add(tmdb_id)
                if already_exists and skip_existing and not update:
                    self.stdout.write(f"{prefix} Skipped: Already exists - {title}")
                    stats["skipped"] += 1
                    stats["processed"] += 1
                    continue

                try:
                    detail = self._request_json(
                        f"/movie/{tmdb_id}",
                        params={"append_to_response": "credits,videos", "language": "en-US"},
                    )
                    if detail is None:
                        raise RuntimeError("empty/invalid movie detail response")

                    movie_data = self._normalize_movie(detail)
                    if dry_run:
                        action = "Would update" if already_exists else "Would import"
                        self.stdout.write(f"{prefix} {action}: {movie_data['name']}")
                        stats["imported" if not already_exists else "updated"] += 1
                        stats["processed"] += 1
                        continue

                    with transaction.atomic():
                        movie, created, theaters_n, seats_n = self._save_movie(
                            movie_data=movie_data,
                            update=update or already_exists,
                            shows_per_movie=shows_per_movie,
                        )

                    existing_tmdb_ids.add(tmdb_id)
                    stats["theaters_created"] += theaters_n
                    stats["seats_created"] += seats_n

                    if created:
                        self.stdout.write(
                            self.style.SUCCESS(f"{prefix} Imported: {movie.name}")
                        )
                        stats["imported"] += 1
                    else:
                        self.stdout.write(
                            self.style.SUCCESS(f"{prefix} Updated: {movie.name}")
                        )
                        stats["updated"] += 1

                except IntegrityError:
                    existing_tmdb_ids.add(tmdb_id)
                    self.stdout.write(f"{prefix} Skipped: Already exists - {title}")
                    stats["skipped"] += 1
                except Exception as exc:
                    self.stdout.write(
                        self.style.ERROR(f"{prefix} Failed: {title} - {exc}")
                    )
                    stats["failed"] += 1

                stats["processed"] += 1

            page += 1
            if total_pages and page > total_pages:
                self.stdout.write(
                    self.style.WARNING("Reached last TMDB discover page.")
                )
                break

        self.stdout.write("")
        self.stdout.write(self.style.NOTICE("======== Import Summary ========"))
        self.stdout.write(f"Total processed : {stats['processed']}")
        self.stdout.write(f"Successfully imported : {stats['imported']}")
        self.stdout.write(f"Updated : {stats['updated']}")
        self.stdout.write(f"Skipped : {stats['skipped']}")
        self.stdout.write(f"Failed : {stats['failed']}")
        self.stdout.write(f"Theatres created : {stats['theaters_created']}")
        self.stdout.write(f"Shows created : {stats['theaters_created']}")
        self.stdout.write(f"Seats created : {stats['seats_created']}")
        self.stdout.write(self.style.NOTICE("================================"))

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _request_json(self, path: str, params: dict | None = None) -> dict | None:
        """GET JSON from TMDB with retries for timeouts and rate limits."""
        url = f"{self.base_url}{path}"
        params = dict(params or {})
        if self.api_key and "api_key" not in params:
            params["api_key"] = self.api_key

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "2"))
                    sleep_for = max(retry_after, 2 ** attempt)
                    self.stdout.write(
                        self.style.WARNING(
                            f"Rate limited (429). Sleeping {sleep_for}s "
                            f"(attempt {attempt}/{MAX_RETRIES})..."
                        )
                    )
                    time.sleep(sleep_for)
                    continue

                if response.status_code >= 500:
                    sleep_for = min(2 ** attempt, 30)
                    self.stdout.write(
                        self.style.WARNING(
                            f"TMDB server error {response.status_code}. "
                            f"Retrying in {sleep_for}s..."
                        )
                    )
                    time.sleep(sleep_for)
                    continue

                if response.status_code >= 400:
                    self.stdout.write(
                        self.style.ERROR(
                            f"HTTP {response.status_code} for {path}: "
                            f"{response.text[:200]}"
                        )
                    )
                    return None

                return response.json()

            except requests.Timeout:
                sleep_for = min(2 ** attempt, 20)
                self.stdout.write(
                    self.style.WARNING(
                        f"Timeout on {path}. Retrying in {sleep_for}s "
                        f"({attempt}/{MAX_RETRIES})..."
                    )
                )
                time.sleep(sleep_for)
            except requests.RequestException as exc:
                sleep_for = min(2 ** attempt, 20)
                self.stdout.write(
                    self.style.WARNING(
                        f"Request error on {path}: {exc}. "
                        f"Retrying in {sleep_for}s ({attempt}/{MAX_RETRIES})..."
                    )
                )
                time.sleep(sleep_for)
            except ValueError as exc:
                self.stdout.write(
                    self.style.ERROR(f"Invalid JSON from {path}: {exc}")
                )
                return None

        return None

    # ------------------------------------------------------------------
    # Data normalization
    # ------------------------------------------------------------------

    def _normalize_movie(self, detail: dict[str, Any]) -> dict[str, Any]:
        tmdb_id = detail["id"]
        name = (detail.get("title") or detail.get("original_title") or "Untitled").strip()
        overview = (detail.get("overview") or "").strip()

        poster_path = detail.get("poster_path")
        poster_url = f"{self.image_base}{poster_path}" if poster_path else None

        vote = detail.get("vote_average") or 0
        try:
            rating = Decimal(str(round(float(vote), 1))).quantize(Decimal("0.1"))
        except (InvalidOperation, TypeError, ValueError):
            rating = Decimal("0.0")
        if rating > Decimal("9.9"):
            rating = Decimal("9.9")

        release_raw = (detail.get("release_date") or "").strip()
        release_date = None
        if release_raw:
            try:
                release_date = datetime.strptime(release_raw, "%Y-%m-%d").date()
            except ValueError:
                release_date = None

        lang_code = (detail.get("original_language") or "").strip().lower()
        language_name = LANGUAGE_CODE_MAP.get(lang_code)
        if not language_name and lang_code:
            language_name = lang_code.upper()

        genres = [
            (g.get("name") or "").strip()
            for g in (detail.get("genres") or [])
            if (g.get("name") or "").strip()
        ]

        cast_names = []
        credits = detail.get("credits") or {}
        for member in (credits.get("cast") or [])[:CAST_LIMIT]:
            cast_name = (member.get("name") or "").strip()
            if cast_name:
                cast_names.append(cast_name)
        cast = ", ".join(cast_names) if cast_names else "Cast unavailable"

        trailer_url = self._extract_trailer_url(detail.get("videos") or {})

        return {
            "tmdb_id": tmdb_id,
            "name": name[:255],
            "description": overview or None,
            "poster_url": poster_url,
            "rating": rating,
            "release_date": release_date,
            "language_name": language_name,
            "genres": genres,
            "cast": cast,
            "trailer_url": trailer_url,
        }

    def _extract_trailer_url(self, videos: dict) -> str | None:
        results = videos.get("results") or []
        youtube = [
            v
            for v in results
            if (v.get("site") or "").lower() == "youtube"
            and (v.get("key") or "").strip()
        ]
        if not youtube:
            return None

        def rank(v: dict) -> tuple:
            type_name = (v.get("type") or "").lower()
            official = 0 if v.get("official") else 1
            type_rank = 0 if type_name == "trailer" else 1 if type_name == "teaser" else 2
            return (type_rank, official)

        youtube.sort(key=rank)
        key = youtube[0]["key"].strip()
        # Strict YouTube watch URL — never invent IDs
        return f"https://www.youtube.com/watch?v={key}"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_movie(
        self,
        movie_data: dict[str, Any],
        update: bool,
        shows_per_movie: int,
    ) -> tuple[Movie, bool, int, int]:
        tmdb_id = movie_data["tmdb_id"]
        defaults = {
            "name": movie_data["name"],
            "description": movie_data["description"],
            "poster_url": movie_data["poster_url"],
            "rating": movie_data["rating"],
            "release_date": movie_data["release_date"],
            "cast": movie_data["cast"],
            "trailer_url": movie_data["trailer_url"],
        }

        movie = Movie.objects.filter(tmdb_id=tmdb_id).first()
        created = False

        if movie is None:
            movie = Movie(tmdb_id=tmdb_id, **defaults)
            movie.save()
            created = True
        elif update:
            for field, value in defaults.items():
                setattr(movie, field, value)
            movie.save(
                update_fields=[
                    "name",
                    "description",
                    "poster_url",
                    "rating",
                    "release_date",
                    "cast",
                    "trailer_url",
                ]
            )
        else:
            # Should not reach here when skip_existing is set, but keep safe.
            pass

        # Genres
        genre_objs = []
        for genre_name in movie_data["genres"]:
            genre, _ = Genre.objects.get_or_create(name=genre_name[:100])
            genre_objs.append(genre)
        if genre_objs:
            if created or update:
                movie.genres.set(genre_objs)

        # Language
        if movie_data["language_name"]:
            language, _ = Language.objects.get_or_create(
                name=movie_data["language_name"][:100]
            )
            if created or update:
                movie.languages.set([language])

        theaters_created = 0
        seats_created = 0

        # Only allocate showtimes/seats when the movie has none yet
        if not movie.theaters.exists():
            theaters_created, seats_created = self._create_showtimes_and_seats(
                movie, shows_per_movie
            )

        return movie, created, theaters_created, seats_created

    def _create_showtimes_and_seats(
        self, movie: Movie, shows_per_movie: int
    ) -> tuple[int, int]:
        now = timezone.now()
        selected_names = random.sample(
            THEATER_NAMES, k=min(shows_per_movie, len(THEATER_NAMES))
        )

        theater_objects = []
        used_keys: set[tuple[str, date, int]] = set()

        for i, name in enumerate(selected_names):
            days_ahead = random.randint(1, 7)
            hour = SHOW_HOURS[i % len(SHOW_HOURS)]
            show_day = (now + timedelta(days=days_ahead)).date()
            key = (name, show_day, hour)
            # Avoid duplicate name+day+hour for same movie in this batch
            if key in used_keys:
                hour = SHOW_HOURS[(i + 1) % len(SHOW_HOURS)]
                key = (name, show_day, hour)
            used_keys.add(key)

            show_time = timezone.make_aware(
                datetime.combine(show_day, datetime.min.time()).replace(
                    hour=hour, minute=30, second=0, microsecond=0
                )
            )

            # Idempotent check against DB
            if Theater.objects.filter(movie=movie, name=name, time=show_time).exists():
                continue

            theater_objects.append(
                Theater(name=name, movie=movie, time=show_time)
            )

        if not theater_objects:
            return 0, 0

        try:
            created_theaters = Theater.objects.bulk_create(theater_objects)
        except IntegrityError:
            # Fallback to get_or_create style if bulk fails
            created_theaters = []
            for obj in theater_objects:
                theater, was_created = Theater.objects.get_or_create(
                    movie=movie,
                    name=obj.name,
                    time=obj.time,
                )
                if was_created:
                    created_theaters.append(theater)

        seat_objects = []
        for theater in created_theaters:
            existing_seats = set(
                Seat.objects.filter(theater=theater).values_list("seat_number", flat=True)
            )
            for label in SEAT_LABELS:
                if label not in existing_seats:
                    seat_objects.append(
                        Seat(
                            theater=theater,
                            seat_number=label,
                            is_booked=False,
                        )
                    )

        seats_created = 0
        if seat_objects:
            Seat.objects.bulk_create(seat_objects, batch_size=500)
            seats_created = len(seat_objects)

        return len(created_theaters), seats_created
