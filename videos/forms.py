import os

from django import forms

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

    def clean(self):
        cleaned_data = super().clean()
        title = cleaned_data.get("title")
        video_file = cleaned_data.get("video_file") or self.files.get("video_file")
        if not title and video_file:
            filename = getattr(video_file, "name", "")
            cleaned_data["title"] = os.path.splitext(filename)[0][:255]
        return cleaned_data
