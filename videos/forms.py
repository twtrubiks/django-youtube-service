import os

from django import forms
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from .models import Category, Video


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name"]
        # slug will be auto-generated


class VideoUploadForm(forms.ModelForm):
    class Meta:
        model = Video
        fields = ["title", "description", "video_file", "thumbnail", "visibility", "category", "tags"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].required = False
        # For editing, video_file and thumbnail are not required
        if self.instance and self.instance.pk:
            self.fields["video_file"].required = False
            self.fields["thumbnail"].required = False

    def clean_video_file(self):
        video_file = self.cleaned_data.get("video_file")
        # 只驗證新上傳的檔案；編輯未換檔時拿到的是既有的 FieldFile
        if not isinstance(video_file, UploadedFile):
            return video_file

        max_size_mb = settings.VIDEO_UPLOAD_MAX_SIZE_MB
        if video_file.size > max_size_mb * 1024 * 1024:
            raise forms.ValidationError(f"File is too large. Maximum size is {max_size_mb} MB.")

        ext = os.path.splitext(video_file.name)[1].lstrip(".").lower()
        if ext not in settings.VIDEO_UPLOAD_ALLOWED_EXTENSIONS:
            allowed = ", ".join(e.upper() for e in settings.VIDEO_UPLOAD_ALLOWED_EXTENSIONS)
            raise forms.ValidationError(f"Unsupported file format. Please upload {allowed}.")

        return video_file

    def clean(self):
        cleaned_data = super().clean()
        title = cleaned_data.get("title")
        video_file = cleaned_data.get("video_file") or self.files.get("video_file")
        if not title and video_file:
            filename = getattr(video_file, "name", "")
            cleaned_data["title"] = os.path.splitext(os.path.basename(filename))[0][:255]
        return cleaned_data
