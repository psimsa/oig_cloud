/* eslint-disable */
/**
 * OIG Cloud Dashboard - API & Data Loading
 *
 * Funkce pro načítání dat ze senzorů, REST API a služeb Home Assistant.
 * Extrahováno z monolitického dashboard-core.js
 *
 * @module dashboard-api
 * @version 1.0.0
 * @date 2025-11-02
 */

// Global inverter SN (může být přepsán)
var INVERTER_SN = new URLSearchParams(window.location.search).get('inverter_sn') || '2206237016';

// ============================================================================
// HOME ASSISTANT ACCESS
// ============================================================================

/**
 * Získá přístup k Home Assistant objektu
 * @returns {object|null} Home Assistant objekt nebo null
 */
function getHass() {
    try {
        return parent.document.querySelector('home-assistant')?.hass || null;
    } catch (e) {
        console.error('[API] Cannot access hass:', e);
        return null;
    }
}

/**
 * Získá HA autentizační token
 * @returns {string|null} Token nebo null
 */
function getHAToken() {
    try {
        return parent.document.querySelector('home-assistant').hass.auth.data.access_token;
    } catch (e) {
        console.error('[API] Cannot get HA token:', e);
        return null;
    }
}

/**
 * Wrapper around fetch() that attaches Home Assistant Bearer token when available.
 * @param {string} url - Absolute or relative URL
 * @param {object} options - Fetch options
 * @returns {Promise<Response>}
 */
async function fetchWithAuth(url, options = {}) {
    const token = getHAToken();
    const mergedHeaders = {
        ...(options.headers || {})
    };

    // Add Bearer token if not already provided.
    if (token && !mergedHeaders.Authorization && !mergedHeaders.authorization) {
        mergedHeaders.Authorization = `Bearer ${token}`;
    }

    return await fetch(url, {
        ...options,
        headers: mergedHeaders
    });
}

// ============================================================================
// SENSOR ID HELPERS
// ============================================================================

/**
 * Vytvoří sensor entity ID
 * @param {string} sensor - Název senzoru
 * @returns {string} Entity ID
 */
function getSensorId(sensor) {
    return `sensor.oig_${INVERTER_SN}_${sensor}`;
}

/**
 * Najde shield sensor s dynamickým suffixem (_2, _3, ...)
 * @param {string} sensorName - Název senzoru
 * @returns {string} Entity ID
 */
function findShieldSensorId(sensorName) {
    try {
        const hass = getHass();
        if (!hass || !hass.states) {
            console.warn(`[API] Cannot find ${sensorName} - hass not available`);
            return getSensorId(sensorName);
        }

        const sensorPrefix = `sensor.oig_${INVERTER_SN}_${sensorName}`;

        // Find exact match or with numeric suffix
        const entityId = Object.keys(hass.states).find(id => {
            if (id === sensorPrefix) return true;
            if (id.startsWith(sensorPrefix + '_')) {
                const suffix = id.substring(sensorPrefix.length + 1);
                return /^\d+$/.test(suffix);
            }
            return false;
        });

        if (!entityId) {
            console.warn(`[API] Sensor not found: ${sensorPrefix}`);
            return getSensorId(sensorName);
        }

        return entityId;
    } catch (e) {
        console.error(`[API] Error finding sensor ${sensorName}:`, e);
        return getSensorId(sensorName);
    }
}

// ============================================================================
// SENSOR DATA LOADING
// ============================================================================

/**
 * Načte numerický sensor
 * @param {string} entityId - Entity ID
 * @returns {Promise<object>} {value, lastUpdated, attributes}
 */
async function getSensor(entityId) {
    try {
        const hass = getHass();
        if (!hass || !hass.states) {
            return { value: 0, lastUpdated: null, attributes: {} };
        }

        const state = hass.states[entityId];
        if (!state) {
            return { value: 0, lastUpdated: null, attributes: {} };
        }

        const value = state.state !== 'unavailable' && state.state !== 'unknown'
            ? parseFloat(state.state) || 0
            : 0;
        const lastUpdated = state.last_updated ? new Date(state.last_updated) : null;
        const attributes = state.attributes || {};
        return { value, lastUpdated, attributes };
    } catch (e) {
        return { value: 0, lastUpdated: null, attributes: {} };
    }
}

/**
 * Načte string sensor
 * @param {string} entityId - Entity ID
 * @returns {Promise<object>} {value, lastUpdated, attributes}
 */
async function getSensorString(entityId) {
    try {
        const hass = getHass();
        if (!hass || !hass.states) {
            return { value: '', lastUpdated: null, attributes: {} };
        }

        const state = hass.states[entityId];
        if (!state) {
            return { value: '', lastUpdated: null, attributes: {} };
        }

        const value = (state.state !== 'unavailable' && state.state !== 'unknown')
            ? state.state
            : '';
        const lastUpdated = state.last_updated ? new Date(state.last_updated) : null;
        const attributes = state.attributes || {};
        return { value, lastUpdated, attributes };
    } catch (e) {
        return { value: '', lastUpdated: null, attributes: {} };
    }
}

/**
 * Načte sensor s kontrolou existence
 * @param {string} entityId - Entity ID
 * @param {boolean} silent - Potlačit logy
 * @returns {Promise<object>} {value, lastUpdated, attributes, exists}
 */
async function getSensorSafe(entityId, silent = true) {
    try {
        const hass = getHass();
        if (!hass || !hass.states) {
            return { value: 0, lastUpdated: null, attributes: {}, exists: false };
        }

        const state = hass.states[entityId];
        if (!state) {
            if (!silent) console.log(`[API] Sensor ${entityId} not available`);
            return { value: 0, lastUpdated: null, attributes: {}, exists: false };
        }

        const value = state.state !== 'unavailable' && state.state !== 'unknown'
            ? parseFloat(state.state) || 0
            : 0;
        const lastUpdated = state.last_updated ? new Date(state.last_updated) : null;
        const attributes = state.attributes || {};
        return { value, lastUpdated, attributes, exists: true };
    } catch (e) {
        if (!silent) console.error(`[API] Error fetching ${entityId}:`, e);
        return { value: 0, lastUpdated: null, attributes: {}, exists: false };
    }
}

/**
 * Načte string sensor s kontrolou existence
 * @param {string} entityId - Entity ID
 * @param {boolean} silent - Potlačit logy
 * @returns {Promise<object>} {value, lastUpdated, exists}
 */
async function getSensorStringSafe(entityId, silent = true) {
    try {
        const hass = getHass();
        if (!hass || !hass.states) {
            return { value: '', lastUpdated: null, exists: false };
        }

        const state = hass.states[entityId];
        if (!state) {
            if (!silent) console.log(`[API] Sensor ${entityId} not available`);
            return { value: '', lastUpdated: null, exists: false };
        }

        const value = (state.state !== 'unavailable' && state.state !== 'unknown')
            ? state.state
            : '';
        const lastUpdated = state.last_updated ? new Date(state.last_updated) : null;
        return { value, lastUpdated, exists: true };
    } catch (e) {
        if (!silent) console.error(`[API] Error fetching ${entityId}:`, e);
        return { value: '', lastUpdated: null, exists: false };
    }
}

// ============================================================================
// REST API CALLS
// ============================================================================

/**
 * Načte data z OIG Cloud REST API
 * @param {string} endpoint - API endpoint (bez /api/oig_cloud prefix)
 * @param {object} options - Fetch options
 * @returns {Promise<object>} API response nebo null
 */
async function fetchOIGAPI(endpoint, options = {}) {
    try {
        const url = `/api/oig_cloud${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
        const response = await fetchWithAuth(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });

        if (!response.ok) {
            console.error(`[API] Error fetching ${url}: ${response.status}`);
            return null;
        }

        return await response.json();
    } catch (e) {
        console.error(`[API] Fetch error for ${endpoint}:`, e);
        return null;
    }
}

/**
 * Načte battery forecast timeline
 * @param {string} inverterSn - Inverter SN
 * @returns {Promise<object>} Timeline data
 */
async function loadBatteryTimeline(inverterSn) {
    return await fetchOIGAPI(`/battery_forecast/${inverterSn}/timeline`);
}

/**
 * Načte unified cost tile
 * @param {string} inverterSn - Inverter SN
 * @returns {Promise<object>} Cost tile data
 */
async function loadUnifiedCostTile(inverterSn) {
    return await fetchOIGAPI(`/battery_forecast/${inverterSn}/unified_cost_tile`);
}

/**
 * Načte spot prices
 * @returns {Promise<object>} Spot price data
 */
async function loadSpotPrices() {
    return await fetchOIGAPI('/spot_prices');
}

/**
 * Načte analytics data
 * @param {string} inverterSn - Inverter SN
 * @returns {Promise<object>} Analytics data
 */
async function loadAnalytics(inverterSn) {
    return await fetchOIGAPI(`/analytics/${inverterSn}`);
}

// ============================================================================
// SERVICE CALLS
// ============================================================================

/**
 * Zavolá Home Assistant service
 * @param {string} domain - Service domain
 * @param {string} service - Service name
 * @param {object} data - Service data
 * @returns {Promise<boolean>} Success
 */
async function callService(domain, service, data = {}) {
    try {
        const hass = getHass();
        if (!hass || !hass.callService) {
            console.error('[API] Cannot call service - hass not available');
            return false;
        }

        await hass.callService(domain, service, data);
        return true;
    } catch (e) {
        console.error(`[API] Service call failed (${domain}.${service}):`, e);
        return false;
    }
}

/**
 * Otevře entity dialog
 * @param {string} entityId - Entity ID
 * @returns {boolean} Success
 */
function openEntityDialog(entityId) {
    try {
        const event = new Event('hass-more-info', { bubbles: true, composed: true });
        event.detail = { entityId };
        parent.document.querySelector('home-assistant').dispatchEvent(event);
        return true;
    } catch (e) {
        console.error('[API] Cannot open entity dialog:', e);
        return false;
    }
}

// ============================================================================
// BATCH LOADING
// ============================================================================

/**
 * Načte multiple senzory najednou (optimalizováno)
 * @param {string[]} entityIds - Array of entity IDs
 * @returns {Promise<object>} Map entityId → sensor data
 */
async function batchLoadSensors(entityIds) {
    const hass = getHass();
    if (!hass || !hass.states) {
        return {};
    }

    const result = {};
    for (const entityId of entityIds) {
        const state = hass.states[entityId];
        if (state) {
            const value = state.state !== 'unavailable' && state.state !== 'unknown'
                ? parseFloat(state.state) || 0
                : 0;
            result[entityId] = {
                value,
                lastUpdated: state.last_updated ? new Date(state.last_updated) : null,
                attributes: state.attributes || {},
                exists: true
            };
        } else {
            result[entityId] = {
                value: 0,
                lastUpdated: null,
                attributes: {},
                exists: false
            };
        }
    }
    return result;
}

// ============================================================================
// INVERTER SN MANAGEMENT
// ============================================================================

/**
 * Nastaví inverter SN
 * @param {string} sn - Inverter serial number
 */
function setInverterSN(sn) {
    INVERTER_SN = sn;
}

/**
 * Získá aktuální inverter SN
 * @returns {string} Inverter SN
 */
function getInverterSN() {
    return INVERTER_SN;
}

// ============================================================================
// PLANNER SETTINGS / PLAN LABELS
// ============================================================================

const PLAN_LABELS = {
    hybrid: { short: 'Plán', long: 'Plánování' }
};

const PlannerState = (() => {
    const CACHE_TTL = 60 * 1000; // 1 minuta
    let cache = null;
    let lastFetch = 0;
    let inflight = null;

    const resolveActivePlan = (settings) => {
        // Single-planner: always hybrid (legacy name).
        return 'hybrid';
    };

    const fetchSettings = async (force = false) => {
        const now = Date.now();
        if (!force && cache && now - lastFetch < CACHE_TTL) {
            return cache;
        }
        if (inflight) {
            return inflight;
        }

        inflight = (async () => {
            if (!window.INVERTER_SN) {
                return null;
            }

            const endpoint = `oig_cloud/battery_forecast/${INVERTER_SN}/planner_settings`;

            try {
                const hass = window.DashboardAPI?.getHass?.() || window.getHass?.();
                let payload;

                if (hass && typeof hass.callApi === 'function') {
                    payload = await hass.callApi('GET', endpoint);
                } else {
                    const headers = { 'Content-Type': 'application/json' };
                    const token = window.DashboardAPI?.getHAToken?.();
                    if (token) {
                        headers.Authorization = `Bearer ${token}`;
                    }

                    const response = await fetch(`/api/${endpoint}`, {
                        method: 'GET',
                        headers,
                        credentials: 'same-origin'
                    });

                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }

                    payload = await response.json();
                }

                cache = payload;
                lastFetch = Date.now();
                return payload;
            } catch (error) {
                console.warn('[PlannerState] Failed to fetch planner settings', error);
                return null;
            } finally {
                inflight = null;
            }
        })();

        return inflight;
    };

    const getDefaultPlan = async (force = false) => {
        const settings = await fetchSettings(force);
        return resolveActivePlan(settings);
    };

    const getCachedSettings = () => cache;

    const getLabels = (plan = 'hybrid') => PLAN_LABELS[plan] || PLAN_LABELS.hybrid;

    return {
        fetchSettings,
        getDefaultPlan,
        getCachedSettings,
        resolveActivePlan,
        getLabels
    };
})();

// ============================================================================
// EXPORT DEFAULT (backward compatibility)
// ============================================================================

if (typeof window !== 'undefined') {
    window.DashboardAPI = {
        getHass,
        getHAToken,
        getSensorId,
        findShieldSensorId,
        getSensor,
        getSensorString,
        getSensorSafe,
        getSensorStringSafe,
        fetchOIGAPI,
        loadBatteryTimeline,
        loadUnifiedCostTile,
        loadSpotPrices,
        loadAnalytics,
        callService,
        openEntityDialog,
        batchLoadSensors,
        setInverterSN,
        getInverterSN,
        plannerState: PlannerState,
        planLabels: PLAN_LABELS
    };

    // Backward compatibility - expose getHass globally
    window.getHass = getHass;
    window.PlannerState = PlannerState;
    window.PLAN_LABELS = PLAN_LABELS;
}
