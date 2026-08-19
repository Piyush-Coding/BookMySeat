import random
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from movies.models import Movie, Theater, Seat

class Command(BaseCommand):
    help = 'Allocates theaters and seats for all movies in the database.'

    def handle(self, *args, **options):
        self.stdout.write("Starting theater and seat allocation process...")

        theater_names = [
            "PVR Cinemas",
            "INOX Multiplex",
            "Cinepolis",
            "Piyush Complex",
            "Prashant Complex",
            "Miraj Cinemas",
            "Carnival Cinemas",
            "Wave Cinemas"
        ]

        # Standard seat numbers per screen (20 seats: Rows A and B, 1-10)
        seat_labels = [f"{row}{num}" for row in ['A', 'B'] for num in range(1, 11)]

        # Fetch movies that need theater allocation (or all movies lacking theaters)
        movies = list(Movie.objects.all())
        total_movies = len(movies)
        self.stdout.write(f"Found {total_movies} total movies in the database.")

        # Identify movies that already have theaters assigned
        movies_with_theaters = set(Theater.objects.values_list('movie_id', flat=True).distinct())
        target_movies = [m for m in movies if m.id not in movies_with_theaters]

        self.stdout.write(f"Movies requiring theater allocation: {len(target_movies)}")

        if not target_movies:
            self.stdout.write(self.style.SUCCESS("All movies already have theaters allocated!"))
            return

        now = timezone.now()
        
        # Batch generation parameters
        theater_objects = []
        
        self.stdout.write("Generating theater entries...")
        
        # For each target movie, assign 2 theaters with future showtimes
        for movie in target_movies:
            selected_names = random.sample(theater_names, 2)
            for i, name in enumerate(selected_names):
                # Random showtime between +1 and +7 days from now
                days_ahead = random.randint(1, 7)
                hours_ahead = random.choice([10, 13, 16, 19, 21])
                show_time = (now + timedelta(days=days_ahead)).replace(hour=hours_ahead, minute=30, second=0, microsecond=0)
                
                theater_objects.append(
                    Theater(
                        name=name,
                        movie=movie,
                        time=show_time
                    )
                )

        self.stdout.write(f"Bulk writing {len(theater_objects)} theaters to database...")
        
        with transaction.atomic():
            created_theaters = Theater.objects.bulk_create(theater_objects, batch_size=5000)

        self.stdout.write(f"Successfully created {len(created_theaters)} theaters.")

        self.stdout.write("Generating seat entries for created theaters...")
        
        seat_objects = []
        seat_batch_count = 0
        total_seats_created = 0

        with transaction.atomic():
            for theater in created_theaters:
                for label in seat_labels:
                    seat_objects.append(
                        Seat(
                            theater=theater,
                            seat_number=label,
                            is_booked=False
                        )
                    )
                
                if len(seat_objects) >= 50000:
                    Seat.objects.bulk_create(seat_objects, batch_size=10000)
                    total_seats_created += len(seat_objects)
                    seat_batch_count += 1
                    self.stdout.write(f"Bulk written batch {seat_batch_count} ({total_seats_created} seats processed so far)...")
                    seat_objects = []

            if seat_objects:
                Seat.objects.bulk_create(seat_objects, batch_size=10000)
                total_seats_created += len(seat_objects)

        self.stdout.write(self.style.SUCCESS(
            f"Successfully allocated {len(created_theaters)} theaters and {total_seats_created} seats across {len(target_movies)} movies!"
        ))
