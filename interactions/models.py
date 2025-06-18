from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class Comment(models.Model):
    video = models.ForeignKey('videos.Video', on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comments')
    parent_comment = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies')
    content = models.TextField()
    timestamp = models.DateTimeField(default=timezone.now)

    def __str__(self):
        if self.parent_comment:
            return f'Reply by {self.user.username} to {self.parent_comment.user.username} on {self.video.title}'
        return f'Comment by {self.user.username} on {self.video.title}'

class LikeDislike(models.Model):
    LIKE = 'like'
    DISLIKE = 'dislike'
    VOTE_CHOICES = [
        (LIKE, 'Like'),
        (DISLIKE, 'Dislike'),
    ]

    video = models.ForeignKey('videos.Video', on_delete=models.CASCADE, related_name='likes_dislikes')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='likes_dislikes')
    type = models.CharField(max_length=7, choices=VOTE_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('video', 'user') # A user can only vote once per video
        ordering = ['-timestamp']

    def __str__(self):
        return f'{self.user.username} {self.type}s {self.video.title}'

class Subscription(models.Model):
    subscriber = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions') # The user who is subscribing
    subscribed_to = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscribers') # The user (channel owner) being subscribed to
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('subscriber', 'subscribed_to') # A user can only subscribe once to another user
        ordering = ['-timestamp']

    def __str__(self):
        return f'{self.subscriber.username} subscribes to {self.subscribed_to.username}'

class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    # Add a sender field. It can be null if the notification is system-generated or doesn't have a specific sender.
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_notifications', null=True, blank=True)
    message = models.TextField()
    link = models.URLField(max_length=200, blank=True, null=True) # Optional link to content
    is_read = models.BooleanField(default=False)
    timestamp = models.DateTimeField(default=timezone.now)
    # Optional: Add a type for different kinds of notifications
    # NOTIFICATION_TYPES = (
    #     ('new_video', 'New Video'),
    #     ('new_comment', 'New Comment'),
    #     ('new_reply', 'New Reply'),
    #     ('new_subscriber', 'New Subscriber'),
    # )
    # notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, blank=True, null=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f'Notification for {self.recipient.username}: {self.message[:50]}'
