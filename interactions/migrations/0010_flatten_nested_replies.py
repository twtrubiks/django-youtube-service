# 留言串改為兩層結構（頂層留言 + 扁平回覆），攤平既有的深巢狀回覆：
# 把「回覆的回覆」逐層上提，直到所有回覆都直接掛在頂層留言下。

from django.db import migrations


def flatten_nested_replies(apps, schema_editor):
    Comment = apps.get_model("interactions", "Comment")
    while True:
        deep_replies = Comment.objects.exclude(parent_comment=None).exclude(parent_comment__parent_comment=None)
        updated = 0
        for comment in deep_replies.select_related("parent_comment"):
            comment.parent_comment_id = comment.parent_comment.parent_comment_id
            comment.save(update_fields=["parent_comment"])
            updated += 1
        if not updated:
            break


class Migration(migrations.Migration):
    dependencies = [
        ("interactions", "0009_alter_comment_content_and_more"),
    ]

    operations = [
        migrations.RunPython(flatten_nested_replies, migrations.RunPython.noop),
    ]
