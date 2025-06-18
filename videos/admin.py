from django.contrib import admin
from .models import Video, Category

@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ('title', 'uploader', 'upload_date', 'visibility', 'category', 'views_count')
    list_filter = ('uploader', 'upload_date', 'visibility', 'category')
    search_fields = ('title', 'description')
    # Taggit handles its own admin integration for the tags field,
    # but you can customize it further if needed.

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}

# Register your models here.
