from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.utils.encoding import filepath_to_uri
from django.utils.text import slugify
from taggit.managers import TaggableManager


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True, allow_unicode=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "categories"


class Video(models.Model):
    VISIBILITY_CHOICES = [
        ("public", "Public"),
        ("private", "Private"),
        ("unlisted", "Unlisted"),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    video_file = models.FileField(upload_to="videos/")
    thumbnail = models.ImageField(upload_to="thumbnails/", null=True, blank=True)
    uploader = models.ForeignKey(User, on_delete=models.CASCADE, related_name="videos")
    upload_date = models.DateTimeField(default=timezone.now, db_index=True)
    views_count = models.IntegerField(default=0)
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default="public")
    processing_status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("transcoding_complete", "Transcoding Complete"),
            ("thumbnail_generated", "Thumbnail Generated"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ],
        default="pending",
        blank=True,
        null=True,
    )
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="videos")
    tags = TaggableManager(blank=True)
    hls_path = models.CharField(max_length=255, blank=True, null=True)
    hls_status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ],
        default="pending",
    )

    class Meta:
        # 首頁/分類/標籤/相關影片都是 filter(visibility="public").order_by("-upload_date")，
        # 複合索引讓分頁查詢直接走索引；visibility 低基數單欄索引由此取代
        indexes = [models.Index(fields=["visibility", "-upload_date"], name="video_vis_upload_idx")]

    def __str__(self):
        return self.title

    @property
    def hls_url(self):
        """master.m3u8 的對外 URL。檔案由 nginx 直接服務，授權由 auth_request 子請求處理（見 nginx/nginx.conf）。"""
        if not self.hls_path:
            return None
        return settings.MEDIA_URL + filepath_to_uri(self.hls_path)

    def likes_count(self):
        return self.likes_dislikes.filter(type="like").count()

    def dislikes_count(self):
        return self.likes_dislikes.filter(type="dislike").count()

    def vote_counts(self):
        """一次 aggregate 同時取得讚/踩數，省去兩次獨立 COUNT。"""
        return self.likes_dislikes.aggregate(
            likes=models.Count("pk", filter=models.Q(type="like")),
            dislikes=models.Count("pk", filter=models.Q(type="dislike")),
        )
