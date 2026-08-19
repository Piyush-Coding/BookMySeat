from django.contrib import admin
from .models import Movie, Theater, Seat, Booking, Genre, Language

@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ['name']

@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ['name']

@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ['name', 'rating', 'tmdb_id', 'release_date', 'has_trailer', 'cast']
    list_filter = ['release_date', 'genres', 'languages']
    search_fields = ['name', 'cast', 'tmdb_id']
    filter_horizontal = ['genres', 'languages']
    fields = [
        'name', 'tmdb_id', 'rating', 'release_date', 'image', 'poster_url',
        'cast', 'description', 'trailer_url', 'genres', 'languages',
    ]
    readonly_fields = []

    @admin.display(boolean=True, description='Trailer Added')
    def has_trailer(self, obj):
        return bool(obj.youtube_video_id)

@admin.register(Theater)
class TheaterAdmin(admin.ModelAdmin):
    list_display = ['name', 'movie', 'time']

@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ['theater', 'seat_number', 'is_booked']

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['user', 'seat', 'movie', 'theater', 'payment_order', 'booked_at']
