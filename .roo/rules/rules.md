# 核心架構概覽

一個類似 YouTube 的網站，其後端架構通常包含以下幾個主要組件：

1. **Web 伺服器 (例如 Nginx):**
    * 接收前端的 HTTP 請求。
    * 提供靜態檔案 (CSS, JavaScript, 圖片)。
    * 作為反向代理，將動態請求轉發給應用程式伺服器。
2. **應用程式伺服器 (WSGI/ASGI):**
    * 運行 Django 應用程式 (例如 Gunicorn (WSGI) 或 Uvicorn/Daphne (ASGI，若使用 Django Channels 處理即時通訊))。
3. **Django 應用程式 (核心後端):**
    * **使用者認證與管理:** 註冊、登入、個人資料。
    * **影片管理:** 上傳、處理、儲存影片元數據 (標題、描述、標籤等)。
    * **互動功能:** 留言、按讚/倒讚、訂閱。
    * **搜尋功能。**
    * **API 端點:** (可選) 若未來有獨立前端 (如 React/Vue) 或手機 App 需求，可使用 Django REST framework。
4. **資料庫 (例如 PostgreSQL):**
    * 儲存結構化數據，如使用者資訊、影片元數據、留言、按讚記錄等。PostgreSQL 因其處理複雜查詢和擴展性的能力，通常是首選。
5. **物件儲存**
    * 儲存大型媒體檔案，主要是影片檔案和縮圖。直接存在 Django 伺服器上不適合大規模應用。
6. **快取系統 (Redis):**
    * 快取常用的數據查詢結果、頁面片段，以提高網站回應速度和減輕資料庫負載。
7. **任務佇列 (例如 Celery 搭配 RabbitMQ 或 Redis 作為 Broker):**
    * 處理耗時的背景任務，例如影片轉檔、發送通知郵件、產生縮圖等，避免阻塞主應用程式的回應。
8. **搜尋引擎 (例如 Elasticsearch, Solr):** (進階)
    * 提供更強大、更快速的搜尋功能，而不僅僅是依賴資料庫的 `LIKE` 查詢。
9. **內容傳遞網路 (CDN):**
    * 將靜態資源 (如 CSS, JS, 圖片) 和影片內容分發到全球各地的邊緣節點，讓使用者可以從最近的伺服器載入，加速存取。
10. **即時通訊 (可選，例如 Django Channels):**
    * 用於實現即時通知、直播聊天等功能。

## 開發步驟 (分階段進行)

將專案分解為多個階段，逐步實現功能，是一種比較好的實踐方式。

### 階段 0: 環境設定與專案初始化

1. **建立 Django 專案:** `django-admin startproject youtube_service`
2. **建立核心應用 (App):**
    * `cd youtube_service`
    * `python manage.py startapp users` (處理使用者相關功能)
    * `python manage.py startapp videos` (處理影片相關功能)
    * `python manage.py startapp interactions` (處理留言、按讚等互動)
3. **資料庫設定:**
    * 在 `settings.py` 中設定你選擇的資料庫 (初期可以使用 SQLite 方便開發，後期建議換成 PostgreSQL)。
4. **執行首次遷移:** `python manage.py migrate`
5. **設定靜態檔案 (Static Files) 和媒體檔案 (Media Files) 路徑:**
    * 在 `settings.py` 中設定 `STATIC_URL`, `STATICFILES_DIRS`, `MEDIA_URL`, `MEDIA_ROOT`。

### 階段 1: 使用者認證與個人頻道基礎

1. **使用者模型 (`users` app):**
    * 可以擴展 Django 內建的 `User` 模型，或建立一個自訂的 `UserProfile` 模型來儲存額外資訊 (例如頭像、頻道描述等)。
    * `models.py`
2. **使用者註冊、登入、登出功能:**
    * 使用 Django 內建的 `django.contrib.auth.views` 或自行撰寫視圖。
    * 建立相應的表單 (`forms.py`) 和模板 (`templates`)。
3. **個人頻道頁面 (基礎):**
    * 顯示使用者上傳的影片列表 (目前為空)。

### 階段 2: 影片上傳與顯示基礎

1. **影片模型 (`videos` app):**
    * `models.py`: 包含欄位如 `title`, `description`, `video_file` (FileField), `thumbnail` (ImageField), `uploader` (ForeignKey to User), `upload_date`, `views_count` (IntegerField, default 0), `visibility` (public, private, unlisted) 等。
2. **影片上傳表單與視圖:**
    * `forms.py`: 建立影片上傳表單。
    * `views.py`: 處理表單提交、儲存影片檔案和影片元數據。
    * 注意檔案上傳的處理 (`request.FILES`)。
3. **影片儲存:**
    * 初期可將影片儲存在 `MEDIA_ROOT` 指定的本地資料夾。
    * **重要:** 長期規劃應使用物件儲存 (AWS S3, Google Cloud Storage等)。
4. **影片播放頁面:**
    * 建立一個簡單的 HTML5 `<video>` 標籤來播放影片。
    * `views.py`: 根據影片 ID 取得影片資訊並傳遞到模板。
    * `templates`: 顯示影片、標題、描述、上傳者等。
5. **影片列表頁面 (首頁):**
    * 顯示最近上傳的影片或熱門影片。

### 階段 3: 影片處理 (背景任務)

* **整合 Celery:**
  * 安裝 Celery 和消息代理 (如 Redis 或 RabbitMQ)。
  * 在 Django 專案中設定 Celery。
* **建立背景任務 (`tasks.py` in `videos` app):**
  * **影片轉檔:** 使用 `ffmpeg` 等工具將上傳的影片轉換為標準格式 (如 H.264 MP4) 和不同解析度，以適應不同網路環境。
  * **HLS 串流生成:** 使用 `ffmpeg` 將影片切分為 HLS (HTTP Live Streaming) 格式，生成播放清單 (.m3u8) 和片段文件 (.ts)，提供更好的拖拉體驗和網路適應性。
  * **縮圖產生:** 從影片中擷取一幀作為縮圖，或允許使用者上傳自訂縮圖。
  * **更新影片狀態:** 在影片模型中增加一個欄位 (例如 `processing_status`) 來追蹤處理進度。
* **觸發任務:** 在影片上傳成功後，異步觸發這些 Celery 任務。

### 階段 3.5: HLS 串流實作 (已實作)

* **HLS 文件生成:**
  * 在 `process_video` 任務中整合 `generate_hls_files` 函數。
  * 使用 FFmpeg 將影片切分為 10 秒片段，生成 `.m3u8` 播放清單和 `.ts` 片段文件。
  * 文件存儲結構：`media/hls/{video_id}_{filename}/playlist.m3u8`
* **HLS 服務端點:**
  * 實作 `serve_hls_playlist` 視圖提供播放清單文件。
  * 實作 `serve_hls_segment` 視圖提供片段文件。
* **前端 HLS 播放器:**
  * 整合 HLS.js 庫支援現代瀏覽器。
  * Safari 使用原生 HLS 支援。
  * 實作錯誤處理和自動回退到 MP4 機制。
* **URL 路由配置:**
  * `/videos/{video_id}/hls/playlist.m3u8` - HLS 播放清單
  * `/videos/{video_id}/hls/{segment_name}` - HLS 片段文件

### 階段 4: 核心互動功能 (`interactions` app)

1. **留言系統:**
    * **Comment 模型:** `models.py` (欄位: `video` (ForeignKey), `user` (ForeignKey), `content` (TextField), `timestamp`)。
    * **新增留言:** 表單和視圖，允許登入使用者在影片下方留言 (可以使用 AJAX 實現無刷新提交)。
    * **顯示留言:** 在影片播放頁面顯示留言列表。
2. **按讚/倒讚系統:**
    * **Like/Dislike 模型:** `models.py` (欄位: `video` (ForeignKey), `user` (ForeignKey), `type` (讚或倒讚))。
    * **邏輯:** 處理使用者對影片的按讚/倒讚操作 (可以使用 AJAX)。
    * **計數更新:** 在影片模型中增加 `likes_count` 和 `dislikes_count` 欄位，或動態計算。
3. **訂閱系統:**
    * **Subscription 模型:** `models.py` (欄位: `subscriber` (ForeignKey to User), `subscribed_to` (ForeignKey to User - 代表頻道擁有者))。
    * **訂閱/取消訂閱按鈕與邏輯。**
4. **觀看次數追蹤:**
    * 在影片模型中增加 `views_count` 欄位。
    * 每次影片被觀看時 (通常是影片播放頁面被載入時)，增加觀看次數。需要考慮防止重複計算 (例如基於 IP 和時間間隔)。

### 階段 5: 搜尋與探索

1. **基本搜尋:**
    * 在 `videos` app 中建立搜尋視圖。
    * 使用 Django ORM 的 `Q` 物件來搜尋影片標題、描述、標籤等。
    * 建立搜尋結果頁面。
2. **標籤 (Tags):**
    * 可以考慮使用 `django-taggit` 或類似套件來為影片添加標籤。
    * 允許按標籤瀏覽影片。
3. **分類 (Categories):**
    * 如果需要，可以為影片增加分類功能。

### 階段 6: 進階功能與擴展

1. **影片推薦系統 (非常複雜):**
    * 初期可以做簡單的「相關影片」(例如基於相同標籤或分類)。
    * 進階的推薦系統需要機器學習演算法。
2. **影片串流優化 (已實作 HLS 基礎版本):**
    * ✅ **已實作 HLS (HTTP Live Streaming):** 提供更好的拖拉體驗、網路適應性和播放穩定性。
    * **進階 HLS 功能 (未來擴展):**
        * 多品質自適應串流 (720p, 1080p, 4K)
        * 根據網路狀況動態調整品質
        * CDN 整合優化
    * **DASH (Dynamic Adaptive Streaming over HTTP):** 作為 HLS 的替代方案考慮。
3. **即時通知 (Django Channels):**
    * 當訂閱的頻道有新影片、或留言被回覆時，發送即時通知。
4. **強化搜尋 (Elasticsearch/Solr):**
    * 整合專業搜尋引擎以提供更相關、更快速的搜尋結果，支援拼寫校正、同義詞等。
5. **管理後台強化:**
    * 客製化 Django Admin，使其更易於管理影片、使用者、審核內容等。

## 建議使用的關鍵 Django App/函式庫

* **`django.contrib.auth`:** 內建使用者認證。
* **`django.contrib.staticfiles`:** 管理靜態檔案。
* **Pillow:** 處理圖片 (例如縮圖)。
* **Celery:** 執行背景任務。
* **django-storages:** 方便整合雲端儲存 (AWS S3, Google Cloud Storage 等)。
* **Django REST framework:** (若需 API) 建立強大的 Web API。
* **django-crispy-forms:** (可選) 美化表單。
* **django-taggit:** (可選) 實現標籤功能。
* **ffmpeg-python:** (Python wrapper for ffmpeg) 用於影片處理任務。
* **Django Channels:** (可選) 用於 WebSocket 和即時通訊。
* **HLS.js:** 前端 JavaScript 庫，用於在現代瀏覽器中播放 HLS 串流。

## HLS (HTTP Live Streaming) 技術說明

### 🎯 為什麼選擇 HLS？

**傳統 MP4 播放的問題：**

* 拖拉進度條時需要下載大量不必要的數據
* 網路不穩定時播放體驗差
* 無法根據網路狀況調整品質

**HLS 的優勢：**
**更好的拖拉體驗：** 影片被切分為小片段（10秒），拖拉時只需下載目標片段
**網路適應性：** 可根據網路狀況調整播放品質
**更快的啟動時間：** 不需要下載整個文件即可開始播放
**錯誤恢復：** 單個片段失敗不會影響整體播放

### 🔧 技術實作細節

**文件結構：**

```cmd
media/hls/{video_id}_{filename}/
├── playlist.m3u8      # 主播放清單
├── segment_000.ts     # 影片片段 (10秒)
├── segment_001.ts
└── ...
```

**核心組件：**

**後端 HLS 生成：** `videos/tasks.py` 中的 `generate_hls_files()` 函數
**HLS 服務端點：** `videos/views.py` 中的播放清單和片段服務視圖
**前端播放器：** 整合 HLS.js 庫，支援自動回退到 MP4

**URL 結構：**

播放清單：`/videos/{video_id}/hls/playlist.m3u8`

片段文件：`/videos/{video_id}/hls/segment_xxx.ts`

### 📊 性能對比

| 場景 | 傳統 MP4 | HLS |
|------|----------|-----|
| 拖拉響應時間 | 3-10 秒 | 0.5-1 秒 |
| 網絡使用效率 | 低 | 高 |
| 記憶體使用 | 高 | 低 |
| 錯誤恢復能力 | 差 | 好 |

## 重要考量

* **從 MVP (最小可行性產品) 開始:** 先實現最核心的功能 (使用者、影片上傳/播放)，然後逐步迭代增加功能。
* **影片處理的複雜性:** 影片轉檔、儲存和串流是這個專案中最具挑戰性的部分之一，需要仔細規劃。
* **擴展性:** 隨著使用者和影片數量的增長，需要考慮資料庫優化、快取策略、負載平衡等。
* **成本:** 物件儲存、CDN、強大的伺服器都會帶來營運成本。
* **安全性:** 保護使用者數據，防止惡意上傳和攻擊。
* **版權問題:** 如果允許使用者上傳內容，需要考慮版權檢測和處理機制。

這是一個龐大但非常有趣的專案。祝你開發順利！在開發過程中遇到具體問題時，隨時可以提出。
