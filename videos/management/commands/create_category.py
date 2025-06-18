from django.core.management.base import BaseCommand
from videos.models import Category

class Command(BaseCommand):
    help = 'Creates category if it does not exist.'

    # python3 manage.py create_category

    def handle(self, *args, **kwargs):
        categories = [
            {"name": "人物與網誌", "slug": "people-and-blogs"},
            {"name": "汽車與車輛", "slug": "autos-and-vehicles"},
            {"name": "非營利組織與社運活動", "slug": "nonprofits-and-activism"},
            {"name": "科學與科技", "slug": "science-and-technology"},
            {"name": "音樂", "slug": "music"},
            {"name": "娛樂", "slug": "entertainment"},
            {"name": "旅遊與活動", "slug": "travel-and-events"},
            {"name": "教育", "slug": "education"},
            {"name": "喜劇", "slug": "comedy"},
            {"name": "新聞與政治", "slug": "news-and-politics"},
            {"name": "遊戲", "slug": "gaming"},
            {"name": "電影與動畫", "slug": "film-and-animation"},
            {"name": "寵物與動物", "slug": "pets-and-animals"},
            {"name": "體育", "slug": "sports"},
            {"name": "DIY 教學與生活風格", "slug": "diy-howto-and-style"}
        ]

        for category in categories:
            category_obj, created = \
                Category.objects.get_or_create(name=category['name'], slug=category['slug'])
            self.stdout.write(self.style.SUCCESS(f'Successfully created category "{category_obj.name}"'))
