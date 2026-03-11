/* eslint-disable */
/**
 * OIG Cloud - Detail Tabs Dashboard Component
 *
 * FÁZE 6: Frontend integrace pro Detail Tabs API
 *
 * Purpose:
 * - Zobrazení mode-agregovaných dat pro Včera/Dnes/Zítra
 * - Mode match detection (plán vs. realita)
 * - Adherence % tracking
 * - Tab navigation
 *
 * API: /api/oig_cloud/battery_forecast/{box_id}/detail_tabs
 *
 * @author OIG Cloud Team
 * @version 1.0.0
 * @date 2025-11-06
 */

// Mode configuration (inherited from dashboard-timeline.js)
const DETAIL_TABS_MODE_CONFIG = {
    'HOME I': { icon: '🏠', color: 'rgba(76, 175, 80, 0.7)', label: 'HOME I' },
    'HOME II': { icon: '⚡', color: 'rgba(33, 150, 243, 0.7)', label: 'HOME II' },
    'HOME III': { icon: '🔋', color: 'rgba(156, 39, 176, 0.7)', label: 'HOME III' },
    'HOME UPS': { icon: '🛡️', color: 'rgba(255, 152, 0, 0.7)', label: 'HOME UPS' },
    'FULL HOME UPS': { icon: '🛡️', color: 'rgba(255, 152, 0, 0.7)', label: 'FULL HOME UPS' },
    'DO NOTHING': { icon: '⏸️', color: 'rgba(158, 158, 158, 0.7)', label: 'DO NOTHING' },
    'Unknown': { icon: '❓', color: 'rgba(158, 158, 158, 0.5)', label: 'Unknown' }
};

/**
 * DetailTabsDialog Class - manages the detail tabs popup dialog
 * Shows mode-aggregated data with adherence tracking
 */
class DetailTabsDialog {
    constructor(boxId) {
        this.boxId = boxId;
        this.dialogElement = null;
        this.isOpen = false;
        this.activeTab = 'today'; // Default tab - DNES
        this.plan = 'hybrid';
        this.cache = {
            yesterday: null,
            today: null,
            tomorrow: null,
            lastUpdate: null
        };
        this.updateInterval = null;
    }

    /**
     * Initialize dialog - called once on page load
     */
    init() {
        this.dialogElement = document.getElementById('detail-tabs-dialog');
        if (!this.dialogElement) {
            console.error('[DetailTabs] Dialog element not found');
            return;
        }

        // Setup close button
        const closeBtn = this.dialogElement.querySelector('.close-dialog');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.close());
        }

        // Setup tab buttons
        const tabBtns = this.dialogElement.querySelectorAll('.tab-btn');
        tabBtns.forEach((btn) => {
            btn.addEventListener('click', (e) => {
                const target = e.target;
                const tab = target.dataset.tab;
                if (tab) {
                    this.switchTab(tab);
                }
            });
        });

        console.log('[DetailTabs] Dialog initialized');
    }

    /**
     * Open dialog with specific tab
     */
    async open(tab = 'today', plan = 'hybrid') {
        if (!this.dialogElement) {
            console.error('[DetailTabs] Dialog not initialized');
            return;
        }

        this.isOpen = true;
        this.activeTab = tab;
        this.plan = plan || 'hybrid';
        this.dialogElement.style.display = 'block';

        // Fetch data
        await this.fetchData();

        // Render active tab
        this.switchTab(this.activeTab);

        // Start auto-refresh for today/tomorrow tabs (60s interval matches cache TTL)
        if (this.activeTab === 'today' || this.activeTab === 'tomorrow') {
            this.startAutoRefresh();
        }

        console.log(`[DetailTabs] Dialog opened with ${tab} tab (${this.plan})`);
    }

    /**
     * Close dialog
     */
    close() {
        if (this.dialogElement) {
            this.dialogElement.style.display = 'none';
        }
        this.isOpen = false;
        this.stopAutoRefresh();
        console.log('[DetailTabs] Dialog closed');
    }

    /**
     * Switch to specific tab
     */
    switchTab(tab) {
        this.activeTab = tab;

        // Update tab buttons
        const tabBtns = this.dialogElement?.querySelectorAll('.tab-btn');
        tabBtns?.forEach((btn) => {
            if (btn.dataset.tab === tab) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        // Render tab content
        this.renderTab(tab);

        // Auto-refresh strategy
        this.stopAutoRefresh();
        if (tab === 'today' || tab === 'tomorrow') {
            this.startAutoRefresh();
        }

        console.log(`[DetailTabs] Switched to ${tab} tab`);
    }

    /**
     * Fetch data from Detail Tabs API
     */
    async fetchData() {
        try {
            const params = [];
            if (this.plan) {
                params.push(`plan=${this.plan}`);
            }
            if (this.activeTab) {
                params.push(`tab=${this.activeTab}`);
            }
            const query = params.length ? `?${params.join('&')}` : '';
            const apiUrl = `/api/oig_cloud/battery_forecast/${this.boxId}/detail_tabs${query}`;
            console.log(`[DetailTabs] Fetching data from ${apiUrl}`);

            const response = await fetchWithAuth(apiUrl);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            this.cache = {
                yesterday: data.yesterday || null,
                today: data.today || null,
                tomorrow: data.tomorrow || null,
                lastUpdate: new Date()
            };

            console.log('[DetailTabs] Data fetched:', {
                yesterday: this.cache.yesterday?.mode_blocks?.length || 0,
                today: this.cache.today?.mode_blocks?.length || 0,
                tomorrow: this.cache.tomorrow?.mode_blocks?.length || 0
            });
        } catch (error) {
            console.error('[DetailTabs] Failed to fetch data:', error);
        }
    }

    /**
     * Render specific tab
     */
    renderTab(tab) {
        const container = document.getElementById(`${tab}-detail-container`);
        if (!container) {
            console.error(`[DetailTabs] Container for ${tab} not found`);
            return;
        }

        const tabData = this.cache[tab];
        if (!tabData || !tabData.mode_blocks || tabData.mode_blocks.length === 0) {
            container.innerHTML = this.renderNoData(tab);
            return;
        }

        // Render summary + mode blocks
        container.innerHTML = this.renderTabContent(tabData, tab);

        console.log(`[DetailTabs] Rendered ${tab} tab with ${tabData.mode_blocks.length} mode blocks`);
    }

    /**
     * Render tab content: summary + mode blocks
     */
    renderTabContent(tabData, tabName) {
        const { date, mode_blocks, summary } = tabData;

        const summaryHtml = this.renderSummary(summary, tabName);

        // Pro DNES tab: rozdělit na sekce podle statusu
        let blocksHtml = '';
        if (tabName === 'today') {
            const completedBlocks = mode_blocks.filter(b => b.status === 'completed');
            const currentBlocks = mode_blocks.filter(b => b.status === 'current');
            const plannedBlocks = mode_blocks.filter(b => b.status === 'planned');

            blocksHtml = `
                ${completedBlocks.length > 0 ? `
                    <div class="mode-section">
                        <h3 class="section-header">⏮️ Uplynulé</h3>
                        <div class="mode-blocks-container">
                            ${completedBlocks.map((block, index) => this.renderModeBlock(block, index)).join('')}
                        </div>
                    </div>
                ` : ''}

                ${currentBlocks.length > 0 ? `
                    <div class="mode-section current-section">
                        <h3 class="section-header">▶️ Aktuální</h3>
                        <div class="mode-blocks-container">
                            ${currentBlocks.map((block, index) => this.renderModeBlock(block, index)).join('')}
                        </div>
                    </div>
                ` : ''}

                ${plannedBlocks.length > 0 ? `
                    <div class="mode-section">
                        <h3 class="section-header">⏭️ Plán</h3>
                        <div class="mode-blocks-container">
                            ${plannedBlocks.map((block, index) => this.renderModeBlock(block, index)).join('')}
                        </div>
                    </div>
                ` : ''}
            `;
        } else {
            // VČERA/ZÍTRA: flat list
            blocksHtml = `
                <div class="mode-blocks-container">
                    ${mode_blocks.map((block, index) => this.renderModeBlock(block, index)).join('')}
                </div>
            `;
        }

        return `
            <div class="detail-tab-content">
                <!-- Summary Tiles -->
                ${summaryHtml}

                <!-- Mode Blocks -->
                ${blocksHtml}

                <!-- Date Footer -->
                <div class="tab-footer">
                    <span class="tab-date">📅 ${this.formatDate(date)}</span>
                </div>
            </div>
        `;
    }

    /**
     * Render summary tiles at top of tab
     * BE již počítá aggregované metriky v summary.metrics
     */
    renderSummary(summary, tabName) {
        if (!summary) {
            return '';
        }

        const { overall_adherence, mode_switches } = summary;
        const metrics = summary.metrics || {};

        // Hlavní 4 metriky (BE aggregace)
        const metricTiles = [
            this.renderSmartMetricTile(metrics.cost, '💰', 'Náklady', 'Kč', tabName),
            this.renderSmartMetricTile(metrics.solar, '☀️', 'Solární výroba', 'kWh', tabName),
            this.renderSmartMetricTile(metrics.consumption, '🏠', 'Spotřeba', 'kWh', tabName),
            this.renderSmartMetricTile(metrics.grid, '⚡', 'Odběr ze sítě', 'kWh', tabName),
        ]
            .filter(Boolean)
            .join('');

        // Kompaktní meta info pod hlavními metrikami
        const adherenceLabel = overall_adherence !== null && overall_adherence < 100
            ? `${overall_adherence.toFixed(0)}% shoda`
            : '✓ Dle plánu';

        const metaInfo = `
            <div class="summary-meta-compact">
                <span class="meta-item">${adherenceLabel}</span>
                <span class="meta-separator">|</span>
                <span class="meta-item">${mode_switches || 0} přepnutí</span>
            </div>
        `;

        return `
            <div class="summary-tiles-smart">
                ${metricTiles}
            </div>
            ${overall_adherence !== null && overall_adherence < 100 ? metaInfo : ''}
        `;
    }

    /**
     * Render smart metric tile - jednoduchý design s porovnáním
     * Logika: Pokud máme actual, zobrazujeme actual vs plán
     *         Pokud nemáme actual, zobrazujeme jen plán
     */
    renderSmartMetricTile(metric, icon, label, unit, tabName) {
        if (!metric) {
            return '';
        }

        const plan = Number(metric.plan ?? 0);
        const actualValue =
            metric.actual === null || metric.actual === undefined
                ? null
                : Number(metric.actual);
        const hasActual =
            actualValue !== null &&
            (metric.has_actual || metric.actual_samples > 0) &&
            tabName !== 'tomorrow';

        const mainValue = hasActual ? actualValue : plan;
        const mainLabel = hasActual ? 'Skutečnost' : 'Plán';

        const planRow = hasActual
            ? `
                <div class="tile-sub-row">
                    <span>Plán:</span>
                    <span>${this.formatMetricValue(plan)} ${unit}</span>
                </div>
            `
            : '';

        const hintRow =
            !hasActual && tabName === 'tomorrow'
                ? `
                    <div class="tile-sub-row hint-row">
                        Plánovaná hodnota (čeká na živá data)
                    </div>
                `
                : '';

        let deltaRow = '';
        if (hasActual) {
            const delta = actualValue - plan;
            const absDelta = Math.abs(delta);

            const preferLower = label === 'Náklady' || label === 'Odběr ze sítě';
            const preferHigher = label === 'Solární výroba';

            let deltaState = 'delta-neutral';
            if (absDelta >= 0.01) {
                if (preferLower) {
                    deltaState = delta <= 0 ? 'delta-better' : 'delta-worse';
                } else if (preferHigher) {
                    deltaState = delta >= 0 ? 'delta-better' : 'delta-worse';
                }
            }

            const deltaText =
                deltaState === 'delta-better'
                    ? 'Lépe než plán'
                    : deltaState === 'delta-worse'
                    ? 'Hůře než plán'
                    : 'Rozdíl vs. plán';

            const deltaValueText =
                absDelta >= 0.01
                    ? `${delta > 0 ? '+' : ''}${this.formatMetricValue(delta)} ${unit}`
                    : '±0';

            deltaRow = `
                <div class="tile-delta ${deltaState}">
                    <span>${deltaText}</span>
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

    renderSummaryMetricTile(metric, icon, label) {
        if (!metric) {
            return '';
        }

        const plan = metric.plan ?? 0;
        const actual = metric.actual ?? null;
        const unit = metric.unit || '';
        const hasActual = metric.has_actual;
        const delta =
            hasActual && actual !== null ? actual - plan : null;

        const planLabel = `${plan.toFixed(2)} ${unit}`;

        let actualHtml = '';
        if (hasActual && actual !== null) {
            const deltaClass =
                delta > 0 ? 'delta-positive' : delta < 0 ? 'delta-negative' : '';
            const deltaLabel =
                delta !== null && Math.abs(delta) > 0.009
                    ? `<span class="metric-delta ${deltaClass}">${delta > 0 ? '+' : ''}${delta.toFixed(2)} ${unit}</span>`
                    : '';
            actualHtml = `
                <div class="metric-actual">
                    <span class="metric-label">Skutečnost:</span>
                    <span class="metric-value">${actual.toFixed(2)} ${unit}</span>
                    ${deltaLabel}
                </div>
            `;
        }

        return `
            <div class="summary-tile metric-tile">
                <div class="tile-icon">${icon}</div>
                <div class="tile-label">${label}</div>
                <div class="metric-plan">
                    <span class="metric-label">Plán:</span>
                    <span class="metric-value">${planLabel}</span>
                </div>
                ${actualHtml}
            </div>
        `;
    }

    /**
     * Render single mode block
     */
    renderModeBlock(block, index) {
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
            solar_planned_kwh,
            solar_actual_kwh,
            consumption_planned_kwh,
            consumption_actual_kwh,
            grid_import_planned_kwh,
            grid_import_actual_kwh,
            grid_export_planned_kwh,
            grid_export_actual_kwh,
            interval_reasons
        } = block;

        // Get mode config
        const historicalMode = DETAIL_TABS_MODE_CONFIG[mode_historical] || DETAIL_TABS_MODE_CONFIG['Unknown'];
        const plannedMode = DETAIL_TABS_MODE_CONFIG[mode_planned] || DETAIL_TABS_MODE_CONFIG['Unknown'];

        // Status icon
        const statusIcons = {
            completed: '✅',
            current: '▶️',
            planned: '📅'
        };
        const statusIcon = statusIcons[status] || '❓';

        const isPlannedOnly = status === 'planned';
        const hasActualData =
            !isPlannedOnly &&
            mode_historical &&
            mode_historical !== 'Unknown' &&
            cost_historical !== null &&
            cost_historical !== undefined;

        // Match indicator
        const matchClass = isPlannedOnly
            ? 'match-neutral'
            : mode_match
              ? 'match-yes'
              : 'match-no';
        const matchIcon = isPlannedOnly ? 'ℹ️' : mode_match ? '✅' : '❌';
        const matchLabel = isPlannedOnly ? 'Plán' : mode_match ? 'Shoda' : 'Odchylka';

        // Cost delta indicator
        let costDeltaHtml = '';
        if (!isPlannedOnly && cost_delta !== null && cost_delta !== undefined) {
            const deltaClass = cost_delta > 0 ? 'cost-higher' : cost_delta < 0 ? 'cost-lower' : 'cost-equal';
            const deltaIcon = cost_delta > 0 ? '⬆️' : cost_delta < 0 ? '⬇️' : '➡️';
            costDeltaHtml = `
                <span class="cost-delta ${deltaClass}">
                    ${deltaIcon} ${cost_delta > 0 ? '+' : ''}${cost_delta.toFixed(2)} Kč
                </span>
            `;
        }

        // Build compact single-line layout
        let modeCompare;
        if (hasActualData && mode_planned !== 'Unknown') {
            modeCompare = `<span class="mode-badge" style="background: ${historicalMode.color};">${historicalMode.icon} ${historicalMode.label}</span>
               <span class="mode-arrow">→</span>
               <span class="mode-badge mode-planned" style="background: ${plannedMode.color};">${plannedMode.icon} ${plannedMode.label}</span>`;
        } else {
            modeCompare = `<span class="mode-badge mode-planned" style="background: ${plannedMode.color};">${plannedMode.icon} ${plannedMode.label}</span>`;
        }

        const costCompare = this.renderPlanActualValue(
            hasActualData ? cost_historical : null,
            cost_planned ?? 0,
            'Kč',
            costDeltaHtml
        );

        const modeLabelText = hasActualData ? 'Skutečnost/Plán:' : 'Plánovaný režim:';
        const costLabelText = hasActualData ? 'Cena (skutečná/plán):' : 'Plánovaná cena:';

        const timeRange = this.formatTimeRange(start_time, end_time);
        const reasonsHtml = this.renderIntervalReasons(interval_reasons, status);

        return `
            <div class="mode-block ${matchClass}" data-index="${index}">
                <div class="block-header">
                    <div class="block-time">
                        ${statusIcon} <strong>${timeRange}</strong>
                        <span class="block-duration">(${duration_hours?.toFixed(1)}h)</span>
                    </div>
                    <div class="block-match ${matchClass}">
                        ${matchIcon} ${matchLabel}
                    </div>
                </div>

                <div class="block-content-row">
                    <!-- Režim -->
                    <div class="block-item">
                        <span class="item-label">${modeLabelText}</span>
                        <div class="item-value">${modeCompare}</div>
                    </div>

                    <!-- Náklady -->
                    <div class="block-item">
                        <span class="item-label">${costLabelText}</span>
                        <div class="item-value">${costCompare}</div>
                    </div>

                    <!-- Solár -->
                    <div class="block-item">
                        <span class="item-label">☀️ Solár:</span>
                        <div class="item-value">
                            ${this.renderPlanActualValue(
                                solar_actual_kwh,
                                solar_planned_kwh,
                                'kWh'
                            )}
                        </div>
                    </div>

                    <!-- Spotřeba -->
                    <div class="block-item">
                        <span class="item-label">🏠 Spotřeba:</span>
                        <div class="item-value">
                            ${this.renderPlanActualValue(
                                consumption_actual_kwh,
                                consumption_planned_kwh,
                                'kWh'
                            )}
                        </div>
                    </div>

                    <!-- Import -->
                    <div class="block-item">
                        <span class="item-label">⬇️ Import:</span>
                        <div class="item-value">
                            ${this.renderPlanActualValue(
                                grid_import_actual_kwh,
                                grid_import_planned_kwh,
                                'kWh'
                            )}
                        </div>
                    </div>

                    <!-- Export -->
                    <div class="block-item">
                        <span class="item-label">⬆️ Export:</span>
                        <div class="item-value">
                            ${this.renderPlanActualValue(
                                grid_export_actual_kwh,
                                grid_export_planned_kwh,
                                'kWh'
                            )}
                        </div>
                    </div>

                    ${reasonsHtml}
                </div>
            </div>
        `;
    }

    renderIntervalReasons(intervalReasons, status) {
        if (!intervalReasons || intervalReasons.length === 0) {
            return '';
        }

        const items = intervalReasons.map(item => {
            const timeLabel = this.formatTimeLabel(item.time);
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

    renderPlanActualValue(actual, planned, unit = 'kWh', extra = '') {
        const hasActual =
            actual !== null && actual !== undefined;
        const planValue =
            planned !== null && planned !== undefined
                ? `${planned.toFixed(2)} ${unit}`
                : 'N/A';

        if (!hasActual) {
            return `<span class="metric-plan">${planValue}</span>`;
        }

        const delta = actual - (planned ?? 0);
        const deltaClass =
            delta > 0 ? 'delta-positive' : delta < 0 ? 'delta-negative' : '';
        const deltaLabel =
            Math.abs(delta) > 0.009
                ? `<span class="metric-delta ${deltaClass}">${delta > 0 ? '+' : ''}${delta.toFixed(2)} ${unit}</span>`
                : '';

        return `
            <span class="metric-value-pair">
                <span class="metric-actual">${actual.toFixed(2)} ${unit}</span>
                <span class="metric-arrow">→</span>
                <span class="metric-plan">${planValue}</span>
                ${deltaLabel}
                ${extra || ''}
            </span>
        `;
    }

    /**
     * Format ISO timestamps into local HH:MM range (cs-CZ)
     */
    formatTimeRange(startIso, endIso) {
        try {
            const fmt = new Intl.DateTimeFormat('cs-CZ', {
                hour: '2-digit',
                minute: '2-digit'
            });
            const startDate = new Date(startIso);
            const endDate = new Date(endIso);
            if (isNaN(startDate.getTime()) || isNaN(endDate.getTime())) {
                return `${startIso} - ${endIso}`;
            }
            return `${fmt.format(startDate)} – ${fmt.format(endDate)}`;
        } catch (err) {
            console.warn('[DetailTabs] Failed to format time range', err);
            return `${startIso} - ${endIso}`;
        }
    }

    formatTimeLabel(isoTs) {
        if (!isoTs) return '--:--';
        try {
            const dt = new Date(isoTs);
            if (isNaN(dt.getTime())) {
                return '--:--';
            }
            return dt.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' });
        } catch (err) {
            return '--:--';
        }
    }

    /**
     * Render "No Data" message
     */
    renderNoData(tab) {
        const messages = {
            yesterday: 'Včerejší data nejsou k dispozici',
            today: 'Dnešní data nejsou k dispozici',
            tomorrow: 'Plán pro zítřek ještě není k dispozici (OTE ceny přijdou po 13:00)'
        };

        return `
            <div class="no-data">
                <div class="no-data-icon">📊</div>
                <h3>${messages[tab] || 'Data nejsou k dispozici'}</h3>
            </div>
        `;
    }

    /**
     * Format date for display
     */
    formatDate(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        return date.toLocaleDateString('cs-CZ', {
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
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
     * Start auto-refresh timer
     */
    startAutoRefresh() {
        this.stopAutoRefresh();
        // Refresh every 60s to match cache TTL
        this.updateInterval = setInterval(async () => {
            if (this.isOpen) {
                console.log('[DetailTabs] Auto-refreshing data...');
                await this.fetchData();
                this.renderTab(this.activeTab);
            }
        }, 60000); // 60s
    }

    /**
     * Stop auto-refresh timer
     */
    stopAutoRefresh() {
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
            this.updateInterval = null;
        }
    }

    /**
     * Destroy dialog and cleanup
     */
    destroy() {
        this.close();
        this.cache = {
            yesterday: null,
            today: null,
            tomorrow: null,
            lastUpdate: null
        };
        console.log('[DetailTabs] Dialog destroyed');
    }
}

// Global instance
window.DetailTabsDialog = null;

/**
 * Initialize Detail Tabs Dialog
 */
function initDetailTabsDialog(boxId) {
    if (!window.DetailTabsDialog) {
        window.DetailTabsDialog = new DetailTabsDialog(boxId);
        window.DetailTabsDialog.init();
        console.log('[DetailTabs] Global instance created');
    }
}

/**
 * Open Detail Tabs Dialog
 */
function openDetailTabsDialog(tab = 'today', plan = 'hybrid') {
    if (window.DetailTabsDialog) {
        window.DetailTabsDialog.open(tab, plan);
    } else {
        console.error('[DetailTabs] Dialog not initialized. Call initDetailTabsDialog() first.');
    }
}

// Export for global access
window.initDetailTabsDialog = initDetailTabsDialog;
window.openDetailTabsDialog = openDetailTabsDialog;
