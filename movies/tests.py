from django.test import TestCase
from movies.models import Movie
from movies.admin import MovieAdmin
from django.contrib.admin.sites import AdminSite

class MovieTrailerSecurityTests(TestCase):
    def test_valid_youtube_urls_extraction(self):
        """Test extraction of 11-character video ID across various valid YouTube URL formats."""
        valid_urls = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s", "dQw4w9WgXcQ"),
            ("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ]
        
        for url, expected_id in valid_urls:
            movie = Movie(name="Test Movie", rating=8.5, cast="Cast", trailer_url=url)
            self.assertEqual(movie.youtube_video_id, expected_id)
            self.assertEqual(
                movie.youtube_embed_url,
                f"https://www.youtube-nocookie.com/embed/{expected_id}?rel=0&modestbranding=1&enablejsapi=1"
            )

    def test_xss_and_malicious_urls_prevention(self):
        """Test that malicious script injections and non-YouTube URLs return None."""
        malicious_urls = [
            "javascript:alert('XSS')",
            "<script>evil()</script>",
            "https://evil-site.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=short",
            "https://www.youtube.com/watch?v=toolongvideoidentifier123",
            "http://malicious.com/?v=dQw4w9WgXcQ",
            "",
            None
        ]
        
        for bad_url in malicious_urls:
            movie = Movie(name="Test Movie", rating=8.5, cast="Cast", trailer_url=bad_url)
            self.assertIsNone(movie.youtube_video_id, f"Failed to reject malicious/invalid URL: {bad_url}")
            self.assertIsNone(movie.youtube_embed_url, f"Failed to reject malicious embed URL for: {bad_url}")

    def test_admin_has_trailer_display(self):
        """Test admin list display helper for trailer presence."""
        admin_obj = MovieAdmin(Movie, AdminSite())
        
        movie_with_trailer = Movie(name="Movie 1", rating=8.0, cast="Cast", trailer_url="https://youtu.be/dQw4w9WgXcQ")
        movie_without_trailer = Movie(name="Movie 2", rating=7.0, cast="Cast", trailer_url="")
        
        self.assertTrue(admin_obj.has_trailer(movie_with_trailer))
        self.assertFalse(admin_obj.has_trailer(movie_without_trailer))

