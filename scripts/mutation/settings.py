"""變異測試專用設定：沿用專案設定，只調整與被測行為無關、但影響速度與隔離的部分。"""

import os

# 測試需要 DEBUG=True（否則 SECURE_SSL_REDIRECT 讓所有請求 301），與 docker 的 .env 一致
os.environ.setdefault("DEBUG", "True")

from youtube_service.settings import *  # noqa: E402,F403

# 每個 mutant 都要跑一次完整測試；測試大量 create_user/login，PBKDF2 雜湊占了九成以上的執行時間
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# 平行 worker 各自使用獨立的測試資料庫
DATABASES["default"]["TEST"] = {"NAME": os.environ.get("MUTATION_TEST_DB", "test_mutation")}  # noqa: F405

LOGGING = {"version": 1, "disable_existing_loggers": False, "root": {"handlers": [], "level": "CRITICAL"}}
