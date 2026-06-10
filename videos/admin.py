import os

from django.contrib import admin

from .models import Category, Video
from .tasks import generate_hls_files


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "uploader", "upload_date", "visibility", "category", "views_count", "hls_status")
    list_filter = ("uploader", "upload_date", "visibility", "category", "hls_status")
    search_fields = ("title", "description")
    actions = ["regenerate_hls"]
    # Taggit handles its own admin integration for the tags field,
    # but you can customize it further if needed.

    @admin.action(description="重新生成所選影片的 HLS 串流")
    def regenerate_hls(self, request, queryset):
        count = 0
        for video in queryset:
            if not video.video_file:
                continue
            file_name_without_ext = os.path.splitext(os.path.basename(video.video_file.name))[0]
            video.hls_status = "pending"
            video.save(update_fields=["hls_status"])
            generate_hls_files.delay(video.id, video.video_file.path, file_name_without_ext)
            count += 1
        self.message_user(request, f"已為 {count} 部影片排程 HLS 重新生成。")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
