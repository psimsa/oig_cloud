/* eslint-disable */
const MODE_CONFIG = {
    'HOME I': { icon: '🏠', color: 'rgba(76, 175, 80, 0.7)', label: 'HOME I' },
    'HOME II': { icon: '⚡', color: 'rgba(33, 150, 243, 0.7)', label: 'HOME II' },
    'HOME III': { icon: '🔋', color: 'rgba(156, 39, 176, 0.7)', label: 'HOME III' },
    'HOME UPS': { icon: '🛡️', color: 'rgba(255, 152, 0, 0.7)', label: 'HOME UPS' },
    'FULL HOME UPS': { icon: '🛡️', color: 'rgba(255, 152, 0, 0.7)', label: 'FULL HOME UPS' },
    'DO NOTHING': { icon: '⏸️', color: 'rgba(158, 158, 158, 0.7)', label: 'DO NOTHING' }
};

const TIMELINE_MODE_ICON_PLUGIN_ID = 'timelineModeIcons';
let timelineModeIconPluginRegistered = false;

const timelineModeIconPlugin = {
    id: TIMELINE_MODE_ICON_PLUGIN_ID,
    beforeDatasetsDraw(chart, args, pluginOptions) {
        const segments = pluginOptions?.segments;
        if (!segments || segments.length === 0) {
            return;
        }

        const meta = chart.getDatasetMeta(0);
        if (!meta || !meta.data || meta.data.length === 0) {
            return;
        }

        const chartArea = chart.chartArea;
        if (!chartArea) {
            return;
        }

        const ctx = chart.ctx;
        ctx.save();
        ctx.globalAlpha = pluginOptions?.backgroundOpacity ?? 0.12;

        segments.forEach((segment) => {
            const pixelRange = getModeSegmentPixelRange(meta, segment);
            if (!pixelRange) {
                return;
            }

            ctx.fillStyle = segment.color || 'rgba(255, 255, 255, 0.1)';
            ctx.fillRect(
                pixelRange.left,
                chartArea.top,
                pixelRange.width,
                chartArea.bottom - chartArea.top
            );
        });

        ctx.restore();
    },
    afterDatasetsDraw(chart, args, pluginOptions) {
        const segments = pluginOptions?.segments;
        if (!segments || segments.length === 0) {
            return;
        }

        const meta = chart.getDatasetMeta(0);
        if (!meta || !meta.data || meta.data.length === 0) {
            return;
        }

        const chartArea = chart.chartArea;
        if (!chartArea) {
            return;
        }

        const iconSize = pluginOptions?.iconSize ?? 18;
        const labelSize = pluginOptions?.labelSize ?? 10;
        const iconOffset = pluginOptions?.iconOffset ?? 8;
        const iconFont = `${iconSize}px "Inter", "Segoe UI Emoji", "Noto Color Emoji", sans-serif`;
        const labelFont = `${labelSize}px "Inter", sans-serif`;
        const iconColor = pluginOptions?.iconColor || 'rgba(255, 255, 255, 0.95)';
        const labelColor = pluginOptions?.labelColor || 'rgba(255, 255, 255, 0.7)';
        const axisY = chartArea.bottom + iconOffset;

        const ctx = chart.ctx;
        ctx.save();
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';

        segments.forEach((segment) => {
            const pixelRange = getModeSegmentPixelRange(meta, segment);
            if (!pixelRange) {
                return;
            }
            const centerX = pixelRange.left + pixelRange.width / 2;

            ctx.font = iconFont;
            ctx.fillStyle = iconColor;
            ctx.fillText(segment.icon || '❓', centerX, axisY);

            if (segment.shortLabel) {
                ctx.font = labelFont;
                ctx.fillStyle = labelColor;
                ctx.fillText(segment.shortLabel, centerX, axisY + iconSize - 2);
            }
        });

        ctx.restore();
    }
};

function ensureTimelineModeIconPluginRegistered() {
    if (typeof Chart === 'undefined' || !Chart.register) {
        return;
    }

    if (!timelineModeIconPluginRegistered) {
        Chart.register(timelineModeIconPlugin);
        timelineModeIconPluginRegistered = true;
    }
}

function getModeSegmentPixelRange(meta, segment) {
    const elements = meta?.data || [];
    if (!elements.length) {
        return null;
    }

    const lastIndex = elements.length - 1;
    const startIndex = Math.max(0, Math.min(segment.startIndex, lastIndex));
    const endIndex = Math.max(0, Math.min(segment.endIndex, lastIndex));
    const startEl = elements[startIndex];
    const endEl = elements[endIndex];

    if (!startEl || !endEl) {
        return null;
    }

    const startWidth = startEl.width ?? 0;
    const endWidth = endEl.width ?? 0;
    const left = (startEl.x ?? 0) - startWidth / 2;
    const right = (endEl.x ?? 0) + endWidth / 2;
    const width = right - left;

    if (!isFinite(width) || width <= 0) {
        return null;
    }

    return {
        left,
        width
    };
}

function runWhenIdle(task, timeoutMs = 2000, fallbackDelayMs = 600) {
    if (typeof window.requestIdleCallback === 'function') {
        window.requestIdleCallback(() => task(), { timeout: timeoutMs });
        return;
    }
    setTimeout(task, fallbackDelayMs);
}

// Global Today Plan Tile instance
var todayPlanTileInstance = null;

/**
 * Render Today Plan Tile - live tracking of today's plan vs actual with EOD prediction
 * Event-driven refresh triggered by buildExtendedTimeline()
 */
function renderTodayPlanTile(tileSummary) {
    const container = document.getElementById('today-plan-tile-container');
    if (!container) {
        console.warn('[Today Plan Tile] Container not found - skipping render');
        return;
    }

    // Lazy load TodayPlanTile class if not already loaded
    if (typeof TodayPlanTile === 'undefined') {
        console.log('[Today Plan Tile] Loading module...');
        const script = document.createElement('script');
        script.type = 'module';
        script.src = '/local/oig_cloud/www/modules/today-plan-tile.js';
        script.onload = () => {
            console.log('[Today Plan Tile] Module loaded, rendering...');
            initTodayPlanTile(container, tileSummary);
        };
        script.onerror = () => {
            console.error('[Today Plan Tile] Failed to load module');
        };
        document.head.appendChild(script);
        return;
    }

    // Update existing instance or create new one
    if (todayPlanTileInstance) {
        console.log('[Today Plan Tile] Updating existing instance');
        todayPlanTileInstance.update(tileSummary);
    } else {
        console.log('[Today Plan Tile] Creating new instance');
        initTodayPlanTile(container, tileSummary);
    }
}

/**
 * Initialize Today Plan Tile instance
 * @param {HTMLElement} container - Container element
 * @param {object} tileSummary - Tile summary data from API
 */
function initTodayPlanTile(container, tileSummary) {
    try {
        todayPlanTileInstance = new TodayPlanTile(
            container,
            tileSummary,
            () => {
                // Click handler - open DNES tab in timeline dialog
                console.log('[Today Plan Tile] Opening timeline dialog with DNES tab');
                if (window.DashboardTimeline?.openTimelineDialog) {
                    window.DashboardTimeline.openTimelineDialog('today');
                }
            }
        );
        console.log('[Today Plan Tile] Instance created');
    } catch (error) {
        console.error('[Today Plan Tile] Failed to create instance:', error);
    }
}

// =============================================================================
// TIMELINE DIALOG - Clean Implementation
// =============================================================================

/**
 * TimelineDialog Class - manages the timeline popup dialog
 * Clean lifecycle: init → open → render → update → close → destroy
 */
class TimelineDialog {
    constructor() {
        this.dialogElement = null;
        this.isOpen = false;
        this.updateInterval = null;
        this.activeTab = 'today'; // Default tab - DNES
        this.plan = 'hybrid';
        this.cache = {
            hybrid: this.createEmptyCache()
        };
        this.plannerMode = 'hybrid';
        this.autoModeSwitchEnabled = null;
        this.autoSettingsLoaded = false;
        this.autoModeToggleBusy = false;
        this.autoModeToggleErrorTimeout = null;
        this.autoPlanSyncEnabled = true;
        this.activePlannerPlan = 'hybrid';  // Always hybrid
        this.compareCharts = {};
        this.timelineCharts = {};
        this.chartResizeObservers = new Map();
    }

    createEmptyCache() {
        return {
            yesterday: null,
            today: null,
            tomorrow: null,
            detail: null,
            history: null,
            compare: null
        };
    }

    resolvePlanFromMode(mode) {
        if (!mode) {
            return null;
        }
        return 'hybrid';
    }

    getPlanCache(plan = this.plan) {
        if (!this.cache[plan]) {
            this.cache[plan] = this.createEmptyCache();
        }
        return this.cache[plan];
    }

    setupAutoModeToggle() {
        const input = document.getElementById('auto-mode-toggle-input');
        if (!input || input.dataset.listenerAttached === '1') {
            return;
        }

        input.addEventListener('change', (event) => {
            this.handleAutoModeToggleChange(event.target.checked);
        });
        input.dataset.listenerAttached = '1';
    }

    setAutoModeToggleLoading(isLoading, message = null) {
        const container = document.getElementById('auto-mode-toggle');
        const statusEl = document.getElementById('auto-mode-toggle-status');
        const input = document.getElementById('auto-mode-toggle-input');
        if (!container || !statusEl || !input) {
            return;
        }

        container.classList.toggle('loading', isLoading);
        input.disabled = !!isLoading;
        if (isLoading && message) {
            statusEl.textContent = message;
            statusEl.classList.remove('enabled', 'disabled', 'error');
        }
    }

    updateAutoModeToggleUI() {
        const container = document.getElementById('auto-mode-toggle');
        const statusEl = document.getElementById('auto-mode-toggle-status');
        const input = document.getElementById('auto-mode-toggle-input');
        if (!container || !statusEl || !input) {
            return;
        }

        container.classList.remove('error');
        statusEl.classList.remove('error');

        if (this.autoModeSwitchEnabled === null) {
            statusEl.textContent = 'N/A';
            statusEl.classList.remove('enabled');
            statusEl.classList.add('disabled');
            input.checked = false;
            return;
        }

        const enabled = !!this.autoModeSwitchEnabled;
        input.checked = enabled;
        statusEl.textContent = enabled ? 'Zapnuto' : 'Vypnuto';
        statusEl.classList.toggle('enabled', enabled);
        statusEl.classList.toggle('disabled', !enabled);
    }

    showAutoModeToggleError(message) {
        const container = document.getElementById('auto-mode-toggle');
        const statusEl = document.getElementById('auto-mode-toggle-status');
        if (!container || !statusEl) {
            return;
        }

        container.classList.add('error');
        statusEl.classList.add('error');
        statusEl.textContent = message;

        if (this.autoModeToggleErrorTimeout) {
            clearTimeout(this.autoModeToggleErrorTimeout);
        }

        this.autoModeToggleErrorTimeout = setTimeout(() => {
            container.classList.remove('error');
            statusEl.classList.remove('error');
            this.updateAutoModeToggleUI();
            this.autoModeToggleErrorTimeout = null;
        }, 3000);
    }

    async requestPlannerSettings(method = 'GET', payload = null) {
        if (!window.INVERTER_SN) {
            throw new Error('Missing inverter serial number');
        }

        const endpoint = `oig_cloud/battery_forecast/${INVERTER_SN}/planner_settings`;
        const hass = typeof window !== 'undefined' && typeof window.getHass === 'function'
            ? window.getHass()
            : null;

        if (hass && typeof hass.callApi === 'function') {
            return hass.callApi(method, endpoint, method === 'GET' ? undefined : payload || {});
        }

        const headers = { 'Content-Type': 'application/json' };
        const token = window.DashboardAPI?.getHAToken?.();
        if (token) {
            headers.Authorization = `Bearer ${token}`;
        } else {
            console.warn('[TimelineDialog] HA token not available, relying on cookies for auth');
        }

        const response = await fetch(`/api/${endpoint}`, {
            method,
            headers,
            body: method === 'GET' ? undefined : JSON.stringify(payload || {}),
            credentials: 'same-origin'
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        return response.json();
    }

    async ensurePlannerSettingsLoaded(force = false) {
        const applyCurrentPreference = async () => {
            const resolvedPlan = this.activePlannerPlan || this.resolvePlanFromMode(this.plannerMode);
            const fallbackPlan = resolvedPlan || 'hybrid';

            let desiredPlan;
            if (this.autoModeSwitchEnabled) {
                desiredPlan = resolvedPlan || fallbackPlan;
            } else {
                desiredPlan = fallbackPlan;
            }

            await this.syncPlanWithAutoMode(desiredPlan);
        };

        if (this.autoSettingsLoaded && !force) {
            this.updateAutoModeToggleUI();
            await applyCurrentPreference();
            return;
        }

        if (!window.INVERTER_SN) {
            return;
        }

        this.setAutoModeToggleLoading(true, 'Načítám…');
        try {
            const data = await this.requestPlannerSettings('GET');
            this.autoModeSwitchEnabled = !!data.auto_mode_switch_enabled;
            if (data.planner_mode) {
                this.plannerMode = data.planner_mode;
            }
            this.activePlannerPlan = this.resolvePlanFromMode(this.plannerMode);
            this.autoSettingsLoaded = true;
            this.updateAutoModeToggleUI();
            await applyCurrentPreference();
        } catch (error) {
            console.error('[TimelineDialog] Failed to load planner settings', error);
            this.showAutoModeToggleError('Chyba načtení');
        } finally {
            this.setAutoModeToggleLoading(false);
        }
    }

    async handleAutoModeToggleChange(enabled) {
        if (this.autoModeToggleBusy || !window.INVERTER_SN) {
            return;
        }

        const previousValue = this.autoModeSwitchEnabled;
        this.autoModeToggleBusy = true;
        this.setAutoModeToggleLoading(true, 'Ukládám…');

        try {
            const payload = { auto_mode_switch_enabled: enabled };
            const data = await this.requestPlannerSettings('POST', payload);
            this.autoModeSwitchEnabled = !!data.auto_mode_switch_enabled;
            if (data.planner_mode) {
                this.plannerMode = data.planner_mode;
            }
            this.autoSettingsLoaded = true;
            const desiredPlan = 'hybrid';
            this.updateAutoModeToggleUI();
            await this.syncPlanWithAutoMode(desiredPlan);
        } catch (error) {
            console.error('[TimelineDialog] Failed to update planner settings', error);
            this.autoModeSwitchEnabled = previousValue;
            const input = document.getElementById('auto-mode-toggle-input');
            if (input) {
                input.checked = !!previousValue;
            }
            this.showAutoModeToggleError('Chyba uložení');
        } finally {
            this.setAutoModeToggleLoading(false);
            this.autoModeToggleBusy = false;
        }
    }

    async syncPlanWithAutoMode(desiredPlan) {
        if (!this.autoPlanSyncEnabled) {
            return;
        }
        if (!desiredPlan || this.plan === desiredPlan) {
            return;
        }

        console.log(`[TimelineDialog] Syncing plan view to active mode: ${desiredPlan}`);
        await this.switchPlan(desiredPlan, { origin: 'auto', forceRefresh: true });
    }

    /**
     * Initialize dialog - called once on page load
     */
    init() {
        this.dialogElement = document.getElementById('mode-timeline-dialog');
        if (!this.dialogElement) {
            console.error('[TimelineDialog] Dialog element not found');
            return;
        }

        // Attach event listeners
        this.attachEventListeners();

        // Prefetch data for all tabs (proactive caching)
        this.prefetchAllTabs();

        console.log('[TimelineDialog] Initialized');
    }

    /**
     * Prefetch data for all tabs (called on init, not on open)
     */
    prefetchAllTabs() {
        runWhenIdle(async () => {
            console.log('[TimelineDialog] Prefetching all tab data...');

            try {
                let defaultPlan = 'hybrid';
                if (window.PlannerState) {
                    try {
                        defaultPlan = await window.PlannerState.getDefaultPlan();
                    } catch (error) {
                        console.warn('[TimelineDialog] Failed to resolve default plan for prefetch', error);
                    }
                }
                await this.loadAllTabsData(false, defaultPlan);
                console.log('[TimelineDialog] Prefetch complete');
            } catch (error) {
                console.warn('[TimelineDialog] Prefetch failed:', error);
            }
        }, 2500, 900);
    }

    /**
     * Load all tabs data in ONE API call (more efficient)
     */
    async loadAllTabsData(forceRefresh = false, planOverride = null) {
        const plan = planOverride || this.plan;
        const planCache = this.getPlanCache(plan);

        if (!forceRefresh && planCache.yesterday && planCache.today && planCache.tomorrow) {
            console.log(`[TimelineDialog] All tabs already cached for plan ${plan}`);
            return;
        }

        console.log(`[TimelineDialog] Loading ALL tabs data for plan ${plan}...`);

        try {
            const apiUrl = `/api/oig_cloud/battery_forecast/${INVERTER_SN}/detail_tabs?plan=${plan}`;
            const response = await fetchWithAuth(apiUrl);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();

            if (!data) {
                throw new Error('No data returned from detail_tabs');
            }

            ['yesterday', 'today', 'tomorrow', 'history', 'detail'].forEach(dayType => {
                if (data[dayType]) {
                    planCache[dayType] = data[dayType];
                    console.log(
                        `[TimelineDialog] Cached ${dayType} data for plan ${plan}:`,
                        planCache[dayType]
                    );
                } else {
                    planCache[dayType] = null;
                }
            });
        } catch (error) {
            console.error(`[TimelineDialog] Failed to load tabs data for plan ${plan}:`, error);
            this.cache[plan] = this.createEmptyCache();
        }
    }

    /**
     * Attach event listeners to dialog controls
     */
    attachEventListeners() {
        // Tab buttons
        const tabButtons = this.dialogElement.querySelectorAll('.timeline-tab-btn');
        tabButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const tab = e.currentTarget.dataset.tab;
                this.switchTab(tab);
            });
        });

        const planButtons = this.dialogElement.querySelectorAll('.plan-toggle-btn');
        planButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                const plan = btn.dataset.plan || 'hybrid';
                this.switchPlan(plan, { origin: 'manual' });
            });
        });

        // Close button
        const closeBtn = this.dialogElement.querySelector('.close-timeline-dialog');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.close());
        }

        // Click outside to close
        this.dialogElement.addEventListener('click', (e) => {
            if (e.target === this.dialogElement) {
                this.close();
            }
        });

        this.setupAutoModeToggle();
    }

    /**
     * Open dialog and load data
     */
    async open(tabName = null, planOverride = null) {
        if (this.isOpen) {
            console.log('[TimelineDialog] Already open');
            return;
        }

        console.log('[TimelineDialog] Opening...');
        this.isOpen = true;
        this.dialogElement.style.display = 'flex';

        if (tabName) {
            this.activeTab = tabName;
        }

        this.autoPlanSyncEnabled = !planOverride;
        if (planOverride && planOverride !== this.plan) {
            this.plan = planOverride;
        }
        this.updatePlanButtons();
        await this.ensurePlannerSettingsLoaded(false);

        // Load all tabs data in ONE API call if not cached
        const planCache = this.getPlanCache(this.plan);
        if (!planCache.yesterday || !planCache.today || !planCache.tomorrow) {
            console.log('[TimelineDialog] Loading missing tabs...');
            await this.loadAllTabsData(false, this.plan);
        }

        // Switch to active tab (this will render + set CSS classes)
        this.switchTab(this.activeTab);

        // Start update interval (refresh every 60s)
        this.startUpdateInterval();
    }

    /**
     * Close dialog and cleanup
     */
    close() {
        console.log('[TimelineDialog] Closing...');
        this.isOpen = false;
        this.dialogElement.style.display = 'none';

        // Stop update interval
        this.stopUpdateInterval();
        this.destroyCompareCharts();
        Object.values(this.timelineCharts).forEach((chart) => {
            if (chart && typeof chart.destroy === 'function') {
                chart.destroy();
            }
        });
        this.timelineCharts = {};
        this.chartResizeObservers.forEach((observer) => observer.disconnect());
        this.chartResizeObservers.clear();
        this.autoPlanSyncEnabled = true;
        this.syncPlanWithAutoMode('hybrid');
    }

    /**
     * Load data for specific tab from API
     */
    async loadTabData(dayType, forceRefresh = false, planOverride = null) {
        const plan = planOverride || this.plan;
        const planCache = this.getPlanCache(plan);

        // Check cache first (unless forced refresh)
        if (!forceRefresh && planCache[dayType]) {
            console.log(`[TimelineDialog] Using cached ${dayType} data`);
            return;
        }

        console.log(`[TimelineDialog] Loading ${dayType} data...`);

        try {
            const apiUrl = `/api/oig_cloud/battery_forecast/${INVERTER_SN}/detail_tabs?tab=${dayType}&plan=${plan}`;
            const response = await fetchWithAuth(apiUrl);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();

            if (!data) {
                throw new Error('No data returned from detail_tabs');
            }

            // Extract the specific day data from response
            // API returns: { "today": { "date": "...", "mode_blocks": [...], "summary": {...} } }
            const dayData = data[dayType];
            if (!dayData) {
                throw new Error(`No data for ${dayType} in response`);
            }

            // Cache the day-specific data
            planCache[dayType] = dayData;
            console.log(`[TimelineDialog] ${dayType} data loaded for plan ${plan}:`, planCache[dayType]);

            // Extra debug
            if (planCache[dayType]?.mode_blocks) {
                console.log(`[TimelineDialog] ${dayType} mode_blocks count: ${planCache[dayType].mode_blocks.length}`);
                if (planCache[dayType].mode_blocks.length > 0) {
                    console.log(`[TimelineDialog] First block:`, JSON.stringify(planCache[dayType].mode_blocks[0], null, 2));
                }
            }
        } catch (error) {
            console.error(`[TimelineDialog] Failed to load ${dayType} data:`, error);
            planCache[dayType] = null;
        }
    }

    /**
     * Switch to different tab
     */
    switchTab(dayType) {
        console.log(`[TimelineDialog] Switching to ${dayType} tab`);

        // Update active tab
        this.activeTab = dayType;

        // Update tab buttons visual state
        const tabButtons = this.dialogElement.querySelectorAll('.timeline-tab-btn');
        console.log(`[TimelineDialog] Found ${tabButtons.length} tab buttons`);
        tabButtons.forEach(btn => {
            if (btn.dataset.tab === dayType) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        // Update tab content visibility
        const allTabContents = this.dialogElement.querySelectorAll('.timeline-tab-content');
        console.log(`[TimelineDialog] Found ${allTabContents.length} tab contents`);
        allTabContents.forEach(content => {
            content.classList.remove('active');
        });

        const activeContent = document.getElementById(`timeline-${dayType}-content`);
        console.log(`[TimelineDialog] Active content element:`, activeContent);
        if (activeContent) {
            activeContent.classList.add('active');
            console.log(`[TimelineDialog] Added 'active' class to timeline-${dayType}-content`);
        }

        // Render the tab
        this.renderTab(dayType);
    }

    async switchPlan(plan, options = {}) {
        if (!plan) {
            return;
        }

        const origin = options.origin || 'manual';
        const forceRefresh = options.forceRefresh !== undefined ? options.forceRefresh : true;

        if (!forceRefresh && plan === this.plan) {
            return;
        }

        if (origin === 'manual') {
            this.autoPlanSyncEnabled = false;
        }

        this.plan = plan;
        this.updatePlanButtons();

        if (forceRefresh) {
            this.cache[plan] = this.createEmptyCache();
        }

        await this.loadAllTabsData(forceRefresh, plan);
        this.renderTab(this.activeTab);

        if (origin === 'manual' && this.autoModeSwitchEnabled) {
            await this.updateAutoModePlanPreference(plan);
        }
    }

    updatePlanButtons() {
        const planButtons = this.dialogElement?.querySelectorAll('.plan-toggle-btn');
        planButtons?.forEach(btn => {
            const isActive = btn.dataset.plan === this.plan;
            if (isActive) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
    }

    /**
     * Render specific tab based on dayType
     */
    renderTab(dayType) {
        console.log(`[TimelineDialog] Rendering ${dayType} tab`);

        const planCache = this.getPlanCache();
        const containerId = `${dayType}-timeline-container`;
        const container = document.getElementById(containerId);

        if (!container) {
            console.error(`[TimelineDialog] Container ${containerId} not found`);
            return;
        }

        if (dayType === 'compare') {
            const yesterdayData = planCache.yesterday;
            const todayData = planCache.today;
            if (
                !yesterdayData ||
                !todayData ||
                !Array.isArray(yesterdayData.intervals) ||
                !Array.isArray(todayData.intervals)
            ) {
                container.innerHTML = this.renderNoData(dayType);
                return;
            }

            container.innerHTML = this.renderCompareTab(yesterdayData, todayData);
            this.initializeCompareCharts(yesterdayData, todayData);
            return;
        }

        const data = planCache[dayType];
        if (!data || !data.mode_blocks || data.mode_blocks.length === 0) {
            container.innerHTML = this.renderNoData(dayType);
            return;
        }

        // Render based on tab type
        if (dayType === 'yesterday') {
            container.innerHTML = this.renderYesterdayTab(data);
            // Charts will be added later if needed
        } else if (dayType === 'today') {
            container.innerHTML = this.renderTodayTab(data);
            // Charts will be added later if needed
        } else if (dayType === 'tomorrow') {
            container.innerHTML = this.renderTomorrowTab(data);
        } else if (dayType === 'history') {
            container.innerHTML = this.renderHistoryTab(data);
        }
    }

    scheduleChartResize(chart, canvas) {
        if (!chart || !canvas) {
            return;
        }

        const resize = () => {
            try {
                chart.resize();
            } catch (err) {
                // Ignore resize errors when chart is being destroyed
            }
        };

        if (typeof window.requestAnimationFrame === 'function') {
            window.requestAnimationFrame(() => {
                resize();
                window.requestAnimationFrame(resize);
            });
        } else {
            setTimeout(resize, 50);
        }

        if (typeof ResizeObserver !== 'undefined') {
            const container = canvas.parentElement;
            if (container && !this.chartResizeObservers.has(canvas)) {
                const observer = new ResizeObserver(() => resize());
                observer.observe(container);
                this.chartResizeObservers.set(canvas, observer);
            }
        }
    }

    /**
     * Render "No Data" message
     */
    renderNoData(dayType) {
        const messages = {
            yesterday: 'Včerejší data nejsou k dispozici',
            today: 'Dnešní data nejsou k dispozici',
            tomorrow: 'Plán pro zítřek ještě není k dispozici',
            history: 'Historická data nejsou k dispozici',
            compare: 'Srovnání 48h zatím není k dispozici'
        };

        return `
            <div class="no-data" style="padding: 60px 20px; text-align: center;">
                <div style="font-size: 3em; margin-bottom: 20px;">📊</div>
                <h3 style="color: var(--text-secondary); margin-bottom: 10px;">
                    ${messages[dayType] || 'Data nejsou k dispozici'}
                </h3>
            </div>
        `;
    }
    /**
     * Render VČERA tab - Plan vs Actual comparison
     * FÁZE 6: Now using Detail Tabs API data (mode_blocks)
     */
    renderYesterdayTab(data) {
        const { mode_blocks, summary } = data;

        if (!mode_blocks || mode_blocks.length === 0) {
            return this.renderNoData('yesterday');
        }

        // Check if we have any planned data
        const hasPlannedData = mode_blocks.some(b => b.mode_planned && b.mode_planned !== 'Unknown');

        return `
            ${this.renderDetailTabHeader(summary, 'Včera')}

            <!-- Collapsible section for all blocks -->
            <div class="collapsible-section">
                <div class="section-header" onclick="this.parentElement.classList.toggle('expanded')">
                    <div class="section-title">
                        <span class="section-icon">📊</span>
                        <span class="section-name">Režimy a náklady</span>
                        <span class="section-badge">${mode_blocks.length} bloků</span>
                    </div>
                    <div class="section-summary">
                        <span class="summary-item">💰 ${summary.total_cost?.toFixed(2) || '0.00'} Kč</span>
                        <span class="summary-item">📊 ${summary.overall_adherence?.toFixed(1) || '0'}% shoda</span>
                        <span class="expand-icon">▼</span>
                    </div>
                </div>
                <div class="section-content">
                    ${this.renderModeBlocks(mode_blocks, { showCosts: true, showAdherence: true })}
                </div>
            </div>

            ${!hasPlannedData ? '<div class="no-plan-notice"><p>ℹ️ Pro tento den nebyl dostupný plán, zobrazena pouze skutečnost.</p></div>' : ''}
        `;
    }

    /**
     * Render VČERA header from BE data (FÁZE 2)
     */
    renderYesterdayHeaderBE(summary) {
        const plannedCost = summary.plan_total_cost || 0;
        const actualCost = summary.actual_total_cost || 0;
        const deltaCost = summary.delta || 0;
        const deltaPercent = summary.vs_plan_pct || 0;
        const modeAdherence = summary.mode_adherence_pct || 0;

        // Calculate total intervals from mode_groups
        const totalIntervals = summary.mode_groups?.reduce((sum, g) => sum + (g.interval_count || 0), 0) || 96;
        const totalMatches = summary.mode_groups?.reduce((sum, g) => sum + (g.mode_matches || 0), 0) || 0;

        return `
            <div class="today-header-cards">
                <div class="header-progress-large">
                    <div class="progress-bar-gradient">
                        <div class="progress-fill-gradient" style="width: ${modeAdherence}%"></div>
                        <div class="progress-label-overlay">${modeAdherence.toFixed(0)}% shoda režimů</div>
                    </div>
                </div>

                <div class="metric-cards-grid">
                    <div class="metric-card card-completed">
                        <div class="card-header">
                            <span class="card-icon">💰</span>
                            <span class="card-title">Plán</span>
                        </div>
                        <div class="card-body">
                            <div class="card-main-value">${plannedCost.toFixed(2)} Kč</div>
                            <div class="card-details">
                                <span class="detail-item">${totalIntervals} intervalů</span>
                            </div>
                        </div>
                    </div>

                    <div class="metric-card card-active">
                        <div class="card-header">
                            <span class="card-icon">💸</span>
                            <span class="card-title">Skutečnost</span>
                        </div>
                        <div class="card-body">
                            <div class="card-main-value">${actualCost.toFixed(2)} Kč</div>
                            <div class="card-details">
                                <span class="detail-item">režimy OK ${totalMatches}/${totalIntervals}</span>
                            </div>
                        </div>
                    </div>

                    <div class="metric-card card-eod">
                        <div class="card-header">
                            <span class="card-icon">📊</span>
                            <span class="card-title">Výsledek</span>
                        </div>
                        <div class="card-body">
                            <div class="card-main-value">${deltaCost > 0 ? '+' : ''}${deltaCost.toFixed(2)} Kč</div>
                            <div class="card-details">
                                <span class="detail-separator">•</span>
                                <span class="detail-delta ${deltaPercent < -2 ? 'positive' : deltaPercent > 2 ? 'negative' : 'neutral'}">
                                    ${deltaPercent > 0 ? '+' : ''}${deltaPercent.toFixed(1)}%
                                </span>
                                <span class="detail-separator">•</span>
                                <span class="detail-item">${deltaCost < 0 ? 'lepší' : deltaCost > 0 ? 'horší' : 'na plánu'}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Render mode groups from BE data (FÁZE 2)
     */
    renderYesterdayModeGroupsBE(groups) {
        if (!groups || groups.length === 0) {
            return '<div class="interval-section"><p>Žádné skupiny</p></div>';
        }

        const modeIcons = {
            'HOME I': '🏠',
            'HOME II': '⚡',
            'HOME III': '🔋',
            'HOME UPS': '⚡'
        };

        const rows = groups.map(group => {
            const delta = group.delta || 0;
            const deltaClass = delta < -0.5 ? 'positive' : delta > 0.5 ? 'negative' : 'neutral';
            const icon = modeIcons[group.mode] || '🎯';
            const adherence = group.adherence_pct || 0;

            return `
                <div class="interval-section">
                    <div class="section-header">
                        <span class="section-icon">${icon}</span>
                        <span class="section-title">${group.mode}</span>
                        <span class="section-meta">
                            <span class="meta-item">⏱️ ${group.interval_count}×15min</span>
                            <span class="meta-item">💰 ${group.actual_cost.toFixed(2)} Kč</span>
                            <span class="meta-item ${deltaClass}">△ ${delta > 0 ? '+' : ''}${delta.toFixed(2)} Kč</span>
                            <span class="meta-item">✅ ${adherence.toFixed(0)}% shoda</span>
                        </span>
                    </div>
                </div>
            `;
        }).join('');

        return rows;
    }

    /**
     * Render top variances from BE data (FÁZE 2)
     */
    renderTopVariancesBE(variances) {
        if (!variances || variances.length === 0) {
            return '';
        }

        const rows = variances.map((v, idx) => {
            const deltaClass = v.variance < 0 ? 'positive' : 'negative';
            const icon = v.variance < 0 ? '✅' : '❌';

            return `
                <div class="variance-row">
                    <span class="variance-rank">#${idx + 1}</span>
                    <span class="variance-time">${v.time}</span>
                    <span class="variance-planned">Plán: ${v.planned} Kč</span>
                    <span class="variance-actual">Skutečnost: ${v.actual} Kč</span>
                    <span class="variance-delta ${deltaClass}">${icon} ${v.variance > 0 ? '+' : ''}${v.variance} Kč (${v.variance_pct > 0 ? '+' : ''}${v.variance_pct}%)</span>
                </div>
            `;
        }).join('');

        return `
            <div class="interval-section collapsible collapsed">
                <div class="section-header" onclick="toggleSection('top-variances-be')">
                    <span class="section-icon">📊</span>
                    <span class="section-title">TOP 3 ODCHYLKY</span>
                    <span class="section-toggle">▶</span>
                </div>
                <div class="interval-list" id="top-variances-be" style="display: none;">
                    ${rows}
                </div>
            </div>
        `;
    }

    /**
     * Render card-based header for VČERA tab (v2.2 Dark) - FE fallback
     */
    renderYesterdayHeader(summary) {
        const plannedCost = summary?.planned_total_cost || 0;
        const actualCost = summary?.actual_total_cost || 0;
        const deltaCost = actualCost - plannedCost;
        const deltaPercent = plannedCost > 0 ? ((deltaCost / plannedCost) * 100) : 0;

        const modeAdherence = summary?.mode_adherence_pct || 0;
        const modeMatches = summary?.mode_matches || 0;
        const totalIntervals = summary?.total_intervals || 96;

        return `
            <div class="today-header-cards">
                <div class="header-progress-large">
                    <div class="progress-bar-gradient">
                        <div class="progress-fill-gradient" style="width: ${modeAdherence}%"></div>
                        <div class="progress-label-overlay">${modeAdherence.toFixed(0)}% shoda režimů</div>
                    </div>
                </div>

                <div class="metric-cards-grid">
                    <div class="metric-card card-completed">
                        <div class="card-header">
                            <span class="card-icon">💰</span>
                            <span class="card-title">Plán</span>
                        </div>
                        <div class="card-body">
                            <div class="card-main-value">${plannedCost.toFixed(2)} Kč</div>
                            <div class="card-details">
                                <span class="detail-item">${totalIntervals} intervalů</span>
                            </div>
                        </div>
                    </div>

                    <div class="metric-card card-active">
                        <div class="card-header">
                            <span class="card-icon">💸</span>
                            <span class="card-title">Skutečnost</span>
                        </div>
                        <div class="card-body">
                            <div class="card-main-value">${actualCost.toFixed(2)} Kč</div>
                            <div class="card-details">
                                <span class="detail-item">režimy OK ${modeMatches}/${totalIntervals}</span>
                            </div>
                        </div>
                    </div>

                    <div class="metric-card card-eod">
                        <div class="card-header">
                            <span class="card-icon">📊</span>
                            <span class="card-title">Výsledek</span>
                        </div>
                        <div class="card-body">
                            <div class="card-main-value">${deltaCost > 0 ? '+' : ''}${deltaCost.toFixed(2)} Kč</div>
                            <div class="card-details">
                                <span class="detail-separator">•</span>
                                <span class="detail-delta ${deltaPercent < -2 ? 'positive' : deltaPercent > 2 ? 'negative' : 'neutral'}">
                                    ${deltaPercent > 0 ? '+' : ''}${deltaPercent.toFixed(1)}%
                                </span>
                                <span class="detail-separator">•</span>
                                <span class="detail-item">${deltaCost < 0 ? 'lepší' : deltaCost > 0 ? 'horší' : 'na plánu'}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Render interval analysis for VČERA tab - grouped by mode with variance details
     */
    renderYesterdayIntervalAnalysis(intervals) {
        // Group intervals by mode (both planned and actual)
        const modeGroups = {};

        intervals.forEach(interval => {
            const plannedMode = interval.planned?.mode_name || 'Unknown';
            const actualMode = interval.actual?.mode_name || 'Unknown';

            if (!modeGroups[plannedMode]) {
                modeGroups[plannedMode] = {
                    mode: plannedMode,
                    intervals: [],
                    totalPlanned: 0,
                    totalActual: 0,
                    matchCount: 0,
                    mismatchCount: 0
                };
            }

            const costPlanned = interval.planned?.net_cost || 0;
            const costActual = interval.actual?.net_cost || 0;
            const matched = plannedMode === actualMode;

            modeGroups[plannedMode].intervals.push(interval);
            modeGroups[plannedMode].totalPlanned += costPlanned;
            modeGroups[plannedMode].totalActual += costActual;
            if (matched) modeGroups[plannedMode].matchCount++;
            else modeGroups[plannedMode].mismatchCount++;
        });        // Sort by total cost (highest first)
        const sortedGroups = Object.values(modeGroups).sort((a, b) => b.totalPlanned - a.totalPlanned);

        const modeEmojis = {
            'Balancer': '⚖️',
            'PV_to_Grid': '☀️',
            'Grid_Charging': '🔌',
            'Export_Peak': '📤',
            'Import_Only': '📥',
            'Self_Consumption': '🔋'
        };

        const groupsHtml = sortedGroups.map(group => {
            const delta = group.totalActual - group.totalPlanned;
            const adherence = group.intervals.length > 0 ? (group.matchCount / group.intervals.length * 100) : 0;
            const deltaPercent = group.totalPlanned > 0 ? (delta / group.totalPlanned * 100) : 0;
            const emoji = modeEmojis[group.mode] || '🎯';

            return `
                <div class="interval-group">
                    <div class="interval-group-header">
                        <div class="interval-group-mode">
                            <span class="mode-emoji">${emoji}</span>
                            <span class="mode-name">${group.mode}</span>
                            <span class="mode-count">${group.intervals.length} intervalů</span>
                        </div>
                        <div class="interval-group-stats">
                            <div class="stat-item">
                                <span class="stat-label">Plán:</span>
                                <span class="stat-value">${group.totalPlanned.toFixed(2)} Kč</span>
                            </div>
                            <div class="stat-item">
                                <span class="stat-label">Skutečnost:</span>
                                <span class="stat-value">${group.totalActual.toFixed(2)} Kč</span>
                            </div>
                            <div class="stat-item ${delta < 0 ? 'positive' : delta > 0 ? 'negative' : 'neutral'}">
                                <span class="stat-label">Delta:</span>
                                <span class="stat-value">${delta > 0 ? '+' : ''}${delta.toFixed(2)} Kč (${deltaPercent > 0 ? '+' : ''}${deltaPercent.toFixed(1)}%)</span>
                            </div>
                            <div class="stat-item ${adherence >= 80 ? 'positive' : adherence >= 50 ? 'neutral' : 'negative'}">
                                <span class="stat-label">Shoda režimů:</span>
                                <span class="stat-value">${adherence.toFixed(0)}% (${group.matchCount}/${group.intervals.length})</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        return `
            <div class="yesterday-interval-analysis">
                <h4>📋 Analýza intervalů podle režimů</h4>
                <div class="interval-groups">
                    ${groupsHtml}
                </div>
            </div>
        `;
    }

    /**
     * FÁZE 6.1: Render Detail Tab Header
     * Přináší metriky (cost/solar/consumption/grid) srovnání plán vs. realita.
     */
    renderDetailTabHeader(summary, tabName) {
        if (!summary) {
            return '';
        }

        const { overall_adherence, mode_switches } = summary;
        const metrics = summary.metrics || {};

        // Adherence color coding
        let adherenceColor = '#888'; // Gray default
        let adherenceIcon = '📊';
        if (typeof overall_adherence === 'number') {
            if (overall_adherence >= 80) {
                adherenceColor = '#4CAF50'; // Green
                adherenceIcon = '✅';
            } else if (overall_adherence >= 50) {
                adherenceColor = '#FF9800'; // Orange
                adherenceIcon = '⚠️';
            } else {
                adherenceColor = '#F44336'; // Red
                adherenceIcon = '❌';
            }
        }

        const metricTiles = [
            this.renderSummaryMetricTile(metrics.cost, '💰', 'Náklady', 'cost'),
            this.renderSummaryMetricTile(metrics.solar, '☀️', 'Solární výroba', 'solar'),
            this.renderSummaryMetricTile(metrics.consumption, '🏠', 'Spotřeba', 'consumption'),
            this.renderSummaryMetricTile(metrics.grid, '⚡', 'Odběr ze sítě', 'grid'),
        ]
            .filter(Boolean)
            .join('');

        const metaInfo =
            typeof overall_adherence === 'number'
                ? `
                    <div class="summary-meta-compact">
                        <span class="meta-item">${overall_adherence.toFixed(0)}% shoda</span>
                        <span class="meta-separator">|</span>
                        <span class="meta-item">${mode_switches || 0} přepnutí</span>
                    </div>
                `
                : '';

        return `
            <div class="summary-tiles-smart">
                ${metricTiles}
            </div>
            ${metaInfo}
        `;
    }

    /**
     * Helper: render single metric tile (plan vs actual)
     */
    renderSummaryMetricTile(metric, icon, label, metricKey) {
        if (!metric) {
            return '';
        }

        const unit = metric.unit || '';
        const plan = Number(metric.plan ?? 0);
        const hasActual =
            metric.has_actual && metric.actual !== null && metric.actual !== undefined;
        const actual = hasActual ? Number(metric.actual) : null;

        const mainValue = hasActual ? actual : plan;
        const mainLabel = hasActual ? 'Skutečnost' : 'Plán';

        const planRow = hasActual
            ? `
                <div class="tile-sub-row">
                    <span>Plán:</span>
                    <span>${this.formatMetricValue(plan)} ${unit}</span>
                </div>
            `
            : '';

        const hintRow = !hasActual
            ? `
                <div class="tile-sub-row hint-row">
                    Plánovaná hodnota (čeká na živá data)
                </div>
            `
            : '';

        let deltaRow = '';
        if (hasActual) {
            const delta = (actual ?? 0) - plan;
            const absDelta = Math.abs(delta);

            const contextInfo = this.getMetricContext(delta, metricKey);
            const deltaClassMap = {
                'metric-context--positive': 'delta-better',
                'metric-context--negative': 'delta-worse',
                'metric-context--neutral': 'delta-neutral',
            };
            const deltaClass = deltaClassMap[contextInfo.className] || 'delta-neutral';
            const deltaValueText =
                absDelta >= 0.01
                    ? `${delta > 0 ? '+' : ''}${this.formatMetricValue(delta)} ${unit}`
                    : '±0';

            deltaRow = `
                <div class="tile-delta ${deltaClass}">
                    <span>${contextInfo.text}</span>
                    <span>${deltaValueText}</span>
                </div>
            `;
        }

        const supplemental = [planRow, hintRow, deltaRow].filter(Boolean).join('');

        return `
            <div class="summary-tile-smart">
                <div class="tile-header">
                    <div class="tile-title">
                        <span class="tile-icon">${icon}</span>
                        <span class="tile-label">${label}</span>
                    </div>
                    <span class="tile-value-label">${mainLabel}</span>
                </div>
                <div class="tile-value-big">
                    ${this.formatMetricValue(mainValue)} <span class="unit">${unit}</span>
                </div>
                ${supplemental}
            </div>
        `;
    }

    getMetricContext(delta, metricKey) {
        const preferences = {
            cost: 'lower',
            solar: 'higher',
            consumption: 'lower',
            grid: 'lower',
        };

        const preference = preferences[metricKey] || 'lower';

        if (delta === null) {
            return { text: 'Na plánu', className: 'metric-context--neutral' };
        }

        if (Math.abs(delta) < 0.001) {
            return { text: 'Na plánu', className: 'metric-context--neutral' };
        }

        const isBetter =
            preference === 'higher' ? delta > 0 : preference === 'lower' ? delta < 0 : false;

        return {
            text: isBetter ? 'Lépe než plán' : 'Hůře než plán',
            className: isBetter ? 'metric-context--positive' : 'metric-context--negative',
        };
    }

    formatMetricValue(value) {
        const num = Number(value);
        if (!Number.isFinite(num)) {
            return '0.00';
        }

        const abs = Math.abs(num);
        if (abs >= 1000) {
            return num.toFixed(0);
        }
        if (abs >= 100) {
            return num.toFixed(1);
        }
        return num.toFixed(2);
    }

    /**
     * FÁZE 6: Render Mode Blocks from Detail Tabs API
     */
    renderModeBlocks(blocks, options = {}) {
        if (!blocks || blocks.length === 0) {
            return '<div class="no-mode-blocks"><p>Žádné mode bloky k dispozici</p></div>';
        }

        const blocksHtml = blocks.map((block, index) => {
            const {
                mode_historical,
                mode_planned,
                mode_match,
                status,
                start_time,
                end_time,
                duration_hours,
                cost_historical,
                cost_planned,
                cost_delta,
                adherence_pct,
                solar_total_kwh,
                consumption_total_kwh,
                grid_import_total_kwh,
                grid_export_total_kwh,
                interval_reasons
            } = block;

            // Get mode config
            const historicalMode = MODE_CONFIG[mode_historical] || { icon: '❓', color: 'rgba(158, 158, 158, 0.5)', label: mode_historical };
            const plannedMode = MODE_CONFIG[mode_planned] || { icon: '❓', color: 'rgba(158, 158, 158, 0.5)', label: mode_planned };
            const hasActualMode = Boolean(mode_historical && mode_historical !== 'Unknown' && status !== 'planned');
            const hasPlannedMode = Boolean(mode_planned && mode_planned !== 'Unknown');
            const plannedOnly = !hasActualMode && hasPlannedMode;

            // Status icon
            const statusIcons = {
                completed: '✅',
                current: '▶️',
                planned: '📅'
            };
            const statusIcon = statusIcons[status] || '❓';

            // Match indicator
            const matchClass = mode_match ? 'match-yes' : 'match-no';
            const matchIcon = mode_match ? '✅' : '❌';
            const matchLabel = mode_match ? 'Shoda' : 'Odchylka';

            // Cost delta indicator
            let costDeltaHtml = '';
            if (cost_delta !== null && cost_delta !== undefined) {
                const deltaClass = cost_delta > 0 ? 'cost-higher' : cost_delta < 0 ? 'cost-lower' : 'cost-equal';
                const deltaIcon = cost_delta > 0 ? '⬆️' : cost_delta < 0 ? '⬇️' : '➡️';
                costDeltaHtml = `
                    <span class="cost-delta ${deltaClass}">
                        ${deltaIcon} ${cost_delta > 0 ? '+' : ''}${cost_delta.toFixed(2)} Kč
                    </span>
                `;
            }

            const reasonsHtml = this.renderIntervalReasons(interval_reasons, status);

            return `
                <div class="mode-block ${matchClass}" data-index="${index}">
                    <!-- Header -->
                    <div class="block-header">
                        <div class="block-time">
                            ${statusIcon} ${start_time} - ${end_time}
                            <span class="block-duration">(${duration_hours?.toFixed(1)}h)</span>
                        </div>
                        <div class="block-match ${matchClass}">
                            ${matchIcon} ${matchLabel}
                        </div>
                    </div>

                    <!-- Single-line layout (aligned with detail-tabs.js) -->
                    <div class="block-content-row">
                        <!-- Režim -->
                        <div class="block-item">
                            <span class="item-label">${plannedOnly ? 'Plán:' : 'Skutečnost/Plán:'}</span>
                            <div class="item-value">
                                ${hasActualMode ? `<span class="mode-badge" style="background: ${historicalMode.color};">${historicalMode.icon} ${historicalMode.label}</span>` : ''}
                                ${hasActualMode && hasPlannedMode ? `
                                <span class="mode-arrow">→</span>
                                <span class="mode-badge mode-planned" style="background: ${plannedMode.color};">${plannedMode.icon} ${plannedMode.label}</span>
                                ` : (!hasActualMode && hasPlannedMode ? `
                                <span class="mode-badge mode-planned" style="background: ${plannedMode.color};">${plannedMode.icon} ${plannedMode.label}</span>
                                ` : '')}
                            </div>
                        </div>

                        <!-- Náklady -->
                        <div class="block-item">
                            <span class="item-label">Cena (skutečná/plán):</span>
                            <div class="item-value">
                                <span class="cost-actual">${cost_historical?.toFixed(2) || 'N/A'} Kč</span>
                                ${cost_planned !== null && cost_planned !== undefined ? `
                                <span class="cost-arrow">→</span>
                                <span class="cost-planned">${cost_planned.toFixed(2)} Kč</span>
                                ${costDeltaHtml}
                                ` : ''}
                            </div>
                        </div>

                        <!-- Solár -->
                        <div class="block-item">
                            <span class="item-label">☀️ Solár:</span>
                            <div class="item-value">${solar_total_kwh?.toFixed(2) || '0.00'} kWh</div>
                        </div>

                        <!-- Spotřeba -->
                        <div class="block-item">
                            <span class="item-label">🏠 Spotřeba:</span>
                            <div class="item-value">${consumption_total_kwh?.toFixed(2) || '0.00'} kWh</div>
                        </div>

                        <!-- Import -->
                        <div class="block-item">
                            <span class="item-label">⬇️ Import:</span>
                            <div class="item-value">${grid_import_total_kwh?.toFixed(2) || '0.00'} kWh</div>
                        </div>

                        <!-- Export -->
                        <div class="block-item">
                            <span class="item-label">⬆️ Export:</span>
                            <div class="item-value">${grid_export_total_kwh?.toFixed(2) || '0.00'} kWh</div>
                        </div>

                        ${reasonsHtml}
                    </div>
                </div>
            `;
        }).join('');

        return blocksHtml;
    }

    formatReasonTime(isoTs) {
        if (!isoTs) {
            return '--:--';
        }
        try {
            const fmt = new Intl.DateTimeFormat('cs-CZ', {
                hour: '2-digit',
                minute: '2-digit'
            });
            const dt = new Date(isoTs);
            if (Number.isNaN(dt.getTime())) {
                return isoTs;
            }
            return fmt.format(dt);
        } catch (err) {
            return isoTs;
        }
    }

    renderIntervalReasons(intervalReasons, status) {
        if (!intervalReasons || intervalReasons.length === 0) {
            return '';
        }

        const items = intervalReasons.map(item => {
            const timeLabel = this.formatReasonTime(item.time);
            return `<div class="reason-line"><span class="reason-time">${timeLabel}</span>${item.reason}</div>`;
        }).join('');

        return `
            <div class="block-item block-reasons">
                <span class="item-label">🧠 Důvod${status === 'completed' ? ' (plán)' : ''}:</span>
                <div class="item-value reason-list">
                    ${items}
                </div>
            </div>
        `;
    }

    /**
     * Render DNES tab - Live tracking + EOD prediction
     */
    renderTodayTab(data) {
        const { mode_blocks, summary } = data;

        if (!mode_blocks || mode_blocks.length === 0) {
            return this.renderNoData('today');
        }

        // Split into completed, current, and planned blocks
        const completedBlocks = mode_blocks.filter(b => b.status === 'completed');
        const currentBlock = mode_blocks.find(b => b.status === 'current');
        const plannedBlocks = mode_blocks.filter(b => b.status === 'planned');

        // Get sub-summaries from API
        const completedSummary = summary.completed_summary || {
            count: completedBlocks.length,
            total_cost: completedBlocks.reduce((sum, b) => sum + (b.cost_historical || 0), 0),
            adherence_pct: 0
        };

        const plannedSummary = summary.planned_summary || {
            count: plannedBlocks.length,
            total_cost: plannedBlocks.reduce((sum, b) => sum + (b.cost_planned || 0), 0)
        };

        const activePlan = data.metadata?.active_plan?.toUpperCase?.();
        const planBanner = activePlan ? `
            <div class="plan-status-banner plan-${activePlan.toLowerCase()}">
                <span>Aktivní plán: ${activePlan}</span>
                ${!data.comparison && data.metadata?.comparison_plan_available ? `<span class="plan-hint">Druhý plán: ${data.metadata.comparison_plan_available.toUpperCase()}</span>` : ''}
            </div>
        ` : '';

        const comparisonHtml = this.renderComparisonSection(data.comparison);

        return `
            ${this.renderDetailTabHeader(summary, 'Dnes')}
            ${planBanner}

            <!-- Uplynulé (Collapsed) -->
            ${completedBlocks.length > 0 ? `
                <div class="collapsible-section">
                    <div class="section-header" onclick="this.parentElement.classList.toggle('expanded')">
                        <div class="section-title">
                            <span class="section-icon">✅</span>
                            <span class="section-name">Uplynulé</span>
                            <span class="section-badge">${completedSummary.count} bloků</span>
                        </div>
                        <div class="section-summary">
                            <span class="summary-item">💰 ${completedSummary.total_cost.toFixed(2)} Kč</span>
                            <span class="summary-item">📊 ${completedSummary.adherence_pct.toFixed(1)}% shoda</span>
                            <span class="expand-icon">▼</span>
                        </div>
                    </div>
                    <div class="section-content">
                        ${this.renderModeBlocks(completedBlocks, { showCosts: true, showAdherence: true })}
                    </div>
                </div>
            ` : ''}

            <!-- Aktuální (Always visible) -->
            ${currentBlock ? `
                <div class="collapsible-section current-section">
                    <div class="section-header-simple">
                        <span class="section-icon">⏱️</span>
                        <span class="section-name">Aktuální režim</span>
                    </div>
                    <div class="section-content visible">
                        ${this.renderModeBlocks([currentBlock], { showCosts: true, showAdherence: false })}
                    </div>
                </div>
            ` : ''}

            <!-- Plánované (Collapsed) -->
            ${plannedBlocks.length > 0 ? `
                <div class="collapsible-section">
                    <div class="section-header" onclick="this.parentElement.classList.toggle('expanded')">
                        <div class="section-title">
                            <span class="section-icon">📅</span>
                            <span class="section-name">Plánované</span>
                            <span class="section-badge">${plannedSummary.count} bloků</span>
                        </div>
                        <div class="section-summary">
                            <span class="summary-item">💰 ${plannedSummary.total_cost.toFixed(2)} Kč</span>
                            <span class="expand-icon">▼</span>
                        </div>
                    </div>
                    <div class="section-content">
                        ${this.renderModeBlocks(plannedBlocks, { showCosts: true, showAdherence: false })}
                    </div>
                </div>
            ` : ''}

            ${comparisonHtml}
        `;
    }

    /**
     * Render DNES header from BE data (FÁZE 1)
     */
    renderTodayHeaderBE(data) {
        const eodPredicted = data.eod_prediction?.predicted_total || 0;
        const eodPlan = data.plan_total_cost || 0;
        const eodVsPlan = data.eod_prediction?.vs_plan || 0;
        const eodVsPlanPct = data.vs_plan_pct || 0;

        const actualSoFar = data.actual_total_cost || 0;
        const planSoFar = data.completed_so_far?.planned_cost || 0;
        const deltaSoFar = data.completed_so_far?.delta_cost || 0;
        const deltaSoFarPct = data.completed_so_far?.delta_pct || 0;

        const predictedSavings = data.eod_prediction?.predicted_savings || 0;
        const plannedSavings = data.eod_prediction?.planned_savings || 0;

        const progressPct = data.progress_pct || 0;

        return `
            <div class="today-header-cards">
                <div class="header-progress-large">
                    <div class="progress-bar-gradient">
                        <div class="progress-fill-gradient" style="width: ${progressPct}%"></div>
                        <div class="progress-label-overlay">${progressPct.toFixed(0)}% dne • ${new Date().toLocaleTimeString('cs-CZ', {hour: '2-digit', minute: '2-digit'})}</div>
                    </div>
                </div>

                <div class="metric-cards-grid">
                    <div class="metric-card card-completed">
                        <div class="card-header">
                            <span class="card-icon">💰</span>
                            <span class="card-title">Odhad nákladů na konec dne</span>
                        </div>
                        <div class="card-body">
                            <div class="card-main-value">${eodPredicted.toFixed(2)} Kč</div>
                            <div class="card-details">
                                <span class="detail-item">plán: ${eodPlan.toFixed(2)} Kč</span>
                                <span class="detail-separator">•</span>
                                <span class="detail-delta ${eodVsPlanPct < -2 ? 'positive' : eodVsPlanPct > 2 ? 'negative' : 'neutral'}">
                                    ${eodVsPlanPct > 0 ? '+' : ''}${eodVsPlanPct.toFixed(1)}%
                                </span>
                            </div>
                        </div>
                    </div>

                    <div class="metric-card card-active">
                        <div class="card-header">
                            <span class="card-icon">📊</span>
                            <span class="card-title">Dosud skutečně</span>
                        </div>
                        <div class="card-body">
                            <div class="card-main-value">${actualSoFar.toFixed(2)} Kč</div>
                            <div class="card-details">
                                <span class="detail-item">plán: ${planSoFar.toFixed(2)} Kč</span>
                                <span class="detail-separator">•</span>
                                <span class="detail-delta ${deltaSoFarPct < -2 ? 'positive' : deltaSoFarPct > 2 ? 'negative' : 'neutral'}">
                                    ${deltaSoFarPct > 0 ? '+' : ''}${deltaSoFarPct.toFixed(1)}%
                                </span>
                            </div>
                        </div>
                    </div>

                    <div class="metric-card card-eod">
                        <div class="card-header">
                            <span class="card-icon">💎</span>
                            <span class="card-title">Předpokládaná úspora</span>
                        </div>
                        <div class="card-body">
                            <div class="card-main-value">${predictedSavings.toFixed(2)} Kč</div>
                            <div class="card-details">
                                <span class="detail-item">vs. HOME I režim</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Group 15-min intervals into time blocks by mode (HOME regime changes)
     */
    groupIntervalsByMode(intervals) {
        if (intervals.length === 0) return [];

        const groups = [];
        let currentGroup = null;

        intervals.forEach((interval, idx) => {
            // Normalize mode name (trim whitespace)
            const rawMode = interval.planned?.mode_name || interval.actual?.mode_name || '?';
            const mode = rawMode.trim();

            if (!currentGroup || currentGroup.mode !== mode) {
                // Start new group
                currentGroup = {
                    mode: mode,
                    intervals: [interval],
                    startTime: interval.time,
                    endTime: interval.time
                };
                groups.push(currentGroup);
            } else {
                // Add to existing group
                currentGroup.intervals.push(interval);
                currentGroup.endTime = interval.time;
            }
        });

        console.log(`[TimelineDialog] Grouped ${intervals.length} intervals into ${groups.length} groups by mode`);

        return groups;
    }

    resolveIntervalMode(interval) {
        if (!interval) {
            return null;
        }

        const status = interval.status;
        const baseMode = (status === 'historical' || status === 'current')
            ? (interval.actual?.mode_name || interval.planned?.mode_name || interval.mode_name)
            : (interval.planned?.mode_name || interval.mode_name || interval.actual?.mode_name);

        if (!baseMode || typeof baseMode !== 'string') {
            return null;
        }

        const normalized = baseMode.trim();
        return normalized.length ? normalized : null;
    }

    getModeShortLabel(modeName) {
        if (!modeName) {
            return '';
        }

        if (modeName.startsWith('HOME ')) {
            return modeName.replace('HOME ', '').trim();
        }

        if (modeName === 'FULL HOME UPS') {
            return 'UPS';
        }

        if (modeName === 'HOME UPS') {
            return 'UPS';
        }

        if (modeName === 'DO NOTHING') {
            return 'DN';
        }

        return modeName.substring(0, 3).toUpperCase();
    }

    buildModeSegmentsForChart(intervals) {
        if (!Array.isArray(intervals) || intervals.length === 0) {
            return [];
        }

        const segments = [];
        let currentSegment = null;

        intervals.forEach((interval, idx) => {
            const mode = this.resolveIntervalMode(interval);

            if (!mode) {
                currentSegment = null;
                return;
            }

            if (!currentSegment || currentSegment.mode !== mode) {
                currentSegment = {
                    mode,
                    startIndex: idx,
                    endIndex: idx
                };
                segments.push(currentSegment);
            } else {
                currentSegment.endIndex = idx;
            }
        });

        return segments.map((segment) => {
            const config = MODE_CONFIG[segment.mode] || { icon: '❓', color: 'rgba(158, 158, 158, 0.6)', label: segment.mode || 'Unknown' };
            return {
                ...segment,
                icon: config.icon || '❓',
                color: config.color || 'rgba(158, 158, 158, 0.6)',
                label: config.label || segment.mode,
                shortLabel: this.getModeShortLabel(segment.mode)
            };
        });
    }

    /**
     * Render intervals for VČERA tab (backward compatibility fallback)
     * Shows all completed intervals grouped by mode
     */
    renderYesterdayIntervals(intervals) {
        // Group all intervals by mode (they're all completed for yesterday)
        const completedGroups = this.groupIntervalsByMode(intervals);

        // Render using the completed intervals renderer
        return this.renderCompletedIntervalGroups(completedGroups);
    }

    /**
     * Render intervals for DNES tab (v2.1 compact format)
     * FÁZE 1-3: Now uses BE grouped data
     */
    renderTodayIntervals(intervals, unifiedCostData) {
        const now = new Date();

        // FÁZE 1: Use BE grouped data if available
        if (unifiedCostData && unifiedCostData.completed_groups && unifiedCostData.future_groups) {
            console.log('[TimelineDialog DNES] Using BE grouped data:', {
                completed: unifiedCostData.completed_groups.length,
                active: unifiedCostData.active_group ? 1 : 0,
                future: unifiedCostData.future_groups.length
            });

            return `
                ${this.renderCompletedIntervalGroupsBE(unifiedCostData.completed_groups)}
                ${unifiedCostData.active_group ? this.renderActiveIntervalBE(unifiedCostData.active_group) : ''}
                ${this.renderFutureIntervalGroupsBE(unifiedCostData.future_groups)}
            `;
        }

        // Fallback to FE grouping (backward compatibility)
        console.log('[TimelineDialog DNES] BE grouped data not available, using FE grouping');

        // Separate intervals by status
        const completed = [];
        let active = null;
        const future = [];

        intervals.forEach(interval => {
            const status = interval.status;

            if (status === 'historical') {
                completed.push(interval);
            } else if (status === 'current') {
                active = interval;
            } else {
                future.push(interval);
            }
        });

        console.log(`[TimelineDialog] Separated intervals: completed=${completed.length}, active=${active ? 1 : 0}, future=${future.length}`);

        // Group intervals by mode (HOME regime changes)
        const completedGroups = this.groupIntervalsByMode(completed);
        const futureGroups = this.groupIntervalsByMode(future);

        // Get active interval data from unifiedCostData
        const activeIntervalData = unifiedCostData?.active_interval;

        return `
            ${this.renderCompletedIntervalGroups(completedGroups)}
            ${active ? this.renderActiveInterval(active, activeIntervalData) : ''}
            ${this.renderFutureIntervalGroups(futureGroups, unifiedCostData)}
        `;
    }

    /**
     * Render completed interval groups - compact one-line format
     */
    renderCompletedIntervalGroups(groups) {
        if (groups.length === 0) {
            return '<div class="interval-section"><p>Žádné uplynulé intervaly</p></div>';
        }

        const totalIntervals = groups.reduce((sum, g) => sum + g.intervals.length, 0);

        // Calculate aggregated values
        const totalActualCost = groups.reduce((sum, g) => {
            return sum + g.intervals.reduce((s, iv) => s + (iv.actual?.net_cost || 0), 0);
        }, 0);

        const totalPlannedCost = groups.reduce((sum, g) => {
            return sum + g.intervals.reduce((s, iv) => s + (iv.planned?.net_cost || 0), 0);
        }, 0);

        const totalSavings = groups.reduce((sum, g) => {
            return sum + g.intervals.reduce((s, iv) => s + (iv.actual?.savings || 0), 0);
        }, 0);

        const totalDelta = totalActualCost - totalPlannedCost;
        const totalDeltaPct = totalPlannedCost > 0 ? ((totalDelta / totalPlannedCost) * 100) : 0;
        const deltaClass = totalDelta < -0.5 ? 'positive' : totalDelta > 0.5 ? 'negative' : 'neutral';

        const rows = groups.map((group, idx) => {
            const startTime = new Date(group.startTime);
            const endTime = new Date(group.endTime);

            // Calculate end time + 15 minutes for the range
            const rangeEnd = new Date(endTime.getTime() + 15 * 60 * 1000);

            const startStr = `${startTime.getHours().toString().padStart(2, '0')}:${startTime.getMinutes().toString().padStart(2, '0')}`;
            const endStr = `${rangeEnd.getHours().toString().padStart(2, '0')}:${rangeEnd.getMinutes().toString().padStart(2, '0')}`;
            const timeRange = `${startStr} - ${endStr}`;

            const mode = group.mode;
            const modeIcon = mode.includes('HOME I') ? '🏠' : mode.includes('HOME UPS') ? '⚡' : '🔋';

            // Sum costs across all intervals in group
            const actualCost = group.intervals.reduce((sum, iv) => sum + (iv.actual?.net_cost || 0), 0);
            const plannedCost = group.intervals.reduce((sum, iv) => sum + (iv.planned?.net_cost || 0), 0);
            const actualSavings = group.intervals.reduce((sum, iv) => sum + (iv.actual?.savings || 0), 0);

            const delta = actualCost - plannedCost;
            const deltaPct = plannedCost > 0 ? ((delta / plannedCost) * 100) : 0;

            const deltaClass = delta < -0.5 ? 'positive' : delta > 0.5 ? 'negative' : 'neutral';
            const deltaIcon = delta < -0.5 ? '✅' : delta > 0.5 ? '❌' : '⚪';

            const intervalCount = group.intervals.length;

            return `
                <div class="interval-row completed" data-interval-id="${idx}">
                    <div class="interval-summary" onclick="toggleIntervalDetail(${idx})">
                        <span class="interval-time">${timeRange}</span>
                        <span class="interval-mode">${modeIcon} ${mode}</span>
                        <span class="interval-count">(${intervalCount}×15min)</span>
                        <span class="interval-cost ${deltaClass}">${actualCost.toFixed(2)} Kč</span>
                        <span class="interval-delta ${deltaClass}">${deltaIcon} ${Math.abs(deltaPct).toFixed(0)}%</span>
                        <span class="interval-toggle">▼</span>
                    </div>
                    <div class="interval-detail" id="interval-detail-${idx}" style="display: none;">
                        <div class="detail-grid">
                            <div class="detail-item">
                                <span class="detail-label">⏱️ Trvání:</span>
                                <span class="detail-value">${intervalCount} × 15 min = ${(intervalCount * 15)} min</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">💰 Náklady:</span>
                                <span class="detail-value">${actualCost.toFixed(2)} Kč skutečně <span class="detail-plan">(plán: ${plannedCost.toFixed(2)} Kč)</span></span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">💎 Úspora:</span>
                                <span class="detail-value">${actualSavings.toFixed(2)} Kč</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">📊 Delta:</span>
                                <span class="detail-value ${deltaClass}">${delta > 0 ? '+' : ''}${delta.toFixed(2)} Kč (${deltaPct > 0 ? '+' : ''}${deltaPct.toFixed(1)}%)</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        return `
            <div class="interval-section collapsible collapsed">
                <div class="section-header" onclick="toggleSection('completed-intervals')">
                    <span class="section-icon">✅</span>
                    <span class="section-title">UPLYNULÉ</span>
                    <span class="section-meta">
                        <span class="meta-item">💰 ${totalActualCost.toFixed(2)} Kč</span>
                        <span class="meta-item">💎 ${totalSavings.toFixed(2)} Kč</span>
                        <span class="meta-item ${deltaClass}">✅ ${totalDelta > 0 ? '+' : ''}${totalDelta.toFixed(2)} Kč (${totalDeltaPct > 0 ? '+' : ''}${totalDeltaPct.toFixed(0)}%)</span>
                    </span>
                    <span class="section-toggle">▶</span>
                </div>
                <div class="interval-list" id="completed-intervals" style="display: none;">
                    ${rows}
                </div>
            </div>
        `;
    }

    /**
     * Render completed interval groups from BE data (FÁZE 1)
     */
    renderCompletedIntervalGroupsBE(groups) {
        if (!groups || groups.length === 0) {
            return '<div class="interval-section"><p>Žádné uplynulé intervaly</p></div>';
        }

        const totalActualCost = groups.reduce((sum, g) => sum + (g.actual_cost || 0), 0);
        const totalPlannedCost = groups.reduce((sum, g) => sum + (g.planned_cost || 0), 0);
        const totalDelta = groups.reduce((sum, g) => sum + (g.delta || 0), 0);
        const totalDeltaPct = totalPlannedCost > 0 ? ((totalDelta / totalPlannedCost) * 100) : 0;
        const deltaClass = totalDelta < -0.5 ? 'positive' : totalDelta > 0.5 ? 'negative' : 'neutral';

        const rows = groups.map((group, idx) => {
            const deltaClass = group.delta < -0.5 ? 'positive' : group.delta > 0.5 ? 'negative' : 'neutral';
            const deltaIcon = group.delta < -0.5 ? '✅' : group.delta > 0.5 ? '❌' : '⚪';
            const modeIcon = group.mode.includes('HOME I') ? '🏠' : group.mode.includes('HOME UPS') ? '⚡' : '🔋';

            return `
                <div class="interval-row completed">
                    <div class="interval-summary">
                        <span class="interval-time">${group.start_time} - ${group.end_time}</span>
                        <span class="interval-mode">${modeIcon} ${group.mode}</span>
                        <span class="interval-count">(${group.interval_count}×15min)</span>
                        <span class="interval-cost ${deltaClass}">${group.actual_cost.toFixed(2)} Kč</span>
                        <span class="interval-delta ${deltaClass}">${deltaIcon} ${Math.abs(group.delta_pct || 0).toFixed(0)}%</span>
                    </div>
                </div>
            `;
        }).join('');

        return `
            <div class="interval-section collapsible collapsed">
                <div class="section-header" onclick="toggleSection('completed-intervals-be')">
                    <span class="section-icon">✅</span>
                    <span class="section-title">UPLYNULÉ</span>
                    <span class="section-meta">
                        <span class="meta-item">💰 ${totalActualCost.toFixed(2)} Kč</span>
                        <span class="meta-item ${deltaClass}">△ ${totalDelta > 0 ? '+' : ''}${totalDelta.toFixed(2)} Kč</span>
                    </span>
                    <span class="section-toggle">▶</span>
                </div>
                <div class="interval-list" id="completed-intervals-be" style="display: none;">
                    ${rows}
                </div>
            </div>
        `;
    }

    /**
     * Render active interval from BE data (FÁZE 1)
     */
    renderActiveIntervalBE(group) {
        const modeIcon = group.mode.includes('HOME I') ? '🏠' : group.mode.includes('HOME UPS') ? '⚡' : '🔋';
        const plannedCost = group.planned_cost || 0;
        const actualCost = group.actual_cost || 0;
        const progress = 50; // Default mid-interval

        return `
            <div class="interval-section active">
                <div class="section-header">
                    <span class="section-icon">🔥</span>
                    <span class="section-title">AKTIVNÍ INTERVAL</span>
                </div>
                <div class="interval-list">
                    <div class="interval-row active-interval">
                        <div class="interval-summary">
                            <span class="interval-time">${group.start_time}</span>
                            <span class="interval-mode">${modeIcon} ${group.mode}</span>
                            <span class="interval-cost">${plannedCost.toFixed(2)} Kč plán</span>
                            <span class="interval-progress">⏳ ${progress}%</span>
                        </div>
                        <div class="active-progress-bar">
                            <div class="progress-fill" style="width: ${progress}%"></div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Render future interval groups from BE data (FÁZE 1)
     */
    renderFutureIntervalGroupsBE(groups) {
        if (!groups || groups.length === 0) {
            return '<div class="interval-section"><p>Žádné budoucí intervaly</p></div>';
        }

        const totalPlannedCost = groups.reduce((sum, g) => sum + (g.planned_cost || 0), 0);
        const totalPlannedSavings = groups.reduce((sum, g) => sum + (g.planned_savings || 0), 0);

        const rows = groups.map((group, idx) => {
            const modeIcon = group.mode.includes('HOME I') ? '🏠' : group.mode.includes('HOME UPS') ? '⚡' : '🔋';
            const plannedSavings = group.planned_savings || 0;

            return `
                <div class="interval-row future">
                    <div class="interval-summary">
                        <span class="interval-time">${group.start_time} - ${group.end_time}</span>
                        <span class="interval-mode">${modeIcon} ${group.mode}</span>
                        <span class="interval-count">(${group.interval_count}×15min)</span>
                        <span class="interval-cost">${group.planned_cost.toFixed(2)} Kč</span>
                        ${plannedSavings > 0 ? `<span class="interval-savings">💎 ${plannedSavings.toFixed(2)} Kč</span>` : ''}
                    </div>
                </div>
            `;
        }).join('');

        return `
            <div class="interval-section collapsible collapsed">
                <div class="section-header" onclick="toggleSection('future-intervals-be')">
                    <span class="section-icon">🔮</span>
                    <span class="section-title">BUDOUCÍ PLÁN</span>
                    <span class="section-meta">
                        <span class="meta-item">💰 ${totalPlannedCost.toFixed(2)} Kč</span>
                        ${totalPlannedSavings > 0 ? `<span class="meta-item">💎 ${totalPlannedSavings.toFixed(2)} Kč</span>` : ''}
                    </span>
                    <span class="section-toggle">▶</span>
                </div>
                <div class="interval-list" id="future-intervals-be" style="display: none;">
                    ${rows}
                </div>
            </div>
        `;
    }

    /**
     * Render active interval with progress bar
     */
    renderActiveInterval(interval, activeData) {
        const time = new Date(interval.time);
        const timeStr = `${time.getHours().toString().padStart(2, '0')}:${time.getMinutes().toString().padStart(2, '0')}`;

        const mode = interval.planned?.mode_name || '?';
        const modeIcon = mode.includes('HOME I') ? '🏠' : mode.includes('HOME UPS') ? '⚡' : '🔋';

        const plannedCost = interval.planned?.net_cost || 0;
        const progress = activeData?.progress_pct || 0;
        const actualCostSoFar = activeData?.actual_cost_so_far || 0;
        const expectedCost = activeData?.expected_cost_at_progress || 0;
        const costDelta = actualCostSoFar - expectedCost;
        const costDeltaPct = activeData?.cost_delta_pct || 0;

        const deltaClass = costDelta < -0.5 ? 'positive' : costDelta > 0.5 ? 'negative' : 'neutral';
        const deltaIcon = costDelta < -0.5 ? '✅' : costDelta > 0.5 ? '❌' : '⚪';

        return `
            <div class="interval-section active">
                <div class="section-header">
                    <span class="section-icon">🔥</span>
                    <span class="section-title">AKTIVNÍ INTERVAL</span>
                    <span class="section-count">1 interval</span>
                </div>
                <div class="interval-list">
                    <div class="interval-row active-interval">
                        <div class="interval-summary">
                            <span class="interval-time">${timeStr}</span>
                            <span class="interval-mode">${modeIcon} ${mode}</span>
                            <span class="interval-cost">${plannedCost.toFixed(2)} Kč plán</span>
                            <span class="interval-progress">⏳ ${progress.toFixed(0)}%</span>
                        </div>
                        <div class="active-progress-bar">
                            <div class="progress-fill" style="width: ${progress}%"></div>
                        </div>
                        <div class="active-details">
                            <span>Skutečně dosud: ${actualCostSoFar.toFixed(2)} Kč (${progress.toFixed(0)}% plánu) ${deltaIcon} ${costDeltaPct > 0 ? '+' : ''}${costDeltaPct.toFixed(1)}%</span>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Render future interval groups - minimalist format
     */
    renderFutureIntervalGroups(groups, unifiedCostData) {
        if (groups.length === 0) {
            return '';
        }

        const totalIntervals = groups.reduce((sum, g) => sum + g.intervals.length, 0);

        // Calculate aggregated planned costs for FUTURE intervals only
        const totalPlannedCost = groups.reduce((sum, g) => {
            return sum + g.intervals.reduce((s, iv) => s + (iv.planned?.net_cost || 0), 0);
        }, 0);

        const displayGroups = groups.slice(0, 20);  // Show first 20 groups

        const rows = displayGroups.map((group, idx) => {
            const startTime = new Date(group.startTime);
            const endTime = new Date(group.endTime);

            // Calculate end time + 15 minutes for the range
            const rangeEnd = new Date(endTime.getTime() + 15 * 60 * 1000);

            const startStr = `${startTime.getHours().toString().padStart(2, '0')}:${startTime.getMinutes().toString().padStart(2, '0')}`;
            const endStr = `${rangeEnd.getHours().toString().padStart(2, '0')}:${rangeEnd.getMinutes().toString().padStart(2, '0')}`;
            const timeRange = `${startStr} - ${endStr}`;

            const mode = group.mode;
            const modeIcon = mode.includes('HOME I') ? '🏠' : mode.includes('HOME UPS') ? '⚡' : '🔋';

            const plannedCost = group.intervals.reduce((sum, iv) => sum + (iv.planned?.net_cost || 0), 0);
            const plannedSavings = group.intervals.reduce((sum, iv) => sum + (iv.planned?.savings_vs_home_i || 0), 0);
            const intervalCount = group.intervals.length;

            return `
                <div class="interval-row future">
                    <div class="interval-summary">
                        <span class="interval-time">${timeRange}</span>
                        <span class="interval-mode">${modeIcon} ${mode}</span>
                        <span class="interval-count">(${intervalCount}×15min)</span>
                        <span class="interval-cost">${plannedCost.toFixed(2)} Kč</span>
                        ${plannedSavings > 0 ? `<span class="interval-savings">💎 ${plannedSavings.toFixed(2)} Kč</span>` : ''}
                    </div>
                </div>
            `;
        }).join('');

        const remaining = groups.length - 20;

        return `
            <div class="interval-section collapsible collapsed">
                <div class="section-header" onclick="toggleSection('future-intervals')">
                    <span class="section-icon">📅</span>
                    <span class="section-title">BUDOUCÍ</span>
                    <span class="section-meta">
                        <span class="meta-item">💰 ${totalPlannedCost.toFixed(2)} Kč</span>
                    </span>
                    <span class="section-toggle">▶</span>
                </div>
                <div class="interval-list" id="future-intervals" style="display: none;">
                    ${rows}
                    ${remaining > 0 ? `<div class="interval-row future muted">... a dalších ${remaining} úseků</div>` : ''}
                </div>
            </div>
        `;
    }

    /**
    /**
     * Render ZÍTRA tab - Tomorrow's plan with card design
     */
    renderTomorrowTab(data) {
        const { mode_blocks, summary } = data;

        if (!mode_blocks || mode_blocks.length === 0) {
            return this.renderNoData('tomorrow');
        }

        const activePlan = data.metadata?.active_plan?.toUpperCase?.();
        const planBanner = activePlan ? `
            <div class="plan-status-banner plan-${activePlan.toLowerCase()}">
                <span>Aktivní plán: ${activePlan}</span>
                ${!data.comparison && data.metadata?.comparison_plan_available ? `<span class="plan-hint">Druhý plán: ${data.metadata.comparison_plan_available.toUpperCase()}</span>` : ''}
            </div>
        ` : '';

        const comparisonHtml = this.renderComparisonSection(data.comparison);

        // All blocks should be planned for tomorrow
        return `
            ${this.renderDetailTabHeader(summary, 'Zítra')}
            ${planBanner}

            <!-- Collapsible section for planned blocks -->
            <div class="collapsible-section">
                <div class="section-header" onclick="this.parentElement.classList.toggle('expanded')">
                    <div class="section-title">
                        <span class="section-icon">📅</span>
                        <span class="section-name">Plánované režimy</span>
                        <span class="section-badge">${mode_blocks.length} bloků</span>
                    </div>
                    <div class="section-summary">
                        <span class="summary-item">💰 ${summary.total_cost?.toFixed(2) || '0.00'} Kč</span>
                        <span class="expand-icon">▼</span>
                    </div>
                </div>
                <div class="section-content">
                    ${this.renderModeBlocks(mode_blocks, { showCosts: true, showAdherence: false })}
                </div>
            </div>

            ${comparisonHtml}
        `;
    }

    renderComparisonSection(comparison) {
        if (!comparison || !comparison.mode_blocks || comparison.mode_blocks.length === 0) {
            return '';
        }
        const planName = comparison.plan ? comparison.plan.toUpperCase() : 'JINÝ PLÁN';
        return `
            <div class="collapsible-section comparison-section">
                <div class="section-header-simple">
                    <span class="section-icon">🔀</span>
                    <span class="section-name">Alternativní plán (${planName})</span>
                </div>
                <div class="section-content visible">
                    ${this.renderModeBlocks(comparison.mode_blocks, { showCosts: true, showAdherence: false })}
                </div>
            </div>
        `;
    }

    /**
     * Render mode distribution chart (FÁZE 3)
     */
    renderModeDistributionBE(distribution) {
        if (!distribution || Object.keys(distribution).length === 0) {
            return '<p style="color: var(--text-secondary);">Žádná distribuce</p>';
        }

        const total = Object.values(distribution).reduce((a, b) => a + b, 0);
        const modeIcons = {
            'HOME I': '🏠',
            'HOME II': '⚡',
            'HOME III': '🔋',
            'HOME UPS': '⚡'
        };

        const bars = Object.entries(distribution)
            .sort((a, b) => b[1] - a[1])
            .map(([mode, count]) => {
                const pct = total > 0 ? (count / total * 100) : 0;
                const icon = modeIcons[mode] || '🎯';

                return `
                    <div class="mode-dist-row">
                        <span class="mode-name">${icon} ${mode}</span>
                        <div class="mode-bar-container">
                            <div class="mode-bar-fill" style="width: ${pct}%"></div>
                            <span class="mode-bar-label">${count} intervalů (${pct.toFixed(0)}%)</span>
                        </div>
                    </div>
                `;
            }).join('');

        return `<div class="mode-distribution">${bars}</div>`;
    }

    /**
     * Render tomorrow's intervals grouped by mode
     */
    renderTomorrowIntervals(intervals) {
        if (!intervals || intervals.length === 0) {
            return '<p style="color: var(--text-secondary);">Žádné intervaly k dispozici</p>';
        }

        // Group by mode
        const groups = this.groupIntervalsByMode(intervals);

        return groups.map(group => {
            const totalCost = group.intervals.reduce((sum, iv) => sum + (iv.planned?.net_cost || 0), 0);
            const timeRange = `${group.intervals[0].time_start} - ${group.intervals[group.intervals.length - 1].time_end}`;

            return `
                <div class="interval-group tomorrow-group">
                    <div class="group-header">
                        <span class="mode-badge">${group.mode}</span>
                        <span class="time-range">${timeRange}</span>
                        <span class="interval-count">${group.intervals.length} bloků</span>
                        <span class="group-cost">${totalCost.toFixed(2)} Kč</span>
                    </div>
                </div>
            `;
        }).join('');
    }

    /**
     * Render HISTORIE tab - Multi-day historical comparison
     */
    renderHistoryTab(data) {
        // For now, placeholder
        return `
            <div style="padding: 40px 20px; text-align: center;">
                <div style="font-size: 3em; margin-bottom: 20px;">📈</div>
                <h3 style="color: var(--text-secondary); margin-bottom: 10px;">
                    Historie posledních 7 dní
                </h3>
                <p style="color: var(--text-muted); margin-top: 10px;">
                    Graf přesnosti plánu a kumulativní dopady<br>
                    <small>(v přípravě)</small>
                </p>
            </div>
        `;
    }

    /**
     * Render 48h compare tab (včera + dnes)
     */
    renderCompareTab(yesterdayData, todayData) {
        const yesterdayCount = Array.isArray(yesterdayData?.intervals)
            ? yesterdayData.intervals.length
            : 0;
        const todayCount = Array.isArray(todayData?.intervals)
            ? todayData.intervals.length
            : 0;
        const totalCount = yesterdayCount + todayCount;

        return `
            <div class="compare-tab">
                <div class="compare-header">
                    <div>
                        <div class="compare-title">📊 Srovnání 48h (včera + dnes)</div>
                        <div class="compare-sub">15min intervaly • ${totalCount} bodů</div>
                    </div>
                    <div class="compare-legend">
                        <span class="legend-item"><span class="legend-line legend-actual"></span> Skutečnost</span>
                        <span class="legend-item"><span class="legend-line legend-planned"></span> Plán</span>
                    </div>
                </div>

                <div class="compare-grid">
                    <div class="compare-card">
                        <div class="compare-card-title">🏠 Spotřeba & ☀️ Solár</div>
                        <canvas id="compare-energy-chart"></canvas>
                    </div>
                    <div class="compare-card">
                        <div class="compare-card-title">🔋 SoC (%)</div>
                        <canvas id="compare-soc-chart"></canvas>
                    </div>
                    <div class="compare-card">
                        <div class="compare-card-title">💰 Náklady (Kč / 15 min)</div>
                        <canvas id="compare-cost-chart"></canvas>
                    </div>
                </div>
            </div>
        `;
    }

    async getBatteryCapacityKwh() {
        try {
            const sensorId = getSensorId('installed_battery_capacity_kwh');
            const sensor = await getSensor(sensorId);
            const value = Number(sensor?.value);
            if (!Number.isFinite(value) || value <= 0) {
                return null;
            }
            return value / 1000;
        } catch (err) {
            return null;
        }
    }

    buildCompareSeries(yesterdayData, todayData, capacityKwh) {
        const yesterdayIntervals = Array.isArray(yesterdayData?.intervals)
            ? yesterdayData.intervals
            : [];
        const todayIntervals = Array.isArray(todayData?.intervals)
            ? todayData.intervals
            : [];
        const intervals = [...yesterdayIntervals, ...todayIntervals];
        const boundaryIndex = yesterdayIntervals.length;

        const labels = [];
        const times = [];
        const consumptionActual = [];
        const consumptionPlanned = [];
        const solarActual = [];
        const solarPlanned = [];
        const costActual = [];
        const costPlanned = [];
        const socActual = [];
        const socPlanned = [];

        const toNumber = (value) => {
            if (value === null || value === undefined) {
                return null;
            }
            const num = Number(value);
            return Number.isFinite(num) ? num : null;
        };

        const totalIntervals = intervals.length;
        const labelStride = totalIntervals > 160 ? 12 : totalIntervals > 120 ? 8 : 4;

        intervals.forEach((interval, idx) => {
            const time = new Date(interval.time);
            times.push(time);

            let label = '';
            if (idx % labelStride === 0) {
                const hh = time.getHours().toString().padStart(2, '0');
                const mm = time.getMinutes().toString().padStart(2, '0');
                label = `${hh}:${mm}`;
                if (hh === '00' && mm === '00') {
                    const dd = time.getDate().toString().padStart(2, '0');
                    const mo = (time.getMonth() + 1).toString().padStart(2, '0');
                    label = `${dd}.${mo} ${label}`;
                }
            }
            labels.push(label);

            const planned = interval.planned || {};
            const actual = interval.actual || {};

            consumptionActual.push(toNumber(actual.consumption_kwh));
            consumptionPlanned.push(toNumber(planned.consumption_kwh));
            solarActual.push(toNumber(actual.solar_kwh));
            solarPlanned.push(toNumber(planned.solar_kwh));
            costActual.push(toNumber(actual.net_cost));
            costPlanned.push(toNumber(planned.net_cost));

            const actualSoc = toNumber(actual.battery_soc);
            socActual.push(actualSoc);

            let plannedSoc = toNumber(planned.battery_soc);
            if (plannedSoc === null) {
                const plannedKwh = toNumber(planned.battery_kwh);
                if (plannedKwh !== null && capacityKwh) {
                    plannedSoc = (plannedKwh / capacityKwh) * 100;
                }
            }
            socPlanned.push(plannedSoc);
        });

        let nowIndex = -1;
        const now = new Date();
        times.forEach((time, idx) => {
            if (time <= now) {
                nowIndex = idx;
            }
        });

        return {
            labels,
            times,
            boundaryIndex,
            nowIndex,
            consumptionActual,
            consumptionPlanned,
            solarActual,
            solarPlanned,
            costActual,
            costPlanned,
            socActual,
            socPlanned
        };
    }

    buildCompareAnnotations(series) {
        const annotations = {};

        if (series.boundaryIndex > 0 && series.boundaryIndex < series.labels.length) {
            annotations.daySplit = {
                type: 'line',
                xMin: series.boundaryIndex,
                xMax: series.boundaryIndex,
                borderColor: 'rgba(255, 255, 255, 0.25)',
                borderWidth: 2,
                label: {
                    display: true,
                    content: 'DNES',
                    position: 'start',
                    backgroundColor: 'rgba(255, 255, 255, 0.15)',
                    color: 'rgba(255, 255, 255, 0.8)',
                    font: { size: 10, weight: '600' }
                }
            };
        }

        if (series.nowIndex >= 0) {
            annotations.nowLine = {
                type: 'line',
                xMin: series.nowIndex,
                xMax: series.nowIndex,
                borderColor: 'rgba(255, 152, 0, 0.8)',
                borderWidth: 2,
                label: {
                    display: true,
                    content: 'TEĎ',
                    position: 'start',
                    backgroundColor: 'rgba(255, 152, 0, 0.85)',
                    color: '#fff',
                    font: { size: 10, weight: '700' }
                }
            };
        }

        return annotations;
    }

    destroyCompareCharts() {
        Object.values(this.compareCharts || {}).forEach((chart) => {
            if (chart && typeof chart.destroy === 'function') {
                chart.destroy();
            }
        });
        this.compareCharts = {};
    }

    async initializeCompareCharts(yesterdayData, todayData) {
        if (typeof Chart === 'undefined') {
            console.warn('[TimelineDialog] Chart.js not available - compare charts skipped');
            return;
        }

        const energyCanvas = document.getElementById('compare-energy-chart');
        const socCanvas = document.getElementById('compare-soc-chart');
        const costCanvas = document.getElementById('compare-cost-chart');

        if (!energyCanvas || !socCanvas || !costCanvas) {
            return;
        }

        this.destroyCompareCharts();

        const capacityKwh = await this.getBatteryCapacityKwh();
        const series = this.buildCompareSeries(yesterdayData, todayData, capacityKwh);
        const annotations = this.buildCompareAnnotations(series);

        const gridColor = 'rgba(255, 255, 255, 0.08)';
        const tickColor = 'rgba(255, 255, 255, 0.7)';
        const legendColor = 'rgba(255, 255, 255, 0.75)';
        const zoomOptions = {
            pan: {
                enabled: true,
                mode: 'x',
                modifierKey: 'shift'
            },
            zoom: {
                wheel: {
                    enabled: true,
                    speed: 0.1
                },
                pinch: {
                    enabled: true
                },
                drag: {
                    enabled: true,
                    backgroundColor: 'rgba(33, 150, 243, 0.2)',
                    borderColor: 'rgba(33, 150, 243, 0.4)',
                    borderWidth: 1
                },
                mode: 'x'
            }
        };

        const tooltipLabel = (unit, decimals = 2) => (context) => {
            const value = context.parsed?.y;
            if (!Number.isFinite(value)) {
                return `${context.dataset.label}: —`;
            }
            return `${context.dataset.label}: ${value.toFixed(decimals)} ${unit}`;
        };

        this.compareCharts.energy = new Chart(energyCanvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: series.labels,
                datasets: [
                    {
                        label: 'Spotřeba – skutečnost',
                        data: series.consumptionActual,
                        borderColor: 'rgba(33, 150, 243, 0.9)',
                        backgroundColor: 'rgba(33, 150, 243, 0.12)',
                        borderWidth: 2,
                        tension: 0.25,
                        pointRadius: 0
                    },
                    {
                        label: 'Spotřeba – plán',
                        data: series.consumptionPlanned,
                        borderColor: 'rgba(33, 150, 243, 0.5)',
                        borderDash: [6, 4],
                        borderWidth: 2,
                        tension: 0.25,
                        pointRadius: 0
                    },
                    {
                        label: 'Solár – skutečnost',
                        data: series.solarActual,
                        borderColor: 'rgba(255, 193, 7, 0.9)',
                        backgroundColor: 'rgba(255, 193, 7, 0.15)',
                        borderWidth: 2,
                        tension: 0.25,
                        pointRadius: 0
                    },
                    {
                        label: 'Solár – plán',
                        data: series.solarPlanned,
                        borderColor: 'rgba(255, 193, 7, 0.5)',
                        borderDash: [6, 4],
                        borderWidth: 2,
                        tension: 0.25,
                        pointRadius: 0
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        labels: { color: legendColor }
                    },
                    tooltip: {
                        callbacks: { label: tooltipLabel('kWh', 2) }
                    },
                    zoom: zoomOptions,
                    annotation: { annotations }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: {
                            color: tickColor,
                            autoSkip: true,
                            maxTicksLimit: 12,
                            maxRotation: 0,
                            minRotation: 0
                        }
                    },
                    y: {
                        grid: { color: gridColor },
                        ticks: {
                            color: tickColor,
                            callback: (value) => `${value.toFixed(2)} kWh`
                        },
                        title: { display: true, text: 'kWh / 15 min', color: tickColor }
                    }
                }
            }
        });
        this.scheduleChartResize(this.compareCharts.energy, energyCanvas);

        this.compareCharts.soc = new Chart(socCanvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: series.labels,
                datasets: [
                    {
                        label: 'SoC – skutečnost',
                        data: series.socActual,
                        borderColor: 'rgba(76, 175, 80, 0.9)',
                        backgroundColor: 'rgba(76, 175, 80, 0.12)',
                        borderWidth: 2,
                        tension: 0.2,
                        pointRadius: 0
                    },
                    {
                        label: 'SoC – plán',
                        data: series.socPlanned,
                        borderColor: 'rgba(76, 175, 80, 0.5)',
                        borderDash: [6, 4],
                        borderWidth: 2,
                        tension: 0.2,
                        pointRadius: 0
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        labels: { color: legendColor }
                    },
                    tooltip: {
                        callbacks: { label: tooltipLabel('%', 1) }
                    },
                    zoom: zoomOptions,
                    annotation: { annotations }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: {
                            color: tickColor,
                            autoSkip: true,
                            maxTicksLimit: 12,
                            maxRotation: 0,
                            minRotation: 0
                        }
                    },
                    y: {
                        grid: { color: gridColor },
                        ticks: {
                            color: tickColor,
                            callback: (value) => `${value.toFixed(0)}%`
                        },
                        min: 0,
                        max: 100
                    }
                }
            }
        });
        this.scheduleChartResize(this.compareCharts.soc, socCanvas);

        this.compareCharts.cost = new Chart(costCanvas.getContext('2d'), {
            data: {
                labels: series.labels,
                datasets: [
                    {
                        type: 'bar',
                        label: 'Náklady – skutečnost',
                        data: series.costActual,
                        backgroundColor: 'rgba(255, 152, 0, 0.45)',
                        borderColor: 'rgba(255, 152, 0, 0.75)',
                        borderWidth: 1
                    },
                    {
                        type: 'line',
                        label: 'Náklady – plán',
                        data: series.costPlanned,
                        borderColor: 'rgba(255, 152, 0, 0.9)',
                        borderDash: [6, 4],
                        borderWidth: 2,
                        tension: 0.25,
                        pointRadius: 0
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        labels: { color: legendColor }
                    },
                    tooltip: {
                        callbacks: { label: tooltipLabel('Kč', 2) }
                    },
                    zoom: zoomOptions,
                    annotation: { annotations }
                },
                scales: {
                    x: {
                        stacked: false,
                        grid: { display: false },
                        ticks: {
                            color: tickColor,
                            autoSkip: true,
                            maxTicksLimit: 12,
                            maxRotation: 0,
                            minRotation: 0
                        }
                    },
                    y: {
                        grid: { color: gridColor },
                        ticks: {
                            color: tickColor,
                            callback: (value) => `${value.toFixed(2)} Kč`
                        }
                    }
                }
            }
        });
        this.scheduleChartResize(this.compareCharts.cost, costCanvas);
    }

    /**
     * Render header with overall stats
     */
    renderHeader(summary, dayType) {
        const plannedCost = summary?.planned_total_cost || 0;
        const actualCost = summary?.actual_total_cost || 0;
        const deltaCost = actualCost - plannedCost;
        const deltaPercent = plannedCost > 0 ? ((deltaCost / plannedCost) * 100) : 0;

        const deltaClass = deltaCost > 0 ? 'negative' : 'positive';
        const deltaIcon = deltaCost > 0 ? '❌' : '✅';

        // Calculate mode adherence from intervals (need to pass it separately)
        const modeAdherence = summary?.mode_adherence_pct || 0;
        const modeMatches = summary?.mode_matches || 0;
        const totalIntervals = summary?.total_intervals || 96;

        // Find biggest variance
        const biggestVariance = summary?.biggest_variance || null;

        return `
            <div class="yesterday-header">
                <h3>📊 Včera - Plán vs Skutečnost</h3>

                <div class="stats-row">
                    <div class="stat-box">
                        <div class="stat-label">💰 Plán</div>
                        <div class="stat-value">${plannedCost.toFixed(2)} Kč</div>
                    </div>

                    <div class="stat-box">
                        <div class="stat-label">💸 Skutečnost</div>
                        <div class="stat-value">${actualCost.toFixed(2)} Kč</div>
                    </div>

                    <div class="stat-box ${deltaClass}">
                        <div class="stat-label">📊 Výsledek</div>
                        <div class="stat-value">
                            ${deltaCost > 0 ? '+' : ''}${deltaCost.toFixed(2)} Kč<br>
                            <small>${deltaIcon} ${Math.abs(deltaPercent).toFixed(1)}% ${deltaCost > 0 ? 'horší' : 'lepší'}</small>
                        </div>
                    </div>
                </div>

                <div class="header-footer">
                    <div class="footer-stat">
                        ✅ Shoda režimů: ${modeAdherence.toFixed(0)}% (${modeMatches}/${totalIntervals} intervalů)
                    </div>
                    ${biggestVariance && biggestVariance.delta != null ? `
                        <div class="footer-stat">
                            ⚠️ Největší odchylka: ${biggestVariance.time} (${biggestVariance.delta > 0 ? '+' : ''}${biggestVariance.delta.toFixed(2)} Kč)
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }

    /**
     * Render top 3 variances ranking
     */
    renderTopVariances(variances) {
        if (variances.length === 0) {
            return '<div class="top-variances"><p>Žádné významné odchylky</p></div>';
        }

        const medals = ['🥇', '🥈', '🥉'];

        const html = variances.map((v, idx) => {
            // Safety check for null values
            const delta = v.delta ?? 0;
            const planned = v.planned ?? 0;

            const deltaClass = delta > 0 ? 'negative' : 'positive';
            const arrow = delta > 0 ? '⬆️' : '⬇️';
            const percent = planned > 0 ? Math.abs((delta / planned) * 100) : 0;

            return `
                <div class="variance-item ${deltaClass}">
                    <div class="variance-rank">${medals[idx] || `#${idx + 1}`}</div>
                    <div class="variance-details">
                        <div class="variance-time">${v.time || '--'}</div>
                        <div class="variance-modes">${v.plannedMode || '?'} → ${v.actualMode || '?'}</div>
                        <div class="variance-impact">
                            ${delta > 0 ? '+' : ''}${delta.toFixed(2)} Kč ${arrow} ${percent.toFixed(0)}% ${delta > 0 ? 'horší' : 'lepší'}
                        </div>
                        <div class="variance-reason">${v.reason || 'Žádný důvod'}</div>
                    </div>
                </div>
            `;
        }).join('');

        return `
            <div class="top-variances">
                <h4>⚠️ Top 3 největší odchylky</h4>
                ${html}
            </div>
        `;
    }

    /**
     * Render variance chart for VČERA
     */
    renderVarianceChart(intervals, dayType) {
        // Return placeholder div, actual chart will be rendered via Chart.js after DOM insert
        return `
            <div class="variance-chart-container">
                <h4>📊 Variance Analysis - Plán vs Skutečnost</h4>
                <canvas id="variance-chart-${dayType}" style="height: 300px;"></canvas>
            </div>
        `;
    }

    /**
     * Render live header for DNES tab (v2.1 compact format)
     */
    renderLiveHeader(progress, eodPrediction, unifiedCostData) {
        const now = new Date();
        const timeStr = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;

        const today = unifiedCostData || {};
        const eod = today.eod_prediction || {};
        const completed = today.completed_so_far || {};

        const progressPercent = today.progress_pct || progress.percent || 0;
        const eodPredicted = eod.predicted_total || eodPrediction.predicted || 0;
        // FIX: Use today.plan_total_cost FIRST (contains full day plan), not eod.planned_total
        const eodPlanned = today.plan_total_cost || eod.planned_total || eodPrediction.planned || 0;
        const eodSavingsPredicted = eod.predicted_savings || 0;

        const completedCost = completed.actual_cost || progress.actualCost || 0;
        const completedPlanned = completed.planned_cost || progress.plannedCost || 0;

        const eodDelta = eodPredicted - eodPlanned;
        const eodDeltaPct = eodPlanned > 0 ? ((eodDelta / eodPlanned) * 100) : 0;
        const eodDeltaClass = eodDelta < -0.5 ? 'positive' : eodDelta > 0.5 ? 'negative' : 'neutral';
        const eodDeltaIcon = eodDelta < -0.5 ? '✅' : eodDelta > 0.5 ? '❌' : '⚪';

        const completedDelta = completedCost - completedPlanned;
        const completedDeltaPct = completed.delta_pct || (completedPlanned > 0 ? ((completedDelta / completedPlanned) * 100) : 0);
        const completedDeltaClass = completedDelta < -0.5 ? 'positive' : completedDelta > 0.5 ? 'negative' : 'neutral';

        return `
            <div class="today-header-simple">
                <div class="header-progress">
                    <div class="progress-bar-large">
                        <div class="progress-fill" style="width: ${progressPercent}%"></div>
                        <div class="progress-label">${progressPercent.toFixed(0)}% dne • ${timeStr}</div>
                    </div>
                </div>

                <div class="header-cards">
                    <div class="card card-primary">
                        <div class="card-icon">💰</div>
                        <div class="card-content">
                            <div class="card-title">Odhad nákladů na konec dne</div>
                            <div class="card-value">${eodPredicted.toFixed(2)} Kč</div>
                            <div class="card-sub">plán: ${eodPlanned.toFixed(2)} Kč • ${eodDeltaIcon} ${eodDeltaPct > 0 ? '+' : ''}${eodDeltaPct.toFixed(1)}%</div>
                        </div>
                    </div>

                    <div class="card card-secondary">
                        <div class="card-icon">📊</div>
                        <div class="card-content">
                            <div class="card-title">Dosud skutečně</div>
                            <div class="card-value ${completedDeltaClass}">${completedCost.toFixed(2)} Kč</div>
                            <div class="card-sub">plán: ${completedPlanned.toFixed(2)} Kč • ${completedDeltaPct > 0 ? '+' : ''}${completedDeltaPct.toFixed(1)}%</div>
                        </div>
                    </div>

                    <div class="card card-accent">
                        <div class="card-icon">💎</div>
                        <div class="card-content">
                            <div class="card-title">Předpokládaná úspora</div>
                            <div class="card-value">${eodSavingsPredicted.toFixed(2)} Kč</div>
                            <div class="card-sub">vs. HOME I režim</div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
    /**
     * Render timeline chart for DNES tab
     */
    renderTimelineChart(intervals, dayType) {
        return `
            <div class="timeline-chart-container">
                <h4>📊 Timeline - Plán vs Skutečnost</h4>
                <canvas id="timeline-chart-${dayType}" style="height: 350px;"></canvas>
            </div>
        `;
    }

    /**
     * Calculate statistics from intervals
     */
    calculateStats(intervals) {
        let plannedCost = 0;
        let actualCost = 0;
        let modeMatches = 0;
        let totalIntervals = 0;

        intervals.forEach(interval => {
            if (interval.planned) {
                plannedCost += interval.planned.net_cost || 0;
            }

            if (interval.actual) {
                actualCost += interval.actual.net_cost || 0;
                totalIntervals++;

                if (interval.planned && interval.actual.mode_name === interval.planned.mode_name) {
                    modeMatches++;
                }
            }
        });

        return {
            plannedCost,
            actualCost,
            deltaCost: actualCost - plannedCost,
            modeMatches,
            totalIntervals,
            adherence: totalIntervals > 0 ? (modeMatches / totalIntervals) * 100 : 0
        };
    }

    /**
     * Get top N variances sorted by absolute delta
     */
    getTopVariances(intervals, count = 3) {
        const variances = [];

        intervals.forEach(interval => {
            if (!interval.actual || !interval.planned) return;

            const delta = (interval.actual.net_cost || 0) - (interval.planned.net_cost || 0);

            // Only include significant variances (>0.5 Kč)
            if (Math.abs(delta) < 0.5) return;

            const time = new Date(interval.time);
            const timeStr = `${time.getHours().toString().padStart(2, '0')}:${time.getMinutes().toString().padStart(2, '0')}`;

            variances.push({
                time: timeStr,
                delta: delta,
                planned: interval.planned.net_cost || 0,
                actual: interval.actual.net_cost || 0,
                plannedMode: interval.planned.mode_name || '?',
                actualMode: interval.actual.mode_name || '?',
                reason: this.getVarianceReason(interval)
            });
        });

        // Sort by absolute delta (biggest first)
        variances.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));

        return variances.slice(0, count);
    }

    /**
     * Determine reason for variance
     */
    getVarianceReason(interval) {
        const planned = interval.planned;
        const actual = interval.actual;

        if (!planned || !actual) return 'Neznámý důvod';

        // Check mode mismatch
        if (planned.mode_name !== actual.mode_name) {
            return `Režim se nezměnil na ${planned.mode_name}`;
        }

        // Check consumption variance
        const consumptionDelta = (actual.consumption_kwh || 0) - (planned.consumption_kwh || 0);
        if (Math.abs(consumptionDelta) > 0.1) {
            return consumptionDelta > 0 ? 'Vyšší spotřeba než plánováno' : 'Nižší spotřeba než plánováno';
        }

        // Check price variance
        const priceDelta = (actual.spot_price || 0) - (planned.spot_price || 0);
        if (Math.abs(priceDelta) > 0.1) {
            return priceDelta > 0 ? 'Vyšší cena než plánováno' : 'Nižší cena než plánováno';
        }

        return 'Odchylka způsobena kombinací faktorů';
    }

    /**
     * Calculate current progress (for DNES tab)
     */
    calculateProgress(intervals) {
        const now = new Date();
        const historical = intervals.filter(i => i.status === 'historical' || i.status === 'current');

        console.log(`[TimelineDialog] calculateProgress - total intervals: ${intervals.length}, historical: ${historical.length}`);

        if (historical.length > 0) {
            console.log('[TimelineDialog] Sample historical interval:', historical[0]);
            console.log('[TimelineDialog] Sample planned object:', historical[0].planned);
            console.log('[TimelineDialog] Sample actual object:', historical[0].actual);
            console.log('[TimelineDialog] Sample delta object:', historical[0].delta);
        }

        let plannedCost = 0;
        let actualCost = 0;
        let modeMatches = 0;

        historical.forEach((interval, idx) => {
            const pCost = interval.planned?.net_cost || 0;
            const aCost = interval.actual?.net_cost || 0;

            if (idx === 0) {
                console.log(`[TimelineDialog] First interval - planned.net_cost: ${interval.planned?.net_cost}, actual.net_cost: ${interval.actual?.net_cost}`);
            }

            plannedCost += pCost;
            actualCost += aCost;

            // Count mode matches
            if (interval.actual && interval.planned) {
                const plannedMode = interval.planned.mode_name || '';
                const actualMode = interval.actual.mode_name || '';
                if (plannedMode === actualMode) {
                    modeMatches++;
                }
            }
        });

        console.log(`[TimelineDialog] Progress - planned: ${plannedCost.toFixed(2)}, actual: ${actualCost.toFixed(2)}`);

        // Calculate % of day elapsed (96 intervals = 24 hours)
        const percent = (historical.length / 96) * 100;
        const modeAdherence = historical.length > 0 ? (modeMatches / historical.length) * 100 : 0;

        return {
            plannedCost,
            actualCost,
            percent,
            intervalsCompleted: historical.length,
            modeMatches,
            modeAdherence
        };
    }

    /**
     * Calculate EOD prediction (for DNES tab)
     */
    calculateEODPrediction(intervals) {
        const historical = intervals.filter(i => i.status === 'historical' || i.status === 'current');
        const planned = intervals.filter(i => i.status === 'planned');

        // Historical costs
        let historicalPlanned = 0;
        let historicalActual = 0;

        historical.forEach(interval => {
            historicalPlanned += interval.planned?.net_cost || 0;
            historicalActual += interval.actual?.net_cost || 0;
        });

        // Future planned costs
        let futurePlanned = 0;
        planned.forEach(interval => {
            futurePlanned += interval.planned?.net_cost || 0;
        });

        // Total planned
        const totalPlanned = historicalPlanned + futurePlanned;

        // Calculate drift ratio
        const driftRatio = historicalPlanned > 0 ? (historicalActual / historicalPlanned) : 1.0;

        // Predict EOD = actual so far + (future planned * drift ratio)
        const predicted = historicalActual + (futurePlanned * driftRatio);

        return {
            planned: totalPlanned,
            predicted: predicted
        };
    }

    /**
     * Start update interval (refresh every 60s)
     */
    startUpdateInterval() {
        this.stopUpdateInterval(); // Clear existing

        this.updateInterval = setInterval(() => {
            console.log('[TimelineDialog] Auto-refresh...');

            // Reload ALL tabs data in one call (force refresh)
            this.loadAllTabsData(true, this.plan).then(() => {
                // Re-render active tab with fresh data
                this.renderTab(this.activeTab);
            });
        }, 60000); // 60 seconds
    }

    /**
     * Stop update interval
     */
    stopUpdateInterval() {
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
            this.updateInterval = null;
        }
    }

    /**
     * Initialize Chart.js for VČERA tab - Variance Chart
     */
    initializeYesterdayCharts(intervals, dayType) {
        const canvasId = `variance-chart-${dayType}`;
        const canvas = document.getElementById(canvasId);

        if (!canvas) {
            console.warn(`[TimelineDialog] Canvas ${canvasId} not found`);
            return;
        }

        console.log(`[TimelineDialog] Initializing variance chart for ${dayType}`);

        // Prepare data
        const labels = [];
        const deltaData = [];
        const colors = [];

        intervals.forEach((interval, idx) => {
            const intervalTime = new Date(interval.time);
            const timeStr = `${intervalTime.getHours().toString().padStart(2, '0')}:${intervalTime.getMinutes().toString().padStart(2, '0')}`;

            // Show every 4th label (1 hour)
            labels.push(idx % 4 === 0 ? timeStr : '');

            // Calculate delta
            const delta = interval.actual && interval.planned
                ? (interval.actual.net_cost || 0) - (interval.planned.net_cost || 0)
                : 0;

            deltaData.push(delta);

            // Color coding
            let color = 'rgba(150, 150, 150, 0.5)';
            if (delta < -0.05) {
                color = 'rgba(76, 175, 80, 0.8)'; // Green - better
            } else if (delta > 0.05) {
                color = 'rgba(244, 67, 54, 0.8)'; // Red - worse
            } else if (interval.actual) {
                color = 'rgba(33, 150, 243, 0.8)'; // Blue - neutral
            }
            colors.push(color);
        });

        // Create chart
        const ctx = canvas.getContext('2d');
        if (this._costDeltaChart) {
            this._costDeltaChart.destroy();
        }
        this._costDeltaChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Odchylka od plánu (Kč)',
                    data: deltaData,
                    backgroundColor: colors,
                    borderColor: colors.map(c => c.replace('0.8', '1').replace('0.5', '0.8')),
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        enabled: true,
                        backgroundColor: 'rgba(30, 40, 50, 0.95)',
                        titleColor: 'rgba(255, 255, 255, 0.95)',
                        bodyColor: 'rgba(255, 255, 255, 0.8)',
                        borderColor: 'rgba(255, 255, 255, 0.2)',
                        borderWidth: 1,
                        callbacks: {
                            title: (context) => {
                                const idx = context[0].dataIndex;
                                const interval = intervals[idx];
                                const time = new Date(interval.time);
                                const endTime = new Date(time.getTime() + 15 * 60000);
                                return `${time.getHours().toString().padStart(2, '0')}:${time.getMinutes().toString().padStart(2, '0')} - ${endTime.getHours().toString().padStart(2, '0')}:${endTime.getMinutes().toString().padStart(2, '0')}`;
                            },
                            label: (context) => {
                                const idx = context.dataIndex;
                                const interval = intervals[idx];
                                const delta = context.parsed.y;

                                if (!interval.actual) {
                                    return 'Plánováno (ještě nenastalo)';
                                }

                                return [
                                    `Odchylka: ${delta >= 0 ? '+' : ''}${delta.toFixed(2)} Kč`,
                                    `Plán: ${(interval.planned?.net_cost || 0).toFixed(2)} Kč`,
                                    `Skutečnost: ${(interval.actual?.net_cost || 0).toFixed(2)} Kč`,
                                    `Režim: ${interval.actual?.mode_name || interval.planned?.mode_name || '?'}`
                                ];
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: {
                            display: false
                        },
                        ticks: {
                            color: 'rgba(255, 255, 255, 0.7)',
                            maxRotation: 0,
                            autoSkip: false
                        }
                    },
                    y: {
                        grid: {
                            color: 'rgba(255, 255, 255, 0.1)'
                        },
                        ticks: {
                            color: 'rgba(255, 255, 255, 0.7)',
                            callback: function(value) {
                                return value.toFixed(1) + ' Kč';
                            }
                        },
                        title: {
                            display: true,
                            text: 'Odchylka od plánu',
                            color: 'rgba(255, 255, 255, 0.9)'
                        }
                    }
                }
            }
        });
    }

    /**
     * Initialize Chart.js for DNES tab - Timeline Chart with NOW marker
     */
    initializeTodayCharts(intervals, dayType) {
        const canvasId = `timeline-chart-${dayType}`;
        const canvas = document.getElementById(canvasId);

        if (!canvas) {
            console.warn(`[TimelineDialog] Canvas ${canvasId} not found`);
            return;
        }

        console.log(`[TimelineDialog] Initializing timeline chart for ${dayType}`);

        const now = new Date();
        const labels = [];
        const deltaData = [];
        const colors = [];
        let nowIndex = -1;
        const modeSegments = this.buildModeSegmentsForChart(intervals);
        const timelineModeIconsOptions = modeSegments.length ? {
            segments: modeSegments,
            iconSize: 18,
            labelSize: 10,
            iconOffset: 10,
            iconColor: 'rgba(255, 255, 255, 0.95)',
            labelColor: 'rgba(255, 255, 255, 0.7)',
            backgroundOpacity: 0.14
        } : null;

        if (timelineModeIconsOptions) {
            ensureTimelineModeIconPluginRegistered();
        }

        intervals.forEach((interval, idx) => {
            const intervalTime = new Date(interval.time);
            const timeStr = `${intervalTime.getHours().toString().padStart(2, '0')}:${intervalTime.getMinutes().toString().padStart(2, '0')}`;

            labels.push(idx % 4 === 0 ? timeStr : '');

            const isHistorical = interval.status === 'historical' || interval.status === 'current';

            if (isHistorical && interval.actual && interval.planned) {
                const delta = (interval.actual.net_cost || 0) - (interval.planned.net_cost || 0);
                deltaData.push(delta);

                // Color: green/red/blue for historical
                if (delta < -0.05) {
                    colors.push('rgba(76, 175, 80, 0.8)');
                } else if (delta > 0.05) {
                    colors.push('rgba(244, 67, 54, 0.8)');
                } else {
                    colors.push('rgba(33, 150, 243, 0.8)');
                }
            } else {
                // Future: show as 0 with gray
                deltaData.push(0);
                colors.push('rgba(150, 150, 150, 0.3)');
            }

            // Find NOW marker
            if (intervalTime <= now) {
                nowIndex = idx;
            }
        });

        // Build annotations object for NOW marker
        const annotations = {};
        if (nowIndex >= 0) {
            annotations.nowLine = {
                type: 'line',
                xMin: nowIndex,
                xMax: nowIndex,
                borderColor: 'rgba(255, 152, 0, 0.8)',
                borderWidth: 3,
                label: {
                    display: true,
                    content: 'TEĎKA',
                    position: 'start',
                    backgroundColor: 'rgba(255, 152, 0, 0.9)',
                    color: '#fff',
                    font: {
                        size: 11,
                        weight: 'bold'
                    }
                }
            };
        }

        // Create chart with NOW marker annotation
        if (this.timelineCharts[dayType]) {
            try {
                this.timelineCharts[dayType].destroy();
            } catch (err) {
                // Ignore destroy errors
            }
            this.timelineCharts[dayType] = null;
        }

        const ctx = canvas.getContext('2d');
        const chart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Odchylka od plánu (Kč)',
                    data: deltaData,
                    backgroundColor: colors,
                    borderColor: colors.map(c => c.replace('0.8', '1').replace('0.3', '0.5')),
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        enabled: true,
                        callbacks: {
                            title: (context) => {
                                const idx = context[0].dataIndex;
                                const interval = intervals[idx];
                                const time = new Date(interval.time);
                                const endTime = new Date(time.getTime() + 15 * 60000);
                                return `${time.getHours().toString().padStart(2, '0')}:${time.getMinutes().toString().padStart(2, '0')} - ${endTime.getHours().toString().padStart(2, '0')}:${endTime.getMinutes().toString().padStart(2, '0')}`;
                            },
                            label: (context) => {
                                const idx = context.dataIndex;
                                const interval = intervals[idx];
                                const isHistorical = interval.status === 'historical' || interval.status === 'current';

                                if (!isHistorical || !interval.actual) {
                                    return 'Plánováno (ještě nenastalo)';
                                }

                                const delta = context.parsed.y;
                                return [
                                    `Odchylka: ${delta >= 0 ? '+' : ''}${delta.toFixed(2)} Kč`,
                                    `Plán: ${(interval.planned?.net_cost || 0).toFixed(2)} Kč`,
                                    `Skutečnost: ${(interval.actual?.net_cost || 0).toFixed(2)} Kč`,
                                    `Režim: ${interval.actual?.mode_name || interval.planned?.mode_name || '?'}`
                                ];
                            }
                        }
                    },
                    annotation: {
                        annotations: annotations
                    },
                    ...(timelineModeIconsOptions ? { timelineModeIcons: timelineModeIconsOptions } : {})
                },
                layout: {
                    padding: {
                        top: 12,
                        bottom: timelineModeIconsOptions
                            ? timelineModeIconsOptions.iconOffset + timelineModeIconsOptions.iconSize + timelineModeIconsOptions.labelSize + 6
                            : 12
                    }
                },
                scales: {
                    x: {
                        grid: {
                            display: false
                        },
                        ticks: {
                            color: 'var(--text-secondary)',
                            maxRotation: 0,
                            autoSkip: false
                        }
                    },
                    y: {
                        grid: {
                            color: 'rgba(255, 255, 255, 0.1)'
                        },
                        ticks: {
                            color: 'var(--text-secondary)',
                            callback: function(value) {
                                return value.toFixed(1) + ' Kč';
                            }
                        },
                        title: {
                            display: true,
                            text: 'Odchylka od plánu',
                            color: 'var(--text-secondary)'
                        }
                    }
                }
            }
        });

        this.timelineCharts[dayType] = chart;
        this.scheduleChartResize(chart, canvas);
    }

    /**
     * Destroy dialog instance
     */
    destroy() {
        this.close();
        this.dialogElement = null;
        this.cache = {
            hybrid: this.createEmptyCache()
        };
        this.plan = 'hybrid';
    }
}

// Global instance
var timelineDialogInstance = null;

// Initialize on page load
function initTimelineDialog() {
    timelineDialogInstance = new TimelineDialog();
    timelineDialogInstance.init();
}

// Open dialog (called from Today Plan Tile)
function openModeTimelineDialog(tabName = null, plan = null) {
    if (!timelineDialogInstance) {
        initTimelineDialog();
    }
    timelineDialogInstance.open(tabName, plan);
}

// Alias for openModeTimelineDialog (used by Unified Cost Tile onclick)
function openTimelineDialog(tabName = null, plan = null) {
    if (!timelineDialogInstance) {
        initTimelineDialog();
    }
    if (tabName) {
        timelineDialogInstance.open(tabName, plan);
    } else {
        timelineDialogInstance.open(null, plan);
    }
}

// Close dialog
function closeModeTimelineDialog() {
    if (timelineDialogInstance) {
        timelineDialogInstance.close();
    }
}

// =============================================================================
// END TIMELINE DIALOG
// =============================================================================

// Global instance for Today Plan Tile
var todayPlanTileInstance = null;

// =============================================================================


/**
 * Build extended timeline with historical data - ONLY TODAY's plan vs actual
 * Shows clear comparison for completed intervals
 */
async function buildExtendedTimeline() {
    const apiUrl = `/api/oig_cloud/battery_forecast/${INVERTER_SN}/detail_tabs?tab=today`;

    try {
        const response = await fetchWithAuth(apiUrl);
        if (!response.ok) {
            console.error('[Extended Timeline] Failed to fetch data:', response.status);
            return;
        }

        const data = await response.json();
        // API returns data in data.today object
        const todayData = data.today || data;
        const todayTileSummary = todayData.summary;
        const modeBlocks = todayData.mode_blocks;

        if (!modeBlocks || modeBlocks.length === 0) {
            console.warn('[Extended Timeline] No today data available');
            return;
        }

        console.log('[Extended Timeline] Loaded TODAY data:', {
            mode_blocks: modeBlocks.length,
            summary: todayTileSummary ? 'present' : 'missing'
        });

        // NOTE: renderTodayComparison() removed - replaced by Today Plan Tile
        // Old timeline comparison view is deprecated

        // Update Today Plan Tile (event-driven refresh)
        if (todayTileSummary) {
            renderTodayPlanTile(todayTileSummary);
        }

        // Update Cost Comparison Tile (event-driven refresh)
        if (typeof loadCostComparisonTile === 'function') {
            loadCostComparisonTile().catch((error) => {
                console.error('[TimelineDialog] Failed to load cost comparison tile', error);
            });
        }

    } catch (error) {
        console.error('[Extended Timeline] Error fetching data:', error);
    }
}

/**
 * Render Today Plan Tile - live tracking of today's plan vs actual with EOD prediction
 * Event-driven refresh triggered by buildExtendedTimeline()
 */

// Export timeline functions
window.DashboardTimeline = {
    MODE_CONFIG,
    TimelineDialog,
    initTimelineDialog,
    openModeTimelineDialog,
    openTimelineDialog,
    closeModeTimelineDialog,
    init: function() {
        console.log('[DashboardTimeline] Initialized');
        initTimelineDialog();
    }
};

// Export timelineDialogInstance to window for access from other modules
if (!window.hasOwnProperty('timelineDialogInstance')) {
    Object.defineProperty(window, 'timelineDialogInstance', {
        get: function() { return timelineDialogInstance; },
        set: function(value) { timelineDialogInstance = value; },
        configurable: true
    });
}

console.log('[DashboardTimeline] Module loaded');
