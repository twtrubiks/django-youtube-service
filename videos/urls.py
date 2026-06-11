from django.urls import path

from . import views

app_name = "videos"

urlpatterns = [
    path("upload/", views.upload_video, name="upload_video"),
    path("<int:video_id>/", views.video_detail, name="video_detail"),
    path("<int:video_id>/edit/", views.edit_video, name="edit_video"),  # Added for editing video
    path("<int:video_id>/delete/", views.delete_video, name="delete_video"),  # Added for deleting video
    # Assuming you want the home page of videos app to be distinct,
    # or it could be the root of the site later.
    path("", views.home, name="home"),  # Changed name to 'home'
    path("search/", views.search_videos, name="search_videos"),
    path("search/suggest/", views.search_suggest, name="search_suggest"),
    path("category/add/", views.add_category, name="add_category"),  # Moved up
    # str 而非 slug：taggit 與 Category 的 slug 允許 unicode（如中文），slug converter 只收 ASCII
    path("category/<str:category_slug>/", views.videos_by_category, name="videos_by_category"),
    path("category/<int:category_id>/delete/", views.delete_category, name="delete_category"),
    path("tag/<str:tag_slug>/", views.videos_by_tag, name="videos_by_tag"),
    path("<int:video_id>/status/", views.video_status, name="video_status"),
    # nginx auth_request 子請求端點：受保護媒體（HLS、mp4）的授權判斷，見 nginx/nginx.conf
    path("media-auth/", views.media_auth, name="media_auth"),
]
