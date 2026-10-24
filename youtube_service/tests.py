"""專案層級測試：健康檢查端點、model 與 migration 一致性。"""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse


class HealthCheckTests(TestCase):
    def test_health_check_ok(self):
        response = self.client.get(reverse("health_check"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_check_degraded_when_db_unavailable(self):
        """DB 連不上時仍回 200 並標記 degraded（docker healthcheck 只看 app 是否存活）"""
        with patch("youtube_service.urls.connection") as mock_connection:
            mock_connection.ensure_connection.side_effect = Exception("connection refused")
            response = self.client.get(reverse("health_check"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "degraded", "db": "unavailable"})


class MigrationConsistencyTests(TestCase):
    def test_no_missing_migrations(self):
        """model 定義必須與 migration 檔一致。

        生產環境不跑 makemigrations（見 entrypoint.sh），漏 commit 的 migration 會讓 schema 與程式碼脫節；
        max_length、db_index、unique、null 等欄位選項的修改也因此必須伴隨 migration。
        """
        out = StringIO()
        try:
            call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=StringIO())
        except SystemExit:
            self.fail(f"model 變更缺少對應的 migration：\n{out.getvalue()}")
