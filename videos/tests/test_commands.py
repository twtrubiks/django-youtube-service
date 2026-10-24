"""管理指令測試：create_category。"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from videos.models import Category


class CreateCategoryCommandTests(TestCase):
    def test_creates_default_categories(self):
        call_command("create_category", stdout=StringIO())

        self.assertEqual(Category.objects.count(), 15)
        self.assertTrue(Category.objects.filter(name="音樂", slug="music").exists())

    def test_is_idempotent(self):
        """entrypoint.sh 每次容器啟動都會執行，重跑不可重複建立或報錯"""
        call_command("create_category", stdout=StringIO())
        call_command("create_category", stdout=StringIO())

        self.assertEqual(Category.objects.count(), 15)
