// 假設您在模板中以某種方式設定了 currentUserId
// 例如: const currentUserId = JSON.parse(document.getElementById('current-user-id').textContent);
// 或者直接在腳本中嵌入，但前者更安全

var wsReconnectAttempts = 0;

function initializeNotificationWebSocket(userId) {
    if (!userId) {
        console.log("User ID not provided, WebSocket for notifications not started.");
        return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsPath = `${protocol}//${window.location.host}/ws/notifications/${userId}/`;

    const notificationSocket = new WebSocket(wsPath);

    notificationSocket.onopen = function(e) {
        console.log("Notification WebSocket connection established.");
        wsReconnectAttempts = 0;
    };

    notificationSocket.onmessage = function(e) {
        const data = JSON.parse(e.data); // data = {type: 'new_video', message: { actual_payload }}
        console.log("Notification received via WebSocket:", data);

        // Construct a notification object similar to historical ones for consistent handling
        // The consumer now saves to DB and should ideally send back the created notification object,
        // including its ID. For now, we assume `data.message` is the payload and `data.type` is the notification type.
        // A true WebSocket notification is always new and unread.
        const wsNotificationObject = {
            id: data.message.id || `ws-${Date.now()}`, // Use server-sent ID if available, else temporary
            message: data.message, // This is the payload object
            link: data.message.url || (data.message.video_id ? `/videos/${data.message.video_id}/` : '#'), // Construct link
            is_read: false,
            timestamp: new Date().toISOString(), // Use current time for WS messages
            type: data.type // This is the 'new_video', 'new_reply' etc.
        };

        // If the link needs a comment anchor
        if (data.message.video_id && data.message.parent_comment_id) {
            wsNotificationObject.link = `/videos/${data.message.video_id}/#comment-${data.message.parent_comment_id}`;
        } else if (data.message.video_id && data.message.comment_id) {
             wsNotificationObject.link = `/videos/${data.message.video_id}/#comment-${data.message.comment_id}`;
        }


        addNotificationToDropdown(wsNotificationObject, true); // Prepend new WS notifications

        unreadNotificationCount++;
        updateUnreadCountDisplay(); // Update bell icon indicator
    };

    notificationSocket.onclose = function(e) {
        console.error('Notification WebSocket closed. Code:', e.code);
        if (e.code !== 1000) {
            var delay = Math.min(1000 * Math.pow(2, wsReconnectAttempts), 30000);
            wsReconnectAttempts++;
            console.log('Reconnecting in ' + delay + 'ms (attempt ' + wsReconnectAttempts + ')');
            setTimeout(function() { initializeNotificationWebSocket(userId); }, delay);
        }
    };

    notificationSocket.onerror = function(err) {
        console.error('Notification WebSocket error:', err.message);
    };

}

// --- 通知指示器和下拉列表相關函數 ---
let unreadNotificationCount = 0;
const MAX_DROPDOWN_NOTIFICATIONS = 15; // Max notifications to show in dropdown

// Function to get CSRF token
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}
window.csrftoken = getCookie('csrftoken');

function updateUnreadCountDisplay() {
    const countElement = document.getElementById('notification-count');
    const indicatorDot = document.getElementById('notification-indicator-dot');

    if (unreadNotificationCount > 0) {
        if (countElement) {
            countElement.textContent = unreadNotificationCount > 9 ? '9+' : unreadNotificationCount;
            countElement.style.display = 'block';
        }
        if (indicatorDot) {
            indicatorDot.style.display = 'block';
        }
    } else {
        if (countElement) {
            countElement.style.display = 'none';
        }
        if (indicatorDot) {
            indicatorDot.style.display = 'none';
        }
    }
}

function showNotificationIndicator() {
    // This function now primarily ensures the display is updated if count changes.
    // The actual incrementing of unreadNotificationCount will happen when a new unread notification is added.
    updateUnreadCountDisplay();
}

function clearNotificationIndicator() { // Called when dropdown opens
    const indicator = document.getElementById('notification-indicator-dot');
    const countElement = document.getElementById('notification-count');
    if (indicator) {
        indicator.style.display = 'none';
    }
    if (countElement) {
        countElement.style.display = 'none';
    }
    // Mark all as read on server - will be called by markAllNotificationsAsReadAPI
    // markAllNotificationsAsReadAPI(); // We will call this explicitly in toggleNotificationDropdown
}

function escapeHTML(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

const NOTIFICATION_ICONS = {
    'new_video': `<div class="notification-icon notification-icon--video">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/>
        </svg>
    </div>`,
    'new_reply': `<div class="notification-icon notification-icon--reply">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <path d="M10 9V5l-7 7 7 7v-4.1c5 0 8.5 1.6 11 5.1-1-5-4-10-11-11z"/>
        </svg>
    </div>`,
    'new_comment_on_video': `<div class="notification-icon notification-icon--comment">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <path d="M21.99 4c0-1.1-.89-2-1.99-2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h14l4 4-.01-18z"/>
        </svg>
    </div>`,
    'new_subscription': `<div class="notification-icon notification-icon--subscription">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <path d="M15 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm-9-2V7H4v3H1v2h3v3h2v-3h3v-2H6zm9 4c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>
        </svg>
    </div>`
};

const NOTIFICATION_ICON_GENERIC = `<div class="notification-icon notification-icon--generic">
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
        <path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.89 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/>
    </svg>
</div>`;

function getNotificationIcon(notificationType) {
    return NOTIFICATION_ICONS[notificationType] || NOTIFICATION_ICON_GENERIC;
}

function buildCommentNotificationHTML(actorName, videoTitle, verb, content) {
    return `
        <span class="notification-detail-line">
            <span class="notification-detail-value"><strong>${escapeHTML(actorName)}</strong> 在 <em>${escapeHTML(videoTitle)}</em> ${verb}</span>
        </span>
        <span class="notification-detail-quote">"${escapeHTML(content)}"</span>`;
}

function formatNotificationHTML(notification) {
    let payload = notification.message;
    let notificationType = notification.type;

    if (typeof payload === 'string') {
        try {
            payload = JSON.parse(payload);
            if (payload && payload.type && !notificationType) {
                notificationType = payload.type;
            }
        } catch (e) {
            // not JSON, use as-is
        }
    }

    let title = "通知";
    let detailsHTML = "";
    let link = notification.link || (payload && payload.url) || '#';
    let typeForClass = notificationType || 'generic-notification';
    let thumbnailHTML = "";

    if (typeof payload === 'object' && payload !== null) {
        if ((!notification.link || notification.link === '#') && payload.video_id) {
            link = `/videos/${payload.video_id}/`;
            if (payload.parent_comment_id) {
                link += `#comment-${payload.parent_comment_id}`;
            } else if (payload.comment_id) {
                link += `#comment-${payload.comment_id}`;
            }
        }

        if (notificationType === 'new_video') {
            title = "新影片發布！";
            detailsHTML = `
                <span class="notification-detail-line">
                    <span class="notification-detail-label">頻道</span>
                    <span class="notification-detail-value">${escapeHTML(payload.uploader_name)}</span>
                </span>
                <span class="notification-detail-line">
                    <span class="notification-detail-label">標題</span>
                    <span class="notification-detail-value">${escapeHTML(payload.video_title)}</span>
                </span>`;
            if (payload.thumbnail_url) {
                thumbnailHTML = `<img class="notification-thumbnail" src="${escapeHTML(payload.thumbnail_url)}" alt="影片縮圖">`;
            }
        } else if (notificationType === 'new_reply') {
            title = "您的留言有新回覆！";
            detailsHTML = buildCommentNotificationHTML(
                payload.replier_name || 'N/A', payload.video_title || 'N/A',
                '回覆了您', payload.comment_content || '');
        } else if (notificationType === 'new_comment_on_video') {
            title = "您的影片有新留言！";
            detailsHTML = buildCommentNotificationHTML(
                payload.commenter_name || 'N/A', payload.video_title || 'N/A',
                '留言', payload.comment_content || '');
        } else if (notificationType === 'new_subscription') {
            title = "有新的訂閱者！";
            detailsHTML = `
                <span class="notification-detail-line">
                    <span class="notification-detail-value"><strong>${escapeHTML(payload.subscriber_name)}</strong> 訂閱了您的頻道</span>
                </span>`;
        } else {
            title = escapeHTML(payload.title) || "通知";
            detailsHTML = `<span class="notification-detail-line"><span class="notification-detail-value">${escapeHTML(payload.text || JSON.stringify(payload))}</span></span>`;
        }
    } else if (typeof payload === 'string') {
        detailsHTML = `<span class="notification-detail-line"><span class="notification-detail-value">${escapeHTML(payload)}</span></span>`;
    } else {
        detailsHTML = `<span class="notification-detail-line"><span class="notification-detail-value">無法正確顯示通知內容。</span></span>`;
    }

    const timestampHTML = notification.timestamp
        ? `<span class="notification-timestamp">${timeSince(new Date(notification.timestamp))}</span>`
        : '';

    return `
        <div class="notification-item-content ${escapeHTML(typeForClass)}">
            ${getNotificationIcon(notificationType)}
            <div class="notification-body">
                <div class="notification-header-row">
                    <p class="notification-title">${escapeHTML(title)}</p>
                    ${timestampHTML}
                </div>
                <div class="notification-details">
                    ${detailsHTML}
                </div>
                ${thumbnailHTML}
                ${link && link !== '#' ? `<a href="${escapeHTML(link)}" class="notification-link">查看詳情 &rarr;</a>` : ''}
            </div>
        </div>
    `;
}

// Helper function for time since
function timeSince(date) {
    if (!(date instanceof Date) || isNaN(date)) {
        return ''; // Return empty if date is invalid
    }
    const seconds = Math.floor((new Date() - date) / 1000);
    let interval = seconds / 31536000;
    if (interval > 1) return Math.floor(interval) + " 年前";
    interval = seconds / 2592000;
    if (interval > 1) return Math.floor(interval) + " 月前";
    interval = seconds / 86400;
    if (interval > 1) return Math.floor(interval) + " 天前";
    interval = seconds / 3600;
    if (interval > 1) return Math.floor(interval) + " 小時前";
    interval = seconds / 60;
    if (interval > 1) return Math.floor(interval) + " 分鐘前";
    if (seconds < 0) return "剛剛"; // Handle future or same time
    return Math.floor(seconds) + " 秒前";
}

function addNotificationToDropdown(notification, prepend = true) { // notification is an object
    const dropdownList = document.getElementById('notification-dropdown-list');
    if (dropdownList) {
        const listItem = document.createElement('li');
        listItem.className = 'notification-item'; // Add a general class for all items
        listItem.innerHTML = formatNotificationHTML(notification);
        listItem.dataset.notificationId = notification.id;

        if (!notification.is_read) {
            listItem.classList.add('unread');
        }


        if (prepend) {
            dropdownList.prepend(listItem);
        } else {
            dropdownList.appendChild(listItem); // For historical, append to maintain order (oldest at bottom)
        }

        // Maintain max items
        while (dropdownList.children.length > MAX_DROPDOWN_NOTIFICATIONS) {
            if (prepend) { // if adding to top, remove from bottom
                dropdownList.removeChild(dropdownList.lastChild);
            } else { // if adding to bottom (historical), remove from top
                dropdownList.removeChild(dropdownList.firstChild);
            }
        }
    }
}

async function fetchAndDisplayHistoricalNotifications() {
    if (typeof currentLoggedInUserId === 'undefined' || !currentLoggedInUserId) {
        console.log("User ID not available for fetching historical notifications.");
        return;
    }
    try {
        const response = await fetch('/interactions/notifications/');
        if (!response.ok) {
            console.error('Failed to fetch historical notifications:', response.status, await response.text());
            return;
        }
        const data = await response.json();
        const notifications = data.data.notifications || [];

        const dropdownList = document.getElementById('notification-dropdown-list');
        if(dropdownList) dropdownList.innerHTML = ''; // Clear previous items before loading new ones

        let currentUnreadCount = 0;
        // Reverse the array from server (newest-first) to process oldest-first.
        // Then, use prepend in addNotificationToDropdown (by passing true).
        // This ensures that when iterating oldest-first and prepending,
        // the newest items correctly end up at the top of the dropdown.
        notifications.reverse().forEach(notification => {
            addNotificationToDropdown(notification, true); // true for prepend
            if (!notification.is_read) {
                currentUnreadCount++;
            }
        });
        unreadNotificationCount = currentUnreadCount;
        updateUnreadCountDisplay();

    } catch (error) {
        console.error('Error fetching historical notifications:', error);
    }
}

// --- Mark as Read API Calls ---
async function markNotificationAsReadAPI(notificationId, listItemElement) {
    if (!notificationId) return;
    try {
        const response = await fetch(`/interactions/notifications/${notificationId}/mark-as-read/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': window.csrftoken,
                'Content-Type': 'application/json' // Though body is empty, CSRF usually needs it
            },
            // body: JSON.stringify({}) // No body needed for this request
        });
        if (response.ok) {
            const data = await response.json();
            if (data.status === 'success') { // Only decrement if successfully marked as read (not 'noop')
                if (listItemElement && listItemElement.classList.contains('unread')) {
                    listItemElement.classList.remove('unread');
                    unreadNotificationCount = Math.max(0, unreadNotificationCount - 1);
                    updateUnreadCountDisplay();
                }
            } else if (data.status === 'noop') {
                // Already read, ensure UI reflects this if it was somehow out of sync
                 if (listItemElement && listItemElement.classList.contains('unread')) {
                    listItemElement.classList.remove('unread');
                 }
            }
        } else {
            console.error('Failed to mark notification as read on server:', response.status, await response.text());
        }
    } catch (error) {
        console.error('Error marking notification as read:', error);
    }
}

async function markAllNotificationsAsReadAPI() {
    try {
        const response = await fetch('/interactions/notifications/mark-all-as-read/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': window.csrftoken,
                'Content-Type': 'application/json'
            },
        });
        if (response.ok) {
            const data = await response.json();
            if (data.status === 'success' || data.status === 'noop') {
                document.querySelectorAll('#notification-dropdown-list .notification-item.unread').forEach(item => {
                    item.classList.remove('unread');
                });
                unreadNotificationCount = 0;
                updateUnreadCountDisplay();
            }
        } else {
            console.error('Failed to mark all notifications as read on server:', response.status, await response.text());
        }
    } catch (error) {
        console.error('Error marking all notifications as read:', error);
    }
}

function toggleNotificationDropdown() {
    console.log("toggleNotificationDropdown function called.");
    const dropdown = document.getElementById('notification-dropdown');
    if (dropdown) {
        console.log("Dropdown element (ID: notification-dropdown) found.");
        // 使用 classList.contains('visible') 來檢查可見性，因為我們也用 class 來控制動畫
        const isVisible = dropdown.style.display === 'block' || dropdown.classList.contains('visible');

        if (isVisible) {
            // If it's currently visible, we want to hide it.
            dropdown.classList.remove('visible'); // Start transition out
            console.log("Dropdown hiding: removed 'visible' class.");
            // Set display to none after the CSS transition (0.2s)
            setTimeout(() => {
                // Only set display:none if it's still meant to be hidden (i.e., visible class was not re-added)
                if (!dropdown.classList.contains('visible')) {
                    dropdown.style.display = 'none';
                    console.log("Dropdown hidden: set display to none after transition.");
                }
            }, 200); // Corresponds to CSS transition duration 0.2s
        } else {
            // If it's hidden, we want to show it.
            dropdown.style.display = 'block'; // Make it part of the layout
            console.log("Dropdown showing: set display to block.");
            // Force a reflow to ensure 'display: block' is applied before adding 'visible' class for transition
            void dropdown.offsetHeight; // This is a common trick to trigger reflow
            dropdown.classList.add('visible'); // Add class to trigger transition in
            console.log("Dropdown showing: added 'visible' class.");
            // clearNotificationIndicator(); // Old way
            markAllNotificationsAsReadAPI(); // New: Mark all as read when dropdown is opened
        }
    } else {
        console.error("CRITICAL: Notification dropdown element (ID: notification-dropdown) not found when trying to toggle.");
    }
}


// --- 初始化 ---
// 您需要在您的 HTML 模板中，當使用者登入後，獲取 currentUserId 並呼叫此函數
document.addEventListener('DOMContentLoaded', function() {
    console.log("notifications.js - DOMContentLoaded event fired."); // 新增的 log
    // 綁定通知圖示的點擊事件
    const bellIcon = document.getElementById('notification-bell-icon');
    if (bellIcon) {
        console.log("Notification bell icon (ID: notification-bell-icon) found. Adding click listener.");
        bellIcon.addEventListener('click', function(event) {
            console.log("Notification bell icon clicked.");
            event.stopPropagation(); // 防止事件冒泡關閉下拉
            toggleNotificationDropdown();
        });
    } else {
        console.error("CRITICAL: Notification bell icon (ID: notification-bell-icon) not found in DOM at DOMContentLoaded. Click events will not work.");
    }

    // 綁定「全部標記已讀」按鈕
    const markAllReadBtn = document.getElementById('mark-all-read-btn');
    if (markAllReadBtn) {
        markAllReadBtn.addEventListener('click', function(event) {
            event.stopPropagation();
            markAllNotificationsAsReadAPI();
        });
    }

    // 事件委派：通知項目點擊處理
    var dropdownList = document.getElementById('notification-dropdown-list');
    if (dropdownList) {
        dropdownList.addEventListener('click', function(event) {
            var listItem = event.target.closest('.notification-item');
            if (!listItem) return;

            if (listItem.classList.contains('unread')) {
                markNotificationAsReadAPI(listItem.dataset.notificationId, listItem);
            }

            var targetIsLink = event.target.classList.contains('notification-link') || event.target.closest('.notification-link');
            if (!targetIsLink) {
                var linkElement = listItem.querySelector('.notification-link');
                if (linkElement && linkElement.href && linkElement.href !== '#') {
                    if (linkElement.getAttribute('href').startsWith('/')) {
                        window.location.href = linkElement.getAttribute('href');
                    } else {
                        window.open(linkElement.getAttribute('href'), '_blank');
                    }
                }
            }
        });
    }

    // 點擊頁面其他地方關閉下拉
    document.addEventListener('click', function(event) {
        const dropdown = document.getElementById('notification-dropdown');
        const bellIcon = document.getElementById('notification-bell-icon');
        if (dropdown && bellIcon && dropdown.style.display === 'block') {
            if (!dropdown.contains(event.target) && !bellIcon.contains(event.target)) {
                dropdown.style.display = 'none';
            }
        }
    });


    // 假設您在模板中以某種方式設定了 currentUserId
    // 例如: const currentUserId = JSON.parse(document.getElementById('current-user-id').textContent);
    // 或者直接在腳本中嵌入
    // const currentUserId = "{{ user.id }}"; // 這行在JS檔案中無效，需要在HTML模板中設定

    // 這裡需要您在HTML中設定一個全域變數 currentLoggedInUserId，或者從某個元素讀取
    // For testing, you might declare: let currentLoggedInUserId = 'your_user_id'; at the top of this script or in HTML.
    if (typeof currentLoggedInUserId !== 'undefined' && currentLoggedInUserId) {
        initializeNotificationWebSocket(currentLoggedInUserId);
        fetchAndDisplayHistoricalNotifications(); // Fetch historical notifications
    } else {
        // 嘗試從元素讀取 (作為備案)
        const userIdElement = document.getElementById('current-user-id-data'); // 假設您有一個元素儲存ID
        if (userIdElement && userIdElement.dataset.userId) {
            // Make currentLoggedInUserId globally available if found this way
            window.currentLoggedInUserId = userIdElement.dataset.userId;
            initializeNotificationWebSocket(window.currentLoggedInUserId);
            fetchAndDisplayHistoricalNotifications(); // Fetch historical notifications
        } else {
            console.log("Current user ID not found. Notification WebSocket and historical fetch not initialized.");
        }
    }
});
