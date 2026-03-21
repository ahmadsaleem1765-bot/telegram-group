/**
 * Telegram Controller - Frontend Application
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
    groupsTableBody: document.getElementById('groupsTableBody'),
    filterBtns: document.querySelectorAll('.filter-btn'),
    // Automation
    broadcastTarget: document.getElementById('broadcastTarget'),
    broadcastInactivityPeriodContainer: document.getElementById('broadcastInactivityPeriodContainer'),
    broadcastPeriodValue: document.getElementById('broadcastPeriodValue'),
    broadcastPeriodUnit: document.getElementById('broadcastPeriodUnit'),
    broadcastPreviewContainer: document.getElementById('broadcastPreviewContainer'),
    broadcastPreviewText: document.getElementById('broadcastPreviewText'),
    broadcastMessage: document.getElementById('broadcastMessage'),
    sendBroadcastBtn: document.getElementById('sendBroadcastBtn'),
    
    // Rules
    addRuleBtn: document.getElementById('addRuleBtn'),
    addRuleForm: document.getElementById('addRuleForm'),
    cancelRuleBtn: document.getElementById('cancelRuleBtn'),
    saveRuleBtn: document.getElementById('saveRuleBtn'),
    rulePeriodValue: document.getElementById('rulePeriodValue'),
    rulePeriodUnit: document.getElementById('rulePeriodUnit'),
    ruleMessage: document.getElementById('ruleMessage'),
    rulesList: document.getElementById('rulesList'),
    
    // Progress
    progressCard: document.getElementById('progressCard'),
    progressFill: document.getElementById('progressFill'),
    progressText: document.getElementById('progressText'),
    logsList: document.getElementById('logsList'),
    refreshLogsBtn: document.getElementById('refreshLogsBtn'),
    clearLogsBtn: document.getElementById('clearLogsBtn'),
    
    // Modal
    loginModal: document.getElementById('loginModal'),
    closeLoginModal: document.getElementById('closeLoginModal'),
    cancelLoginBtn: document.getElementById('cancelLoginBtn'),
    loginModalTitle: document.getElementById('loginModalTitle'),
    loginStep1: document.getElementById('loginStep1'),
    loginStep2: document.getElementById('loginStep2'),
    loginStep3: document.getElementById('loginStep3'),
    apiId: document.getElementById('apiId'),
    apiHash: document.getElementById('apiHash'),
    phoneNumber: document.getElementById('phoneNumber'),
    verificationCode: document.getElementById('verificationCode'),
    twoFaPassword: document.getElementById('twoFaPassword'),
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
        loadGroups();
        renderGroups();
    } else if (viewId === 'automation') {
        // Ensure groups are loaded for broadcast preview
        loadGroups().then(() => updateBroadcastPreview());
        loadRules();
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
        elements.userStatus.textContent = state.user.username ? '@' + state.user.username : 'No Username';
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

const loginState = {
    step: 1, // 1: request code, 2: verify code, 3: verify password
    phoneCodeHash: null,
    phone: null
};

function resetLoginModal() {
    loginState.step = 1;
    loginState.phoneCodeHash = null;
    loginState.phone = null;
    
    elements.apiId.value = '';
    elements.apiHash.value = '';
    elements.phoneNumber.value = '';
    elements.verificationCode.value = '';
    elements.twoFaPassword.value = '';
    
    elements.loginStep1.style.display = 'block';
    elements.loginStep2.style.display = 'none';
    elements.loginStep3.style.display = 'none';
    
    elements.loginModalTitle.textContent = 'Connect Telegram';
    elements.loginBtn.textContent = 'Request Code';
}

function openLoginModal() {
    resetLoginModal();
    elements.loginModal.classList.add('active');
}

function closeLoginModal() {
    elements.loginModal.classList.remove('active');
    resetLoginModal();
}

async function processLoginStep() {
    if (loginState.step === 1) {
        await requestSmsCode();
    } else if (loginState.step === 2) {
        await verifySmsCode();
    } else if (loginState.step === 3) {
        await verifyTwoFaPassword();
    }
}

async function requestSmsCode() {
    const apiId = elements.apiId.value.trim();
    const apiHash = elements.apiHash.value.trim();
    const phone = elements.phoneNumber.value.trim();
    
    if (!apiId || !apiHash || !phone) {
        showToast('API ID, API Hash, and Phone Number are required', 'error');
        return;
    }
    
    try {
        elements.loginBtn.disabled = true;
        elements.loginBtn.innerHTML = '<span class="spinner"></span> Requesting...';
        
        const response = await fetch('/api/auth/request-code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_id: apiId, api_hash: apiHash, phone })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            loginState.phoneCodeHash = data.phone_code_hash;
            loginState.phone = phone;
            loginState.step = 2;
            
            elements.loginStep1.style.display = 'none';
            elements.loginStep2.style.display = 'block';
            elements.loginModalTitle.textContent = 'Verification Code';
            elements.loginBtn.textContent = 'Verify Code';
            showToast('Code requested successfully!', 'success');
        } else {
            showToast(data.error || 'Failed to request code', 'error');
        }
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    } finally {
        elements.loginBtn.disabled = false;
        if (loginState.step === 1) elements.loginBtn.textContent = 'Request Code';
    }
}

async function verifySmsCode() {
    const code = elements.verificationCode.value.trim();
    
    if (!code) {
        showToast('Verification code is required', 'error');
        return;
    }
    
    try {
        elements.loginBtn.disabled = true;
        elements.loginBtn.innerHTML = '<span class="spinner"></span> Verifying...';
        
        const response = await fetch('/api/auth/verify-code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                phone: loginState.phone, 
                code, 
                phone_code_hash: loginState.phoneCodeHash 
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            if (data.password_required) {
                loginState.step = 3;
                elements.loginStep2.style.display = 'none';
                elements.loginStep3.style.display = 'block';
                elements.loginModalTitle.textContent = 'Two-Step Verification';
                elements.loginBtn.textContent = 'Submit Password';
                showToast('2FA Password required', 'info');
            } else {
                // Success
                state.isAuthenticated = true;
                state.user = data.user;
                updateAuthUI();
                closeLoginModal();
                showToast('Connected successfully!', 'success');
            }
        } else {
            showToast(data.error || 'Verification failed', 'error');
        }
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    } finally {
        elements.loginBtn.disabled = false;
        if (loginState.step === 2) elements.loginBtn.textContent = 'Verify Code';
    }
}

async function verifyTwoFaPassword() {
    const password = elements.twoFaPassword.value.trim();
    
    if (!password) {
        showToast('Password is required', 'error');
        return;
    }
    
    try {
        elements.loginBtn.disabled = true;
        elements.loginBtn.innerHTML = '<span class="spinner"></span> Verifying...';
        
        const response = await fetch('/api/auth/verify-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            state.isAuthenticated = true;
            state.user = data.user;
            updateAuthUI();
            closeLoginModal();
            showToast('Connected successfully!', 'success');
        } else {
            showToast(data.error || 'Password verification failed', 'error');
        }
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    } finally {
        elements.loginBtn.disabled = false;
        if (loginState.step === 3) elements.loginBtn.textContent = 'Submit Password';
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
    
    // update is_active for each group based on 30-day threshold
    const thresholdMs = Date.now() - (30 * 86400 * 1000);
    state.groups.forEach(g => {
        if (!g.last_message_time) {
            g.is_active = false;
        } else {
            const lastMsgDate = new Date(g.last_message_time).getTime();
            g.is_active = lastMsgDate >= thresholdMs;
        }
    });

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

window.viewGroup = function(groupId) {
    const group = state.groups.find(g => g.id === groupId);
    if (group) {
        showToast(`Group: ${group.name} (${group.member_count || 'Unknown'} members)`, 'info');
    }
};

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
        
        const response = await fetch('/api/groups/scan', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
        const data = await response.json();
        
        if (response.ok) {
            showToast('Scan started...', 'info');
            checkScanStatus();
        } else {
            showToast(data.error || 'Scan failed', 'error');
            state.isScanning = false;
            elements.scanGroupsBtn.disabled = false;
            elements.scanGroupsBtn.textContent = 'Scan Now';
        }
    } catch (error) {
        showToast('Scan failed: ' + error.message, 'error');
        state.isScanning = false;
        elements.scanGroupsBtn.disabled = false;
        elements.scanGroupsBtn.textContent = 'Scan Now';
    }
}

function checkScanStatus() {
    const interval = setInterval(async () => {
        try {
            const res = await fetch('/api/dashboard');
            const data = await res.json();
            if (!data.is_scanning) {
                clearInterval(interval);
                state.isScanning = false;
                elements.scanGroupsBtn.disabled = false;
                elements.scanGroupsBtn.textContent = 'Scan Now';
                elements.totalGroups.textContent = data.total_groups;
                elements.activeGroups.textContent = data.active_groups;
                elements.inactiveGroups.textContent = data.inactive_groups;
                showToast(`Scan complete`, 'success');
                await loadGroups();
            }
        } catch (e) {
            console.error('Error polling scan status:', e);
        }
    }, 2000);
}

// ==================== Inactivity Filter ====================
async function applyThreshold() {
    if (!elements.thresholdDate || !elements.thresholdTime) {
        showToast('Filter configuration UI is deprecated or updating', 'warning');
        return;
    }
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

// ==================== Message Automation & Rules ====================
async function updateBroadcastPreview() {
    if (!state.groups || state.groups.length === 0) {
        if(elements.broadcastPreviewContainer) elements.broadcastPreviewContainer.style.display = 'none';
        return;
    }

    const target = elements.broadcastTarget.value;
    if (target === 'all') {
        elements.broadcastInactivityPeriodContainer.style.display = 'none';
        elements.broadcastPreviewContainer.style.display = 'block';
        elements.broadcastPreviewText.textContent = `Ready to send to ${state.groups.length} groups`;
        return;
    }

    // Inactive Groups calculation
    elements.broadcastInactivityPeriodContainer.style.display = 'block';
    elements.broadcastPreviewContainer.style.display = 'block';
    
    const val = parseInt(elements.broadcastPeriodValue.value);
    const unit = elements.broadcastPeriodUnit.value;
    
    if (isNaN(val) || val <= 0) {
        elements.broadcastPreviewText.textContent = `Invalid period entered.`;
        return;
    }

    // Convert to seconds
    let secondsAgo = val;
    if (unit === 'Minutes') secondsAgo *= 60;
    else if (unit === 'Hours') secondsAgo *= 3600;
    else if (unit === 'Days') secondsAgo *= 86400;

    const thresholdMs = Date.now() - (secondsAgo * 1000);
    
    let inactiveCount = 0;
    for(const group of state.groups) {
        if (!group.last_message_time) {
            inactiveCount++; // assume inactive if no messages
        } else {
            const lastMsgDate = new Date(group.last_message_time).getTime();
            if (lastMsgDate < thresholdMs) inactiveCount++;
        }
    }

    elements.broadcastPreviewText.textContent = `Ready to send to ${inactiveCount} inactive groups`;
}

async function sendBroadcast() {
    if (state.isSending) return;
    
    const target = elements.broadcastTarget.value;
    const message = elements.broadcastMessage.value.trim();
    if (!message) {
        showToast('Please enter a message', 'error');
        return;
    }
    
    const config = { target, message };

    if (target === 'inactive') {
        config.period_value = parseInt(elements.broadcastPeriodValue.value);
        config.period_unit = elements.broadcastPeriodUnit.value;
    }
    
    try {
        state.isSending = true;
        elements.sendBroadcastBtn.disabled = true;
        elements.progressCard.style.display = 'block';
        
        const response = await fetch('/api/automation/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showToast('Broadcast started...', 'info');
            checkBroadcastStatus();
        } else {
            showToast(data.error || 'Broadcast failed', 'error');
            state.isSending = false;
            elements.sendBroadcastBtn.disabled = false;
        }
    } catch (error) {
        showToast('Broadcast error: ' + error.message, 'error');
        state.isSending = false;
        elements.sendBroadcastBtn.disabled = false;
    }
}

function checkBroadcastStatus() {
    const interval = setInterval(async () => {
        try {
            const res = await fetch('/api/automation/status');
            const data = await res.json();
            
            if (data.results && data.results.total > 0) {
                const progress = data.results.total > 0 ? (data.results.sent + data.results.failed) / data.results.total : 0;
                elements.progressFill.style.width = (progress * 100) + '%';
                elements.progressText.textContent = `${data.results.sent} / ${data.results.total} sent`;
            }
            
            if (!data.is_running) {
                clearInterval(interval);
                state.isSending = false;
                elements.sendBroadcastBtn.disabled = false;
                const summary = data.results || {};
                showToast(`Broadcast complete! Sent ${summary.sent || 0}, ${summary.failed || 0} failed`, 'success');
                elements.broadcastMessage.value = ''; // clear
                await loadGroups();
                await loadDashboard();
                updateBroadcastPreview();
            }
        } catch (e) {
            console.error('Error polling broadcast status:', e);
        }
    }, 2000);
}

async function loadRules() {
    try {
        const response = await fetch('/api/rules');
        const data = await response.json();
        renderRules(data.rules || []);
    } catch (error) {
        console.error('Failed to load rules:', error);
    }
}

function renderRules(rules) {
    if (!rules || rules.length === 0) {
        elements.rulesList.innerHTML = '<div style="color: #94a3b8; font-style: italic;">No active rules</div>';
        return;
    }
    
    elements.rulesList.innerHTML = rules.map(rule => `
        <div style="background: rgba(255,255,255,0.05); border: 1px solid #333; border-radius: 8px; padding: 15px; margin-bottom: 15px; display: flex; justify-content: space-between; align-items: start;">
            <div>
                <div style="font-size: 1.1rem; font-weight: 600; color: #fff; margin-bottom: 5px;">
                    Send if inactive for > ${rule.period_value} ${rule.period_unit}
                </div>
                <div style="color: #94a3b8; font-size: 0.9rem; margin-bottom: 10px;">
                    "${escapeHtml(rule.message)}"
                </div>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <span style="display: inline-block; width: 8px; height: 8px; background: ${rule.is_active ? '#10b981' : '#ef4444'}; border-radius: 50%;"></span>
                    <span style="font-size: 0.8rem; color: #94a3b8;">${rule.is_active ? 'Active' : 'Paused'}</span>
                </div>
            </div>
            <div>
                <button onclick="deleteRule('${rule.id}')" style="background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 4px; padding: 6px 12px; cursor: pointer;">Delete</button>
            </div>
        </div>
    `).join('');
}

async function saveRule() {
    const period_value = parseInt(elements.rulePeriodValue.value);
    const period_unit = elements.rulePeriodUnit.value;
    const message = elements.ruleMessage.value.trim();

    if (!period_value || !message) {
        showToast('Please provide an inactivity period and a message.', 'error');
        return;
    }

    try {
        elements.saveRuleBtn.disabled = true;
        const response = await fetch('/api/rules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ period_value, period_unit, message })
        });
        const data = await response.json();
        
        if (response.ok) {
            showToast('Rule saved successfully.', 'success');
            elements.ruleMessage.value = '';
            elements.rulePeriodValue.value = '30';
            elements.addRuleForm.style.display = 'none';
            loadRules(); // reload
        } else {
            showToast(data.error || 'Failed to save rule', 'error');
        }
    } catch (error) {
        showToast('Save error: ' + error.message, 'error');
    } finally {
        elements.saveRuleBtn.disabled = false;
    }
}

window.deleteRule = async function(ruleId) {
    if(!confirm("Are you sure you want to delete this rule?")) return;
    try {
        const response = await fetch('/api/rules/' + ruleId, { method: 'DELETE' });
        if(response.ok) {
            showToast('Rule deleted', 'success');
            loadRules(); // Reload rules
        } else {
            showToast('Failed to delete rule', 'error');
        }
    } catch(err) {
        showToast('Delete error: ' + err.message, 'error');
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
    elements.loginBtn.addEventListener('click', processLoginStep);
    
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
    
    // Automation Buttons
    if (elements.broadcastTarget) elements.broadcastTarget.addEventListener('change', updateBroadcastPreview);
    if (elements.broadcastPeriodValue) elements.broadcastPeriodValue.addEventListener('input', updateBroadcastPreview);
    if (elements.broadcastPeriodUnit) elements.broadcastPeriodUnit.addEventListener('change', updateBroadcastPreview);
    if (elements.sendBroadcastBtn) elements.sendBroadcastBtn.addEventListener('click', sendBroadcast);
    if (elements.addRuleBtn) elements.addRuleBtn.addEventListener('click', () => { elements.addRuleForm.style.display = 'block'; });
    if (elements.cancelRuleBtn) elements.cancelRuleBtn.addEventListener('click', () => { elements.addRuleForm.style.display = 'none'; });
    if (elements.saveRuleBtn) elements.saveRuleBtn.addEventListener('click', saveRule);
    
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
    
    // Load rules
    await loadRules();
    
    // Init broadcast preview if groups already loaded
    updateBroadcastPreview();
    
    showToast('Application loaded', 'info');
}

// Start app
document.addEventListener('DOMContentLoaded', init);
