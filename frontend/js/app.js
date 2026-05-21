// Constants & State
const API_BASE = "";
let state = {
    settings: {
        email: "",
        app_password: "",
        imap_server: "imap.gmail.com",
        smtp_server: "smtp.gmail.com",
        imap_port: 993,
        smtp_port: 587,
        sandbox_mode: true,
        check_interval_mins: 5,
        auth_mode: "sandbox",
        oauth_client_id: "",
        oauth_client_secret: "",
        oauth_access_token: "",
        oauth_refresh_token: "",
        oauth_token_expires_at: ""
    },
    reminders: [],
    emails: [],
    selectedEmail: null,
    activeTab: "dashboard"
};


// SSE Connection Reference
let sseSource = null;

// Synthetic Audio Chime (Synthesized via Web Audio API to prevent 404 resource errors)
function playSystemChime() {
    try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) return;
        
        const ctx = new AudioCtx();
        const now = ctx.currentTime;
        
        // Beautiful arpeggio chime
        const notes = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6
        notes.forEach((freq, idx) => {
            const osc = ctx.createOscillator();
            const gainNode = ctx.createGain();
            
            osc.type = "sine";
            osc.frequency.setValueAtTime(freq, now + idx * 0.12);
            
            gainNode.gain.setValueAtTime(0.12, now + idx * 0.12);
            gainNode.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.12 + 0.8);
            
            osc.connect(gainNode);
            gainNode.connect(ctx.destination);
            
            osc.start(now + idx * 0.12);
            osc.stop(now + idx * 0.12 + 0.85);
        });
    } catch (e) {
        console.error("Synthesizer blocked or failed: ", e);
    }
}

// Format relative date for human-readable labels
function formatTimeDelta(isoString) {
    const target = new Date(isoString);
    const now = new Date();
    const diffMs = target - now;
    const isPast = diffMs < 0;
    const absDiff = Math.abs(diffMs);
    
    const sec = Math.floor((absDiff / 1000) % 60);
    const min = Math.floor((absDiff / (1000 * 60)) % 60);
    const hr = Math.floor((absDiff / (1000 * 60 * 60)) % 24);
    const days = Math.floor(absDiff / (1000 * 60 * 60 * 24));
    
    const pad = (num) => String(num).padStart(2, '0');
    
    if (isPast) {
        if (days > 0) return { label: `OVERDUE by ${days}d ${pad(hr)}h`, type: "overdue" };
        if (hr > 0) return { label: `OVERDUE by ${pad(hr)}:${pad(min)}:${pad(sec)}`, type: "overdue" };
        return { label: `OVERDUE by ${pad(min)}:${pad(sec)}`, type: "overdue" };
    } else {
        if (days > 0) return { label: `Due in ${days}d ${pad(hr)}h`, type: "pending" };
        if (hr > 0) return { label: `Due in ${pad(hr)}:${pad(min)}:${pad(sec)}`, type: "pending" };
        if (min < 5) return { label: `Due in ${pad(min)}:${pad(sec)}`, type: "urgent" };
        return { label: `Due in ${pad(min)}:${pad(sec)}`, type: "pending" };
    }
}

// Initialize Application
document.addEventListener("DOMContentLoaded", async () => {
    // Setup Navigation Tabs
    setupNavigation();
    
    // Setup Clocks and Tickers
    startDynamicClock();
    startCountdownTicker();
    
    // Fetch settings and reminders
    await fetchSettings();
    await refreshReminders();
    
    // Connect SSE channel for real-time notifications
    connectRealtimeSSE();
    
    // Initial UI Render
    switchTab("dashboard");
    
    // Attach Global Modal Button Handlers
    document.getElementById("btn-quick-add").addEventListener("click", () => openModal("modal-add-reminder"));
    document.getElementById("btn-close-modal").addEventListener("click", () => closeModal("modal-add-reminder"));
    document.getElementById("form-quick-reminder").addEventListener("submit", handleAddReminderSubmit);
    document.getElementById("form-settings").addEventListener("submit", handleSettingsSubmit);
    document.getElementById("btn-scan-inbox").addEventListener("click", triggerInboxScan);
    
    // Attach OAuth authorization event handler
    document.getElementById("btn-oauth-authorize").addEventListener("click", handleOAuthAuthorization);
    
    // Handle 3-way radio pill clicks
    document.querySelectorAll(".auth-mode-pill").forEach(pill => {
        pill.addEventListener("click", () => {
            document.querySelectorAll(".auth-mode-pill").forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            
            const radio = pill.querySelector("input[type='radio']");
            radio.checked = true;
            const mode = radio.value;
            
            // Toggle forms
            document.querySelectorAll(".config-auth-section").forEach(sec => sec.classList.add("hidden"));
            document.getElementById(`section-config-${mode}`).classList.remove("hidden");
            
            // Sync with local state
            state.settings.auth_mode = mode;
        });
    });

    // Setup developer guide details expander
    const guideHeader = document.getElementById("guide-header");
    if (guideHeader) {
        guideHeader.addEventListener("click", () => {
            const content = document.getElementById("guide-content");
            const arrow = document.getElementById("guide-arrow");
            content.classList.toggle("hidden");
            arrow.classList.toggle("rotated");
        });
    }

    // Listen for postMessage from Google Callback redirection success screen
    window.addEventListener("message", async (event) => {
        if (event.data === "oauth_authorized") {
            console.log("[OAuth] Received postMessage authorization payload. Syncing settings.");
            await fetchSettings();
            alert("Google Account connection authorized successfully!");
        }
    });
    
    // Pre-populate reminder creation form with tomorrow morning as default
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(9, 0, 0, 0);
    // Format to local date time-local string format
    const pad = (n) => String(n).padStart(2, '0');
    const localDateTime = `${tomorrow.getFullYear()}-${pad(tomorrow.getMonth()+1)}-${pad(tomorrow.getDate())}T${pad(tomorrow.getHours())}:${pad(tomorrow.getMinutes())}`;
    document.getElementById("reminder-due-time").value = localDateTime;
});


// Setup sidebar navigations
function setupNavigation() {
    const navItems = document.querySelectorAll(".nav-item");
    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const tabId = item.getAttribute("data-tab");
            switchTab(tabId);
        });
    });
}

function switchTab(tabId) {
    state.activeTab = tabId;
    
    // Update active nav class
    document.querySelectorAll(".nav-item").forEach(item => {
        item.classList.remove("active");
        if (item.getAttribute("data-tab") === tabId) {
            item.classList.add("active");
        }
    });
    
    // Update active section class
    document.querySelectorAll(".content-section").forEach(sec => {
        sec.classList.remove("active");
    });
    document.getElementById(`section-${tabId}`).classList.add("active");
    
    // Load fresh data specific to tabs
    if (tabId === "reminders" || tabId === "dashboard" || tabId === "logs") {
        refreshReminders();
    }
}

// Clock Display Header
function startDynamicClock() {
    const clockEl = document.getElementById("header-clock");
    const update = () => {
        const now = new Date();
        clockEl.innerHTML = `<i class="far fa-clock"></i> ${now.toLocaleTimeString()} | ${now.toLocaleDateString(undefined, {month: 'short', day: 'numeric'})}`;
    };
    update();
    setInterval(update, 1000);
}

// Dynamic interval to update countdown indicators
function startCountdownTicker() {
    setInterval(() => {
        // Scan for elements with class 'js-countdown'
        document.querySelectorAll(".js-countdown").forEach(badge => {
            const targetTime = badge.getAttribute("data-due");
            const status = badge.getAttribute("data-status");
            
            if (status === "completed") {
                badge.innerText = "Completed";
                badge.className = "countdown-badge completed";
                return;
            }
            
            const delta = formatTimeDelta(targetTime);
            badge.innerText = delta.label;
            badge.className = `countdown-badge js-countdown ${delta.type}`;
        });
    }, 1000);
}

// REST Transactions
async function fetchSettings() {
    try {
        const res = await fetch(`${API_BASE}/api/settings`);
        if (!res.ok) throw new Error("Failed to fetch settings.");
        state.settings = await res.json();
        
        // Ensure default auth_mode
        if (!state.settings.auth_mode) {
            state.settings.auth_mode = state.settings.sandbox_mode ? "sandbox" : "app_password";
        }
        
        // Update sidebar indicators
        const pulse = document.getElementById("sidebar-status-dot");
        const label = document.getElementById("sidebar-status-dot").nextElementSibling;
        
        if (state.settings.auth_mode === "sandbox") {
            pulse.className = "pulse-dot sandbox";
            label.innerText = "Sandbox Mode";
        } else if (state.settings.auth_mode === "oauth") {
            pulse.className = "pulse-dot active";
            label.innerText = "OAuth Active Mode";
        } else {
            pulse.className = "pulse-dot active";
            label.innerText = "SMTP/IMAP Mode";
        }
        
        // Sync the 3-Way Selector Pills
        document.querySelectorAll(".auth-mode-pill").forEach(pill => {
            const radio = pill.querySelector("input[type='radio']");
            if (radio.value === state.settings.auth_mode) {
                document.querySelectorAll(".auth-mode-pill").forEach(p => p.classList.remove("active"));
                pill.classList.add("active");
                radio.checked = true;
            }
        });
        
        // Toggle Config form sections
        document.querySelectorAll(".config-auth-section").forEach(sec => sec.classList.add("hidden"));
        document.getElementById(`section-config-${state.settings.auth_mode}`).classList.remove("hidden");
        
        // Sync general inputs in all sections
        document.getElementById("user-email").value = state.settings.email || "";
        document.getElementById("user-password").value = state.settings.app_password || "";
        document.getElementById("imap-server").value = state.settings.imap_server || "imap.gmail.com";
        document.getElementById("smtp-server").value = state.settings.smtp_server || "smtp.gmail.com";
        document.getElementById("imap-port").value = state.settings.imap_port || 993;
        document.getElementById("smtp-port").value = state.settings.smtp_port || 587;
        
        document.getElementById("oauth-email").value = state.settings.email || "";
        document.getElementById("oauth-client-id").value = state.settings.oauth_client_id || "";
        document.getElementById("oauth-client-secret").value = state.settings.oauth_client_secret || "";
        
        document.getElementById("check-interval").value = state.settings.check_interval_mins || 5;
        
        // Render Google Handshake console connection status
        const oauthBadge = document.getElementById("oauth-status-badge");
        if (state.settings.oauth_refresh_token) {
            oauthBadge.className = "badge completed";
            oauthBadge.innerText = "CONNECTED";
            oauthBadge.style.backgroundColor = "var(--accent-teal)";
        } else {
            oauthBadge.className = "badge triggered";
            oauthBadge.innerText = "NOT CONNECTED";
            oauthBadge.style.backgroundColor = "var(--accent-coral)";
        }
    } catch (e) {
        console.error(e);
    }
}

async function handleSettingsSubmit(e) {
    e.preventDefault();
    const mode = state.settings.auth_mode;
    
    let email = "";
    let appPassword = "";
    let oauthClientId = "";
    let oauthClientSecret = "";
    
    if (mode === "sandbox") {
        // Safe mocks
    } else if (mode === "app_password") {
        email = document.getElementById("user-email").value.trim();
        appPassword = document.getElementById("user-password").value.trim();
        if (!email || !appPassword) {
            alert("App Password mode requires a valid Gmail address and Google App Password.");
            return;
        }
    } else if (mode === "oauth") {
        email = document.getElementById("oauth-email").value.trim();
        oauthClientId = document.getElementById("oauth-client-id").value.trim();
        oauthClientSecret = document.getElementById("oauth-client-secret").value.trim();
        if (!email || !oauthClientId || !oauthClientSecret) {
            alert("Google OAuth requires Gmail Address, OAuth Client ID, and Client Secret.");
            return;
        }
    }
    
    const payload = {
        email: email || state.settings.email || "",
        app_password: appPassword || state.settings.app_password || "",
        imap_server: document.getElementById("imap-server").value.trim(),
        smtp_server: document.getElementById("smtp-server").value.trim(),
        imap_port: parseInt(document.getElementById("imap-port").value) || 993,
        smtp_port: parseInt(document.getElementById("smtp-port").value) || 587,
        sandbox_mode: (mode === "sandbox"),
        check_interval_mins: parseInt(document.getElementById("check-interval").value) || 5,
        auth_mode: mode,
        oauth_client_id: oauthClientId || state.settings.oauth_client_id || "",
        oauth_client_secret: oauthClientSecret || state.settings.oauth_client_secret || "",
        oauth_access_token: state.settings.oauth_access_token || "",
        oauth_refresh_token: state.settings.oauth_refresh_token || "",
        oauth_token_expires_at: state.settings.oauth_token_expires_at || ""
    };
    
    try {
        const res = await fetch(`${API_BASE}/api/settings`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        if (!res.ok) throw new Error("Could not update settings on backend.");
        
        alert("Configuration saved successfully!");
        await fetchSettings();
    } catch (e) {
        alert("Error saving settings: " + e.message);
    }
}

async function handleOAuthAuthorization() {
    // Save configuration settings first
    const email = document.getElementById("oauth-email").value.trim();
    const oauthClientId = document.getElementById("oauth-client-id").value.trim();
    const oauthClientSecret = document.getElementById("oauth-client-secret").value.trim();
    
    if (!email || !oauthClientId || !oauthClientSecret) {
        alert("Please provide a valid Gmail Address, OAuth Client ID, and Client Secret first.");
        return;
    }
    
    const payload = {
        email: email,
        app_password: state.settings.app_password || "",
        imap_server: document.getElementById("imap-server").value.trim(),
        smtp_server: document.getElementById("smtp-server").value.trim(),
        imap_port: parseInt(document.getElementById("imap-port").value) || 993,
        smtp_port: parseInt(document.getElementById("smtp-port").value) || 587,
        sandbox_mode: false,
        check_interval_mins: parseInt(document.getElementById("check-interval").value) || 5,
        auth_mode: "oauth",
        oauth_client_id: oauthClientId,
        oauth_client_secret: oauthClientSecret,
        oauth_access_token: state.settings.oauth_access_token || "",
        oauth_refresh_token: state.settings.oauth_refresh_token || "",
        oauth_token_expires_at: state.settings.oauth_token_expires_at || ""
    };
    
    try {
        // Call backend API to save the client configuration details first
        const saveRes = await fetch(`${API_BASE}/api/settings`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        if (!saveRes.ok) throw new Error("Could not save client credentials to server.");
        
        // Update local settings cache
        state.settings = await saveRes.json();
        
        // Fetch Consent Screen Authorization URL from backend
        const urlRes = await fetch(`${API_BASE}/api/auth/url`);
        if (!urlRes.ok) {
            const errJson = await urlRes.json();
            throw new Error(errJson.detail || "Failed to fetch Google authorization endpoint.");
        }
        
        const data = await urlRes.json();
        
        // Open standard OAuth Consent Popup dialog
        const width = 600, height = 700;
        const left = (window.screen.width - width) / 2;
        const top = (window.screen.height - height) / 2;
        const oauthWindow = window.open(data.url, "Google Account Authorization", `width=${width},height=${height},top=${top},left=${left},scrollbars=yes`);
        
        if (!oauthWindow) {
            alert("Popup blocked! Please allow popups for this dashboard to authorize secure Google services.");
        }
    } catch (e) {
        alert("Authorization setup failed: " + e.message);
    }
}


async function refreshReminders() {
    try {
        const res = await fetch(`${API_BASE}/api/reminders`);
        if (!res.ok) throw new Error("Could not retrieve reminders list.");
        state.reminders = await res.json();
        
        // Re-render relevant sections
        renderDashboardStats();
        if (state.activeTab === "dashboard") {
            renderDashboardRemindersList();
        } else if (state.activeTab === "reminders") {
            renderRemindersBoard();
        } else if (state.activeTab === "logs") {
            renderLogsTable();
        }
    } catch (e) {
        console.error("Retrieval failure: ", e);
    }
}

// Modal open/close helpers
function openModal(id) {
    document.getElementById(id).classList.add("active");
}
function closeModal(id) {
    document.getElementById(id).classList.remove("active");
}

async function handleAddReminderSubmit(e) {
    e.preventDefault();
    const title = document.getElementById("reminder-title").value.trim();
    const content = document.getElementById("reminder-desc").value.trim();
    const rawTime = document.getElementById("reminder-due-time").value;
    
    if (!title || !rawTime) {
        alert("Reminder Title and Trigger Time are required.");
        return;
    }
    
    // Convert to ISO 8601
    const isoTime = new Date(rawTime).toISOString();
    
    try {
        const res = await fetch(`${API_BASE}/api/reminders`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                title: title,
                content: content,
                due_time: isoTime
            })
        });
        
        if (!res.ok) throw new Error("Fail adding reminder to backend database.");
        
        closeModal("modal-add-reminder");
        // Clear form
        document.getElementById("reminder-title").value = "";
        document.getElementById("reminder-desc").value = "";
        
        await refreshReminders();
    } catch (e) {
        alert("Error creating reminder: " + e.message);
    }
}

// Stats & Metics Renderer
function renderDashboardStats() {
    const total = state.reminders.length;
    const pending = state.reminders.filter(r => r.status === "pending").length;
    const triggered = state.reminders.filter(r => r.status === "triggered").length;
    const completed = state.reminders.filter(r => r.status === "completed").length;
    
    document.getElementById("stat-total").innerText = total;
    document.getElementById("stat-pending").innerText = pending;
    document.getElementById("stat-triggered").innerText = triggered;
    document.getElementById("stat-completed").innerText = completed;
    
    // Progress fill percentages
    const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
    document.getElementById("progress-completed-fill").style.width = `${pct}%`;
    document.getElementById("progress-completed-pct").innerText = `${pct}% Rate`;
    
    // Impending alert stats
    const urgentCount = state.reminders.filter(r => {
        if (r.status !== "pending") return false;
        const diff = new Date(r.due_time) - new Date();
        return diff > 0 && diff < 5 * 60 * 1000; // < 5 mins
    }).length;
    
    document.getElementById("stat-urgent-label").innerText = `${urgentCount} Impending Alerts`;
}

// Dashboard View Renderer
function renderDashboardRemindersList() {
    const container = document.getElementById("dashboard-reminders-container");
    container.innerHTML = "";
    
    // Show only pending/triggered reminders in main dashboard
    const pendingOrTriggered = state.reminders.filter(r => r.status !== "completed");
    
    if (pendingOrTriggered.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="far fa-bell-slash"></i>
                <p>No active reminders at this time.</p>
                <button class="btn btn-secondary btn-quick-trigger" onclick="openModal('modal-add-reminder')">Create Custom Reminder</button>
            </div>
        `;
        return;
    }
    
    // Take top 5 impending
    pendingOrTriggered.slice(0, 5).forEach(r => {
        const card = createReminderCardElement(r);
        container.appendChild(card);
    });
}

// Reminders Board Renderer (Splitted categories)
function renderRemindersBoard() {
    const boardPending = document.getElementById("board-pending");
    const boardTriggered = document.getElementById("board-triggered");
    const boardCompleted = document.getElementById("board-completed");
    
    boardPending.innerHTML = "";
    boardTriggered.innerHTML = "";
    boardCompleted.innerHTML = "";
    
    const pendings = state.reminders.filter(r => r.status === "pending");
    const triggereds = state.reminders.filter(r => r.status === "triggered");
    const completeds = state.reminders.filter(r => r.status === "completed");
    
    // Pendings render
    if (pendings.length === 0) {
        boardPending.innerHTML = `<div class="empty-state" style="padding: 24px;"><p style="font-size:12px;">No pending alerts.</p></div>`;
    } else {
        pendings.forEach(r => boardPending.appendChild(createReminderCardElement(r)));
    }
    
    // Triggered render
    if (triggereds.length === 0) {
        boardTriggered.innerHTML = `<div class="empty-state" style="padding: 24px;"><p style="font-size:12px;">No triggered alerts.</p></div>`;
    } else {
        triggereds.forEach(r => boardTriggered.appendChild(createReminderCardElement(r)));
    }
    
    // Completed render
    if (completeds.length === 0) {
        boardCompleted.innerHTML = `<div class="empty-state" style="padding: 24px;"><p style="font-size:12px;">No completed alerts.</p></div>`;
    } else {
        completeds.forEach(r => boardCompleted.appendChild(createReminderCardElement(r)));
    }
}

// Create individual Reminder card item
function createReminderCardElement(r) {
    const div = document.createElement("div");
    div.className = `reminder-card glass-panel ${r.status}`;
    div.id = `reminder-card-${r.id}`;
    
    const delta = formatTimeDelta(r.due_time);
    
    let actionButtons = "";
    if (r.status === "pending") {
        actionButtons = `
            <button class="icon-btn complete" onclick="markReminderStatus(${r.id}, 'completed')" title="Mark Complete">
                <i class="fas fa-check"></i>
            </button>
            <button class="icon-btn delete" onclick="deleteReminder(${r.id})" title="Remove">
                <i class="fas fa-trash-alt"></i>
            </button>
        `;
    } else if (r.status === "triggered") {
        actionButtons = `
            <button class="icon-btn complete" onclick="markReminderStatus(${r.id}, 'completed')" title="Acknowledge & Complete">
                <i class="fas fa-check-double"></i>
            </button>
            <button class="icon-btn" onclick="promptSnooze(${r.id})" title="Snooze">
                <i class="fas fa-history"></i>
            </button>
        `;
    } else {
        actionButtons = `
            <button class="icon-btn delete" onclick="deleteReminder(${r.id})" title="Delete History">
                <i class="fas fa-trash-alt"></i>
            </button>
        `;
    }
    
    div.innerHTML = `
        <div class="reminder-info">
            <div class="reminder-title">
                ${r.title}
                ${r.source_email_subject ? `<span class="source-badge">Gmail</span>` : ''}
            </div>
            ${r.content ? `<div class="reminder-desc">${r.content}</div>` : ''}
            <div class="reminder-meta">
                <span class="countdown-badge js-countdown ${r.status === 'completed' ? 'completed' : delta.type}" data-due="${r.due_time}" data-status="${r.status}">
                    ${r.status === 'completed' ? 'Completed' : delta.label}
                </span>
                ${r.snooze_count > 0 ? `<span><i class="fas fa-history"></i> Snoozed ${r.snooze_count}x</span>` : ''}
            </div>
        </div>
        <div class="card-actions">
            ${actionButtons}
        </div>
    `;
    return div;
}

// Modify Reminder Status (REST API call)
async function markReminderStatus(id, newStatus) {
    try {
        const res = await fetch(`${API_BASE}/api/reminders/${id}/status?status=${newStatus}`, {
            method: "PUT"
        });
        if (!res.ok) throw new Error("Status update failed");
        
        // Remove toast overlay if active
        const toast = document.getElementById(`toast-overlay-${id}`);
        if (toast) toast.remove();
        
        await refreshReminders();
    } catch (e) {
        console.error(e);
    }
}

// Prompt custom Snooze
function promptSnooze(id) {
    const minsStr = prompt("Enter snooze duration in minutes:", "10");
    if (!minsStr) return;
    const mins = parseInt(minsStr);
    if (isNaN(mins) || mins <= 0) {
        alert("Please enter a valid positive number.");
        return;
    }
    snoozeReminder(id, mins);
}

async function snoozeReminder(id, minutes) {
    try {
        const res = await fetch(`${API_BASE}/api/reminders/${id}/snooze`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ minutes: minutes })
        });
        if (!res.ok) throw new Error("Snooze API call failed.");
        
        const toast = document.getElementById(`toast-overlay-${id}`);
        if (toast) toast.remove();
        
        await refreshReminders();
    } catch (e) {
        console.error(e);
    }
}

async function deleteReminder(id) {
    if (!confirm("Are you sure you want to permanently remove this reminder?")) return;
    try {
        const res = await fetch(`${API_BASE}/api/reminders/${id}`, {
            method: "DELETE"
        });
        if (!res.ok) throw new Error("Deletion failed.");
        
        await refreshReminders();
    } catch (e) {
        console.error(e);
    }
}

// Logs view table renderer
function renderLogsTable() {
    const body = document.getElementById("logs-table-body");
    body.innerHTML = "";
    
    // Sort reminders by created at descending
    const sorted = [...state.reminders].sort((a,b) => new Date(b.created_at) - new Date(a.created_at));
    
    if (sorted.length === 0) {
        body.innerHTML = `<tr><td colspan="5" class="empty-state" style="text-align:center;"><p>No records found.</p></td></tr>`;
        return;
    }
    
    sorted.forEach(r => {
        const tr = document.createElement("tr");
        const createdDate = new Date(r.created_at).toLocaleString();
        const triggerDate = new Date(r.due_time).toLocaleString();
        
        tr.innerHTML = `
            <td style="font-weight:600; color:var(--text-primary);">${r.title}</td>
            <td>${r.source_email_subject || '<span style="color:var(--text-muted);">Manual Quick Add</span>'}</td>
            <td>${createdDate}</td>
            <td>${triggerDate}</td>
            <td><span class="badge-status ${r.status}">${r.status}</span></td>
        `;
        body.appendChild(tr);
    });
}

// Email Scanner (IMAP / Sandbox scan integration)
async function triggerInboxScan() {
    const listContainer = document.getElementById("inbox-email-list");
    const scannerStatus = document.getElementById("stat-scanning-status");
    
    listContainer.innerHTML = `
        <div class="empty-state">
            <i class="fas fa-circle-notch fa-spin"></i>
            <p>Retrieving incoming inbox messages...</p>
        </div>
    `;
    scannerStatus.innerText = "SCANNING...";
    scannerStatus.parentElement.classList.add("scanning");
    
    try {
        const res = await fetch(`${API_BASE}/api/inbox/scan`, { method: "POST" });
        if (!res.ok) {
            const errDetails = await res.json();
            throw new Error(errDetails.detail || "Inbox scan failed.");
        }
        
        state.emails = await res.json();
        renderEmailList();
    } catch (e) {
        listContainer.innerHTML = `
            <div class="empty-state" style="color: var(--accent-coral);">
                <i class="fas fa-exclamation-triangle"></i>
                <p>Scanner Connection Failure</p>
                <span style="font-size:11px; opacity:0.8;">${e.message}</span>
            </div>
        `;
    } finally {
        scannerStatus.innerText = "IDLE";
        scannerStatus.parentElement.classList.remove("scanning");
    }
}

function renderEmailList() {
    const listContainer = document.getElementById("inbox-email-list");
    listContainer.innerHTML = "";
    
    if (state.emails.length === 0) {
        listContainer.innerHTML = `
            <div class="empty-state">
                <i class="far fa-envelope-open"></i>
                <p>Your inbox is pristine! No actionable unseen emails detected.</p>
            </div>
        `;
        // Clear preview detail
        clearEmailDetailPanel();
        return;
    }
    
    state.emails.forEach(email => {
        const div = document.createElement("div");
        div.className = "email-card glass-panel";
        div.id = `email-card-${email.uid}`;
        if (state.selectedEmail && state.selectedEmail.uid === email.uid) {
            div.classList.add("selected");
        }
        
        div.innerHTML = `
            <div class="email-header-info">
                <span class="email-sender">${email.sender.split("<")[0].trim()}</span>
                <span>UID: ${email.uid}</span>
            </div>
            <div class="email-subject">${email.subject}</div>
            <div class="email-snippet">${email.body_preview || email.body.substring(0, 100)}</div>
        `;
        
        div.addEventListener("click", () => selectEmailItem(email));
        listContainer.appendChild(div);
    });
    
    // Select first email automatically if none is selected
    if (!state.selectedEmail && state.emails.length > 0) {
        selectEmailItem(state.emails[0]);
    }
}

function selectEmailItem(email) {
    state.selectedEmail = email;
    
    // Update highlighted cards
    document.querySelectorAll(".email-card").forEach(card => {
        card.classList.remove("selected");
    });
    const activeCard = document.getElementById(`email-card-${email.uid}`);
    if (activeCard) activeCard.classList.add("selected");
    
    // Render Detail Panel
    renderEmailDetail();
}

function clearEmailDetailPanel() {
    state.selectedEmail = null;
    const body = document.getElementById("email-detail-wrapper");
    body.innerHTML = `
        <div class="empty-state" style="height: 100%; justify-content: center;">
            <i class="far fa-envelope"></i>
            <p>Select an email to view parsing details.</p>
        </div>
    `;
}

function renderEmailDetail() {
    const wrapper = document.getElementById("email-detail-wrapper");
    const email = state.selectedEmail;
    
    if (!email) return;
    
    // Convert parsed due ISO to datetime-local format
    let localTimeStr = "";
    if (email.parsed_due) {
        const parsedDate = new Date(email.parsed_due);
        const pad = (n) => String(n).padStart(2, '0');
        localTimeStr = `${parsedDate.getFullYear()}-${pad(parsedDate.getMonth()+1)}-${pad(parsedDate.getDate())}T${pad(parsedDate.getHours())}:${pad(parsedDate.getMinutes())}`;
    }
    
    wrapper.innerHTML = `
        <div class="email-detail-container glass-panel">
            <div class="detail-header">
                <div class="detail-subject">${email.subject}</div>
                <div class="detail-sender">From: <strong>${email.sender}</strong></div>
            </div>
            <div class="detail-body">${email.body}</div>
            
            <div class="detail-parser-panel">
                <div class="parser-title">
                    <i class="fas fa-magic"></i> AI Parser Action Extraction
                </div>
                <div class="parser-card">
                    <div class="parser-field">
                        <label class="parser-label">Action Item / Title</label>
                        <input type="text" id="extracted-action" class="parser-val-input" value="${email.parsed_action || ''}">
                    </div>
                    <div class="parser-field">
                        <label class="parser-label">Extracted Deadline</label>
                        <input type="datetime-local" id="extracted-due-time" class="parser-val-input" value="${localTimeStr}">
                    </div>
                    
                    <button class="btn" style="margin-top: 8px;" onclick="activateParsedReminder()">
                        <i class="fas fa-bell"></i> Activate Reminder Card
                    </button>
                </div>
            </div>
        </div>
    `;
}

// Convert parsed email details into a real reminder
async function activateParsedReminder() {
    const email = state.selectedEmail;
    if (!email) return;
    
    const title = document.getElementById("extracted-action").value.trim();
    const rawTime = document.getElementById("extracted-due-time").value;
    
    if (!title || !rawTime) {
        alert("Please specify a valid Action Title and Deadline.");
        return;
    }
    
    const isoTime = new Date(rawTime).toISOString();
    
    try {
        // Create Reminder
        const res = await fetch(`${API_BASE}/api/reminders`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                title: title,
                content: `Extracted from email. Subject: ${email.subject}\nSender: ${email.sender}`,
                due_time: isoTime,
                source_email_id: email.uid,
                source_email_subject: email.subject
            })
        });
        
        if (!res.ok) throw new Error("Failed to activate reminder.");
        
        // Mark processed so it leaves the active scan list
        await fetch(`${API_BASE}/api/inbox/mark-processed/${email.uid}`, { method: "POST" });
        
        alert("Reminder successfully scheduled!");
        
        // Remove email from state and select next or refresh
        state.emails = state.emails.filter(e => e.uid !== email.uid);
        state.selectedEmail = null;
        renderEmailList();
        
        await refreshReminders();
    } catch (e) {
        alert("Activation error: " + e.message);
    }
}

// Subscribe to SSE streaming
function connectRealtimeSSE() {
    if (sseSource) {
        sseSource.close();
    }
    
    sseSource = new EventSource(`${API_BASE}/api/realtime-events`);
    
    sseSource.onopen = () => {
        console.log("[SSE] Streaming connection opened.");
    };
    
    sseSource.onmessage = (event) => {
        // Empty heartbeat check
        if (!event.data || event.data.trim() === "ping") return;
        
        try {
            const data = JSON.parse(event.data);
            if (data.event === "reminder_triggered") {
                console.log("[SSE] Reminder triggered!", data.reminder);
                // Trigger Sound & Overlay Toast
                triggerReminderAlert(data.reminder);
            }
        } catch (e) {
            console.error("SSE decoding error: ", e);
        }
    };
    
    sseSource.onerror = (err) => {
        console.error("[SSE] Connection error. Reconnecting...", err);
        // Retry connection after 5 seconds
        sseSource.close();
        setTimeout(connectRealtimeSSE, 5000);
    };
}

// Display overlay notifications card in UI
function triggerReminderAlert(reminder) {
    // Play sound!
    playSystemChime();
    
    const container = document.getElementById("trigger-overlay-container");
    
    // Check if toast already exists to avoid duplication
    if (document.getElementById(`toast-overlay-${reminder.id}`)) return;
    
    const toast = document.createElement("div");
    toast.className = "trigger-card";
    toast.id = `toast-overlay-${reminder.id}`;
    
    toast.innerHTML = `
        <div class="trigger-header">
            <span class="trigger-icon">🔔</span>
            <span>Gmail Reminder Fired</span>
        </div>
        <div class="trigger-body">
            <h3>${reminder.title}</h3>
            ${reminder.content ? `<p>${reminder.content.replace(/\n/g, '<br>')}</p>` : '<p>No description</p>'}
        </div>
        <div class="trigger-actions">
            <button class="btn" onclick="markReminderStatus(${reminder.id}, 'completed')">
                <i class="fas fa-check"></i> Complete
            </button>
            <button class="btn btn-secondary" onclick="snoozeReminder(${reminder.id}, 5)">
                Snooze 5m
            </button>
        </div>
    `;
    
    container.appendChild(toast);
    
    // Auto-refresh reminder lists
    refreshReminders();
}
