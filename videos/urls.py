from django.urls import path
from . import views

app_name = 'videos'

urlpatterns = [
    path('upload/', views.upload_video, name='upload_video'),
    path('<int:video_id>/', views.video_detail, name='video_detail'),
    path('<int:video_id>/edit/', views.edit_video, name='edit_video'), # Added for editing video
    path('<int:video_id>/delete/', views.delete_video, name='delete_video'), # Added for deleting video
    # Assuming you want the home page of videos app to be distinct,
    # or it could be the root of the site later.
    path('', views.home, name='home'), # Changed name to 'home'
    path('search/', views.search_videos, name='search_videos'),
    path('category/add/', views.add_category, name='add_category'), # Moved up
    path('category/<slug:category_slug>/', views.videos_by_category, name='videos_by_category'),
    path('category/<int:category_id>/delete/', views.delete_category, name='delete_category'),
    path('tag/<slug:tag_slug>/', views.videos_by_tag, name='videos_by_tag'),
    # HLS streaming endpoints
    path('<int:video_id>/hls/playlist.m3u8', views.serve_hls_playlist, name='hls_playlist'),
    path('<int:video_id>/hls/<str:segment_name>', views.serve_hls_segment, name='hls_segment'),
]