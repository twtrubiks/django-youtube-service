from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from taggit.managers import TaggableManager
from django.utils.text import slugify

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "categories"

class Video(models.Model):
    VISIBILITY_CHOICES = [
        ('public', 'Public'),
        ('private', 'Private'),
        ('unlisted', 'Unlisted'),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    video_file = models.FileField(upload_to='videos/')
    thumbnail = models.ImageField(upload_to='thumbnails/', null=True, blank=True)
    uploader = models.ForeignKey(User, on_delete=models.CASCADE, related_name='videos')
    upload_date = models.DateTimeField(default=timezone.now)
    views_count = models.IntegerField(default=0)
    visibility = models.CharField(
        max_length=10,
        choices=VISIBILITY_CHOICES,
        default='public'
    )
    processing_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('transcoding_complete', 'Transcoding Complete'),
            ('thumbnail_generated', 'Thumbnail Generated'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='pending',
        blank=True,
        null=True
    )
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='videos')
    tags = TaggableManager(blank=True)
    hls_path = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.title

    def likes_count(self):
        return self.likes_dislikes.filter(type='like').count()

    def dislikes_count(self):
        return self.likes_dislikes.filter(type='dislike').count()
