from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import models
from .models import Movie, Theater, Seat, Booking, Genre, Language
from django.contrib.auth.decorators import login_required
import threading
import logging

logger = logging.getLogger('bookings')

def _dispatch_booking_email(booking_ids, recipient_email, payment_id, total_amount_str):
    """
    Non-blocking helper function to execute email dispatch in a background thread.
    Tries Celery .delay() first; falls back to thread-based task execution if broker is down.
    """
    try:
        from bookings.tasks import send_booking_confirmation_email
        send_booking_confirmation_email.delay(
            booking_ids=booking_ids,
            recipient_email=recipient_email,
            payment_id=payment_id,
            total_amount=total_amount_str
        )
    except Exception as e:
        logger.warning(
            f"Celery/Redis broker is unavailable (Error: {str(e)}). "
            f"Falling back to thread-based email dispatch for Booking IDs {booking_ids}."
        )
        try:
            from bookings.tasks import send_booking_confirmation_email
            send_booking_confirmation_email(
                booking_ids=booking_ids,
                recipient_email=recipient_email,
                payment_id=payment_id,
                total_amount=total_amount_str
            )
        except Exception as sync_err:
            logger.error(
                f"Failed thread-based email dispatch for Booking IDs {booking_ids}. "
                f"Error: {str(sync_err)}"
            )


def movie_list(request):
    # Retrieve query params
    search_query = request.GET.get('search', '').strip()
    selected_genres = request.GET.getlist('genres')
    selected_languages = request.GET.getlist('languages')
    sort_by = request.GET.get('sort', 'rating_desc')
    
    # 1. Main Movie list query
    movies = Movie.objects.all()
    
    # Text search on title
    if search_query:
        movies = movies.filter(name__icontains=search_query)
        
    # Optimized Many-to-Many filtering via the intermediate through tables
    # This prevents duplicate rows in the outer query and eliminates the need for a costly DISTINCT on movies_movie columns
    if selected_genres:
        try:
            genre_ids = [int(gid) for gid in selected_genres if gid]
            if genre_ids:
                genre_movie_ids = Movie.genres.through.objects.filter(genre_id__in=genre_ids).values('movie_id')
                movies = movies.filter(id__in=genre_movie_ids)
        except ValueError:
            pass
            
    if selected_languages:
        try:
            lang_ids = [int(lid) for lid in selected_languages if lid]
            if lang_ids:
                lang_movie_ids = Movie.languages.through.objects.filter(language_id__in=lang_ids).values('movie_id')
                movies = movies.filter(id__in=lang_movie_ids)
        except ValueError:
            pass

    # Sorting
    if sort_by == 'rating_desc':
        movies = movies.order_by('-rating', 'id')
    elif sort_by == 'rating_asc':
        movies = movies.order_by('rating', 'id')
    elif sort_by == 'name_asc':
        movies = movies.order_by('name', 'id')
    elif sort_by == 'name_desc':
        movies = movies.order_by('-name', 'id')
    else:
        movies = movies.order_by('-rating', 'id') # default

    # 2. Dynamic Facet Counts
    # For Genre counts: Apply search + selected languages
    genre_qs = Movie.objects.all()
    if search_query:
        genre_qs = genre_qs.filter(name__icontains=search_query)
    if selected_languages:
        try:
            lang_ids = [int(lid) for lid in selected_languages if lid]
            if lang_ids:
                lang_movie_ids = Movie.languages.through.objects.filter(language_id__in=lang_ids).values('movie_id')
                genre_qs = genre_qs.filter(id__in=lang_movie_ids)
        except ValueError:
            pass
            
    genre_counts_raw = (
        genre_qs.values('genres__id')
        .annotate(count=models.Count('id', distinct=True))
    )
    genre_count_map = {item['genres__id']: item['count'] for item in genre_counts_raw if item['genres__id'] is not None}
    
    genres = list(Genre.objects.all().order_by('name'))
    for g in genres:
        g.movie_count = genre_count_map.get(g.id, 0)

    # For Language counts: Apply search + selected genres
    lang_qs = Movie.objects.all()
    if search_query:
        lang_qs = lang_qs.filter(name__icontains=search_query)
    if selected_genres:
        try:
            genre_ids = [int(gid) for gid in selected_genres if gid]
            if genre_ids:
                genre_movie_ids = Movie.genres.through.objects.filter(genre_id__in=genre_ids).values('movie_id')
                lang_qs = lang_qs.filter(id__in=genre_movie_ids)
        except ValueError:
            pass
            
    lang_counts_raw = (
        lang_qs.values('languages__id')
        .annotate(count=models.Count('id', distinct=True))
    )
    lang_count_map = {item['languages__id']: item['count'] for item in lang_counts_raw if item['languages__id'] is not None}
    
    languages = list(Language.objects.all().order_by('name'))
    for l in languages:
        l.movie_count = lang_count_map.get(l.id, 0)

    # 3. Pagination
    paginator = Paginator(movies, 24) # 24 movies per page
    page = request.GET.get('page')
    try:
        paginated_movies = paginator.page(page)
    except PageNotAnInteger:
        paginated_movies = paginator.page(1)
    except EmptyPage:
        paginated_movies = paginator.page(paginator.num_pages)

    # Convert query parameters to preserve them in pagination links
    query_params = request.GET.copy()
    if 'page' in query_params:
        query_params.pop('page')
    
    context = {
        'movies': paginated_movies,
        'genres': genres,
        'languages': languages,
        'selected_genres': [int(x) for x in selected_genres if x.isdigit()],
        'selected_languages': [int(x) for x in selected_languages if x.isdigit()],
        'search_query': search_query,
        'sort_by': sort_by,
        'url_params': query_params.urlencode()
    }
    return render(request, 'movies/movie_list.html', context)


def theater_list(request,movie_id):
    movie = get_object_or_404(Movie,id=movie_id)
    theater=Theater.objects.filter(movie=movie)
    return render(request,'movies/theater_list.html',{'movie':movie,'theaters':theater})



@login_required(login_url='/login/')
def book_seats(request, theater_id):
    from bookings.services import get_seat_availability_map, reserve_seats

    theaters = get_object_or_404(Theater, id=theater_id)
    seats = Seat.objects.filter(theater=theaters).order_by('seat_number')
    seat_states = get_seat_availability_map(theaters, current_user_id=request.user.id)
    for seat in seats:
        seat.state = seat_states.get(seat.id, 'available')

    if request.method == 'POST':
        selected_seats = request.POST.getlist('seats')

        if not selected_seats:
            return render(request, "movies/seats_selection.html", {
                'theaters': theaters,
                'seats': seats,
                'seat_states': seat_states,
                'error': "No seat selected. Please select at least one seat before booking."
            })

        payment_order, error_seats = reserve_seats(
            request.user, theaters, selected_seats
        )

        if error_seats:
            seat_states = get_seat_availability_map(theaters, current_user_id=request.user.id)
            seats = Seat.objects.filter(theater=theaters).order_by('seat_number')
            for seat in seats:
                seat.state = seat_states.get(seat.id, 'available')
            if error_seats == ["Invalid seat selection"]:
                error_message = "Invalid seat selection. Please try again."
            elif len(error_seats) == 1 and "Payment gateway" in error_seats[0]:
                error_message = error_seats[0]
            else:
                error_message = f"The following seat(s) are unavailable: {', '.join(error_seats)}"
            return render(request, 'movies/seats_selection.html', {
                'theaters': theaters,
                'seats': seats,
                'seat_states': seat_states,
                'error': error_message
            })

        return redirect('payment_checkout', order_id=payment_order.public_id)

    return render(request, 'movies/seats_selection.html', {
        'theaters': theaters,
        'seats': seats,
        'seat_states': seat_states,
    })




