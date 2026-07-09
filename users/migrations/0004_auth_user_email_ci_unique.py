from django.conf import settings
from django.db import migrations
from django.db.models import Count
from django.db.models.functions import Lower


def check_no_duplicate_emails(apps, schema_editor):
    """建立唯一索引前先確認沒有既存的重複 email（不分大小寫），有則列出並中止。"""
    User = apps.get_model("auth", "User")
    duplicates = (
        User.objects.exclude(email="")
        .annotate(email_lower=Lower("email"))
        .values("email_lower")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .values_list("email_lower", flat=True)
    )
    if duplicates:
        raise RuntimeError(
            "無法建立 email 唯一索引，以下 email 已有重複（不分大小寫），請先清理再 migrate：" + ", ".join(duplicates)
        )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("users", "0003_add_subscriber_count"),
    ]

    operations = [
        migrations.RunPython(check_no_duplicate_emails, migrations.RunPython.noop),
        # 表單層 clean_email 是「先查再寫」，擋不住併發請求的競態，唯一索引是最後防線。
        # 排除空字串：createsuperuser 等路徑允許不填 email。
        migrations.RunSQL(
            sql="CREATE UNIQUE INDEX auth_user_email_lower_uniq ON auth_user (LOWER(email)) WHERE email <> '';",
            reverse_sql="DROP INDEX auth_user_email_lower_uniq;",
        ),
    ]
