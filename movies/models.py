import re
from django.db import models
from django.contrib.auth.models import User 


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        indexes = [
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return self.name


class Language(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        indexes = [
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return self.name


from urllib.parse import urlparse, parse_qs

class Movie(models.Model):
    name = models.CharField(max_length=255)
    image = models.ImageField(upload_to="movies/", blank=True, null=True)
    poster_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Remote poster URL (e.g. TMDB CDN). Preferred over local image when set.",
    )
    rating = models.DecimalField(max_digits=3, decimal_places=1)
    cast = models.TextField()
    description = models.TextField(blank=True, null=True)
    release_date = models.DateField(blank=True, null=True)
    tmdb_id = models.PositiveIntegerField(
        unique=True,
        blank=True,
        null=True,
        db_index=True,
        help_text="External TMDB movie ID used for idempotent imports.",
    )
    genres = models.ManyToManyField(Genre, related_name='movies', blank=True)
    languages = models.ManyToManyField(Language, related_name='movies', blank=True)
    trailer_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="YouTube trailer URL or embed link (e.g. https://www.youtube.com/watch?v=...)"
    )

    class Meta:
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['rating']),
        ]

    def __str__(self):
        return self.name

    @property
    def poster_display_url(self):
        """Prefer remote poster_url; fall back to local ImageField URL."""
        if self.poster_url:
            return self.poster_url
        if self.image:
            try:
                return self.image.url
            except (ValueError, OSError):
                return None
        return None

    @property
    def youtube_video_id(self):
        """
        Safely extract and validate an 11-character YouTube video ID.
        Prevents XSS, script injection, and invalid domain embedding.
        """
        if not self.trailer_url:
            return None
            
        url_str = str(self.trailer_url).strip()
        
        # 1. Parse URL structure safely
        try:
            parsed = urlparse(url_str)
        except Exception:
            return None

        # 2. Strict Domain Whitelist Check
        netloc = parsed.netloc.lower()
        valid_domains = {
            'youtube.com', 'www.youtube.com', 'm.youtube.com',
            'youtu.be', 'www.youtu.be',
            'youtube-nocookie.com', 'www.youtube-nocookie.com'
        }
        if netloc not in valid_domains:
            return None

        candidate_id = None

        # 3. Extract candidate video ID from path or query parameters
        if 'youtu.be' in netloc:
            path = parsed.path.lstrip('/')
            candidate_id = path.split('/')[0] if path else None
        else:
            if parsed.path.startswith('/embed/'):
                parts = parsed.path.split('/embed/')
                if len(parts) > 1:
                    candidate_id = parts[1].split('/')[0].split('?')[0]
            elif parsed.path.startswith('/v/'):
                parts = parsed.path.split('/v/')
                if len(parts) > 1:
                    candidate_id = parts[1].split('/')[0].split('?')[0]
            elif 'v' in parse_qs(parsed.query):
                v_list = parse_qs(parsed.query).get('v')
                if v_list:
                    candidate_id = v_list[0]

        # 4. Strict 11-Character Alphanumeric Fullmatch Check
        if candidate_id and re.fullmatch(r'^[a-zA-Z0-9_-]{11}$', candidate_id):
            return candidate_id

        return None

    @property
    def youtube_embed_url(self):
        """
        Return secure youtube-nocookie.com embed URL.
        Enforces privacy-enhanced mode and domain whitelisting.
        """
        v_id = self.youtube_video_id
        if v_id:
            return f"https://www.youtube-nocookie.com/embed/{v_id}?rel=0&modestbranding=1&enablejsapi=1"
        return None


class Theater(models.Model):
    name = models.CharField(max_length=255)
    movie = models.ForeignKey(Movie,on_delete=models.CASCADE,related_name='theaters')
    time= models.DateTimeField()

    def __str__(self):
        return f'{self.name} - {self.movie.name} at {self.time}'

class Seat(models.Model):
    theater = models.ForeignKey(Theater,on_delete=models.CASCADE,related_name='seats')
    seat_number = models.CharField(max_length=10)
    is_booked=models.BooleanField(default=False)

    def __str__(self):
        return f'{self.seat_number} in {self.theater.name}'

class Booking(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE)
    seat=models.OneToOneField(Seat,on_delete=models.CASCADE)
    movie=models.ForeignKey(Movie,on_delete=models.CASCADE)
    theater=models.ForeignKey(Theater,on_delete=models.CASCADE)
    payment_order=models.ForeignKey(
        'bookings.PaymentOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bookings',
    )
    booked_at=models.DateTimeField(auto_now_add=True)
    email_sent=models.BooleanField(default=False)
    
    def __str__(self):
        return f'Booking by {self.user.username} for {self.seat.seat_number} at {self.theater.name}'