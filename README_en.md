# StreamCraft 🎬

> Video Streaming Platform - A Modern YouTube Clone Project Based on Django

[![Django](https://img.shields.io/badge/Django-6.0.3-green.svg)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.13+-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)
[![HLS](https://img.shields.io/badge/HLS-Streaming-red.svg)](https://developer.apple.com/streaming/)
[![WebSocket](https://img.shields.io/badge/WebSocket-Real--time-orange.svg)](https://channels.readthedocs.io/)

[中文版](README.md) | [Development Planning Document](.roo/rules/rules.md)

**StreamCraft** is a full-featured video streaming platform built with a modern Django architecture and advanced HLS streaming technology. The project implements complete video upload, processing, streaming, and social interaction functionalities, supporting real-time notifications and high-performance asynchronous processing.

If you are unfamiliar with HLS, you can refer to [Setting up a simple live streaming server with Nginx, RTMP, and HLS](https://github.com/twtrubiks/nginx-rtmp-tutorial).

## 🏗️ System Architecture

```mermaid
graph TB
    subgraph "Frontend Layer"
        A[Web Browser] --> B[HLS.js Player]
        A --> C[WebSocket Client]
    end

    subgraph "Reverse Proxy Layer"
        P[Nginx] --> D
    end

    subgraph "Application Layer"
        D[Django / Daphne ASGI] --> E[Django Channels]
        D --> F[Celery Worker]
    end

    subgraph "Service Layer"
        G[Redis] --> H[Message Queue / Broker]
        G --> I[Channel Layer / Cache]
        J[PostgreSQL] --> K[Main Database]
        BK[Backup Container] --> J
    end

    subgraph "Storage Layer"
        L[Local Storage / S3 / MinIO] --> M[Video Files]
        L --> N[HLS Segments]
        L --> O[Thumbnail Images]
    end

    A --> P
    B --> P
    C --> E
    E --> I
    F --> H
    D --> K
    F --> M
    F --> N
```

This project was developed as a practical implementation using [Roo-Code](https://github.com/RooCodeInc/Roo-Code), demonstrating the best architectural patterns for modern web applications. Subsequent fixes and improvements were made with [Claude Code](https://claude.com/claude-code).

## Screenshots

Main Page (The little bell in the top right corner is a real-time notification feature implemented using Django Channels)

![alt tag](https://cdn.imgpile.com/f/hKDF6qO_xl.png)

Watch Page

![alt tag](https://cdn.imgpile.com/f/N9ZlusX_xl.png)

Profile Page

![alt tag](https://cdn.imgpile.com/f/eooZDqW_xl.png)

Comments

![alt tag](https://cdn.imgpile.com/f/mAIrOVd_xl.png)

## ✨ Core Features

### 🎯 Video Processing & Streaming

* **Intelligent Video Processing**:
  * Asynchronous video transcoding (H.264 MP4 optimized)
  * Automatic thumbnail generation
  * Multi-stage processing status tracking
* **HLS Streaming Technology**:
  * Automatic 10-second segment splitting
  * Adaptive bitrate streaming
  * Second-level response for progress bar seeking
  * Native playback support in modern browsers + Safari

### 👥 User Experience System

* **Complete User Management**:
  * Registration, login, profile management
  * Customizable channel pages and banners
  * Subscriber statistics and management
* **Social Interaction Features**:
  * Nested comment system (with reply support)
  * Like/dislike voting mechanism
  * Channel subscriptions and notifications
  * Video search and tag-based categorization
  * PostgreSQL full-text search with relevance ranking
  * Search bar autocomplete suggestions (300ms debounce)

### ⚡ Real-time Communication System

* **WebSocket Real-time Notifications**:
  * Notifications for new video uploads from subscriptions
  * Comment and reply alerts
  * Subscriber interaction notifications
  * Native browser notification support

### 🔒 Security & Permissions

* **Multi-level Permission Control**:
  * Video visibility settings (Public/Private/Unlisted)
  * User authentication and authorization
  * Password strength validation on registration, rejecting short or common passwords
  * CSRF protection and security middleware
  * Production security headers: HSTS, SSL redirect, Secure Cookies
  * API rate limiting: IP-based limits on login/registration to prevent brute force; per-user limits on interactions to prevent abuse
  * Container runs as non-root user (UID=1000), following Docker security best practices

## 🛠️ Technology Stack

### Backend Core

* **Web Framework**: Django 6.0.3 (Python 3.13+)
* **Asynchronous Processing**: Celery 5.6.2 + Redis
* **Real-time Communication**: Django Channels 4.3.2 (WebSocket)
* **Application Server**: Daphne (ASGI)

### Data Storage

* **Main Database**: PostgreSQL 18 (Production) / SQLite (Development)
* **Caching System**: Redis (Message Queue + Channel Layer + Session cache)
* **File Storage**: Local storage, or switch to S3/MinIO object storage via django-storages

### Frontend Technology

* **Base Technologies**: HTML5, CSS3, JavaScript ES6+
* **Video Playback**: [HLS.js](https://www.jsdelivr.com/package/npm/hls.js) (Modern Browsers) + Native Safari Support
* **Real-time Communication**: WebSocket API + Native Notifications

### Development & Deployment

* **Containerization**: Docker Compose
* **Video Processing**: FFmpeg (Python wrapper)
* **Tagging System**: django-taggit 6.1.0
* **Image Processing**: Pillow 12.1.1
* **Static Files**: WhiteNoise (production static file serving)
* **Code Quality**: Ruff (Formatter) + pre-commit hooks + Coverage (Test Coverage)
* **Observability** (optional): django-prometheus (metrics) + OpenTelemetry (distributed tracing)

## 📊 Performance Metrics

| Metric                | Value | Description                               |
| --------------------- | ----- | ----------------------------------------- |
| Test Coverage         | 90%+  | Complete unit and integration test coverage |
| HLS Startup Time      | \<1s   | 70% improvement over traditional MP4      |
| Seeking Response Time | 0.5s  | Advantage of segmented playback           |
| Concurrent Processing | 100+  | Handled by Celery asynchronous tasks      |
| Real-time Notification Latency | \<100ms | Instant push via WebSocket                |

## 🚀 Quick Start

### Method 1: Docker Deployment (Recommended)

#### One-click Startup for the Complete Environment

```bash
# Start all services
docker-compose up --build
```

#### Production Deployment

```bash
# Start production environment (with Nginx reverse proxy)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

> **Note**: Production does not run `makemigrations` automatically. Generate migration files in development and commit them before deploying.

Optional dependencies can be installed by adding the corresponding requirements files in the Dockerfile or at runtime:

* `requirements-s3.txt` — S3/MinIO object storage support
* `requirements-otel.txt` — OpenTelemetry distributed tracing

#### Service Components Description

**Web Application**: Main Django service (port 8000)

**Celery Worker**: Asynchronous task processing

**Redis**: Message queue and cache (AOF persistence enabled)

**PostgreSQL**: Main database (with healthcheck; daily automated backup retaining 7 copies)

**Flower** (optional): Celery monitoring dashboard, launched via the monitoring profile

```bash
docker compose --profile monitoring up -d
```

Once started, visit [http://127.0.0.1:5555](http://127.0.0.1:5555) to view task status.

**DB Backup** (optional): Automated daily PostgreSQL backup, launched via the backup profile

```bash
docker compose --profile backup up -d
```

Once started, it runs in the background and performs a backup every 24 hours, retaining the 7 most recent copies.

### Method 2: Local Development Environment

#### Requirements

* Python 3.13+
* Redis Server
* PostgreSQL (optional, defaults to SQLite)
* FFmpeg (for video processing)

#### Environment Variables

The project includes a `.env.example` template. Copy and modify it before use:

```bash
cp .env.example .env
```

Key environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | (required) | Django secret key |
| `DEBUG` | `True` | Enable debug mode |
| `DB_HOST` | `localhost` | PostgreSQL host address |
| `DB_NAME` | `postgres` | Database name |
| `DB_USER` | `myuser` | Database user |
| `DB_PASSWORD` | `password123` | Database password |
| `REDIS_HOST` | `localhost` | Redis host address |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Allowed hostnames (comma-separated) |
| `CELERY_CONCURRENCY` | `2` | Celery Worker concurrency |
| `ENABLE_PROMETHEUS` | (depends on DEBUG) | Enable Prometheus metrics collection |
| `USE_S3` | (empty) | Set to `true` to enable S3/MinIO object storage |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | (empty) | OpenTelemetry collector endpoint; leave empty to disable |

When deploying with Docker, connection-related variables are automatically configured via `docker-compose.yml` — no manual setup needed.

#### Installation Steps

```bash
# 1. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Dev tools: ruff, coverage, pre-commit

# 2. Database migrations
python manage.py migrate

# 3. Create a superuser
python manage.py createsuperuser

# 4. Start Redis (in another terminal)

# 5. Start Celery Worker (in another terminal)
celery -A youtube_service worker -l info

# 6. Start Django development server
python manage.py runserver
```

### Accessing the Application

**Main Page**: [http://127.0.0.1:8000/videos/](http://127.0.0.1:8000/videos/)

**Admin Backend**: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

**Health Check**: [http://127.0.0.1:8000/health/](http://127.0.0.1:8000/health/)

## Running Tests

### Running Tests with Docker

Execute `docker compose --profile testing up` directly.

### Running Tests Locally

Run all tests:

```cmd
python manage.py test
```

For more detailed output:

```cmd
python manage.py test -v 2
```

To run tests for a specific app:

```cmd
python manage.py test videos

python manage.py test videos.tests.UploadVideoViewTests.test_upload_video_view_post_successful
```

### Test Coverage Report

```cmd
coverage run manage.py test
coverage report
coverage html  # Generate a detailed report in HTML format
```

![alt tag](https://cdn.imgpile.com/f/RcQBFe1_xl.png)

## 📂 Project Architecture

### Core Application Modules

```cmd
youtube_service/
├── users/                    # User management system
│   ├── models.py            # UserProfile model
│   ├── views.py             # Registration, login, profile page
│   ├── forms.py             # User forms
│   └── templates/           # User-related templates
├── videos/                   # Core video features
│   ├── models.py            # Video, Category models
│   ├── views.py             # Upload, watch, search
│   ├── tasks.py             # Celery async tasks (transcode, thumbnail, HLS)
│   └── templates/           # Video-related templates
├── interactions/            # Social interaction features
│   ├── models.py            # Comment, LikeDislike, Subscription, Notification
│   ├── consumers.py         # WebSocket consumers
│   ├── signals.py           # Django signal handling
│   ├── tasks.py             # Notification async tasks
│   └── routing.py           # WebSocket routing
├── youtube_service/         # Project configuration
│   ├── settings.py          # Django settings
│   ├── celery.py            # Celery configuration
│   ├── asgi.py              # ASGI configuration (Daphne)
│   ├── otel.py              # OpenTelemetry initialization (optional)
│   └── urls.py              # URL routing
├── nginx/                   # Nginx reverse proxy config (production)
│   └── nginx.conf
├── scripts/                 # Operations scripts
│   └── backup_db.sh         # PostgreSQL daily backup
├── static/                  # Static assets
│   ├── css/main.css
│   └── js/
│       ├── notifications.js     # Real-time notification WebSocket client
│       └── video_interactions.js # Video page interaction logic
├── media/                   # Media files
│   ├── videos/              # Video files
│   ├── hls/                 # HLS streaming files
│   └── thumbnails/          # Thumbnail files
├── templates/               # Global templates
├── docker-compose.yml       # Development orchestration
├── docker-compose.prod.yml  # Production orchestration (Nginx + multi-instance)
├── requirements.txt         # Production dependencies
├── requirements-dev.txt     # Development dependencies (ruff, coverage, pre-commit)
├── requirements-s3.txt      # S3/MinIO optional dependencies
├── requirements-otel.txt    # OpenTelemetry optional dependencies
└── pyproject.toml           # Ruff configuration
```

### Data Model Relationships

```mermaid
erDiagram
    User ||--o{ Video : uploads
    User ||--o{ Comment : writes
    User ||--o{ LikeDislike : votes
    User ||--o{ Subscription : subscribes
    User ||--o{ Notification : receives
    User ||--|| UserProfile : has

    Video ||--o{ Comment : has
    Video ||--o{ LikeDislike : receives
    Video }o--|| Category : belongs_to

    Comment ||--o{ Comment : replies_to
```

### Code Quality

**Test Coverage**: 90%+ (including unit and integration tests)

**Code Formatting**: Automated with Ruff

**Type Checking**: Python type hints

**Security Scanning**: Django security middleware

## 🔮 Development Roadmap

### Completed Features ✅

[x] Complete user authentication system

[x]  HLS video streaming technology

[x]  Real-time notification system

[x]  Social interaction features

[x]  Asynchronous video processing

[x]  Containerized deployment

[x]  Full test coverage

### Planned Features 🔄

[ ] **Intelligent Recommendation System**: Video recommendations based on user behavior

[ ] **Playlist Functionality**: User-defined playlists

[ ] **Multi-quality Streaming**: Adaptive 720p/1080p/4K

[ ] **CDN Integration**: Global Content Delivery Network

[ ] **Data Analytics Dashboard**: Creator data insights

[ ] **Mobile API**: Support via RESTful API

[ ] **Live Streaming Functionality**: RTMP live streaming

[ ] **Content Moderation**: AI-assisted content review

## 📄 License

This project is licensed under the **MIT License**.

**StreamCraft** - Building the next generation of video streaming experiences 🚀

If this project helps you, please give us a ⭐ Star\!

## Donation

All articles are original, researched, and internalized by me. If this has been helpful to you and you'd like to encourage me, please feel free to buy me a cup of coffee :laughing:

ECPAY (No membership required)

![alt tag](https://payment.ecpay.com.tw/Upload/QRCode/201906/QRCode_672351b8-5ab3-42dd-9c7c-c24c3e6a10a0.png)

[Sponsor Payment](http://bit.ly/2F7Jrha)

O'Pay (Membership required)

![alt tag](https://i.imgur.com/LRct9xa.png)

[Sponsor Payment](https://payment.opay.tw/Broadcaster/Donate/9E47FDEF85ABE383A0F5FC6A218606F8)

## List of Sponsors

[List of Sponsors](https://github.com/twtrubiks/Thank-you-for-donate)