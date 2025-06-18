from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from interactions.models import Subscription

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    profile_picture = models.ImageField(upload_to='profile_pics/', null=True, blank=True)
    channel_description = models.TextField(blank=True)
    banner_image = models.ImageField(upload_to='banner_pics/', null=True, blank=True)

    def __str__(self):
        return self.user.username

    def subscribers_count(self):
        # Counts how many users have subscribed to this profile's user
        return Subscription.objects.filter(subscribed_to=self.user).count()

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
    instance.profile.save()
