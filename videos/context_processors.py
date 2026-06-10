from .models import Category


def categories(request):
    """提供側欄與分類列使用的全站分類清單。"""
    return {"nav_categories": Category.objects.order_by("name")}
