/* eslint-disable */
// === SHIELD INTEGRATION FUNCTIONS ===

// Debouncing timers (only for shield-specific functions)
let shieldMonitorTimer = null;
let timelineRefreshTimer = null;

// Debounced shield monitor - prevents excessive calls when shield sensors change rapidly
function debouncedShieldMonitor() {
    try {
        if (shieldMonitorTimer) clearTimeout(shieldMonitorTimer);
    } catch (e) { }
    try {
        shieldMonitorTimer = setTimeout(() => {
        monitorShieldActivity();
        updateShieldQueue();
        updateShieldUI();
        updateButtonStates();
        }, 100); // Wait 100ms before executing (shorter delay for responsive UI)
    } catch (e) {
        // Firefox can throw NS_ERROR_NOT_INITIALIZED if the document/window is being torn down.
        shieldMonitorTimer = null;
    }
}

// Debounced timeline refresh - for Today Plan Tile updates
function debouncedTimelineRefresh() {
    try {
        if (timelineRefreshTimer) clearTimeout(timelineRefreshTimer);
    } catch (e) { }
    try {
        timelineRefreshTimer = setTimeout(() => {
        window.DashboardTimeline?.buildExtendedTimeline?.();
        }, 300); // Wait 300ms before executing
    } catch (e) {
        // Firefox can throw NS_ERROR_NOT_INITIALIZED if the document/window is being torn down.
        timelineRefreshTimer = null;
    }
}

// Subscribe to shield status changes
function subscribeToShield() {
    const hass = getHass();
    if (!hass) {
        console.warn('Cannot subscribe to shield - no HA connection');
        return;
    }

    console.log('[Shield] Subscribing to state changes...');

    try {
        // IMPORTANT: Do NOT create extra `subscribeEvents('state_changed')` subscriptions here.
        // Mobile Safari / HA app can fall behind and HA will stop sending after 4096 pending messages.
        const watcher = window.DashboardStateWatcher;
        if (!watcher) {
            console.warn('[Shield] StateWatcher not available yet, retrying...');
            setTimeout(subscribeToShield, 500);
            return;
        }

        // Start watcher (idempotent)
        watcher.start({
            intervalMs: 1000,
            prefixes: [
                `sensor.oig_${INVERTER_SN}_`,
            ],
        });

        // Prevent duplicate callback registrations
        if (!window.__oigShieldWatcherUnsub) {
            const lastPricingPayload = new Map(); // entityId -> stable signature for skip logic

            window.__oigShieldWatcherUnsub = watcher.onEntityChange((entityId, newState) => {
                if (!entityId) return;

                // Shield status sensors
                if (entityId.includes('service_shield_')) {
                    debouncedShieldMonitor();
                }

                // Target state sensors (box mode, boiler mode, grid delivery)
                if (entityId.includes('box_prms_mode') ||
                    entityId.includes('boiler_manual_mode') ||
                    entityId.includes('invertor_prms_to_grid') ||
                    entityId.includes('invertor_prm1_p_max_feed_grid')) {
                    debouncedShieldMonitor();
                }

                // Data sensors - trigger loadData() on changes
                if (entityId.includes('actual_pv') ||           // Solar power
                    entityId.includes('actual_batt') ||         // Battery power
                    entityId.includes('actual_aci_wtotal') ||   // Grid power
                    entityId.includes('actual_aco_p') ||        // House power
                    entityId.includes('boiler_current_cbb_w') || // Boiler power
                    entityId.includes('extended_battery_soc') || // Battery SOC
                    entityId.includes('extended_battery_voltage') || // Battery voltage
                    entityId.includes('box_temp') ||            // Inverter temp
                    entityId.includes('bypass_status') ||       // Bypass status
                    entityId.includes('chmu_warning_level') ||  // ČHMÚ weather warning
                    entityId.includes('battery_efficiency') ||  // Battery efficiency stats
                    entityId.includes('real_data_update')) {    // Real data update
                    debouncedLoadData();
                }

                // Detail sensors - trigger loadNodeDetails() on changes
                if (entityId.includes('dc_in_fv_p') ||           // Solar strings
                    entityId.includes('extended_fve_') ||        // Solar voltage/current
                    entityId.includes('computed_batt_') ||       // Battery energy
                    entityId.includes('ac_in_') ||               // Grid details
                    entityId.includes('ac_out_') ||              // House phases
                    entityId.includes('spot_price') ||           // Grid pricing
                    entityId.includes('current_tariff') ||       // Tariff
                    entityId.includes('grid_charging_planned') || // Grid charging plan
                    entityId.includes('battery_balancing') ||    // Battery balancing plan
                    entityId.includes('notification_count')) {   // Notifications
                    debouncedLoadNodeDetails();
                }

                // Pricing chart sensors - trigger loadPricingData() on changes
                if (entityId.includes('_spot_price_current_15min') ||   // Spot prices
                    entityId.includes('_export_price_current_15min') || // Export prices
                    entityId.includes('_solar_forecast') ||             // Solar forecast
                    entityId.includes('_battery_forecast')) {           // Battery forecast

                    if (entityId.includes('_battery_forecast')) {
                        debouncedTimelineRefresh();
                    }

                    // Skip if payload didn't actually change (rough equivalent of old_state/new_state compare)
                    if (newState) {
                        let sig = '';
                        try {
                            sig = `${newState.state}|${JSON.stringify(newState.attributes || {})}`;
                        } catch (e) {
                            sig = `${newState.state}`;
                        }
                        const prev = lastPricingPayload.get(entityId);
                        if (prev === sig) return;
                        lastPricingPayload.set(entityId, sig);
                    }

                    if (typeof window.invalidatePricingTimelineCache === 'function') {
                        window.invalidatePricingTimelineCache();
                    }

                    debouncedLoadPricingData();

                    if (entityId.includes('_battery_forecast')) {
                        debouncedUpdatePlannedConsumption();
                    }
                }
            });
        }

        // Subscribe to theme changes (HA events)
        hass.connection.subscribeEvents((event) => {
            console.log('[Theme] HA theme event:', event);
            detectAndApplyTheme();
        }, 'themes_updated');

        // Subscribe to frontend set theme event
        hass.connection.subscribeEvents((event) => {
            console.log('[Theme] Frontend theme changed:', event);
            detectAndApplyTheme();
        }, 'frontend_set_theme');

        // Subscribe to connection state changes (reconnect after HA restart)
        hass.connection.addEventListener('ready', () => {
            console.log('[Connection] WebSocket reconnected - refreshing all data');
            forceFullRefresh();
        });

        hass.connection.addEventListener('disconnected', () => {
            console.warn('[Connection] WebSocket disconnected');
        });

        console.log('[Shield] Successfully subscribed to state changes');
    } catch (e) {
        console.error('[Shield] Failed to subscribe:', e);
    }
}

// Parse shield activity to get pending tasks
function parseShieldActivity(activity) {
    // activity = "set_box_mode: Home 5" or "Idle" or "nečinný" or null
    if (!activity ||
        activity === 'Idle' ||
        activity === 'idle' ||
        activity === 'nečinný' ||
        activity === 'Nečinný') {
        return null;
    }

    const separatorIndex = activity.indexOf(':');
    if (separatorIndex === -1) {
        // Don't warn for known idle states
        if (!['idle', 'Idle', 'nečinný', 'Nečinný'].includes(activity)) {
            console.warn('[Shield] Cannot parse activity:', activity);
        }
        return null;
    }

    const service = activity.slice(0, separatorIndex).trim();
    const target = activity.slice(separatorIndex + 1).trim();
    if (!service || !target) {
        return null;
    }

    return {
        service: service,  // "set_box_mode"
        target: target     // "Home 5"
    };
}

// Update shield UI (global status bar)
async function updateShieldUI() {
    try {
        const statusEl = document.getElementById('shield-global-status');
        if (!statusEl) return;

        // Get shield sensors (use dynamic lookup for queue and activity)
        const shieldStatus = await getSensor(getSensorId('service_shield_status'));
        const shieldQueue = await getSensor(findShieldSensorId('service_shield_queue'));
        const shieldActivity = await getSensor(findShieldSensorId('service_shield_activity'));

        const status = shieldStatus.value || 'Idle';
        const queueCount = parseInt(shieldQueue.value) || 0;
        const activity = shieldActivity.value || 'Idle';

        console.log('[Shield] Status:', status, 'Queue:', queueCount, 'Activity:', activity);

        // Update status bar based on state
        if (status === 'Running' || status === 'running') {
            statusEl.innerHTML = `🔄 Zpracovává: ${activity}`;
            statusEl.className = 'shield-status processing';
        } else if (queueCount > 0) {
            const plural = queueCount === 1 ? 'úkol' : queueCount < 5 ? 'úkoly' : 'úkolů';
            statusEl.innerHTML = `⏳ Ve frontě: ${queueCount} ${plural}`;
            statusEl.className = 'shield-status pending';
        } else {
            statusEl.innerHTML = `✓ Připraveno`;
            statusEl.className = 'shield-status idle';
        }
    } catch (e) {
        console.error('[Shield] Error updating shield UI:', e);
    }
}

// Update button states based on shield status
async function updateButtonStates() {
    try {
        // console.log('[Shield] Updating button states...');

        // Get shield sensors (string values for status/activity, use dynamic lookup)
        const shieldStatus = await getSensorString(getSensorId('service_shield_status'));
        const shieldQueue = await getSensor(findShieldSensorId('service_shield_queue'));
        const shieldActivity = await getSensorString(findShieldSensorId('service_shield_activity'));

        // Get current states (string values)
        const boxMode = await getSensorString(getSensorId('box_prms_mode'));
        const boilerMode = await getSensorStringSafe(getSensorId('boiler_manual_mode'));

        // Parse shield activity
        const pending = parseShieldActivity(shieldActivity.value);
        const isRunning = (shieldStatus.value === 'Running' || shieldStatus.value === 'running');

        // console.log('[Shield] Parsed state:', {
        //     pending,
        //     isRunning,
        //     queueCount,
        //     boxMode: boxMode.value,
        //     boilerMode: boilerMode.value
        // });

        // Update Box Mode buttons
        updateBoxModeButtons(boxMode.value, pending, isRunning);

        // Update Boiler Mode buttons
        updateBoilerModeButtons(boilerMode.value, pending, isRunning);

        // Update Grid Delivery buttons
        await updateGridDeliveryButtons(pending, isRunning);

        // Update Battery Formating buttons
        await updateBatteryFormatingButtons(pending, isRunning);

    } catch (e) {
        console.error('[Shield] Error updating button states:', e);
    }
}

// Update Box Mode buttons
function updateBoxModeButtons(currentMode, pending, isRunning) {
    const modes = ['Home 1', 'Home 2', 'Home 3', 'Home UPS'];
    const buttonIds = {
        'Home 1': 'btn-mode-home1',
        'Home 2': 'btn-mode-home2',
        'Home 3': 'btn-mode-home3',
        'Home UPS': 'btn-mode-ups'
    };

    modes.forEach(mode => {
        const btn = document.getElementById(buttonIds[mode]);
        if (!btn) return;

        // Reset classes
        btn.classList.remove('active', 'pending', 'processing', 'disabled-by-service');

        // OPRAVA: Zamknout VŠECHNA tlačítka pokud běží set_box_mode (nezávisle na target)
        if (pending && pending.service === 'set_box_mode') {
            btn.disabled = true;
            // Pokud je tento mode cílový, zobraz jako processing/pending
            if (pending.target === mode) {
                btn.classList.add(isRunning ? 'processing' : 'pending');
                // console.log(`[Shield] Button ${mode} -> ${isRunning ? 'processing' : 'pending'} (target)`);
            } else {
                // Ostatní tlačítka jen zamknout
                btn.classList.add('disabled-by-service');
                // console.log(`[Shield] Button ${mode} -> disabled (service running)`);
            }
        }
        // Check if this is current mode (exact match)
        else {
            btn.disabled = false;
            if (currentMode === mode) {
                btn.classList.add('active');
                // console.log(`[Shield] Button ${mode} -> active (currentMode: ${currentMode})`);
            }
        }
    });

    // Update status text
    const statusEl = document.getElementById('box-mode-status');
    if (!statusEl) return;

    if (pending && pending.service === 'set_box_mode') {
        const arrow = isRunning ? '🔄' : '⏳';
        statusEl.innerHTML = `${currentMode} ${arrow} <span class="transitioning">${pending.target}</span>`;
    } else {
        statusEl.textContent = currentMode || '--';
    }
}

// Update Boiler Mode buttons
function updateBoilerModeButtons(currentModeRaw, pending, isRunning) {
    // boiler_manual_mode sensor: "CBB" = CBB, "Manuální" = Manual
    const currentMode = currentModeRaw === 'Manuální' ? 'Manual' : 'CBB';
    const modes = ['CBB', 'Manual'];

    modes.forEach(mode => {
        const btnId = `btn-boiler-${mode.toLowerCase()}`;
        const btn = document.getElementById(btnId);
        if (!btn) return;

        // Reset classes
        btn.classList.remove('active', 'pending', 'processing', 'disabled-by-service');

        // OPRAVA: Zamknout VŠECHNA tlačítka pokud běží set_boiler_mode (nezávisle na target)
        if (pending && pending.service === 'set_boiler_mode') {
            btn.disabled = true;
            // Pokud je tento mode cílový, zobraz jako processing/pending
            if (pending.target === mode) {
                btn.classList.add(isRunning ? 'processing' : 'pending');
                // console.log(`[Shield] Boiler ${mode} -> ${isRunning ? 'processing' : 'pending'} (target)`);
            } else {
                // Ostatní tlačítka jen zamknout
                btn.classList.add('disabled-by-service');
                // console.log(`[Shield] Boiler ${mode} -> disabled (service running)`);
            }
        }
        // Check if active
        else {
            btn.disabled = false;
            if (currentMode === mode) {
                btn.classList.add('active');
                // console.log(`[Shield] Boiler ${mode} -> active`);
            }
        }
    });

    // Update status
    const statusEl = document.getElementById('boiler-mode-status');
    if (!statusEl) return;

    if (pending && pending.service === 'set_boiler_mode') {
        const arrow = isRunning ? '🔄' : '⏳';
        statusEl.innerHTML = `${currentMode} ${arrow} <span class="transitioning">${pending.target}</span>`;
    } else {
        statusEl.textContent = currentMode;
    }
}

// Update Grid Delivery buttons
async function updateGridDeliveryButtons(pending, isRunning) {
    try {
        // Get current grid delivery mode (string) and limit (number)
        const gridModeData = await getSensorString(getSensorId('invertor_prms_to_grid'));
        const gridLimitData = await getSensor(getSensorId('invertor_prm1_p_max_feed_grid'));

        const currentMode = gridModeData.value || '';
        const currentLimit = gridLimitData.value || 0;
        const isChanging = currentMode === 'Probíhá změna';

        // console.log('[Shield] Grid delivery - mode:', currentMode, 'limit:', currentLimit, 'isChanging:', isChanging);

        // Update mode buttons
        // Sensor vrací: "Vypnuto", "Zapnuto", "Omezeno" (nebo "Probíhá změna")
        // Mapování sensor hodnota -> button label
        const modeMapping = {
            'Vypnuto': 'Vypnuto / Off',
            'Zapnuto': 'Zapnuto / On',
            'Omezeno': 'S omezením / Limited'
        };

        const modeButtons = {
            'Vypnuto / Off': 'btn-grid-off',
            'Zapnuto / On': 'btn-grid-on',
            'S omezením / Limited': 'btn-grid-limited'
        };

        // Zjistit jaký button label odpovídá current mode
        const currentModeLabel = modeMapping[currentMode] || currentMode;

        Object.entries(modeButtons).forEach(([mode, btnId]) => {
            const btn = document.getElementById(btnId);
            if (!btn) return;

            btn.classList.remove('active', 'pending', 'processing');

            // If "Probíhá změna", disable all buttons and show processing on all
            if (isChanging) {
                btn.disabled = true;
                btn.classList.add('processing');
                // console.log(`[Shield] Grid ${mode} -> disabled (změna probíhá)`);
                return;
            }

            // OPRAVA: Zamknout VŠECHNA tlačítka pokud běží set_grid_delivery (nezávisle na target)
            if (pending && pending.service === 'set_grid_delivery') {
                btn.disabled = true;

                // Pokud pending target je číslo (limit change), animuj tlačítko "S omezením"
                const isLimitChange = !isNaN(parseInt(pending.target));
                const isTargetButton = isLimitChange
                    ? btnId === 'btn-grid-limited'  // Při změně limitu animuj "S omezením"
                    : pending.target && pending.target.includes(mode.split(' ')[0]); // Při změně mode animuj odpovídající tlačítko

                if (isTargetButton) {
                    btn.classList.add(isRunning ? 'processing' : 'pending');
                    // console.log(`[Shield] Grid ${mode} -> ${isRunning ? 'processing' : 'pending'} (target)`);
                } else {
                    // Ostatní tlačítka jen zamknout, nezobrazovat jako pending
                    btn.classList.add('disabled-by-service');
                    // console.log(`[Shield] Grid ${mode} -> disabled (service running)`);
                }
            }
            // Check if active (porovnat label s currentModeLabel)
            else {
                btn.disabled = false;
                if (mode === currentModeLabel) {
                    btn.classList.add('active');
                    // console.log(`[Shield] Grid ${mode} -> active (currentMode: ${currentMode})`);
                }
            }
        });

        // Update limit display
        const inputEl = document.getElementById('grid-limit');
        if (inputEl) {
            // If pending limit change, show target value with highlight
            if (pending && pending.service === 'set_grid_delivery' && !isNaN(parseInt(pending.target))) {
                inputEl.value = pending.target;
                inputEl.style.borderColor = isRunning ? '#42a5f5' : '#ffc107';
            }
            // Otherwise show current limit
            else {
                inputEl.value = currentLimit;
                inputEl.style.borderColor = '';
            }
        }

    } catch (e) {
        console.error('[Shield] Error updating grid delivery buttons:', e);
    }
}

// Update Battery Formating button (charge-battery-btn)
async function updateBatteryFormatingButtons(pending, isRunning) {
    try {
        const chargeBtn = document.getElementById('charge-battery-btn');
        if (!chargeBtn) return;

        // Pokud je pending task pro battery formating
        if (pending && pending.service === 'set_formating_mode') {
            chargeBtn.classList.remove('pending', 'processing');
            chargeBtn.classList.add(isRunning ? 'processing' : 'pending');
            // console.log(`[Shield] Battery charging -> ${pending.target} (${isRunning ? 'processing' : 'pending'})`);
        } else {
            chargeBtn.classList.remove('pending', 'processing');
        }

    } catch (e) {
        console.error('[Shield] Error updating battery formating buttons:', e);
    }
}

// Open entity more-info dialog
function openEntityDialog(entityId) {
    const hass = getHass();
    if (!hass) {
        console.error('Cannot open entity dialog - no HA connection');
        return;
    }

    try {
        const event = new Event('hass-more-info', {
            bubbles: true,
            composed: true
        });
        event.detail = { entityId: entityId };
        parent.document.querySelector('home-assistant').dispatchEvent(event);
        console.log(`[Entity] Opened dialog for ${entityId}`);
    } catch (e) {
        console.error(`[Entity] Failed to open dialog for ${entityId}:`, e);
    }
}

// Call HA service
async function callService(domain, service, data) {
    console.log(`[Service] Calling ${domain}.${service} with data:`, JSON.stringify(data));
    const hass = getHass();
    if (!hass) {
        console.error('[Service] Failed to get hass object');
        window.DashboardUtils?.showNotification('Chyba', 'Nelze získat připojení k Home Assistant', 'error');
        return false;
    }

    try {
        console.log(`[Service] Executing ${domain}.${service}...`);
        await hass.callService(domain, service, data);
        console.log(`[Service] ✅ Success: ${domain}.${service}`);

        // Shield queue will be updated automatically via WebSocket event (sensor state change)
        // No need to manually trigger update here - backend callback handles it instantly

        return true;
    } catch (e) {
        console.error(`[Service] ❌ Error calling ${domain}.${service}:`, e);
        console.error('[Service] Error details:', e.message, e.stack);
        window.DashboardUtils?.showNotification('Chyba', e.message || 'Volání služby selhalo', 'error');
        return false;
    }
}

// Track mode change state
let modeChangeInProgress = false;
let lastModeChangeNotified = false;

// Shield Queue live duration update
let shieldQueueUpdateInterval = null;

function startShieldQueueLiveUpdate() {
    // Clear existing interval
    if (shieldQueueUpdateInterval) {
        clearInterval(shieldQueueUpdateInterval);
    }

    // Update every second for live duration
    shieldQueueUpdateInterval = setInterval(() => {
        updateShieldQueue();
    }, 1000);
}

function stopShieldQueueLiveUpdate() {
    if (shieldQueueUpdateInterval) {
        clearInterval(shieldQueueUpdateInterval);
        shieldQueueUpdateInterval = null;
    }
}

// Update Shield Queue display
function updateShieldQueue() {
    try {
        // Use Hass states directly (instant, no API call needed!)
        const hass = getHass();
        if (!hass || !hass.states) {
            console.warn('[Queue] Hass not available');
            return;
        }

        // Use helper function to find sensor (handles _2, _3 suffixes)
        const entityId = findShieldSensorId('service_shield_activity');

        if (!entityId) {
            console.warn('[Queue] service_shield_activity sensor not found');
            return;
        }

        const activitySensor = hass.states[entityId];
        const container = document.getElementById('shield-queue-container');

        if (!activitySensor || !activitySensor.attributes || !container) {
            console.warn('[Queue] Missing data:', {
                sensor: entityId,
                hasState: !!activitySensor,
                hasAttrs: !!activitySensor?.attributes,
                hasContainer: !!container
            });
            return;
        }

        const attrs = activitySensor.attributes;
        const runningRequests = attrs.running_requests || [];
        const queuedRequests = attrs.queued_requests || [];
        const allRequests = [...runningRequests, ...queuedRequests];

        if (allRequests.length === 0) {
            container.innerHTML = '<div class="queue-empty">✅ Fronta je prázdná</div>';
            stopShieldQueueLiveUpdate(); // Stop live updates when queue is empty

            // OPRAVA: Pokud je fronta prázdná, skryj všechny lístky (fallback, když monitor shieldu vynechá update)
            ['box_mode', 'boiler_mode', 'grid_mode', 'grid_limit'].forEach((type) => hideChangingIndicator(type));
            return;
        }

        // Start live duration updates when there are active requests
        if (!shieldQueueUpdateInterval) {
            startShieldQueueLiveUpdate();
        }

        // Build table
        let html = '<table class="shield-queue-table">';
        html += '<thead><tr><th>Stav</th><th>Služba</th><th>Změny</th><th>Vytvořeno</th><th>Trvání</th><th>Akce</th></tr></thead>';
        html += '<tbody>';

        allRequests.forEach((req, index) => {
            const isRunning = index === 0 && runningRequests.length > 0;
            const isQueued = !isRunning; // Anything not running is queued

            // OPRAVA: Přidat position pro delete button (1-based index pro backend)
            // Running má position 1, queued jsou 2, 3, 4, ...
            req.position = index + 1;

            const statusClass = isRunning ? 'queue-status-running' : 'queue-status-queued';
            const statusIcon = isRunning ? '🔄' : '⏳';
            const statusText = isRunning ? 'Zpracovává se' : 'Čeká';

            // Format service name to human-readable Czech
            const serviceMap = {
                'set_box_mode': '🏠 Změna režimu boxu',
                'set_grid_delivery': '💧 Změna nastavení přetoků',
                'set_grid_delivery_limit': '🔢 Změna limitu přetoků',
                'set_boiler_mode': '🔥 Změna nastavení bojleru',
                'set_formating_mode': '🔋 Změna nabíjení baterie',
                'set_battery_capacity': '⚡ Změna kapacity baterie'
            };
            let serviceName = serviceMap[req.service] || req.service || 'N/A';

            // Format changes
            let changes = 'N/A';
            if (req.changes && Array.isArray(req.changes) && req.changes.length > 0) {
                changes = req.changes.map(ch => {
                    const arrowIndex = ch.indexOf('→');
                    if (arrowIndex === -1) {
                        return ch;
                    }
                    const left = ch.slice(0, arrowIndex).trim();
                    const right = ch.slice(arrowIndex + 1).trim();
                    const colonIndex = left.indexOf(':');
                    const fromRaw = colonIndex === -1 ? left : left.slice(colonIndex + 1);

                    let from = fromRaw.replaceAll("'", '').trim();
                    let to = right.replaceAll("'", '').trim();

                    // Mapování hodnot pro lepší čitelnost
                    const valueMap = {
                        'CBB': 'Inteligentní',
                        'Manual': 'Manuální',
                        'Manuální': 'Manuální'
                    };

                    from = valueMap[from] || from;
                    to = valueMap[to] || to;

                    return `${from} → ${to}`;
                }).join('<br>');
            }

            // Format creation time and duration
            let createdText = '<span style="opacity: 0.4;">--</span>';
            let durationText = '<span style="opacity: 0.4;">--</span>';

            // Try multiple timestamp fields (started_at for running, queued_at for queued)
            const timestamp = req.started_at || req.queued_at || req.created_at || req.timestamp || req.created;

            if (timestamp) {
                try {
                    const createdDate = new Date(timestamp);
                    const now = new Date();
                    const diffSec = Math.floor((now - createdDate) / 1000);

                    // Format creation time (HH:MM)
                    const hours = String(createdDate.getHours()).padStart(2, '0');
                    const minutes = String(createdDate.getMinutes()).padStart(2, '0');
                    createdText = `${hours}:${minutes}`;

                    // Add date if not today
                    const isToday = createdDate.toDateString() === now.toDateString();
                    if (!isToday) {
                        const day = createdDate.getDate();
                        const month = createdDate.getMonth() + 1;
                        createdText = `${day}.${month}. ${createdText}`;
                    }

                    // Format duration (how long in queue)
                    if (diffSec < 60) {
                        durationText = `${diffSec}s`;
                    } else if (diffSec < 3600) {
                        const diffMin = Math.floor(diffSec / 60);
                        const diffSecRem = diffSec % 60;
                        durationText = `${diffMin}m ${diffSecRem}s`;
                    } else {
                        const diffHours = Math.floor(diffSec / 3600);
                        const diffMin = Math.floor((diffSec % 3600) / 60);
                        durationText = `${diffHours}h ${diffMin}m`;
                    }
                } catch (e) {
                    console.warn('[Queue] Invalid timestamp format:', timestamp, e);
                }
            } else {
                console.warn('[Queue] No timestamp found in request:', req);
            }

            html += `
                <tr>
                    <td class="${statusClass}">${statusIcon} ${statusText}</td>
                    <td>${serviceName}</td>
                    <td style="font-size: 11px;">${changes}</td>
                    <td class="queue-time">${createdText}</td>
                    <td class="queue-time" style="font-weight: 600;">${durationText}</td>
                    <td style="text-align: center;">
                        ${isQueued ? `
                            <button
                                onclick="removeFromQueue(${req.position})"
                                style="
                                    background: none;
                                    border: none;
                                    cursor: pointer;
                                    font-size: 18px;
                                    opacity: 0.6;
                                    padding: 4px 8px;
                                    transition: all 0.2s;
                                "
                                onmouseover="this.style.opacity='1'; this.style.transform='scale(1.2)'"
                                onmouseout="this.style.opacity='0.6'; this.style.transform='scale(1)'"
                                title="Odstranit z fronty"
                            >🗑️</button>
                        ` : '<span style="opacity: 0.3;">—</span>'}
                    </td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        container.innerHTML = html;

    } catch (e) {
        console.error('[Queue] Error updating queue display:', e);
    }
}

// ============================================================================
// SHIELD MONITORING - Simplified universal approach
// ============================================================================

// Helper: Parse service request to get type and target value
function parseServiceRequest(request) {
    if (!request || !request.service) {
        return null;
    }

    const service = request.service;

    // NOVÝ PŘÍSTUP: Použij strukturovaná data z targets[] místo parsování changes[]
    if (request.targets && Array.isArray(request.targets) && request.targets.length > 0) {
        const target = request.targets[0];

        // Mapování param → type
        if (service.includes('set_box_mode') && target.param === 'mode') {
            return { type: 'box_mode', targetValue: target.value };
        }

        if (service.includes('set_boiler_mode') && target.param === 'mode') {
            return { type: 'boiler_mode', targetValue: target.value };
        }

        if (service.includes('set_grid_delivery') && target.param === 'mode') {
            return { type: 'grid_mode', targetValue: target.value };
        }

        if (service.includes('set_grid_delivery') && target.param === 'limit') {
            return { type: 'grid_limit', targetValue: target.value };
        }
    }

    // FALLBACK: Starý přístup pro kompatibilitu (pokud targets[] není dostupný)
    if (!request.changes || !Array.isArray(request.changes)) {
        return null;
    }

    const changeStr = request.changes[0] || '';

    // Box mode: "prms_mode: 'Home 1' → 'Home 2'"
    if (service.includes('set_box_mode')) {
        const match = changeStr.match(/→\s*'([^']+)'/);
        return match ? { type: 'box_mode', targetValue: match[1] } : null;
    }

    // Boiler mode: "manual_mode: 'CBB' → 'Manuální'"
    if (service.includes('set_boiler_mode')) {
        const match = changeStr.match(/→\s*'([^']+)'/);
        return match ? { type: 'boiler_mode', targetValue: match[1] } : null;
    }

    // Grid mode: "prms_to_grid: 'Vypnuto' → 'Zapnuto'"
    if (service.includes('set_grid_delivery') && changeStr.includes('prms_to_grid')) {
        const match = changeStr.match(/→\s*'([^']+)'/);
        return match ? { type: 'grid_mode', targetValue: match[1] } : null;
    }

    // Grid limit: "p_max_feed_grid: 5400 → 3000"
    if (service.includes('set_grid_delivery') && changeStr.includes('p_max_feed_grid')) {
        const match = changeStr.match(/→\s*(\d+)/);
        return match ? { type: 'grid_limit', targetValue: match[1] } : null;
    }

    return null;
}

// Helper: Show changing indicator for specific service type
function showChangingIndicator(type, targetValue, startedAt = null) {
    // console.log(`[Shield] Showing change indicator: ${type} → ${targetValue} (started: ${startedAt})`);

    switch (type) {
        case 'box_mode':
            showBoxModeChanging(targetValue);
            break;
        case 'boiler_mode':
            showBoilerModeChanging(targetValue);
            break;
        case 'grid_mode':
            showGridModeChanging(targetValue, startedAt);
            break;
        case 'grid_limit':
            showGridLimitChanging(targetValue, startedAt);
            break;
    }
}

// Helper: Hide changing indicator for specific service type
function hideChangingIndicator(type) {
    // console.log(`[Shield] Hiding change indicator: ${type}`);

    switch (type) {
        case 'box_mode':
            hideBoxModeChanging();
            break;
        case 'boiler_mode':
            hideBoilerModeChanging();
            break;
        case 'grid_mode':
            hideGridModeChanging();
            break;
        case 'grid_limit':
            hideGridLimitChanging();
            break;
    }
}

// Main monitor function - simplified
let isMonitoringShieldActivity = false;

async function monitorShieldActivity() {
    if (isMonitoringShieldActivity) {
        // console.log('[Shield] Skipping - already running');
        return;
    }

    isMonitoringShieldActivity = true;

    try {
        const hass = getHass();
        if (!hass || !hass.states) return;

        // Find activity sensor
        const sensorPrefix = `sensor.oig_${INVERTER_SN}_service_shield_activity`;
        const entityId = Object.keys(hass.states).find(id => id.startsWith(sensorPrefix));
        if (!entityId) return;

        const activitySensor = hass.states[entityId];
        if (!activitySensor || !activitySensor.attributes) return;

        const attrs = activitySensor.attributes;
        const runningRequests = attrs.running_requests || [];
        const queuedRequests = attrs.queued_requests || [];
        const allRequests = [...runningRequests, ...queuedRequests];

        // console.log('[Shield] Monitoring:', {
        //     running: runningRequests.length,
        //     queued: queuedRequests.length,
        //     total: allRequests.length
        // });

        // Track which service types mají aktivní indikátor
        const activeServices = new Set();

        const processRequestList = (requests, { allowIfActive } = { allowIfActive: false }) => {
            requests.forEach((request) => {
                const parsed = parseServiceRequest(request);
                if (!parsed) {
                    return;
                }
                if (!allowIfActive && activeServices.has(parsed.type)) {
                    return;
                }
                activeServices.add(parsed.type);
                showChangingIndicator(parsed.type, parsed.targetValue, request.started_at || request.queued_at || request.created_at || null);
            });
        };

        // Priorita: běžící requesty → teprve potom čekající (pokud pro daný typ nic neběží)
        processRequestList(runningRequests, { allowIfActive: false });
        processRequestList(queuedRequests, { allowIfActive: false });

        // Hide indicators for service types that are no longer active
        const allServiceTypes = ['box_mode', 'boiler_mode', 'grid_mode', 'grid_limit'];
        allServiceTypes.forEach(type => {
            if (!activeServices.has(type)) {
                hideChangingIndicator(type);
            }
        });

    } catch (e) {
        console.error('[Shield] Error monitoring activity:', e);
    } finally {
        isMonitoringShieldActivity = false;
    }
}

// ============================================================================
// SERVICE-SPECIFIC SHOW/HIDE FUNCTIONS
// ============================================================================

// Box Mode
function showBoxModeChanging(targetMode) {
    const modeButtonMap = {
        'Home 1': 'btn-mode-home1',
        'Home 2': 'btn-mode-home2',
        'Home 3': 'btn-mode-home3',
        'Home UPS': 'btn-mode-ups'
    };

    const buttonIds = Object.values(modeButtonMap);
    const buttons = buttonIds.map(id => document.getElementById(id)).filter(b => b);
    const targetButtonId = modeButtonMap[targetMode];

    // Flow diagram: blink mode text
    const inverterModeElement = document.getElementById('inverter-mode');
    if (inverterModeElement) {
        inverterModeElement.classList.add('mode-changing');
    }

    // Show badge
    const modeChangeIndicator = document.getElementById('mode-change-indicator');
    const modeChangeText = document.getElementById('mode-change-text');
    if (modeChangeIndicator && modeChangeText) {
        modeChangeText.textContent = `→ ${targetMode}`;
        modeChangeIndicator.style.display = 'flex';
    }

    // Lock buttons, animate target
    buttons.forEach(btn => {
        btn.disabled = true;
        if (btn.id === targetButtonId) {
            btn.style.animation = 'pulse-pending 1.5s ease-in-out infinite';
            btn.style.opacity = '0.8';
        } else {
            btn.style.animation = '';
            btn.style.opacity = '0.5';
        }
    });
}

function hideBoxModeChanging() {
    const buttonIds = ['btn-mode-home1', 'btn-mode-home2', 'btn-mode-home3', 'btn-mode-ups'];
    const buttons = buttonIds.map(id => document.getElementById(id)).filter(b => b);

    // Remove flow diagram animation
    const inverterModeElement = document.getElementById('inverter-mode');
    if (inverterModeElement) {
        inverterModeElement.classList.remove('mode-changing');
    }

    // Hide badge
    const modeChangeIndicator = document.getElementById('mode-change-indicator');
    if (modeChangeIndicator) {
        modeChangeIndicator.style.display = 'none';
    }

    // Unlock buttons
    buttons.forEach(btn => {
        btn.disabled = false;
        btn.style.animation = '';
        btn.style.opacity = '';
    });
}

// Boiler Mode
function showBoilerModeChanging(targetMode) {
    const boilerModeMap = {
        'CBB': 'cbb',
        'Manual': 'manual',
        'Manuální': 'manual',
        'Inteligentní': 'cbb'
    };

    const boilerButtons = [
        document.getElementById('btn-boiler-cbb'),
        document.getElementById('btn-boiler-manual')
    ].filter(b => b);

    const targetModeLower = boilerModeMap[targetMode] || targetMode?.toLowerCase();
    const targetButtonId = targetModeLower ? `btn-boiler-${targetModeLower}` : null;

    // Flow diagram: blink mode text
    const boilerModeElement = document.getElementById('boiler-mode');
    if (boilerModeElement) {
        boilerModeElement.classList.add('mode-changing');
    }

    // Show badge
    const boilerChangeIndicator = document.getElementById('boiler-change-indicator');
    const boilerChangeText = document.getElementById('boiler-change-text');
    if (boilerChangeIndicator && boilerChangeText) {
        const isIntelligent = targetMode === 'CBB' || targetMode === 'Inteligentní';
        const modeIcon = isIntelligent ? '🤖' : '👤';
        const modeName = isIntelligent ? 'Inteligentní' : 'Manuální';
        boilerChangeText.textContent = `${modeIcon} ${modeName}`;
        boilerChangeIndicator.style.display = 'flex';
    }

    // Lock buttons, animate target
    boilerButtons.forEach(btn => {
        btn.disabled = true;
        if (btn.id === targetButtonId) {
            btn.style.animation = 'pulse-pending 1.5s ease-in-out infinite';
            btn.style.opacity = '0.8';
        } else {
            btn.style.animation = '';
            btn.style.opacity = '0.5';
        }
    });
}

function hideBoilerModeChanging() {
    const boilerButtons = [
        document.getElementById('btn-boiler-cbb'),
        document.getElementById('btn-boiler-manual')
    ].filter(b => b);

    // Remove flow diagram animation
    const boilerModeElement = document.getElementById('boiler-mode');
    if (boilerModeElement) {
        boilerModeElement.classList.remove('mode-changing');
    }

    // Hide badge
    const boilerChangeIndicator = document.getElementById('boiler-change-indicator');
    if (boilerChangeIndicator) {
        boilerChangeIndicator.style.display = 'none';
    }

    // Unlock buttons
    boilerButtons.forEach(btn => {
        btn.disabled = false;
        btn.style.animation = '';
        btn.style.opacity = '';
    });
}

// Grid Mode
function showGridModeChanging(targetMode, startedAt = null) {
    const gridModeMap = {
        'Off': 'off',
        'Vypnuto': 'off',
        'On': 'on',
        'Zapnuto': 'on',
        'Limited': 'limited',
        'Omezeno': 'limited',
        'S omezením': 'limited'
    };

    const gridButtons = [
        document.getElementById('btn-grid-off'),
        document.getElementById('btn-grid-on'),
        document.getElementById('btn-grid-limited')
    ].filter(b => b);

    const gridModeLower = gridModeMap[targetMode];
    const targetButtonId = gridModeLower ? `btn-grid-${gridModeLower}` : null;

    // Flow diagram: blink mode text
    const gridExportModeElement = document.getElementById('inverter-grid-export-mode');
    if (gridExportModeElement) {
        gridExportModeElement.classList.add('mode-changing');
    }

    // Show badge - bez duration!
    const gridChangeIndicator = document.getElementById('grid-change-indicator');
    const gridChangeText = document.getElementById('grid-change-text');
    if (gridChangeIndicator && gridChangeText) {
        const isOff = targetMode === 'Off' || targetMode === 'Vypnuto';
        const isOn = targetMode === 'On' || targetMode === 'Zapnuto';
        const modeIcon = isOff ? '🚫' : isOn ? '💧' : '🚰';
        const modeName = isOff ? 'Vypnuto' : isOn ? 'Zapnuto' : 'Omezeno';

        gridChangeText.textContent = `${modeIcon} ${modeName}`;
        gridChangeIndicator.style.display = 'flex';
    }

    // Lock buttons, animate target
    gridButtons.forEach(btn => {
        btn.disabled = true;
        if (btn.id === targetButtonId) {
            btn.style.animation = 'pulse-pending 1.5s ease-in-out infinite';
            btn.style.opacity = '0.8';
        } else {
            btn.style.animation = '';
            btn.style.opacity = '0.5';
        }
    });
}

function hideGridModeChanging() {
    const gridButtons = [
        document.getElementById('btn-grid-off'),
        document.getElementById('btn-grid-on'),
        document.getElementById('btn-grid-limited')
    ].filter(b => b);

    // Remove flow diagram animation
    const gridExportModeElement = document.getElementById('inverter-grid-export-mode');
    if (gridExportModeElement) {
        gridExportModeElement.classList.remove('mode-changing');
    }

    // Hide badge
    const gridChangeIndicator = document.getElementById('grid-change-indicator');
    if (gridChangeIndicator) {
        gridChangeIndicator.style.display = 'none';
    }

    // Unlock buttons
    gridButtons.forEach(btn => {
        btn.disabled = false;
        btn.style.animation = '';
        btn.style.opacity = '';
    });
}

// Grid Limit
function showGridLimitChanging(targetLimit, startedAt = null) {
    const gridButtons = [
        document.getElementById('btn-grid-off'),
        document.getElementById('btn-grid-on'),
        document.getElementById('btn-grid-limited')
    ].filter(b => b);

    // When only limit changes, animate the Limited button
    const targetButtonId = 'btn-grid-limited';

    // Animate limit value in flow diagram
    const gridLimitElement = document.getElementById('inverter-export-limit');
    if (gridLimitElement) {
        gridLimitElement.classList.add('mode-changing');
    }

    // Show limit badge (different from mode badge) - bez duration!
    const gridLimitIndicator = document.getElementById('grid-limit-indicator');
    const gridLimitText = document.getElementById('grid-limit-text');
    if (gridLimitIndicator && gridLimitText) {
        gridLimitText.textContent = `→ ${targetLimit}W`;
        gridLimitIndicator.style.display = 'flex';
    }

    // Lock buttons, animate Limited
    gridButtons.forEach(btn => {
        btn.disabled = true;
        if (btn.id === targetButtonId) {
            btn.style.animation = 'pulse-pending 1.5s ease-in-out infinite';
            btn.style.opacity = '0.8';
        } else {
            btn.style.animation = '';
            btn.style.opacity = '0.5';
        }
    });
}

function hideGridLimitChanging() {
    const gridButtons = [
        document.getElementById('btn-grid-off'),
        document.getElementById('btn-grid-on'),
        document.getElementById('btn-grid-limited')
    ].filter(b => b);

    // Remove limit value animation in flow diagram
    const gridLimitElement = document.getElementById('inverter-export-limit');
    if (gridLimitElement) {
        gridLimitElement.classList.remove('mode-changing');
    }

    // Hide limit badge
    const gridLimitIndicator = document.getElementById('grid-limit-indicator');
    if (gridLimitIndicator) {
        gridLimitIndicator.style.display = 'none';
    }

    // Unlock buttons (only if no mode change is active)
    gridButtons.forEach(btn => {
        btn.disabled = false;
        btn.style.animation = '';
        btn.style.opacity = '';
    });
}

// ============================================================================
// END OF SHIELD MONITORING
// ============================================================================

// Show grid delivery dialog with optional limit input
function showGridDeliveryDialog(mode, currentLimit) {
    return new Promise((resolve) => {
        const needsLimit = mode === 'S omezením / Limited';
        const modeDisplayName = mode === 'Vypnuto / Off' ? 'Vypnuto' :
            mode === 'Zapnuto / On' ? 'Zapnuto' :
                'S omezením';
        const modeIcon = mode === 'Vypnuto / Off' ? '🚫' :
            mode === 'Zapnuto / On' ? '💧' : '🚰';

        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'ack-dialog-overlay';

        // Create dialog
        const dialog = document.createElement('div');
        dialog.className = 'ack-dialog';

        const limitInputHtml = needsLimit ? `
            <div class="ack-dialog-body" style="margin-bottom: 15px;">
                <label for="grid-limit-input" style="display: block; margin-bottom: 8px; font-weight: 600;">
                    Zadejte limit přetoků (W):
                </label>
                <input type="number"
                       id="grid-limit-input"
                       placeholder="např. 5000"
                       min="1"
                       max="20000"
                       step="100"
                       value="${currentLimit || 5000}"
                       class="dialog-input">
                <small style="display: block; margin-top: 5px; opacity: 0.7;">Rozsah: 1-20000 W</small>
            </div>
        ` : '';

        dialog.innerHTML = `
            <div class="ack-dialog-header">
                ${modeIcon} Změna dodávky do sítě
            </div>
            <div class="ack-dialog-body">
                Chystáte se změnit dodávku do sítě na: <strong>"${modeDisplayName}"</strong>
            </div>
            ${limitInputHtml}
            <div class="ack-dialog-warning">
                ⚠️ <strong>Upozornění:</strong> ${needsLimit ?
                'Režim a limit budou změněny postupně (serializováno). Každá změna může trvat až 10 minut.' :
                'Změna režimu může trvat až 10 minut. Během této doby je systém v přechodném stavu.'}
            </div>
            <div class="ack-checkbox-wrapper">
                <input type="checkbox" id="ack-checkbox">
                <label for="ack-checkbox">
                    <strong>Souhlasím</strong> s tím, že měním dodávku do sítě na vlastní odpovědnost.
                    Aplikace nenese odpovědnost za případné negativní důsledky této změny.
                </label>
            </div>
            <div class="ack-dialog-buttons">
                <button class="btn-cancel">Zrušit</button>
                <button class="btn-confirm" disabled>Potvrdit změnu</button>
            </div>
        `;

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        const checkbox = dialog.querySelector('#ack-checkbox');
        const confirmBtn = dialog.querySelector('.btn-confirm');
        const cancelBtn = dialog.querySelector('.btn-cancel');
        const limitInput = dialog.querySelector('#grid-limit-input');

        // Enable confirm button only when checkbox is checked
        checkbox.addEventListener('change', () => {
            confirmBtn.disabled = !checkbox.checked;
        });

        // Handle confirm
        confirmBtn.addEventListener('click', () => {
            if (checkbox.checked) {
                let limit = null;
                if (needsLimit && limitInput) {
                    limit = parseInt(limitInput.value);
                    if (isNaN(limit) || limit < 1 || limit > 20000) {
                        alert('Prosím zadejte platný limit mezi 1-20000 W');
                        return;
                    }
                }
                document.body.removeChild(overlay);
                resolve({ confirmed: true, mode, limit });
            }
        });

        // Handle cancel
        cancelBtn.addEventListener('click', () => {
            document.body.removeChild(overlay);
            resolve({ confirmed: false });
        });

        // Handle ESC key
        const handleEsc = (e) => {
            if (e.key === 'Escape') {
                document.body.removeChild(overlay);
                document.removeEventListener('keydown', handleEsc);
                resolve({ confirmed: false });
            }
        };
        document.addEventListener('keydown', handleEsc);
    });
}

// Show acknowledgement dialog
function showAcknowledgementDialog(title, message, onConfirm) {
    return new Promise((resolve) => {
        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'ack-dialog-overlay';

        // Create dialog
        const dialog = document.createElement('div');
        dialog.className = 'ack-dialog';

        dialog.innerHTML = `
            <div class="ack-dialog-header">
                ⚠️ ${title}
            </div>
            <div class="ack-dialog-body">
                ${message}
            </div>
            <div class="ack-dialog-warning">
                ⚠️ <strong>Upozornění:</strong> Změna režimu může trvat až 10 minut. Během této doby je systém v přechodném stavu.
            </div>
            <div class="ack-checkbox-wrapper">
                <input type="checkbox" id="ack-checkbox">
                <label for="ack-checkbox">
                    <strong>Souhlasím</strong> s tím, že měním režim boxu na vlastní odpovědnost.
                    Aplikace nenese odpovědnost za případné negativní důsledky této změny.
                </label>
            </div>
            <div class="ack-dialog-buttons">
                <button class="btn-cancel">Zrušit</button>
                <button class="btn-confirm" disabled>Potvrdit změnu</button>
            </div>
        `;

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        const checkbox = dialog.querySelector('#ack-checkbox');
        const confirmBtn = dialog.querySelector('.btn-confirm');
        const cancelBtn = dialog.querySelector('.btn-cancel');

        // Enable confirm button only when checkbox is checked
        checkbox.addEventListener('change', () => {
            confirmBtn.disabled = !checkbox.checked;
        });

        // Handle confirm
        confirmBtn.addEventListener('click', () => {
            if (checkbox.checked) {
                document.body.removeChild(overlay);
                resolve(true);
            }
        });

        // Handle cancel
        cancelBtn.addEventListener('click', () => {
            document.body.removeChild(overlay);
            resolve(false);
        });

        // Handle ESC key
        const handleEsc = (e) => {
            if (e.key === 'Escape') {
                document.body.removeChild(overlay);
                document.removeEventListener('keydown', handleEsc);
                resolve(false);
            }
        };
        document.addEventListener('keydown', handleEsc);
    });
}

// Jednoduchý confirm dialog bez checkboxu a vysvětlení
function showSimpleConfirmDialog(title, message, confirmText = 'OK', cancelText = 'Zrušit') {
    return new Promise((resolve) => {
        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'ack-dialog-overlay';

        // Create dialog
        const dialog = document.createElement('div');
        dialog.className = 'ack-dialog';

        dialog.innerHTML = `
            <div class="ack-dialog-header">
                ⚠️ ${title}
            </div>
            <div class="ack-dialog-body" style="padding: 20px 0;">
                ${message}
            </div>
            <div class="ack-dialog-buttons">
                <button class="btn-cancel">${cancelText}</button>
                <button class="btn-confirm">${confirmText}</button>
            </div>
        `;

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        const confirmBtn = dialog.querySelector('.btn-confirm');
        const cancelBtn = dialog.querySelector('.btn-cancel');

        // Handle confirm
        confirmBtn.addEventListener('click', () => {
            document.body.removeChild(overlay);
            resolve(true);
        });

        // Handle cancel
        cancelBtn.addEventListener('click', () => {
            document.body.removeChild(overlay);
            resolve(false);
        });

        // Handle ESC key
        const handleEsc = (e) => {
            if (e.key === 'Escape') {
                document.body.removeChild(overlay);
                document.removeEventListener('keydown', handleEsc);
                resolve(false);
            }
        };
        document.addEventListener('keydown', handleEsc);
    });
}

// Remove item from shield queue
async function removeFromQueue(position) {
    try {
        // Získat detaily položky pro název akce
        const shieldQueue = await getSensor(findShieldSensorId('service_shield_queue'));
        const requests = shieldQueue.attributes?.requests || [];
        const request = requests.find(r => r.position === position);

        let actionName = 'Operace';
        if (request) {
            if (request.service_name.includes('set_box_mode')) {
                actionName = `Změna režimu na ${request.target_display || request.target_value || 'neznámý'}`;
            } else if (request.service_name.includes('set_grid_limit')) {
                actionName = `Změna limitu do sítě na ${request.target_display || request.target_value || 'neznámý'}`;
            } else if (request.service_name.includes('set_grid_delivery_limit')) {
                actionName = `Změna limitu ze sítě na ${request.target_display || request.target_value || 'neznámý'}`;
            }
        }

        // Jednoduchý confirm dialog
        const confirmed = await showSimpleConfirmDialog(
            actionName,
            'Operace bude odstraněna z fronty bez provedení.',
            'OK',
            'Zrušit'
        );

        if (!confirmed) return;

        console.log(`[Queue] Removing position ${position} from queue`);

        const success = await callService('oig_cloud', 'shield_remove_from_queue', {
            position: position
        });

        if (success) {
            // Tichá aktualizace bez notifikace
            await updateShieldQueue();
            await updateShieldUI();
        } else {
            window.DashboardUtils?.showNotification('Chyba', 'Nepodařilo se odstranit položku z fronty', 'error');
        }
    } catch (e) {
        console.error('[Queue] Error removing from queue:', e);
        window.DashboardUtils?.showNotification('Chyba', 'Chyba při odstraňování z fronty', 'error');
    }
}

// === SHIELD SERVICE CALL HELPERS ===

/**
 * Univerzální wrapper pro volání služeb s pending UI
 * @param {Object} config - Konfigurace
 * @param {string} config.serviceName - Název služby (pro UI)
 * @param {string} config.buttonId - ID tlačítka pro pending state (optional)
 * @param {Function} config.serviceCall - Async funkce která volá service
 * @param {boolean} config.skipQueueWarning - Přeskočit warning při plné frontě
 */
async function executeServiceWithPendingUI(config) {
    const { serviceName, buttonId, serviceCall, skipQueueWarning = false } = config;

    try {
        // Check shield queue before adding task
        if (!skipQueueWarning) {
            const shieldQueue = await getSensor(findShieldSensorId('service_shield_queue'));
            const queueCount = parseInt(shieldQueue.value) || 0;

            if (queueCount >= 3) {
                const proceed = confirm(
                    `⚠️ VAROVÁNÍ: Fronta již obsahuje ${queueCount} úkolů!\n\n` +
                    `Každá změna může trvat až 10 minut.\n` +
                    `Opravdu chcete přidat další úkol?`
                );
                if (!proceed) return false;
            }
        }

        // Show pending state immediately
        const btn = buttonId ? document.getElementById(buttonId) : null;
        if (btn) {
            btn.disabled = true;
            btn.classList.add('pending');
        }

        // Execute service call
        const success = await serviceCall();

        if (success) {
            // Okamžitá aktualizace UI bez čekání na WebSocket debounce
            monitorShieldActivity();
            await updateShieldQueue();
            await updateShieldUI();
            await updateButtonStates();
            return true;
        } else {
            // Re-enable on error
            if (btn) {
                btn.disabled = false;
                btn.classList.remove('pending');
            }
            return false;
        }
    } catch (e) {
        console.error(`[Shield] Error in ${serviceName}:`, e);
        window.DashboardUtils?.showNotification('Chyba', `Nepodařilo se provést: ${serviceName}`, 'error');

        // Re-enable button on error
        const btn = buttonId ? document.getElementById(buttonId) : null;
        if (btn) {
            btn.disabled = false;
            btn.classList.remove('pending');
        }
        return false;
    }
}

// Set box mode
async function setBoxMode(mode) {
    try {
        // Check if mode is already active
        const currentModeData = await getSensorString(getSensorId('box_prms_mode'));
        const currentMode = currentModeData.value || '';

        if (currentMode.includes(mode)) {
            return; // Режим už je aktivní - tiše ignorovat
        }

        // Show acknowledgement dialog
        const confirmed = await showAcknowledgementDialog(
            'Změna režimu střídače',
            `Chystáte se změnit režim boxu na <strong>"${mode}"</strong>.<br><br>` +
            `Tato změna ovlivní chování celého systému a může trvat až 10 minut.`
        );
        if (!confirmed) return;

        // Button ID mapping
        const buttonIds = {
            'Home 1': 'btn-mode-home1',
            'Home 2': 'btn-mode-home2',
            'Home 3': 'btn-mode-home3',
            'Home UPS': 'btn-mode-ups'
        };

        // Execute with pending UI
        await executeServiceWithPendingUI({
            serviceName: 'Změna režimu boxu',
            buttonId: buttonIds[mode],
            serviceCall: async () => {
                return await callService('oig_cloud', 'set_box_mode', {
                    mode: mode,
                    acknowledgement: true
                });
            }
        });

    } catch (e) {
        console.error('[Shield] Error in setBoxMode:', e);
        window.DashboardUtils?.showNotification('Chyba', 'Nepodařilo se změnit režim boxu', 'error');
    }
}

// Set grid delivery - main entry point
async function setGridDelivery(mode) {
    console.log('═══════════════════════════════════════════════');
    console.log('[Grid] setGridDelivery() called with mode:', mode);
    console.log('═══════════════════════════════════════════════');

    try {
        // Get current mode and limit
        const currentModeData = await getSensorString(getSensorId('invertor_prms_to_grid'));
        const currentMode = currentModeData.value || '';
        const currentLimitData = await getSensorSafe(getSensorId('invertor_prm1_p_max_feed_grid'));
        const currentLimit = currentLimitData.value || 5000;

        console.log('[Grid] Current state:', { currentMode, currentLimit });

        // Check if change is already in progress
        if (currentMode === 'Probíhá změna') {
            console.log('[Grid] ⏸️ Change already in progress, skipping silently');
            return;
        }

        // Check if already active (except for Limited - can change limit)
        const isAlreadyActive =
            (mode === 'Vypnuto / Off' && currentMode === 'Vypnuto') ||
            (mode === 'Zapnuto / On' && currentMode === 'Zapnuto');

        if (isAlreadyActive) {
            console.log('[Grid] ⏸️ Mode already active, skipping silently');
            return;
        }

        // Check if Limited is already active
        const isLimitedActive = currentMode === 'Omezeno';
        const isChangingToLimited = mode === 'S omezením / Limited';

        console.log('[Grid] Decision flags:', { isLimitedActive, isChangingToLimited });

        // Show dialog
        console.log('[Grid] 📋 Opening dialog...');
        const result = await showGridDeliveryDialog(mode, currentLimit);

        if (!result.confirmed) {
            console.log('[Grid] ❌ Dialog cancelled by user');
            return;
        }

        console.log('[Grid] ✅ Dialog confirmed with:', result);

        // Determine button ID
        const buttonIds = {
            'Vypnuto / Off': 'btn-grid-off',
            'Zapnuto / On': 'btn-grid-on',
            'S omezením / Limited': 'btn-grid-limited'
        };
        const buttonId = buttonIds[mode];

        // CASE 1: Limited is active, just change limit
        if (isLimitedActive && isChangingToLimited && result.limit) {
            console.log('[Grid] 🔧 Case 1: Changing limit only');

            await executeServiceWithPendingUI({
                serviceName: 'Změna limitu přetoků',
                buttonId: buttonId,
                serviceCall: async () => {
                    return await callService('oig_cloud', 'set_grid_delivery', {
                        limit: result.limit,
                        acknowledgement: true,
                        warning: true
                    });
                }
            });
            return;
        }

        // CASE 2: Mode + Limit together (Limited from Off/On)
        if (isChangingToLimited && result.limit) {
            console.log('[Grid] 🔧 Case 2: Mode + limit together (backend will serialize)');

            await executeServiceWithPendingUI({
                serviceName: 'Nastavení přetoků s omezením',
                buttonId: buttonId,
                serviceCall: async () => {
                    // NOVÁ LOGIKA: Pošleme OBĚ parametry najednou
                    // Backend automaticky rozdělí na 2 volání ve frontě
                    console.log('[Grid] Sending mode + limit together:', { mode, limit: result.limit });
                    return await callService('oig_cloud', 'set_grid_delivery', {
                        mode: mode,
                        limit: result.limit,
                        acknowledgement: true,
                        warning: true
                    });
                }
            });
            return;
        }

        // CASE 3: Single-step change (just mode)
        console.log('[Grid] 🔧 Case 3: Single-step change (mode only)');

        await executeServiceWithPendingUI({
            serviceName: 'Změna dodávky do sítě',
            buttonId: buttonId,
            serviceCall: async () => {
                return await callService('oig_cloud', 'set_grid_delivery', {
                    mode: mode,
                    acknowledgement: true,
                    warning: true
                });
            }
        });

    } catch (e) {
        console.error('[Grid] Error in setGridDelivery:', e);
        window.DashboardUtils?.showNotification('Chyba', 'Nepodařilo se změnit dodávku do sítě', 'error');
    }
}

// OLD FUNCTIONS - KEPT FOR COMPATIBILITY BUT NOT USED
async function setGridDeliveryOld(mode, limit) {
    if (mode === null && limit === null) {
        window.DashboardUtils?.showNotification('Chyba', 'Musíte zadat režim nebo limit!', 'error');
        return;
    }

    if (mode !== null && limit !== null) {
        window.DashboardUtils?.showNotification('Chyba', 'Můžete zadat pouze režim NEBO limit!', 'error');
        return;
    }

    const confirmed = confirm('Opravdu chcete změnit dodávku do sítě?\n\n⚠️ VAROVÁNÍ: Tato změna může ovlivnit chování systému!');
    if (!confirmed) return;

    const data = {
        acknowledgement: true,
        warning: true
    };

    if (mode !== null) {
        data.mode = mode;
    } else {
        data.limit = parseInt(limit);
        if (isNaN(data.limit) || data.limit < 1 || data.limit > 9999) {
            window.DashboardUtils?.showNotification('Chyba', 'Limit musí být 1-9999 W', 'error');
            return;
        }
    }

    const success = await callService('oig_cloud', 'set_grid_delivery', data);

    if (success) {
        const msg = mode ? `Režim: ${mode}` : `Limit: ${data.limit} W`;
        window.DashboardUtils?.showNotification('Dodávka do sítě', msg, 'success');
        setTimeout(forceFullRefresh, 2000);
    }
}

// Set grid delivery limit from input
function setGridDeliveryLimit() {
    const input = document.getElementById('grid-limit');
    const limit = parseInt(input.value);

    if (!limit || limit < 1 || limit > 9999) {
        window.DashboardUtils?.showNotification('Chyba', 'Zadejte limit 1-9999 W', 'error');
        return;
    }

    setGridDeliveryOld(null, limit);
}

// Set boiler mode
async function setBoilerMode(mode) {
    try {
        // Get current mode
        const currentModeData = await getSensorStringSafe(getSensorId('boiler_manual_mode'));
        const currentModeRaw = currentModeData.value || '';
        const currentMode = currentModeRaw === 'Manuální' ? 'Manual' : currentModeRaw;

        console.log('[Boiler] setBoilerMode called:', { mode, currentMode, currentModeRaw });

        // Check if already active
        if (currentMode === mode) {
            console.log('[Boiler] ⏸️ Mode already active, skipping silently');
            return;
        }

        const modeName = mode === 'CBB' ? 'Inteligentní' : 'Manuální';
        const modeIcon = mode === 'CBB' ? '🤖' : '👤';

        // Show acknowledgement dialog
        const confirmed = await showAcknowledgementDialog(
            'Změna režimu bojleru',
            `Chystáte se změnit režim bojleru na <strong>"${modeIcon} ${modeName}"</strong>.<br><br>` +
            `Tato změna ovlivní chování ohřevu vody a může trvat až 10 minut.`
        );
        if (!confirmed) return;

        // Button ID
        const btnId = `btn-boiler-${mode.toLowerCase()}`;

        // Store expected mode for monitoring
        const expectedMode = mode === 'CBB' ? 'CBB' : 'Manuální';
        window._lastRequestedBoilerMode = expectedMode;
        console.log('[Boiler] Stored expected mode for monitoring:', expectedMode);

        // Execute with pending UI
        await executeServiceWithPendingUI({
            serviceName: 'Změna režimu bojleru',
            buttonId: btnId,
            serviceCall: async () => {
                return await callService('oig_cloud', 'set_boiler_mode', {
                    mode: mode,
                    acknowledgement: true
                });
            }
        });

    } catch (e) {
        console.error('[Shield] Error in setBoilerMode:', e);
        window.DashboardUtils?.showNotification('Chyba', 'Nepodařilo se změnit režim bojleru', 'error');
    }
}

// Update solar forecast
async function updateSolarForecast() {
    const confirmed = confirm('Opravdu chcete aktualizovat solární předpověď?');
    if (!confirmed) return;

    const success = await callService('oig_cloud', 'update_solar_forecast', {});

    if (success) {
        window.DashboardUtils?.showNotification('Solární předpověď', 'Předpověď se aktualizuje...', 'success');
        // Delší čas pro forecast update
        setTimeout(forceFullRefresh, 5000);
    }
}

// Load control panel status (now uses shield integration)
async function loadControlStatus() {
    try {
        // Update shield UI and button states
        await updateShieldUI();
        await updateButtonStates();
    } catch (e) {
        console.error('Error loading control status:', e);
    }
}


// Export shield functions
window.DashboardShield = {
    subscribeToShield,
    startShieldQueueLiveUpdate,
    stopShieldQueueLiveUpdate,
    debouncedShieldMonitor,
    monitorShieldActivity,
    updateShieldUI,
    updateButtonStates,
    setBoxMode,
    setGridDelivery,
    setBoilerMode,
    loadControlStatus,
    init: function() {
        console.log('[DashboardShield] Initialized');
        startShieldQueueLiveUpdate();
    }
};

console.log('[DashboardShield] Module loaded');
