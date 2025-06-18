from django import forms
from .models import Video, Category

class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name']
        # slug will be auto-generated

class VideoUploadForm(forms.ModelForm):
    class Meta:
        model = Video
        fields = ['title', 'description', 'video_file', 'thumbnail', 'visibility', 'category', 'tags']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # For editing, video_file and thumbnail are not required
        if self.instance and self.instance.pk:
            self.fields['video_file'].required = False
            self.fields['thumbnail'].required = False