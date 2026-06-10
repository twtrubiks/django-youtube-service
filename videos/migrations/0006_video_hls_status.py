from django.db import migrations, models
from django.db.models import Q


def backfill_hls_status(apps, schema_editor):
    """回填既有影片的 HLS 狀態：有 hls_path 視為完成；已處理完成但無 hls_path 視為失敗（可由 admin 重新生成）。"""
    Video = apps.get_model("videos", "Video")
    Video.objects.exclude(Q(hls_path__isnull=True) | Q(hls_path="")).update(hls_status="completed")
    Video.objects.filter(processing_status="completed").filter(Q(hls_path__isnull=True) | Q(hls_path="")).update(
        hls_status="failed"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("videos", "0005_add_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="video",
            name="hls_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("completed", "Completed"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_hls_status, migrations.RunPython.noop),
    ]
