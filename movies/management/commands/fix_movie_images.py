import os
import random
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction
from movies.models import Movie

class Command(BaseCommand):
    help = 'Remaps movie image fields to existing valid files in media/movies/'

    def handle(self, *args, **options):
        self.stdout.write("Checking media directory for valid movie poster files...")
        media_movies_dir = os.path.join(settings.MEDIA_ROOT, 'movies')

        if not os.path.exists(media_movies_dir):
            self.stdout.write(self.style.ERROR(f"Directory {media_movies_dir} does not exist!"))
            return

        valid_files = [
            f"movies/{f}"
            for f in os.listdir(media_movies_dir)
            if f.endswith(('.jpg', '.png', '.webp', '.jpeg'))
        ]

        if not valid_files:
            self.stdout.write(self.style.ERROR("No valid image files found in media/movies!"))
            return

        self.stdout.write(f"Found {len(valid_files)} valid poster files in media/movies.")

        movies = Movie.objects.all()
        total_movies = movies.count()
        self.stdout.write(f"Evaluating {total_movies} movies in the database...")

        updated_movies = []
        fixed_count = 0

        for idx, movie in enumerate(movies):
            current_image = str(movie.image)
            full_path = os.path.join(settings.MEDIA_ROOT, current_image) if current_image else ""

            if not current_image or not os.path.exists(full_path):
                # Pick a valid image using round-robin distribution
                chosen_image = valid_files[idx % len(valid_files)]
                movie.image = chosen_image
                updated_movies.append(movie)
                fixed_count += 1

        self.stdout.write(f"Found {fixed_count} movies with missing image files.")

        if updated_movies:
            self.stdout.write("Bulk updating movie image paths in database...")
            with transaction.atomic():
                Movie.objects.bulk_update(updated_movies, ['image'], batch_size=5000)

            self.stdout.write(self.style.SUCCESS(f"Successfully remapped {fixed_count} movie image paths!"))
        else:
            self.stdout.write(self.style.SUCCESS("All movies already have valid image files assigned."))
