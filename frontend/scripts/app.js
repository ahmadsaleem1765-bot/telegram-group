/**
 * Telegram Group Messaging Automation - Frontend Application
 * Apple Human Interface Guidelines-inspired Design
 */

// ==================== State ====================
const state = {
    isAuthenticated: false,
    user: null,
    groups: [],
    activeGroups: [],
    inactiveGroups: [],
    currentFilter: 'all',
    isScanning: false,
    isSending: false,
    threshold: null
};

// ==================== DOM Elements ====================
const elements = {
    // Navigation
    navItems: document.querySelectorAll('.nav-item'),
    views: document.querySelectorAll('.view'),
    
    // Dashboard
    totalGroups: document.getElementById('totalGroups'),
    activeGroups: document.getElementById('activeGroups'),
    inactiveGroups: document.getElementById('inactiveGroups'),
    connectBtn: document.getElementById('connectBtn'),
    scanGroupsBtn: document.getElementById('scanGroupsBtn'),
    configureFilterBtn: document.getElementById('configureFilterBtn'),
    
    // User Info
    userName: document.getElementById('userName'),
    userStatus: document.getElementById('userStatus'),
    
    // Groups
    groupSearch: document.getElementById('groupSearch'),
    filterBtns: document.querySelectorAll('.filter-btn'),
    groupsTableBody: document.getElementById('groupsTableBody'),
    
    // Automation
    thresholdDate: document.getElementById('thresholdDate'),
    thresholdTime: document.getElementById('thresholdTime'),
    applyThresholdBtn: document.getElementById('applyThresholdBtn'),
    messageTemplate: document.getElementById('messageTemplate'),
    delayMin: document.getElementById('delayMin'),
    delayMax: document.getElementById('delayMax'),
    maxMessages: document.getElementById('maxMessages'),
    dryRun: document.getElementById('dryRun'),
    sendMessagesBtn: document.getElementById('sendMessagesBtn'),
    stopAutomationBtn: document.getElementById('stopAutomationBtn'),
    inactiveCount: document.getElementById('inactiveCount'),
    progressCard: document.getElementById('progressCard'),
    progressFill: document.getElementById('progressFill'),
    progressText: document.getElementById('progressText'),
    
    // Logs
    logsList: document.getElementById('logsList'),
    refreshLogsBtn: document.getElementById('refreshLogsBtn'),
    clearLogsBtn: document.getElementById('clearLogsBtn'),
    
    // Modal
    loginModal: document.getElementById('loginModal'),
    closeLoginModal: document.getElementById('closeLoginModal'),
    cancelLoginBtn: document.getElementById('cancelLoginBtn'),
    sessionString: document.getElementById('sessionString'),
    loginBtn: document.getElementById('loginBtn'),
    
    // Toast
    toastContainer: document.getElementById('toastContainer')
};

// ==================== Navigation ====================
function initNavigation() {
    elements.navItems.forEach(item => {
        item.addEventListener('click', () => {
            const viewId = item.dataset.view;
            switchView(viewId);
        });
    });
}

function switchView(viewId) {
    // Update nav items
    elements.navItems.forEach(item => {
        item.classList.toggle('active', item.dataset.view === viewId);
    });
    
    // Update views
    elements.views.forEach(view => {
        view.classList.toggle('active', view.id === `${viewId}View`);
    });
    
    // Refresh data if needed
    if (viewId === 'dashboard') {
        loadDashboard();
    } else if (viewId === 'groups') {
        renderGroups();
    } else if (viewId === 'logs') {
        loadLogs();
    }
}

// ==================== Authentication ====================
async function checkAuthStatus() {
    try {
        const response = await fetch('/api/auth/status');
        const data = await response.json();
        
        state.isAuthenticated = data.is_authenticated;
        state.user = data.user;
        
        updateAuthUI();
    } catch (error) {
        console.error('Failed to check auth status:', error);
    }
}

function updateAuthUI() {
    if (state.isAuthenticated && state.user) {
        elements.userName.textContent = state.user.name;
        elements.userStatus.textContent = '@' + state.user.username;
        elements.connectBtn.textContent = 'Connected';
        elements.connectBtn.disabled = true;
        
        elements.scanGroupsBtn.disabled = false;
        elements.configureFilterBtn.disabled = false;
    } else {
        elements.userName.textContent = 'Not logged in';
        elements.userStatus.textContent = 'Offline';
        elements.connectBtn.textContent = 'Connect';
        elements.connectBtn.disabled = false;
        
        elements.scanGroupsBtn.disabled = true;
        elements.configureFilterBtn.disabled = true;
    }
}

function openLoginModal() {
    elements.loginModal.classList.add('active');
}

function closeLoginModal() {
    elements.loginModal.classList.remove('active');
    elements.sessionString.value = '';
}

async function login() {
    const sessionString = elements.sessionString.value.trim();
    
    if (!sessionString) {
        showToast('Please enter a session string', 'error');
        return;
    }
    
    try {
        elements.loginBtn.disabled = true;
        elements.loginBtn.innerHTML = '<span class="spinner"></span>';
        
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_string: sessionString })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            state.isAuthenticated = true;
            state.user = data.user;
            updateAuthUI();
            closeLoginModal();
            showToast('Connected successfully!', 'success');
        } else {
            showToast(data.error || 'Login failed', 'error');
        }
    } catch (error) {
        showToast('Login failed: ' + error.message, 'error');
    } finally {
        elements.loginBtn.disabled = false;
        elements.loginBtn.textContent = 'Connect';
    }
}

// ==================== Dashboard ====================
async function loadDashboard() {
    try {
        const response = await fetch('/api/dashboard');
        const data = await response.json();
        
        elements.totalGroups.textContent = data.total_groups;
        elements.activeGroups.textContent = data.active_groups;
        elements.inactiveGroups.textContent = data.inactive_groups;
        
        if (data.threshold) {
            const date = new Date(data.threshold);
            elements.thresholdDate.value = date.toISOString().split('T')[0];
            elements.thresholdTime.value = date.toTimeString().slice(0, 5);
        }
        
        // Load groups if we have them
        if (data.total_groups > 0) {
            await loadGroups();
        }
    } catch (error) {
        console.error('Failed to load dashboard:', error);
    }
}

// ==================== Groups ====================
async function loadGroups() {
    try {
        const response = await fetch('/api/groups');
        const data = await response.json();
        
        state.groups = data.groups;
        renderGroups();
    } catch (error) {
        console.error('Failed to load groups:', error);
    }
}

function renderGroups() {
    const searchTerm = elements.groupSearch.value.toLowerCase();
    let filteredGroups = state.groups;
    
    // Apply search filter
    if (searchTerm) {
        filteredGroups = filteredGroups.filter(g => 
            g.name.toLowerCase().includes(searchTerm)
        );
    }
    
    // Apply status filter
    if (state.currentFilter === 'active') {
        filteredGroups = filteredGroups.filter(g => g.is_active);
    } else if (state.currentFilter === 'inactive') {
        filteredGroups = filteredGroups.filter(g => !g.is_active);
    }
    
    if (filteredGroups.length === 0) {
        elements.groupsTableBody.innerHTML = `
            <tr>
                <td colspan="4" class="empty-state">
                    <p>No groups found</p>
                </td>
            </tr>
        `;
        return;
    }
    
    elements.groupsTableBody.innerHTML = filteredGroups.map(group => `
        <tr>
            <td>
                <strong>${escapeHtml(group.name)}</strong>
                ${group.username ? `<br><small>@${escapeHtml(group.username)}</small>` : ''}
            </td>
            <td>${group.last_message_time ? formatDate(group.last_message_time) : 'No messages'}</td>
            <td>
                <span class="status-badge ${group.is_active ? 'active' : 'inactive'}">
                    ${group.is_active ? 'Active' : 'Inactive'}
                </span>
            </td>
            <td>
                <button class="btn btn-small btn-secondary" onclick="viewGroup(${group.id})">
                    View
                </button>
            </td>
        </tr>
    `).join('');
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ==================== Scan Groups ====================
async function scanGroups() {
    if (state.isScanning) return;
    
    try {
        state.isScanning = true;
        elements.scanGroupsBtn.disabled = true;
        elements.scanGroupsBtn.innerHTML = '<span class="spinner"></span> Scanning...';
        
        const response = await fetch('/api/groups/scan', { method: 'POST' });
        const data = await response.json();
        
        if (response.ok) {
            state.groups = data.groups;
            elements.totalGroups.textContent = data.count;
            showToast(`Scanned ${data.count} groups`, 'success');
            renderGroups();
        } else {
            showToast(data.error || 'Scan failed', 'error');
        }
    } catch (error) {
        showToast('Scan failed: ' + error.message, 'error');
    } finally {
        state.isScanning = false;
        elements.scanGroupsBtn.disabled = false;
        elements.scanGroupsBtn.textContent = 'Scan Now';
    }
}

// ==================== Inactivity Filter ====================
async function applyThreshold() {
    const date = elements.thresholdDate.value;
    const time = elements.thresholdTime.value || '00:00';
    
    if (!date) {
        showToast('Please select a date', 'error');
        return;
    }
    
    try {
        // Set threshold
        await fetch('/api/filter/set-threshold', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ date, time })
        });
        
        // Apply filter
        const response = await fetch('/api/filter/apply', { method: 'POST' });
        const data = await response.json();
        
        if (response.ok) {
            state.activeGroups = data.active_groups;
            state.inactiveGroups = data.inactive_groups;
            
            elements.activeGroups.textContent = data.statistics.active_groups;
            elements.inactiveGroups.textContent = data.statistics.inactive_groups;
            elements.inactiveCount.textContent = data.statistics.inactive_groups;
            
            // Enable send button if we have inactive groups
            elements.sendMessagesBtn.disabled = data.statistics.inactive_groups === 0;
            
            showToast(`Found ${data.statistics.inactive_groups} inactive groups`, 'success');
            
            // Refresh groups display
            state.groups = [...data.active_groups, ...data.inactive_groups];
            renderGroups();
        } else {
            showToast(data.error || 'Filter failed', 'error');
        }
    } catch (error) {
        showToast('Filter error: ' + error.message, 'error');
    }
}

// ==================== Message Automation ====================
async function sendMessages() {
    if (state.isSending || state.inactiveGroups.length === 0) return;
    
    const message = elements.messageTemplate.value.trim();
    if (!message) {
        showToast('Please enter a message', 'error');
        return;
    }
    
    const config = {
        message,
        delay_min: parseInt(elements.delayMin.value) || 10,
        delay_max: parseInt(elements.delayMax.value) || 30,
        max_messages: parseInt(elements.maxMessages.value) || 50,
        dry_run: elements.dryRun.checked
    };
    
    try {
        state.isSending = true;
        elements.sendMessagesBtn.disabled = true;
        elements.stopAutomationBtn.style.display = 'inline-flex';
        elements.progressCard.style.display = 'block';
        
        if (config.dry_run) {
            showToast('Starting preview mode (no messages will be sent)', 'info');
        }
        
        const response = await fetch('/api/automation/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        
        const data = await response.json();
        
        if (response.ok) {
            const summary = data.summary;
            showToast(`Sent ${summary.sent} messages, ${summary.failed} failed`, 
                summary.failed > 0 ? 'warning' : 'success');
            
            // Update progress to complete
            elements.progressFill.style.width = '100%';
            elements.progressText.textContent = `${summary.sent} / ${summary.total} sent`;
        } else {
            showToast(data.error || 'Automation failed', 'error');
        }
    } catch (error) {
        showToast('Automation error: ' + error.message, 'error');
    } finally {
        state.isSending = false;
        elements.sendMessagesBtn.disabled = false;
        elements.stopAutomationBtn.style.display = 'none';
    }
}

async function stopAutomation() {
    try {
        await fetch('/api/automation/stop', { method: 'POST' });
        showToast('Automation stopped', 'info');
    } catch (error) {
        console.error('Failed to stop automation:', error);
    }
}

// ==================== Logs ====================
async function loadLogs() {
    try {
        const response = await fetch('/api/logs?limit=100');
        const data = await response.json();
        
        if (data.logs.length === 0) {
            elements.logsList.innerHTML = `
                <div class="log-entry info">
                    <span class="log-time">--:--</span>
                    <span class="log-message">No logs yet...</span>
                </div>
            `;
            return;
        }
        
        elements.logsList.innerHTML = data.logs.map(log => {
            const time = new Date(log.timestamp).toLocaleTimeString();
            return `
                <div class="log-entry ${log.level}">
                    <span class="log-time">${time}</span>
                    <span class="log-message">${escapeHtml(log.message)}</span>
                </div>
            `;
        }).join('');
        
        // Scroll to bottom
        elements.logsList.scrollTop = elements.logsList.scrollHeight;
    } catch (error) {
        console.error('Failed to load logs:', error);
    }
}

function clearLogs() {
    elements.logsList.innerHTML = `
        <div class="log-entry info">
            <span class="log-time">--:--</span>
            <span class="log-message">Logs cleared</span>
        </div>
    `;
}

// ==================== Toast Notifications ====================
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    const iconSvg = type === 'success' 
        ? '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M7 10L9 12L13 8" stroke="#34C759" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        : type === 'error'
        ? '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="8" stroke="#FF3B30" stroke-width="2"/><path d="M10 6V10M10 14H10.01" stroke="#FF3B30" stroke-width="2" stroke-linecap="round"/></svg>'
        : '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="8" stroke="#007AFF" stroke-width="2"/><path d="M10 7V10M10 14H10.01" stroke="#007AFF" stroke-width="2" stroke-linecap="round"/></svg>';
    
    toast.innerHTML = `
        <span class="toast-icon">${iconSvg}</span>
        <span class="toast-message">${escapeHtml(message)}</span>
    `;
    
    elements.toastContainer.appendChild(toast);
    
    // Auto-remove after 4 seconds
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        setTimeout(() => toast.remove(), 200);
    }, 4000);
}

// ==================== Event Listeners ====================
function initEventListeners() {
    // Auth
    elements.connectBtn.addEventListener('click', openLoginModal);
    elements.closeLoginModal.addEventListener('click', closeLoginModal);
    elements.cancelLoginBtn.addEventListener('click', closeLoginModal);
    elements.loginBtn.addEventListener('click', login);
    
    // Dashboard actions
    elements.scanGroupsBtn.addEventListener('click', scanGroups);
    elements.configureFilterBtn.addEventListener('click', () => switchView('automation'));
    
    // Groups
    elements.groupSearch.addEventListener('input', renderGroups);
    elements.filterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            elements.filterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.currentFilter = btn.dataset.filter;
            renderGroups();
        });
    });
    
    // Automation
    elements.applyThresholdBtn.addEventListener('click', applyThreshold);
    elements.sendMessagesBtn.addEventListener('click', sendMessages);
    elements.stopAutomationBtn.addEventListener('click', stopAutomation);
    
    // Logs
    elements.refreshLogsBtn.addEventListener('click', loadLogs);
    elements.clearLogsBtn.addEventListener('click', clearLogs);
    
    // Modal close on overlay click
    elements.loginModal.addEventListener('click', (e) => {
        if (e.target === elements.loginModal) {
            closeLoginModal();
        }
    });
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeLoginModal();
        }
    });
}

// ==================== Initialization ====================
async function init() {
    initNavigation();
    initEventListeners();
    
    // Check auth status
    await checkAuthStatus();
    
    // Load dashboard
    await loadDashboard();
    
    // Set default date to 30 days ago
    const thirtyDaysAgo = new Date();
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
    elements.thresholdDate.value = thirtyDaysAgo.toISOString().split('T')[0];
    
    showToast('Application loaded', 'info');
}

// Start app
document.addEventListener('DOMContentLoaded', init);
