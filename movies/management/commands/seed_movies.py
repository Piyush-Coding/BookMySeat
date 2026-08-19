import os
import random
from django.core.management.base import BaseCommand
from django.db import transaction
from movies.models import Movie, Genre, Language

class Command(BaseCommand):
    help = 'Seeds the database with genres, languages, 10 classic Hindi movies, and 5000+ optimized movie catalog entries.'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting database seeding...")

        # 1. Create Genres
        genres_list = [
            "Action", "Comedy", "Drama", "Romance", "Thriller", 
            "Musical", "Family", "Sports", "Sci-Fi", "Horror", 
            "Adventure", "Mystery"
        ]
        genres = {}
        for name in genres_list:
            genre, created = Genre.objects.get_or_create(name=name)
            genres[name] = genre

        # 2. Create Languages
        languages_list = ["Hindi", "English", "Spanish", "French", "Japanese"]
        languages = {}
        for name in languages_list:
            lang, created = Language.objects.get_or_create(name=name)
            languages[name] = lang

        self.stdout.write(f"Created {len(genres)} genres and {len(languages)} languages.")

        # Delete existing data to prevent duplicate runs
        self.stdout.write("Clearing existing movie records...")
        Movie.objects.all().delete()

        # 3. Insert 10 classic Hindi movies
        classic_movies_data = [
            {
                "name": "Gol Maal (1979)",
                "image": "movies/gol_maal__1979_.jpg",
                "rating": 8.5,
                "cast": "Amol Palekar, Utpal Dutt, Bindiya Goswami, David",
                "description": "A comical misunderstanding arises when a man's boss spots him at a sports match after he took leave citing illness. To save his job, he invents a twin brother.",
                "genres_names": ["Comedy", "Drama"],
                "languages_names": ["Hindi"]
            },
            {
                "name": "Arth (1982)",
                "image": "movies/arth__1982_.jpg",
                "rating": 8.0,
                "cast": "Shabana Azmi, Kulbhushan Kharbanda, Smita Patil, Raj Kiran",
                "description": "A filmmaker's extramarital affair with an actress leads to the breakdown of his marriage, leaving his wife to search for her own identity.",
                "genres_names": ["Drama", "Romance"],
                "languages_names": ["Hindi"]
            },
            {
                "name": "Masoom (1983)",
                "image": "movies/masoom__1983_.jpg",
                "rating": 8.4,
                "cast": "Naseeruddin Shah, Shabana Azmi, Jugal Hansraj, Urmila Matondkar",
                "description": "The domestic lives of a family are disrupted when the husband's illegitimate son from a past affair comes to live with them.",
                "genres_names": ["Drama", "Family"],
                "languages_names": ["Hindi"]
            },
            {
                "name": "Saaransh (1984)",
                "image": "movies/saaransh__1984_.jpg",
                "rating": 8.1,
                "cast": "Anupam Kher, Rohini Hattangadi, Soni Razdan, Madan Jain",
                "description": "An elderly schoolteacher and his wife struggle to cope with the loss of their only son, but find new meaning when they shield a young girl from political thugs.",
                "genres_names": ["Drama"],
                "languages_names": ["Hindi"]
            },
            {
                "name": "Mirch Masala (1987)",
                "image": "movies/mirch_masala__1987_.jpg",
                "rating": 7.9,
                "cast": "Naseeruddin Shah, Smita Patil, Om Puri, Deepti Naval",
                "description": "A rebellious woman takes refuge in a spice factory after slapping a tyrannical tax collector, rallying the local women to stand up against patriarchy.",
                "genres_names": ["Thriller", "Drama"],
                "languages_names": ["Hindi"]
            },
            {
                "name": "Qayamat Se Qayamat Tak (1988)",
                "image": "movies/qayamat_se_qayamat_tak__1988_.jpg",
                "rating": 7.5,
                "cast": "Aamir Khan, Juhi Chawla, Goga Kapoor, Dalip Tahil",
                "description": "Two young lovers from warring families elope to be together, but face tragic consequences as their families refuse to accept their union.",
                "genres_names": ["Romance", "Drama", "Musical"],
                "languages_names": ["Hindi"]
            },
            {
                "name": "Maine Pyar Kiya (1989)",
                "image": "movies/maine_pyar_kiya__1989_.jpg",
                "rating": 7.3,
                "cast": "Salman Khan, Bhagyashree, Alok Nath, Reema Lagoo",
                "description": "A young man from a wealthy family falls in love with a simple girl, but must prove himself to her father to earn her hand in marriage.",
                "genres_names": ["Romance", "Drama", "Musical"],
                "languages_names": ["Hindi"]
            },
            {
                "name": "Jo Jeeta Wohi Sikandar (1992)",
                "image": "movies/jo_jeeta_wohi_sikandar__1992_.jpg",
                "rating": 8.1,
                "cast": "Aamir Khan, Ayesha Jhulka, Deepak Tijori, Pooja Bedi",
                "description": "A carefree college student must step up and win a prestigious inter-collegiate bicycle race to restore his family's honor.",
                "genres_names": ["Sports", "Drama", "Romance"],
                "languages_names": ["Hindi"]
            },
            {
                "name": "Andaz Apna Apna (1994)",
                "image": "movies/andaz_apna_apna__1994_.jpg",
                "rating": 8.0,
                "cast": "Aamir Khan, Salman Khan, Raveena Tandon, Karisma Kapoor",
                "description": "Two daydreaming slackers compete for the affection of an heiress, inadvertently getting entangled with a hilarious local gangster.",
                "genres_names": ["Comedy", "Romance"],
                "languages_names": ["Hindi"]
            },
            {
                "name": "Hum Aapke Hain Koun..! (1994)",
                "image": "movies/hum_aapke_hain_koun_____1994_.jpg",
                "rating": 7.5,
                "cast": "Madhuri Dixit, Salman Khan, Mohnish Bahl, Renuka Shahane",
                "description": "A story of family values, love, and sacrifice as two young lovers put their relationship on hold for the sake of their families' happiness.",
                "genres_names": ["Romance", "Comedy", "Family", "Musical"],
                "languages_names": ["Hindi"]
            }
        ]

        # Seed classic movies
        self.stdout.write("Seeding classic Hindi movies...")
        classic_movies = []
        classic_genres_mappings = []
        classic_langs_mappings = []

        for data in classic_movies_data:
            movie = Movie(
                name=data["name"],
                image=data["image"],
                rating=data["rating"],
                cast=data["cast"],
                description=data["description"]
            )
            movie.save()
            
            # Setup genre mapping
            for g_name in data["genres_names"]:
                movie.genres.add(genres[g_name])
            
            # Setup language mapping
            for l_name in data["languages_names"]:
                movie.languages.add(languages[l_name])

        self.stdout.write("10 Classic movies seeded successfully.")

        # 4. Generate 5,000+ movie catalog entries
        self.stdout.write("Generating 5,000 additional movie catalog entries...")
        
        # Lists of terms for generating random movie titles/descriptions/cast
        adjectives = ["Epic", "Dark", "Golden", "Silent", "Lost", "Wild", "Midnight", "Broken", "Hidden", "Eternal", "Fierce", "Infinite", "Secret", "Velvet", "Primal"]
        nouns = ["Journey", "Shadow", "Heart", "Destiny", "Empire", "Legacy", "Storm", "Whisper", "Vengeance", "Echo", "Labyrinth", "Kingdom", "Glory", "Frontier", "Alliance"]
        cast_names = ["Robert Downey Jr.", "Scarlett Johansson", "Leonardo DiCaprio", "Brad Pitt", "Meryl Streep", "Tom Hanks", "Denzel Washington", "Morgan Freeman", "Al Pacino", "Robert De Niro", "Kate Winslet", "Christian Bale"]
        
        poster_images = [data["image"] for data in classic_movies_data]

        # Batch operations to stay extremely fast
        batch_size = 1000
        total_additional = 5000
        
        movie_objects = []
        movie_relations_genres = []
        movie_relations_langs = []

        # We will wrap it in a transaction for speed and safety
        with transaction.atomic():
            for i in range(1, total_additional + 1):
                title = f"{random.choice(adjectives)} {random.choice(nouns)} {i}"
                desc = f"An amazing cinematic tale of a {random.choice(adjectives).lower()} {random.choice(nouns).lower()} featuring spectacular performances."
                rating = round(random.uniform(4.0, 9.5), 1)
                cast_list = ", ".join(random.sample(cast_names, random.randint(2, 4)))
                img = random.choice(poster_images)

                movie_objects.append(
                    Movie(
                        name=title,
                        image=img,
                        rating=rating,
                        cast=cast_list,
                        description=desc
                    )
                )

            # Bulk create movies
            self.stdout.write("Bulk writing movies to database...")
            created_movies = Movie.objects.bulk_create(movie_objects)
            self.stdout.write(f"Successfully bulk created {len(created_movies)} movies.")

            # Create list of IDs for relationship mappings
            all_genres_instances = list(genres.values())
            all_langs_instances = list(languages.values())

            self.stdout.write("Preparing relationship mappings...")
            for movie in created_movies:
                # Randomly assign 1 to 3 genres
                selected_genres = random.sample(all_genres_instances, random.randint(1, 3))
                for g in selected_genres:
                    movie_relations_genres.append(Movie.genres.through(movie_id=movie.id, genre_id=g.id))

                # Randomly assign 1 to 2 languages
                selected_langs = random.sample(all_langs_instances, random.randint(1, 2))
                for l in selected_langs:
                    movie_relations_langs.append(Movie.languages.through(movie_id=movie.id, language_id=l.id))

            # Bulk create relationships
            self.stdout.write("Bulk writing genre relationships...")
            Movie.genres.through.objects.bulk_create(movie_relations_genres, batch_size=5000)
            
            self.stdout.write("Bulk writing language relationships...")
            Movie.languages.through.objects.bulk_create(movie_relations_langs, batch_size=5000)

        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))
