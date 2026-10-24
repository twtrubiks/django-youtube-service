"""測試基礎設施：test runner 與跨 app 共用的測試工具。"""

from unittest.mock import patch

from django.core.cache import cache
from django.test.runner import DiscoverRunner
from django.test.utils import override_settings

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


class IsolatedCacheTestRunner(DiscoverRunner):
    """測試期間把 cache 換成 per-process 記憶體 cache。

    settings 的 cache 指向共用 Redis，session 與 django-ratelimit 的計數都存在這裡：
    直接拿來跑測試，ratelimit 計數會跨測試回合累積（一分鐘內連跑第二次，登入/註冊測試就收到 403），
    在 docker 中還會把測試 session 寫進開發環境正在使用的 Redis。
    """

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._cache_override = override_settings(CACHES=TEST_CACHES)
        self._cache_override.enable()

    def teardown_test_environment(self, **kwargs):
        self._cache_override.disable()
        super().teardown_test_environment(**kwargs)


class RateLimitTestMixin:
    """ratelimit 測試：計數放在專屬且清空的 cache，並凍結 django-ratelimit 的時間。

    專屬 cache 讓灌爆的計數不影響同一回合其他測試的登入/註冊請求；
    django-ratelimit 以固定時間窗計數，凍結時間避免請求剛好跨越時間窗造成偶發失敗。
    """

    def setUp(self):
        super().setUp()
        cache_override = override_settings(
            CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "ratelimit"}}
        )
        cache_override.enable()
        self.addCleanup(cache_override.disable)
        cache.clear()

        time_patcher = patch("django_ratelimit.core.time")
        time_patcher.start().time.return_value = 1_700_000_000.0
        self.addCleanup(time_patcher.stop)

    def assert_rate_limited(self, limit, make_request):
        """前 limit 次請求不被擋，第 limit + 1 次回 403。"""
        for _ in range(limit):
            self.assertNotEqual(make_request().status_code, 403)
        self.assertEqual(make_request().status_code, 403)
