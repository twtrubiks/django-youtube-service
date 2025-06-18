from django.urls import path
from . import views

app_name = 'interactions'

urlpatterns = [
    path('video/<int:video_id>/comment/add/', views.add_comment, name='add_comment'),
    path('video/<int:video_id>/vote/', views.vote_video, name='vote_video'),
    path('user/<int:user_id_to_subscribe>/toggle_subscribe/', views.toggle_subscription, name='toggle_subscription'),

    # Notification URLs
    path('notifications/', views.get_notifications, name='get_notifications'),
    path('notifications/<int:notification_id>/mark-as-read/', views.mark_notification_as_read, name='mark_notification_as_read'),
    path('notifications/mark-all-as-read/', views.mark_all_notifications_as_read, name='mark_all_notifications_as_read'),
]
