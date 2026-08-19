from django.core.management.base import BaseCommand

from bookings.services import release_expired_reservations


class Command(BaseCommand):
    help = "Release expired seat reservations and pending payment orders."

    def handle(self, *args, **options):
        result = release_expired_reservations()
        self.stdout.write(self.style.SUCCESS(f"Done: {result}"))
