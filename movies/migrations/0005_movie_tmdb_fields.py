# Generated manually for TMDB import support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0004_movie_trailer_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='movie',
            name='poster_url',
            field=models.URLField(
                blank=True,
                help_text='Remote poster URL (e.g. TMDB CDN). Preferred over local image when set.',
                max_length=500,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='movie',
            name='release_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='movie',
            name='tmdb_id',
            field=models.PositiveIntegerField(
                blank=True,
                db_index=True,
                help_text='External TMDB movie ID used for idempotent imports.',
                null=True,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name='movie',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='movies/'),
        ),
    ]
