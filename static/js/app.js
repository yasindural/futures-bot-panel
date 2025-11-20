// Global state management with Alpine.js
function appState() {
    return {
        // Auth state
        showLogin: true,
        user: null,
        loginForm: { username: '', password: '' },
        loginError: '',
        
        // UI state
        currentTab: 'dashboard',
        isDarkMode: true,
        globalSearch: '',
        testMode: false,
        showNotifications: false,
        showAddUserModal: false,
        showPositionDetailModal: false,
        selectedPosition: null,
        
        // Data state
        config: {
            BOT_MARGIN_USDT: 5,
            BOT_LEVERAGE: 20,
            BOT_DAILY_MAX_LOSS: -100,
            BOT_INITIAL_SL_ROE: -20,
            BOT_WATCH_INTERVAL_SECONDS: 3,
            USE_DYNAMIC_PRECISION: true,
            TEST_MODE: false,
            AUTO_LOGOUT_MINUTES: 30,
        },
        botVersion: '',
        pnlSummary: {
            daily_realized_pnl: 0,
            total_realized_pnl: 0,
            overall_roi: 0,
        },
        btcStrategy: null,
        positions: [],
        positionFilter: 'all',
        users: [],
        logs: [],
        logFilter: '',
        
        // Simulation state
        simForm: {
            entry_price: 68000,
            direction: 'LONG',
            margin: 5,
            leverage: 20,
            prices: '68000, 68200, 68500, 69000',
        },
        simResults: [],
        simChart: null,
        
        // Webhook test state
        webhookUrl: window.location.origin + '/webhook',
        webhookTest: {
            ticker: 'BTCUSDT',
            dir: 'LONG',
            entry: 68000,
        },
        webhookTestResult: null,
        
        // New user form
        newUser: {
            username: '',
            password: '',
            role: 'trader',
            api_key: '',
            api_secret: '',
        },
        
        // Toast & notifications
        toasts: [],
        notifications: [],
        toastIdCounter: 0,
        notificationIdCounter: 0,
        
        // Auto-refresh
        autoRefresh: true,
        refreshInterval: null,
        
        // Auto-logout
        lastActivity: Date.now(),
        logoutTimer: null,
        
        // Charts
        chart7d: null,
        chart30d: null,
        
        // Computed
        get filteredPositions() {
            let filtered = this.positions;
            if (this.globalSearch) {
                const search = this.globalSearch.toLowerCase();
                filtered = filtered.filter(p => 
                    p.symbol.toLowerCase().includes(search) ||
                    p.position_side.toLowerCase().includes(search)
                );
            }
            if (this.positionFilter === 'long') {
                filtered = filtered.filter(p => p.position_side === 'LONG');
            } else if (this.positionFilter === 'short') {
                filtered = filtered.filter(p => p.position_side === 'SHORT');
            } else if (this.positionFilter === 'profit') {
                filtered = filtered.filter(p => p.peak_pnl > 0);
            } else if (this.positionFilter === 'loss') {
                filtered = filtered.filter(p => p.peak_pnl < 0);
            }
            return filtered;
        },
        
        get filteredLogs() {
            if (!this.logFilter) return this.logs;
            const filter = this.logFilter.toLowerCase();
            return this.logs.filter(log => log.toLowerCase().includes(filter));
        },
        
        get activeWatchers() {
            return this.positions.length;
        },
        
        // Init
        async init() {
            // Check if already logged in
            await this.checkAuth();
            
            // Load theme preference
            const savedTheme = localStorage.getItem('theme') || 'dark';
            this.isDarkMode = savedTheme === 'dark';
            this.applyTheme();
            
            // Setup auto-logout
            this.setupAutoLogout();
            
            // Track activity
            document.addEventListener('click', () => this.updateActivity());
            document.addEventListener('keypress', () => this.updateActivity());
            
            // If logged in, start data loading
            if (!this.showLogin) {
                await this.loadInitialData();
                this.startAutoRefresh();
            }
        },
        
        // Auth functions
        async checkAuth() {
            try {
                const res = await fetch('/api/auth/me');
                if (res.ok) {
                    const data = await res.json();
                    this.user = data.user;
                    this.showLogin = false;
                } else {
                    this.showLogin = true;
                }
            } catch (err) {
                this.showLogin = true;
            }
        },
        
        async handleLogin() {
            try {
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.loginForm),
                });
                const data = await res.json();
                if (res.ok) {
                    this.user = data.user;
                    this.showLogin = false;
                    this.loginError = '';
                    await this.loadInitialData();
                    this.startAutoRefresh();
                    this.addToast('Giriş başarılı', 'success');
                } else {
                    this.loginError = data.message || 'Giriş başarısız';
                }
            } catch (err) {
                this.loginError = 'Bağlantı hatası';
            }
        },
        
        async handleLogout() {
            try {
                await fetch('/api/auth/logout', { method: 'POST' });
                this.user = null;
                this.showLogin = true;
                this.stopAutoRefresh();
                this.addToast('Çıkış yapıldı', 'info');
            } catch (err) {
                console.error('Logout error:', err);
            }
        },
        
        // Data loading
        async loadInitialData() {
            await Promise.all([
                this.loadConfig(),
                this.loadStatus(),
                this.loadPnLSummary(),
                this.loadPositions(),
                this.loadLogs(),
                this.loadBtcStrategy(),
            ]);
            if (this.user?.role === 'admin') {
                await this.loadUsers();
            }
        },
        
        async loadBtcStrategy() {
            try {
                const res = await fetch('/api/btc-strategy-summary');
                if (res.ok) {
                    const data = await res.json();
                    this.btcStrategy = data;
                }
            } catch (err) {
                console.error('BTC strategy load error:', err);
            }
        },
        
        async loadConfig() {
            try {
                const res = await fetch('/api/config');
                if (res.ok) {
                    const data = await res.json();
                    this.config = { ...this.config, ...data.config };
                    this.testMode = this.config.TEST_MODE;
                }
            } catch (err) {
                console.error('Config load error:', err);
            }
        },
        
        async loadStatus() {
            try {
                const res = await fetch('/api/status');
                if (res.ok) {
                    const data = await res.json();
                    this.botVersion = data.bot_version;
                }
            } catch (err) {
                console.error('Status load error:', err);
            }
        },
        
        async loadPnLSummary() {
            try {
                const res = await fetch('/api/pnl/summary');
                if (res.ok) {
                    const data = await res.json();
                    this.pnlSummary = data;
                }
            } catch (err) {
                console.error('PnL summary error:', err);
            }
        },
        
        async loadPositions() {
            try {
                const res = await fetch('/api/open-positions');
                if (res.ok) {
                    const data = await res.json();
                    this.positions = data.positions || [];
                }
            } catch (err) {
                console.error('Positions load error:', err);
            }
        },
        
        async loadUsers() {
            try {
                const res = await fetch('/api/users');
                if (res.ok) {
                    const data = await res.json();
                    this.users = data.users || [];
                }
            } catch (err) {
                console.error('Users load error:', err);
            }
        },
        
        async loadLogs() {
            try {
                const res = await fetch('/api/logs?limit=200');
                if (res.ok) {
                    const data = await res.json();
                    this.logs = data.logs || [];
                }
            } catch (err) {
                console.error('Logs load error:', err);
            }
        },
        
        // Auto-refresh
        startAutoRefresh() {
            if (this.refreshInterval) clearInterval(this.refreshInterval);
            this.refreshInterval = setInterval(() => {
                if (this.autoRefresh && !this.showLogin) {
                    this.loadPositions();
                    if (this.currentTab === 'dashboard') {
                        this.loadPnLSummary();
                    }
                }
            }, 5000);
        },
        
        stopAutoRefresh() {
            if (this.refreshInterval) {
                clearInterval(this.refreshInterval);
                this.refreshInterval = null;
            }
        },
        
        // Auto-logout
        setupAutoLogout() {
            const minutes = this.config.AUTO_LOGOUT_MINUTES || 30;
            const ms = minutes * 60 * 1000;
            this.logoutTimer = setInterval(() => {
                const now = Date.now();
                const inactive = now - this.lastActivity;
                if (inactive > ms && !this.showLogin) {
                    this.addNotification('Uzun süre işlem yapılmadı, otomatik çıkış yapılıyor...');
                    setTimeout(() => this.handleLogout(), 2000);
                }
            }, 60000); // Check every minute
        },
        
        updateActivity() {
            this.lastActivity = Date.now();
        },
        
        // Theme
        toggleTheme() {
            this.isDarkMode = !this.isDarkMode;
            this.applyTheme();
            localStorage.setItem('theme', this.isDarkMode ? 'dark' : 'light');
        },
        
        applyTheme() {
            if (this.isDarkMode) {
                document.body.classList.add('dark', 'bg-binance-dark');
                document.body.classList.remove('bg-white');
            } else {
                document.body.classList.remove('dark', 'bg-binance-dark');
                document.body.classList.add('bg-white');
            }
        },
        
        // Toast system
        addToast(message, type = 'info') {
            const id = ++this.toastIdCounter;
            this.toasts.push({ id, message, type });
            setTimeout(() => this.removeToast(id), 5000);
        },
        
        removeToast(id) {
            this.toasts = this.toasts.filter(t => t.id !== id);
        },
        
        // Notification system
        addNotification(message) {
            const id = ++this.notificationIdCounter;
            const time = new Date().toLocaleTimeString('tr-TR');
            this.notifications.unshift({ id, message, time });
            if (this.notifications.length > 50) {
                this.notifications = this.notifications.slice(0, 50);
            }
        },
        
        // Position functions
        getPositionBorderColor(pos) {
            if (pos.peak_pnl > 0) return 'border-green-500';
            if (pos.peak_pnl < 0) return 'border-red-500';
            return 'border-gray-700';
        },
        
        async closePosition(stateKey) {
            if (!confirm('Pozisyonu kapatmak istediğinize emin misiniz?')) return;
            try {
                const res = await fetch('/api/position/close', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ state_key: stateKey }),
                });
                if (res.ok) {
                    this.addToast('Pozisyon kapatma emri gönderildi', 'success');
                    await this.loadPositions();
                } else {
                    const data = await res.json();
                    this.addToast(data.message || 'Hata oluştu', 'error');
                }
            } catch (err) {
                this.addToast('Bağlantı hatası', 'error');
            }
        },
        
        showPositionDetail(pos) {
            this.selectedPosition = pos;
            this.showPositionDetailModal = true;
        },
        
        exportPositionsCSV() {
            const headers = ['Symbol', 'Side', 'Entry', 'Qty', 'SL', 'SL ROE', 'Peak ROE', 'Peak PnL', 'Leverage', 'Margin', 'Opened At'];
            const rows = this.positions.map(p => [
                p.symbol,
                p.position_side,
                p.entry,
                p.qty,
                p.sl,
                p.sl_roe,
                p.peak_roe,
                p.peak_pnl,
                p.leverage,
                p.margin,
                p.opened_at || '',
            ]);
            const csv = [headers, ...rows].map(row => row.join(',')).join('\n');
            const blob = new Blob([csv], { type: 'text/csv' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `positions_${new Date().toISOString().split('T')[0]}.csv`;
            a.click();
            URL.revokeObjectURL(url);
        },
        
        // Simulation
        async runSimulation() {
            try {
                const prices = this.simForm.prices.split(/[,\s]+/).map(p => parseFloat(p.trim())).filter(p => !isNaN(p));
                if (prices.length === 0) {
                    this.addToast('Geçerli fiyat listesi girin', 'error');
                    return;
                }
                const res = await fetch('/api/simulate-roi-trailing', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        entry_price: parseFloat(this.simForm.entry_price),
                        direction: this.simForm.direction,
                        margin: parseFloat(this.simForm.margin),
                        leverage: parseInt(this.simForm.leverage),
                        prices: prices,
                    }),
                });
                const data = await res.json();
                if (res.ok) {
                    this.simResults = data.steps || [];
                    this.updateSimChart();
                } else {
                    this.addToast(data.message || 'Simülasyon hatası', 'error');
                }
            } catch (err) {
                this.addToast('Bağlantı hatası', 'error');
            }
        },
        
        loadExampleScenario() {
            this.simForm = {
                entry_price: 100,
                direction: 'LONG',
                margin: 5,
                leverage: 20,
                prices: '100, 102, 105, 103, 98, 110, 115, 112, 120',
            };
        },
        
        updateSimChart() {
            const ctx = document.getElementById('sim-chart');
            if (!ctx || this.simResults.length === 0) return;
            
            const labels = this.simResults.map(r => r.step);
            const prices = this.simResults.map(r => r.price);
            const slPrices = this.simResults.map(r => r.sl_price);
            
            if (this.simChart) {
                this.simChart.destroy();
            }
            
            this.simChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Fiyat',
                            data: prices,
                            borderColor: '#10b981',
                            tension: 0.25,
                        },
                        {
                            label: 'SL Fiyatı',
                            data: slPrices,
                            borderColor: '#f59e0b',
                            borderDash: [6, 6],
                            tension: 0.25,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            labels: { color: '#94a3b8' },
                        },
                    },
                    scales: {
                        x: {
                            ticks: { color: '#94a3b8' },
                            grid: { color: 'rgba(148,163,184,0.2)' },
                        },
                        y: {
                            ticks: { color: '#94a3b8' },
                            grid: { color: 'rgba(148,163,184,0.2)' },
                        },
                    },
                },
            });
        },
        
        // Webhook test
        async testWebhook() {
            try {
                const res = await fetch('/webhook', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.webhookTest),
                });
                const data = await res.json();
                this.webhookTestResult = data;
                if (res.ok) {
                    this.addToast('Webhook başarılı', 'success');
                } else {
                    this.addToast(data.msg || 'Webhook hatası', 'error');
                }
            } catch (err) {
                this.addToast('Bağlantı hatası', 'error');
            }
        },
        
        copyWebhookUrl() {
            navigator.clipboard.writeText(this.webhookUrl);
            this.addToast('URL kopyalandı', 'success');
        },
        
        // User management (admin)
        async addUser() {
            try {
                const res = await fetch('/api/users', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.newUser),
                });
                const data = await res.json();
                if (res.ok) {
                    this.addToast('Kullanıcı eklendi', 'success');
                    this.showAddUserModal = false;
                    this.newUser = { username: '', password: '', role: 'trader', api_key: '', api_secret: '' };
                    await this.loadUsers();
                } else {
                    this.addToast(data.message || 'Hata', 'error');
                }
            } catch (err) {
                this.addToast('Bağlantı hatası', 'error');
            }
        },
        
        async deleteUser(username) {
            if (!confirm(`Kullanıcıyı silmek istediğinize emin misiniz: ${username}?`)) return;
            try {
                const res = await fetch(`/api/users/${username}`, { method: 'DELETE' });
                if (res.ok) {
                    this.addToast('Kullanıcı silindi', 'success');
                    await this.loadUsers();
                } else {
                    this.addToast('Hata oluştu', 'error');
                }
            } catch (err) {
                this.addToast('Bağlantı hatası', 'error');
            }
        },
        
        async resetUserPassword(username) {
            try {
                const res = await fetch(`/api/users/${username}/reset-password`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password: 'newpass123' }),
                });
                const data = await res.json();
                if (res.ok) {
                    alert(`Yeni şifre: ${data.new_password}`);
                    this.addToast('Şifre sıfırlandı', 'success');
                } else {
                    this.addToast(data.message || 'Hata', 'error');
                }
            } catch (err) {
                this.addToast('Bağlantı hatası', 'error');
            }
        },
        
        // Config
        async saveConfig() {
            try {
                const res = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.config),
                });
                if (res.ok) {
                    this.addToast('Ayarlar kaydedildi', 'success');
                    this.testMode = this.config.TEST_MODE;
                } else {
                    const data = await res.json();
                    this.addToast(data.message || 'Hata', 'error');
                }
            } catch (err) {
                this.addToast('Bağlantı hatası', 'error');
            }
        },
        
        async resetConfig() {
            if (!confirm('Ayarları varsayılanlara döndürmek istediğinize emin misiniz?')) return;
            try {
                const res = await fetch('/api/config/reset', { method: 'POST' });
                if (res.ok) {
                    const data = await res.json();
                    this.config = data.config;
                    this.addToast('Ayarlar sıfırlandı', 'success');
                } else {
                    this.addToast('Hata oluştu', 'error');
                }
            } catch (err) {
                this.addToast('Bağlantı hatası', 'error');
            }
        },
        
        // Logs
        async refreshLogs() {
            await this.loadLogs();
            this.addToast('Loglar yenilendi', 'success');
        },
        
        // Utility functions
        formatNumber(num, decimals = 2) {
            if (num === null || num === undefined || isNaN(num)) return '-';
            return new Intl.NumberFormat('tr-TR', {
                minimumFractionDigits: decimals,
                maximumFractionDigits: decimals,
            }).format(num);
        },
        
        formatDate(isoString) {
            if (!isoString) return '-';
            try {
                const date = new Date(isoString);
                return date.toLocaleString('tr-TR');
            } catch {
                return isoString;
            }
        },
    };
}
