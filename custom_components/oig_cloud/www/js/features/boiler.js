/* eslint-disable */
/**
 * OIG Bojler Dashboard - Integrace do hlavního dashboardu
 * Heatmap, timeline, profiling
 */

// Global boiler state
const boilerState = {
    profiles: {},
    currentCategory: null,
    plan: null,
    charts: {},
    initialized: false,
    refreshTimer: null
};

// Czech labels
const CATEGORY_LABELS = {
    'workday_spring': 'Pracovní den - Jaro',
    'workday_summer': 'Pracovní den - Léto',
    'workday_autumn': 'Pracovní den - Podzim',
    'workday_winter': 'Pracovní den - Zima',
    'weekend_spring': 'Víkend - Jaro',
    'weekend_summer': 'Víkend - Léto',
    'weekend_autumn': 'Víkend - Podzim',
    'weekend_winter': 'Víkend - Zima',
};

const SOURCE_COLORS = {
    'fve': '#4CAF50',      // Zelená
    'grid': '#FF9800',     // Oranžová
    'alternative': '#2196F3', // Modrá
};

const DAY_LABELS = ['Po', 'Út', 'St', 'Čt', 'Pá', 'So', 'Ne'];

/**
 * Inicializace bojlerového dashboardu
 */
async function initBoilerDashboard() {
    console.log('🔥 [Boiler] Initializing dashboard');

    if (!boilerState.initialized) {
        boilerState.initialized = true;

        // Auto-refresh každých 5 minut (pouze jednou)
        boilerState.refreshTimer = setInterval(() => loadBoilerData(), 5 * 60 * 1000);
    }

    // Vždy načti aktuální data
    await loadBoilerData();
}

/**
 * Načtení dat z backend API
 */
/**
 * Load basic boiler data (profiles and plan)
 * Used for simple boiler tab
 */
async function loadBasicBoilerData() {
    try {
        console.log('🔥 [Boiler] Loading data from API');

        const entryId = new URLSearchParams(window.location.search).get('entry_id');
        if (!entryId) {
            console.error('[Boiler] Missing entry_id');
            return;
        }

        // Načíst profily
        const profilesResp = await fetch(`/api/oig_cloud/${entryId}/boiler_profile`);
        if (profilesResp.ok) {
            const data = await profilesResp.json();
            boilerState.profiles = data.profiles || {};
            boilerState.currentCategory = data.current_category;
            console.log(`🔥 [Boiler] Loaded ${Object.keys(boilerState.profiles).length} profiles`);
        }

        // Načíst plán
        const planResp = await fetch(`/api/oig_cloud/${entryId}/boiler_plan`);
        if (planResp.ok) {
            boilerState.plan = await planResp.json();
            console.log('🔥 [Boiler] Plan loaded');
        }

        // Update UI
        updateCategorySelector();
        createBoilerHeatmap();
        createBoilerTimeline();
        updateBoilerStats();

    } catch (err) {
        console.error('[Boiler] Failed to load data:', err);
    }
}

/**
 * Combined loader that hydrates both API-driven and hass-driven widgets.
 */
async function loadBoilerData() {
    try {
        await loadBasicBoilerData();
    } catch (error) {
        console.error('[Boiler] Basic loader failed:', error);
    }

    try {
        await loadExtendedBoilerData();
    } catch (error) {
        console.error('[Boiler] Extended loader failed:', error);
    }
}

/**
 * Update category selector
 */
function updateCategorySelector() {
    const select = document.getElementById('boiler-category-select');
    if (!select) return;

    select.innerHTML = '';

    Object.keys(CATEGORY_LABELS).forEach(cat => {
        const option = document.createElement('option');
        option.value = cat;
        option.textContent = CATEGORY_LABELS[cat];
        if (cat === boilerState.currentCategory) {
            option.selected = true;
        }
        select.appendChild(option);
    });
}

/**
 * Category change handler
 */
function onBoilerCategoryChange() {
    const select = document.getElementById('boiler-category-select');
    if (!select) return;

    boilerState.currentCategory = select.value;
    createBoilerHeatmap();
}

/**
 * Vytvoření heatmapy 7×24
 */
function createBoilerHeatmap() {
    const canvas = document.getElementById('boiler-heatmap-chart');
    if (!canvas) {
        console.warn('[Boiler] Heatmap canvas not found');
        return;
    }

    const profile = boilerState.profiles[boilerState.currentCategory];
    if (!profile) {
        console.warn('[Boiler] No profile for category:', boilerState.currentCategory);
        return;
    }

    // Destroy existing chart
    if (boilerState.charts.heatmap) {
        boilerState.charts.heatmap.destroy();
    }

    // Připravit data jako bar chart (horizontální)
    const datasets = [];
    const labels = [];

    // Vytvoř dataset pro každý den
    for (let day = 0; day < 7; day++) {
        const dayData = [];
        for (let hour = 0; hour < 24; hour++) {
            const consumption = profile.hourly_avg[hour] || 0;
            dayData.push(consumption);
        }

        datasets.push({
            label: DAY_LABELS[day],
            data: dayData,
            backgroundColor: `rgba(255, 152, 0, 0.${day + 3})`, // Různé opacity pro dny
            borderColor: 'rgba(255, 152, 0, 0.8)',
            borderWidth: 1,
        });
    }

    // Hour labels (0-23)
    for (let h = 0; h < 24; h++) {
        labels.push(`${h}h`);
    }

    const ctx = canvas.getContext('2d');
    boilerState.charts.heatmap = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                intersect: false,
                mode: 'index'
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top'
                },
                tooltip: {
                    callbacks: {
                        label(context) {
                            const day = context.dataset.label;
                            const hour = context.label;
                            const value = context.parsed.y;
                            return `${day} ${hour}: ${value.toFixed(3)} kWh`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    stacked: false,
                    title: {
                        display: true,
                        text: 'Hodina'
                    }
                },
                y: {
                    stacked: false,
                    title: {
                        display: true,
                        text: 'Spotřeba (kWh)'
                    },
                    beginAtZero: true
                }
            }
        }
    });
}

/**
 * Vytvoření timeline grafu
 */
function createBoilerTimeline() {
    const canvas = document.getElementById('boiler-timeline-chart');
    if (!canvas) {
        console.warn('[Boiler] Timeline canvas not found');
        return;
    }

    if (!boilerState.plan) {
        console.warn('[Boiler] No plan data');
        return;
    }

    // Destroy existing chart
    if (boilerState.charts.timeline) {
        boilerState.charts.timeline.destroy();
    }

    // Připravit data - groupnout sloty podle zdroje
    const fveData = [];
    const gridData = [];
    const altData = [];

    boilerState.plan.slots.forEach(slot => {
        const x = new Date(slot.start).getTime();
        const y = slot.avg_consumption_kwh;

        const point = { x, y };

        if (slot.recommended_source === 'fve') {
            fveData.push(point);
        } else if (slot.recommended_source === 'grid') {
            gridData.push(point);
        } else if (slot.recommended_source === 'alternative') {
            altData.push(point);
        }
    });

    const ctx = canvas.getContext('2d');
    boilerState.charts.timeline = new Chart(ctx, {
        type: 'bar',
        data: {
            datasets: [
                {
                    label: 'FVE (zdarma)',
                    data: fveData,
                    backgroundColor: SOURCE_COLORS.fve,
                    borderColor: SOURCE_COLORS.fve,
                    borderWidth: 1
                },
                {
                    label: 'Síť',
                    data: gridData,
                    backgroundColor: SOURCE_COLORS.grid,
                    borderColor: SOURCE_COLORS.grid,
                    borderWidth: 1
                },
                {
                    label: 'Alternativa',
                    data: altData,
                    backgroundColor: SOURCE_COLORS.alternative,
                    borderColor: SOURCE_COLORS.alternative,
                    borderWidth: 1
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'hour',
                        displayFormats: {
                            hour: 'HH:mm'
                        }
                    },
                    title: {
                        display: true,
                        text: 'Čas'
                    }
                },
                y: {
                    stacked: true,
                    title: {
                        display: true,
                        text: 'Spotřeba (kWh)'
                    },
                    beginAtZero: true
                }
            },
            plugins: {
                legend: {
                    position: 'top',
                }
            }
        }
    });
}

/**
 * Update statistik
 */
function updateBoilerStats() {
    if (!boilerState.plan) return;

    const totalEl = document.getElementById('boiler-total-consumption');
    const fveEl = document.getElementById('boiler-fve-consumption');
    const gridEl = document.getElementById('boiler-grid-consumption');
    const costEl = document.getElementById('boiler-estimated-cost');

    if (totalEl) totalEl.textContent = `${boilerState.plan.total_consumption_kwh.toFixed(2)} kWh`;
    if (fveEl) fveEl.textContent = `${boilerState.plan.fve_kwh.toFixed(2)} kWh`;
    if (gridEl) gridEl.textContent = `${boilerState.plan.grid_kwh.toFixed(2)} kWh`;
    if (costEl) costEl.textContent = `${boilerState.plan.estimated_cost_czk.toFixed(2)} Kč`;
}

/**
 * Toggle bojler control panel
 */
function toggleBoilerControlPanel() {
    const panel = document.getElementById('boiler-control-panel');
    if (!panel) return;

    const icon = document.getElementById('boiler-panel-toggle-icon');

    if (panel.classList.contains('minimized')) {
        panel.classList.remove('minimized');
        if (icon) icon.textContent = '−';
    } else {
        panel.classList.add('minimized');
        if (icon) icon.textContent = '+';
    }
}

// Export functions to global scope
window.initBoilerDashboard = initBoilerDashboard;
window.onBoilerCategoryChange = onBoilerCategoryChange;
window.toggleBoilerControlPanel = toggleBoilerControlPanel;

console.log('🔥 [Boiler] Dashboard script loaded');
// === BOILER DATA & CHART ===
var boilerChartInstance = null;

/**
 * Load extended boiler data (sensors, profile, energy breakdown, predictions, charts)
 * Used for advanced boiler dashboard
 */
async function loadExtendedBoilerData() {
    console.log('[Boiler] Loading boiler data...');

    try {
        // Update boiler sensor values
        await updateBoilerSensors();

        // Update boiler profile
        await updateBoilerProfile();

        // NEW: Update energy breakdown
        await updateBoilerEnergyBreakdown();

        // NEW: Update predicted usage
        await updateBoilerPredictedUsage();

        // NEW: Update grade thermometer
        await updateBoilerGradeThermometer();

        // NEW: Render profiling chart
        await renderBoilerProfilingChart();

        // NEW: Render heatmap
        await renderBoilerHeatmap();

        // Initialize or refresh boiler chart
        await initializeBoilerChart();

        console.log('[Boiler] Data loaded successfully');
    } catch (error) {
        console.error('[Boiler] Failed to load data:', error);
    }
}

async function updateBoilerSensors() {
    const hass = getHass();
    if (!hass) return;

    // Boiler sensors have different naming: sensor.oig_bojler_*
    const sensorMap = {
        'boiler-soc-value': 'sensor.oig_bojler_stav_nabiti',
        'boiler-temp-top-value': 'sensor.oig_bojler_teplota_nahore',
        'boiler-energy-required-value': 'sensor.oig_bojler_pozadovana_energie',
        'boiler-plan-cost-value': 'sensor.oig_bojler_cena_planu_ohrevu'
    };

    for (const [elementId, entityId] of Object.entries(sensorMap)) {
        const state = hass?.states?.[entityId];

        const element = document.getElementById(elementId);
        if (element && state) {
            const value = parseFloat(state.state);
            if (!isNaN(value)) {
                if (entityId.includes('stav_nabiti')) {
                    element.textContent = `${value.toFixed(0)} %`;
                } else if (entityId.includes('teplota')) {
                    element.textContent = `${value.toFixed(1)} °C`;
                } else if (entityId.includes('energie')) {
                    element.textContent = `${value.toFixed(2)} kWh`;
                } else if (entityId.includes('cena')) {
                    element.textContent = `${value.toFixed(2)} Kč`;
                }
            }
        }
    }

    // Update plan info
    const planEntityId = 'sensor.oig_bojler_cena_planu_ohrevu';
    const planState = hass?.states?.[planEntityId];

    if (planState?.attributes?.plan) {
        const plan = planState.attributes.plan;
        const slots = plan.slots || [];
        const activeSlots = slots.filter(s => s.heating).length;

        document.getElementById('boiler-plan-digest').textContent = plan.digest || 'N/A';
        document.getElementById('boiler-plan-slots').textContent = slots.length;
        document.getElementById('boiler-plan-active-slots').textContent = activeSlots;

        if (slots.length > 0) {
            const startTime = new Date(slots[0].start_time);
            const endTime = new Date(slots[slots.length - 1].start_time);

            document.getElementById('boiler-plan-start').textContent = startTime.toLocaleString('cs-CZ', {
                day: '2-digit',
                month: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
            document.getElementById('boiler-plan-end').textContent = endTime.toLocaleString('cs-CZ', {
                day: '2-digit',
                month: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        }
    }
}

async function updateBoilerProfile() {
    // Get configuration from energy sensor attributes
    const hass = getHass();
    if (!hass) return;

    const energyEntityId = 'sensor.oig_bojler_pozadovana_energie';
    const energyState = hass?.states?.[energyEntityId];

    if (energyState?.attributes) {
        const attrs = energyState.attributes;

        document.getElementById('boiler-profile-volume').textContent = `${attrs.volume_l || '--'} L`;
        document.getElementById('boiler-profile-target-temp').textContent = `${attrs.target_temp_c || '--'} °C`;

        // Deadline from plan or config
        const planEntityId = 'sensor.oig_bojler_cena_planu_ohrevu';
        const planState = hass?.states?.[planEntityId];
        const deadline = planState?.attributes?.plan?.deadline || attrs.deadline || '--:--';
        document.getElementById('boiler-profile-deadline').textContent = deadline;

        document.getElementById('boiler-profile-stratification').textContent = attrs.stratification_mode || attrs.method || '--';
        document.getElementById('boiler-profile-k-constant').textContent = attrs.k_constant?.toFixed(4) || '--';

        // Heater power - hide if element doesn't exist
        const heaterPowerEl = document.getElementById('boiler-profile-heater-power');
        if (heaterPowerEl) {
            heaterPowerEl.textContent = '--'; // Not available in attributes
        }
    }
}

async function initializeBoilerChart() {
    const canvas = document.getElementById('boiler-chart');
    if (!canvas) {
        console.warn('[Boiler] Chart canvas not found');
        return;
    }

    const hass = getHass();
    if (!hass) {
        console.warn('[Boiler] Hass not available for chart');
        return;
    }

    // Lazy load boiler chart module
    if (!window.BoilerChartModule) {
        try {
            const module = await import('./modules/boiler-chart.js');
            window.BoilerChartModule = module.BoilerChartModule;
        } catch (error) {
            console.error('[Boiler] Failed to load boiler-chart.js:', error);
            return;
        }
    }

    // Create or refresh chart instance
    if (!boilerChartInstance) {
        boilerChartInstance = new window.BoilerChartModule();
        await boilerChartInstance.init(canvas, hass, INVERTER_SN);
    } else {
        await boilerChartInstance.refresh();
    }
}

// Boiler control functions (will use ServiceShield)
async function planBoilerHeating() {
    console.log('[Boiler] Planning heating...');

    const hass = getHass();
    if (!hass) return;

    const service = 'oig_cloud.plan_boiler_heating';
    const entityId = 'sensor.oig_bojler_cena_planu_ohrevu';

    try {
        await hass.callService('oig_cloud', 'plan_boiler_heating', {
            entity_id: entityId
        });

        showNotification('✅ Plán topení byl úspěšně vytvořen', 'success');

        // Refresh after planning
        setTimeout(() => loadBoilerData(), 2000);
    } catch (error) {
        console.error('[Boiler] Failed to plan heating:', error);
        showNotification('❌ Chyba při plánování topení', 'error');
    }
}

async function applyBoilerPlan() {
    console.log('[Boiler] Applying heating plan...');

    const hass = getHass();
    if (!hass) return;

    const service = 'oig_cloud.apply_boiler_plan';
    const entityId = 'sensor.oig_bojler_cena_planu_ohrevu';

    try {
        await hass.callService('oig_cloud', 'apply_boiler_plan', {
            entity_id: entityId
        });

        showNotification('✅ Plán topení byl aplikován', 'success');

        // Refresh after applying
        setTimeout(() => loadBoilerData(), 2000);
    } catch (error) {
        console.error('[Boiler] Failed to apply plan:', error);
        showNotification('❌ Chyba při aplikaci plánu', 'error');
    }
}

async function cancelBoilerPlan() {
    console.log('[Boiler] Canceling heating plan...');

    const hass = getHass();
    if (!hass) return;

    const service = 'oig_cloud.cancel_boiler_plan';
    const entityId = 'sensor.oig_bojler_cena_planu_ohrevu';

    try {
        await hass.callService('oig_cloud', 'cancel_boiler_plan', {
            entity_id: entityId
        });

        showNotification('✅ Plán topení byl zrušen', 'success');

        // Refresh after canceling
        setTimeout(() => loadBoilerData(), 2000);
    } catch (error) {
        console.error('[Boiler] Failed to cancel plan:', error);
        showNotification('❌ Chyba při rušení plánu', 'error');
    }
}

// NEW: Update energy breakdown (grid vs alternative)
async function updateBoilerEnergyBreakdown() {
    const hass = getHass();
    if (!hass) return;

    const planEntityId = 'sensor.oig_bojler_cena_planu_ohrevu';
    const planState = hass?.states?.[planEntityId];

    if (planState?.attributes?.plan) {
        const plan = planState.attributes.plan;
        const gridEnergy = plan.grid_energy_kwh || 0;
        const gridCost = plan.grid_cost_czk || 0;
        const altEnergy = plan.alt_energy_kwh || 0;
        const altCost = plan.alt_cost_czk || 0;

        // Update breakdown cards
        document.getElementById('boiler-grid-energy-value').textContent =
            `${gridEnergy.toFixed(2)} kWh (${gridCost.toFixed(2)} Kč)`;
        document.getElementById('boiler-alt-energy-value').textContent =
            `${altEnergy.toFixed(2)} kWh (${altCost.toFixed(2)} Kč)`;

        // Update heating ratio bar
        const totalEnergy = gridEnergy + altEnergy;
        if (totalEnergy > 0) {
            const gridPercent = (gridEnergy / totalEnergy) * 100;
            const altPercent = (altEnergy / totalEnergy) * 100;

            document.getElementById('boiler-ratio-grid').style.width = `${gridPercent}%`;
            document.getElementById('boiler-ratio-alt').style.width = `${altPercent}%`;
            document.getElementById('boiler-ratio-grid-label').textContent = `${gridPercent.toFixed(0)}% síť`;
            document.getElementById('boiler-ratio-alt-label').textContent = `${altPercent.toFixed(0)}% alternativa`;
        }
    }
}

// NEW: Update predicted usage
async function updateBoilerPredictedUsage() {
    const hass = getHass();
    if (!hass) return;

    const energyEntityId = 'sensor.oig_bojler_pozadovana_energie';
    const energyState = hass?.states?.[energyEntityId];

    if (energyState?.attributes) {
        const predictedToday = energyState.attributes.predicted_usage_today || 0;
        const peakHours = energyState.attributes.peak_hours || [];

        document.getElementById('boiler-predicted-today').textContent = `${predictedToday.toFixed(2)} kWh`;
        document.getElementById('boiler-peak-hours').textContent = peakHours.map(h => `${h}h`).join(', ') || '--';

        // Calculate approximate liters at 40°C
        // Energy = Volume × (40 - 15) × 0.00116
        // Volume = Energy / (25 × 0.00116)
        const liters = predictedToday / (25 * 0.00116);
        document.getElementById('boiler-water-liters').textContent = `${liters.toFixed(0)} L`;
    }
}

// NEW: Update grade thermometer
async function updateBoilerGradeThermometer() {
    const hass = getHass();
    if (!hass) return;

    const tempTopEntityId = 'sensor.oig_bojler_teplota_nahore';
    const socEntityId = 'sensor.oig_bojler_stav_nabiti';
    const energyEntityId = 'sensor.oig_bojler_pozadovana_energie';

    const tempTopState = hass?.states?.[tempTopEntityId];
    const socState = hass?.states?.[socEntityId];
    const energyState = hass?.states?.[energyEntityId];

    if (tempTopState && socState) {
        const tempTop = parseFloat(tempTopState.state);
        const soc = parseFloat(socState.state);
        const tempBottom = energyState?.attributes?.temp_bottom_c || tempTop * 0.8;
        const targetTemp = energyState?.attributes?.target_temp_c || 60;

        // Update water level (based on SOC)
        document.getElementById('boiler-water-level').style.height = `${soc}%`;

        // Update grade label
        document.getElementById('boiler-grade-label').textContent = `${soc.toFixed(0)}% nahřáto`;

        // Update sensor markers
        // Temperature range: 10°C (bottom) to 70°C (top)
        // Position calculation: (temp - 10) / (70 - 10) * 100
        const topPosition = ((tempTop - 10) / 60) * 100;
        const bottomPosition = ((tempBottom - 10) / 60) * 100;
        const targetPosition = ((targetTemp - 10) / 60) * 100;

        document.getElementById('boiler-sensor-top').style.bottom = `${topPosition}%`;
        document.getElementById('boiler-sensor-top').querySelector('.sensor-label').textContent = `${tempTop.toFixed(1)}°C`;

        document.getElementById('boiler-sensor-bottom').style.bottom = `${bottomPosition}%`;
        document.getElementById('boiler-sensor-bottom').querySelector('.sensor-label').textContent = `${tempBottom.toFixed(1)}°C`;

        document.getElementById('boiler-target-line').style.bottom = `${targetPosition}%`;
    }
}

// NEW: Render profiling chart
async function renderBoilerProfilingChart() {
    const canvas = document.getElementById('boiler-profile-chart');
    if (!canvas) return;

    try {
        const hass = getHass();
        if (!hass) {
            console.warn('[Boiler] Hass not available');
            return;
        }

        // Get data from sensor attributes
        const energySensor = hass.states['sensor.oig_bojler_pozadovana_energie'];
        if (!energySensor || !energySensor.attributes) {
            console.warn('[Boiler] Energy sensor not available');
            return;
        }

        const attrs = energySensor.attributes;
        const hourlyData = attrs.hourly_avg_kwh || {};
        const peakHours = attrs.peak_hours || [];
        const predictedToday = attrs.predicted_usage_today || 0;
        const daysTracked = attrs.days_tracked || 7;

        // Prepare data for chart
        const labels = Array.from({ length: 24 }, (_, i) => `${i}h`);
        const data = labels.map((_, i) => parseFloat(hourlyData[i] || 0));

        // Destroy existing chart
        if (window.boilerProfileChart) {
            window.boilerProfileChart.destroy();
        }

        // Create new chart
        const ctx = canvas.getContext('2d');
        window.boilerProfileChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Průměrná spotřeba (kWh)',
                    data: data,
                    backgroundColor: labels.map((_, i) =>
                        peakHours.includes(i)
                            ? 'rgba(244, 67, 54, 0.6)'
                            : 'rgba(33, 150, 243, 0.6)'
                    ),
                    borderColor: labels.map((_, i) =>
                        peakHours.includes(i)
                            ? 'rgba(244, 67, 54, 1)'
                            : 'rgba(33, 150, 243, 1)'
                    ),
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${context.parsed.y.toFixed(2)} kWh`
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'kWh'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Hodina'
                        }
                    }
                }
            }
        });

        // Update stats
        document.getElementById('profile-stat-today').textContent = `${predictedToday.toFixed(2)} kWh`;
        document.getElementById('profile-stat-peaks').textContent = peakHours.map(h => `${h}h`).join(', ') || '--';
        document.getElementById('profile-stat-days').textContent = `${daysTracked} dní`;

    } catch (error) {
        console.error('[Boiler] Error rendering profiling chart:', error);
    }
}

// NEW: Render heatmap
async function renderBoilerHeatmap() {
    const container = document.getElementById('boiler-heatmap');
    if (!container) return;

    try {
        const hass = getHass();
        if (!hass) {
            console.warn('[Boiler] Hass not available');
            return;
        }

        // Get data from sensor attributes
        const energySensor = hass.states['sensor.oig_bojler_pozadovana_energie'];
        if (!energySensor || !energySensor.attributes) {
            console.warn('[Boiler] Energy sensor not available for heatmap');
            return;
        }

        const attrs = energySensor.attributes;
        const heatmapData = attrs.heatmap_data || [];

        // If no heatmap_data, build from hourly_avg_kwh
        let dataMatrix = heatmapData;
        if (!heatmapData || heatmapData.length === 0) {
            const hourlyData = attrs.hourly_avg_kwh || {};
            dataMatrix = Array.from({ length: 7 }, () =>
                Array.from({ length: 24 }, (_, hour) => parseFloat(hourlyData[hour] || 0))
            );
        }

        // Calculate thresholds
        const allValues = dataMatrix.flat();
        const maxValue = Math.max(...allValues, 0.1);
        const lowThreshold = maxValue * 0.3;
        const highThreshold = maxValue * 0.7;

        // Clear container
        container.innerHTML = '';

        // Day labels
        const days = ['Po', 'Út', 'St', 'Čt', 'Pá', 'So', 'Ne'];

        // Header row with hour labels
        const headerDiv = document.createElement('div');
        headerDiv.className = 'heatmap-day-label';
        container.appendChild(headerDiv);

        for (let hour = 0; hour < 24; hour++) {
            const hourLabel = document.createElement('div');
            hourLabel.className = 'heatmap-hour-label';
            hourLabel.textContent = hour;
            container.appendChild(hourLabel);
        }

        // Rows for each day
        days.forEach((day, dayIndex) => {
            const dayLabel = document.createElement('div');
            dayLabel.className = 'heatmap-day-label';
            dayLabel.textContent = day;
            container.appendChild(dayLabel);

            for (let hour = 0; hour < 24; hour++) {
                const value = dataMatrix[dayIndex]?.[hour] || 0;
                const cell = document.createElement('div');
                cell.className = 'heatmap-cell';

                if (value === 0) {
                    cell.classList.add('none');
                } else if (value < lowThreshold) {
                    cell.classList.add('low');
                } else if (value < highThreshold) {
                    cell.classList.add('medium');
                } else {
                    cell.classList.add('high');
                }

                cell.title = `${day} ${hour}h: ${value.toFixed(2)} kWh`;
                container.appendChild(cell);
            }
        });

    } catch (error) {
        console.error('[Boiler] Error rendering heatmap:', error);
    }
}

function toggleBoilerControlPanel() {
    const panel = document.getElementById('boiler-control-panel');
    const icon = document.getElementById('boiler-panel-toggle-icon');

    if (panel.classList.contains('minimized')) {
        panel.classList.remove('minimized');
        icon.textContent = '−';
    } else {
        panel.classList.add('minimized');
        icon.textContent = '+';
    }
}

// Removed duplicate showNotification - using DashboardUtils.showNotification instead


// Export enhanced boiler functions
window.DashboardBoiler = Object.assign(window.DashboardBoiler || {}, {
    initBoilerDashboard,
    loadBoilerData,
    loadBasicBoilerData,
    loadExtendedBoilerData,
    initializeBoilerChart,
    renderBoilerProfilingChart,
    renderBoilerHeatmap,
    updateBoilerSensors,
    updateBoilerProfile,
    planBoilerHeating,
    applyBoilerPlan,
    cancelBoilerPlan,
    init: function() {
        console.log('[DashboardBoiler] Enhanced - Data & Chart loaded');
    }
});

console.log('[DashboardBoiler] Enhanced module loaded');
