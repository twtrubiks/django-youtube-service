from django.contrib import admin
from .models import Comment, LikeDislike, Subscription

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('user', 'video', 'content', 'timestamp')
    list_filter = ('timestamp', 'video')
    search_fields = ('user__username', 'video__title', 'content')

@admin.register(LikeDislike)
class LikeDislikeAdmin(admin.ModelAdmin):
    list_display = ('user', 'video', 'type', 'timestamp')
    list_filter = ('timestamp', 'video', 'type')
    search_fields = ('user__username', 'video__title')

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('subscriber', 'subscribed_to', 'timestamp')
    list_filter = ('timestamp',)
    search_fields = ('subscriber__username', 'subscribed_to__username')
