/* eslint-disable */
/**
 * Battery Health Dashboard Module
 * Zobrazuje kvalitu baterie (SoH%), quality metrics, cycle progress
 *
 * Umístění: Tab "💰 Predikce a statistiky" vedle Battery Efficiency
 * Import: Přidat do dashboard.html
 */

// Cache pro Battery Health data (change detection)
var batteryHealthCache = {
    soh: null,
    capacity: null,
    measurementCount: null,
    lastMeasured: null,
    degradation3m: null,
    degradation6m: null,
    degradation12m: null
};

/**
 * Update Battery Health statistics na Pricing tab
 * Načítá data z battery_health senzoru a zobrazuje SoH metriky
 * Používá change detection pro optimalizaci
 */
async function updateBatteryHealthStats() {
    const hass = getHass();
    if (!hass) {
        console.warn('[Battery Health] No HA connection');
        return;
    }

    const sensorId = `sensor.oig_${INVERTER_SN}_battery_health`;
    const sensor = hass.states[sensorId];

    console.log('[Battery Health] Checking sensor:', sensorId, 'state:', sensor?.state);

    if (!sensor) {
        console.log('[Battery Health] Sensor not found:', sensorId);
        return;
    }

    const attrs = sensor.attributes || {};
    const state = sensor.state; // Průměrný SoH% za 30 dní

    console.log('[Battery Health] Sensor state:', state, 'attributes:', attrs);

    // Získat data ze senzoru (NOVÁ STRUKTURA PO REFACTORINGU)
    const soh = (state !== 'unknown' && state !== 'unavailable') ? parseFloat(state) : null;

    // 30-day průměry
    const capacity = attrs.capacity_kwh || null; // Průměrná kapacita za 30 dní
    const measurementCount = attrs.measurement_count || 0;
    const lastMeasured = attrs.last_measured || null;
    const minCapacity = attrs.min_capacity_kwh || null;
    const maxCapacity = attrs.max_capacity_kwh || null;
    const qualityScore = attrs.quality_score || null;

    // Degradation trends (3, 6, 12 měsíců)
    const degradation3mPercent = attrs.degradation_3_months_percent || null;
    const degradation6mPercent = attrs.degradation_6_months_percent || null;
    const degradation12mPercent = attrs.degradation_12_months_percent || null;

    // Long-term trend (regression analysis)
    const degradationPerYearPercent = attrs.degradation_per_year_percent || null;
    const estimatedEolDate = attrs.estimated_eol_date || null;
    const yearsTo80Pct = attrs.years_to_80pct || null;
    const trendConfidence = attrs.trend_confidence || null;

    // Change detection
    const hasChanged =
        batteryHealthCache.soh !== soh ||
        batteryHealthCache.capacity !== capacity ||
        batteryHealthCache.measurementCount !== measurementCount ||
        batteryHealthCache.lastMeasured !== lastMeasured ||
        batteryHealthCache.degradation3m !== degradation3mPercent ||
        batteryHealthCache.degradation6m !== degradation6mPercent ||
        batteryHealthCache.degradation12m !== degradation12mPercent;

    if (!hasChanged) {
        // Žádné změny, přeskočit update
        return;
    }

    // Update cache
    batteryHealthCache.soh = soh;
    batteryHealthCache.capacity = capacity;
    batteryHealthCache.measurementCount = measurementCount;
    batteryHealthCache.lastMeasured = lastMeasured;
    batteryHealthCache.degradation3m = degradation3mPercent;
    batteryHealthCache.degradation6m = degradation6mPercent;
    batteryHealthCache.degradation12m = degradation12mPercent;

    console.log('[Battery Health] Values changed, updating UI:', {
        soh,
        capacity,
        measurementCount,
        lastMeasured,
        degradation3mPercent,
        degradation6mPercent,
        degradation12mPercent
    });

    // Najít nebo vytvořit battery health tile
    let container = document.getElementById('battery-health-container');
    if (!container) {
        // Vytvořit nový container
        container = createBatteryHealthContainer();
    }

    // Update HTML
    updateBatteryHealthUI(container, {
        soh,
        capacity,
        measurementCount,
        lastMeasured,
        minCapacity,
        maxCapacity,
        qualityScore,
        degradation3mPercent,
        degradation6mPercent,
        degradation12mPercent,
        degradationPerYearPercent,
        estimatedEolDate,
        yearsTo80Pct,
        trendConfidence
    });
}

/**
 * Vytvoří HTML container pro Battery Health tile
 */
function createBatteryHealthContainer() {
    console.log('[Battery Health] Creating new container');

    // Najít Battery Efficiency tile - je to .stat-card s #battery-efficiency-main uvnitř
    const efficiencyTile = document.querySelector('.stat-card #battery-efficiency-main');

    if (!efficiencyTile) {
        console.warn('[Battery Health] Battery Efficiency tile not found, trying fallback position');
        // Fallback: najít pricing-tab a vložit dovnitř
        const pricingTab = document.getElementById('pricing-tab');
        if (!pricingTab) {
            console.error('[Battery Health] Cannot find pricing tab!');
            return null;
        }

        // Vytvořit wrapper vedle první stat-card grid
        const statGrid = pricingTab.querySelector('div[style*="grid-template-columns"]');
        if (statGrid) {
            const wrapper = document.createElement('div');
            wrapper.className = 'battery-health-tile';
            wrapper.id = 'battery-health-container';

            // Vložit za stat-card grid
            statGrid.parentNode.insertBefore(wrapper, statGrid.nextSibling);

            console.log('[Battery Health] Container created at fallback position');
            return wrapper;
        }
    }

    // Najít parent .stat-card (rodič #battery-efficiency-main)
    const parentCard = efficiencyTile.closest('.stat-card');
    if (!parentCard) {
        console.error('[Battery Health] Cannot find parent stat-card');
        return null;
    }

    // Vytvořit novou stat-card pro Battery Health
    const wrapper = document.createElement('div');
    wrapper.className = 'stat-card battery-health-tile';
    wrapper.id = 'battery-health-container';
    wrapper.style.background = 'linear-gradient(135deg, rgba(76, 217, 100, 0.15) 0%, rgba(76, 217, 100, 0.05) 100%)';
    wrapper.style.border = '1px solid rgba(76, 217, 100, 0.3)';
    wrapper.style.minHeight = '160px'; // Shodný s efficiency tile pro konzistentní výšku

    // Vložit vedle Efficiency card (jako součást stejného grid)
    parentCard.parentNode.insertBefore(wrapper, parentCard.nextSibling);

    console.log('[Battery Health] Container created and positioned next to Efficiency');
    return wrapper;
}

/**
 * Aktualizuje UI Battery Health tile
 */
function updateBatteryHealthUI(container, data) {
    const {
        soh,
        capacity,
        measurementCount,
        lastMeasured,
        minCapacity,
        maxCapacity,
        qualityScore,
        degradation3mPercent,
        degradation6mPercent,
        degradation12mPercent,
        degradationPerYearPercent,
        estimatedEolDate,
        yearsTo80Pct,
        trendConfidence
    } = data;

    // Určit status a barvu
    let statusClass = 'status-unknown';
    let statusIcon = '❓';
    let statusText = 'Čekám na data';

    if (soh !== null) {
        if (soh >= 95) {
            statusClass = 'status-excellent';
            statusIcon = '✅';
            statusText = 'Výborný stav';
        } else if (soh >= 90) {
            statusClass = 'status-good';
            statusIcon = '✔️';
            statusText = 'Dobrý stav';
        } else if (soh >= 80) {
            statusClass = 'status-fair';
            statusIcon = '⚠️';
            statusText = 'Střední degradace';
        } else {
            statusClass = 'status-poor';
            statusIcon = '❌';
            statusText = 'Vysoká degradace';
        }
    }

    // Funkce pro barvu degradace
    const getDegradationColor = (value) => {
        if (value === null || value === undefined) return 'var(--text-secondary)';
        if (value <= 2) return '#44ff44'; // zelená - výborné
        if (value <= 5) return '#ffaa00'; // oranžová - střední
        return '#ff4444'; // červená - vysoká
    };

    // Degradace trendy (3/6/12 měsíců)
    let degradationHTML = '';
    if (degradation3mPercent !== null || degradation6mPercent !== null || degradation12mPercent !== null) {
        degradationHTML = `
            <div style="font-size: 0.75em; color: var(--text-secondary); margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.05);">
                <div style="font-weight: 600; margin-bottom: 4px;">📉 Degradace kapacity:</div>
                ${degradation3mPercent !== null ? `
                <div style="display: flex; justify-content: space-between; margin-top: 2px;">
                    <span>3 měsíce:</span>
                    <span style="color: ${getDegradationColor(degradation3mPercent)}; font-weight: 600;">${degradation3mPercent.toFixed(2)}%</span>
                </div>
                ` : ''}
                ${degradation6mPercent !== null ? `
                <div style="display: flex; justify-content: space-between; margin-top: 2px;">
                    <span>6 měsíců:</span>
                    <span style="color: ${getDegradationColor(degradation6mPercent)}; font-weight: 600;">${degradation6mPercent.toFixed(2)}%</span>
                </div>
                ` : ''}
                ${degradation12mPercent !== null ? `
                <div style="display: flex; justify-content: space-between; margin-top: 2px;">
                    <span>12 měsíců:</span>
                    <span style="color: ${getDegradationColor(degradation12mPercent)}; font-weight: 600;">${degradation12mPercent.toFixed(2)}%</span>
                </div>
                ` : ''}
            </div>
        `;
    }

    // Dlouhodobá predikce (pokud je dostatečná spolehlivost)
    let predictionHTML = '';
    if (trendConfidence !== null && trendConfidence >= 70 && yearsTo80Pct !== null) {
        const yearsText = yearsTo80Pct >= 10 ? '10+' : yearsTo80Pct.toFixed(1);
        const eolText = estimatedEolDate || 'N/A';

        predictionHTML = `
            <div style="font-size: 0.75em; color: var(--text-secondary); margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.05);">
                <div style="font-weight: 600; margin-bottom: 4px;">🔮 Dlouhodobá predikce:</div>
                ${degradationPerYearPercent !== null ? `
                <div style="display: flex; justify-content: space-between; margin-top: 2px;">
                    <span>Degradace/rok:</span>
                    <span style="color: ${getDegradationColor(degradationPerYearPercent)}; font-weight: 600;">${degradationPerYearPercent.toFixed(2)}%</span>
                </div>
                ` : ''}
                <div style="display: flex; justify-content: space-between; margin-top: 2px;">
                    <span>Do 80% SoH:</span>
                    <span style="color: var(--text-primary); font-weight: 600;">${yearsText} let</span>
                </div>
                ${eolText !== 'N/A' ? `
                <div style="display: flex; justify-content: space-between; margin-top: 2px;">
                    <span>Očekávaný konec:</span>
                    <span style="color: var(--text-primary); font-weight: 600;">${eolText}</span>
                </div>
                ` : ''}
                <div style="font-size: 0.85em; opacity: 0.7; margin-top: 4px; font-style: italic;">
                    Spolehlivost: ${trendConfidence.toFixed(0)}%
                </div>
            </div>
        `;
    }

    // Sestavit HTML (stat-card kompatibilní struktura)
    container.innerHTML = `
        <div class="stat-label" style="color: #4cd964; font-weight: 600; display: flex; justify-content: space-between; align-items: center;">
            <span>🔋 Kvalita baterie</span>
            <span class="battery-health-status ${statusClass}" style="font-size: 0.8em; padding: 4px 8px; border-radius: 12px;">
                ${statusIcon} ${statusText}
            </span>
        </div>

        ${soh !== null ? `
        <div class="stat-value" style="font-size: 1.8em; margin: 10px 0; color: #4cd964;">
            ${soh.toFixed(1)}<span style="font-size: 0.6em; opacity: 0.7;">% SoH</span>
        </div>
        <div style="font-size: 0.7em; color: var(--text-secondary); margin-top: -5px;">
            (z ${measurementCount || 0} měření)
        </div>
        ` : `
        <div style="text-align: center; padding: 20px 0; font-size: 0.9em; color: var(--text-secondary);">
            <div style="font-size: 2em; margin-bottom: 8px; opacity: 0.5;">⏳</div>
            <div>Čekám na první měření...</div>
            <div style="font-size: 0.8em; margin-top: 8px; padding: 8px; background: rgba(255,255,255,0.05); border-radius: 4px;">
                <div style="font-weight: 600; margin-bottom: 4px;">Jak to funguje:</div>
                <div style="text-align: left;">
                    1. Baterii vybijte pod 90% SoC<br>
                    2. Nabijte na 95%+ SoC<br>
                    3. Snažte se nabíjet čistě ze slunce<br>
                    4. Měření se uloží každý den v 01:00
                </div>
            </div>
        </div>
        `}

        <div style="font-size: 0.75em; color: var(--text-secondary); margin-top: 8px;">
            ${capacity !== null ? `
            <div style="display: flex; justify-content: space-between;">
                <span>📊 Aktuální kapacita:</span>
                <span style="color: var(--text-primary); font-weight: 600;">${capacity.toFixed(2)} kWh</span>
            </div>
            ${minCapacity !== null && maxCapacity !== null ? `
            <div style="display: flex; justify-content: space-between; font-size: 0.9em; opacity: 0.7;">
                <span>Rozsah:</span>
                <span>${minCapacity.toFixed(2)} - ${maxCapacity.toFixed(2)} kWh</span>
            </div>
            ` : ''}
            ` : ''}

            ${measurementCount > 0 ? `
            <div style="display: flex; justify-content: space-between; margin-top: 4px; padding-top: 4px; border-top: 1px solid rgba(255,255,255,0.05);">
                <span>📈 Počet měření:</span>
                <span style="color: var(--text-primary); font-weight: 600;">${measurementCount}</span>
            </div>
            ${lastMeasured ? `
            <div style="display: flex; justify-content: space-between; font-size: 0.9em; opacity: 0.7;">
                <span>Poslední měření:</span>
                <span>${new Date(lastMeasured).toLocaleDateString('cs-CZ')}</span>
            </div>
            ` : ''}
            ${qualityScore !== null ? `
            <div style="display: flex; justify-content: space-between;">
                <span>⭐ Kvalita:</span>
                <span style="color: var(--text-primary); font-weight: 600;">${qualityScore.toFixed(1)}/100</span>
            </div>
            ` : ''}
            ` : ''}
        </div>

        ${degradationHTML}
        ${predictionHTML}
    `;

    console.log('[Battery Health] UI updated successfully');
}

/**
 * Subscribe to battery_health sensor changes
 */
function subscribeBatteryHealthUpdates() {
    const hass = getHass();
    if (!hass) {
        console.warn('[Battery Health] Cannot subscribe - no HA connection');
        return;
    }

    const sensorId = `sensor.oig_${INVERTER_SN}_battery_health`;

    console.log('[Battery Health] Subscribing to updates:', sensorId);

    const watcher = window.DashboardStateWatcher;
    if (!watcher) {
        console.warn('[Battery Health] StateWatcher not available yet, retrying...');
        setTimeout(subscribeBatteryHealthUpdates, 500);
        return;
    }

    // Ensure watcher is running (idempotent)
    watcher.start({ intervalMs: 1000, prefixes: [`sensor.oig_${INVERTER_SN}_`] });

    // Register and subscribe once
    if (!window.__oigBatteryHealthWatcherUnsub) {
        watcher.registerEntities([sensorId]);
        window.__oigBatteryHealthWatcherUnsub = watcher.onEntityChange((entityId) => {
            if (entityId !== sensorId) return;
            console.log('[Battery Health] Sensor changed, updating...');
            updateBatteryHealthStats();
        });
    }

    // První načtení
    updateBatteryHealthStats();
}

// Export funkcí pro použití v dashboard.html
window.updateBatteryHealthStats = updateBatteryHealthStats;
window.subscribeBatteryHealthUpdates = subscribeBatteryHealthUpdates;

console.log('[Battery Health] Module loaded ✅');
