// 假設您在模板中以某種方式設定了 currentUserId
// 例如: const currentUserId = JSON.parse(document.getElementById('current-user-id').textContent);
// 或者直接在腳本中嵌入，但前者更安全

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
        console.error('Notification WebSocket closed unexpectedly. Code:', e.code, 'Reason:', e.reason);
        // 可以嘗試重新連線
        // setTimeout(() => initializeNotificationWebSocket(userId), 5000); // 5秒後重試
    };

    notificationSocket.onerror = function(err) {
        console.error('Notification WebSocket error:', err.message, 'Closing socket');
        notificationSocket.close();
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

function formatNotificationHTML(notification) {
    // notification:
    // - from WS: { id, message: {payload_obj}, link, is_read, timestamp, type: "outer_type" }
    // - from DB (historical): { id, message: "json_string_payload", link, is_read, timestamp, type: undefined }

    let payload = notification.message;
    let notificationType = notification.type; // This is set for WS messages (e.g. 'new_video')

    // If message is a string (historical), try to parse it as JSON.
    // The actual notification type for historical items is inside this parsed payload.
    if (typeof payload === 'string') {
        try {
            payload = JSON.parse(payload);
            // If historical, and not already set (i.e., not a WS message), get type from parsed payload
            if (payload && payload.type && !notificationType) {
                notificationType = payload.type;
            }
        } catch (e) {
            // If parsing fails, it's a plain string message. payload remains the string.
            // console.warn("Notification message is a non-JSON string or parse failed:", notification.message, e);
        }
    }

    // Initialize defaults
    let title = "通知";
    let details = "";
    // Use notification.link if provided (e.g. from consumer for specific actions), otherwise try to build from payload.
    let link = notification.link || (payload && payload.url) || '#';
    let typeForClass = notificationType || 'generic-notification'; // For CSS styling

    // Now, payload should be an object if it was a parsable JSON string or originally an object from WS.
    // Or it could still be a string if it was a simple non-JSON message.
    if (typeof payload === 'object' && payload !== null) {
        // Re-evaluate link based on payload if not already set by notification.link
        if ((!notification.link || notification.link === '#') && payload.video_id) {
            link = `/videos/${payload.video_id}/`;
            if (payload.parent_comment_id) {
                link += `#comment-${payload.parent_comment_id}`;
            } else if (payload.comment_id) { // For top-level comments on video
                link += `#comment-${payload.comment_id}`;
            }
        }

        // Use notificationType (which now correctly reflects the type for both WS and historical)
        if (notificationType === 'new_video') {
            title = "新影片發布！";
            details = `頻道: ${payload.uploader_name || 'N/A'}<br>標題: ${payload.video_title || 'N/A'}`;
            if (payload.thumbnail_url) {
                details += `<br><img src="${payload.thumbnail_url}" alt="Thumbnail" style="max-width: 80px; height: auto; margin-top: 5px; border-radius: 4px;">`;
            }
        } else if (notificationType === 'new_reply') {
            title = "您的留言有新回覆！";
            details = `來自: ${payload.replier_name || 'N/A'}<br>影片: ${payload.video_title || 'N/A'}<br>回覆: "${payload.comment_content || ''}"`;
        } else if (notificationType === 'new_comment_on_video') {
            title = "您的影片有新留言！";
            details = `來自: ${payload.commenter_name || 'N/A'}<br>影片: ${payload.video_title || 'N/A'}<br>留言: "${payload.comment_content || ''}"`;
        } else if (notificationType === 'new_subscription') {
            title = "有新的訂閱者！";
            details = `${payload.subscriber_name || 'N/A'} 訂閱了您的頻道`;
        } else { // Generic object payload or unhandled type
            title = payload.title || "通知"; // Allow title from payload if present
            details = payload.text || JSON.stringify(payload); // Fallback to 'text' field or stringifying the object
        }
    } else if (typeof payload === 'string') { // It was a simple, non-JSON string message
        details = payload; // Display the plain string
        // title remains "通知"
    } else { // Fallback for unexpected payload type after potential parsing
        details = "無法正確顯示通知內容。";
        // title remains "通知"
    }

    // typeForClass is already set based on notificationType
    return `
        <div class="notification-item-content ${typeForClass}">
            <p class="notification-title"><strong>${title}</strong></p>
            <p class="notification-details">${details}</p>
            ${link && link !== '#' ? `<a href="${link}" class="notification-link" target="_blank">查看詳情</a>` : ''}
            ${notification.timestamp ? `<span class="notification-timestamp">${timeSince(new Date(notification.timestamp))}</span>` : ''}
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

        // Click listener for the whole item
        listItem.addEventListener('click', function(event) {
            const targetIsLink = event.target.classList.contains('notification-link') || event.target.closest('.notification-link');

            // If it's an unread notification, mark it as read.
            if (this.classList.contains('unread')) {
                markNotificationAsReadAPI(this.dataset.notificationId, this);
            }

            // If the click was not on the "查看詳情" link, and a link exists, navigate.
            // The link itself will handle its own navigation if clicked directly.
            if (!targetIsLink) {
                const linkElement = this.querySelector('.notification-link');
                if (linkElement && linkElement.href && linkElement.href !== '#') {
                     // Check if it's an absolute URL or needs prefixing
                    if (linkElement.getAttribute('href').startsWith('/')) {
                        window.location.href = linkElement.getAttribute('href'); // Navigate in the same tab for internal links
                    } else {
                        window.open(linkElement.getAttribute('href'), '_blank'); // Open external links in new tab
                    }
                }
            }
            // If it was the link, the browser handles it. If no link, nothing more to do.
        });


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
        const notifications = data.notifications || []; // Sorted newest first from server

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
