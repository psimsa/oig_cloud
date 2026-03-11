/* eslint-disable */
/**
 * OIG Cloud Dashboard - Utility Functions
 *
 * Helpers pro formatting, notifications, debouncing a další utility funkce.
 * Extrahováno z monolitického dashboard-core.js
 *
 * @module dashboard-utils
 * @version 1.0.0
 * @date 2025-11-02
 */

// ============================================================================
// FORMATTING FUNCTIONS
// ============================================================================

/**
 * Formátuje výkon (W → kW při >= 1000W)
 * @param {number} watts - Výkon ve wattech
 * @returns {string} Formátovaný string s jednotkou
 */
function formatPower(watts) {
    if (watts === null || watts === undefined || isNaN(watts)) return '-- W';
    const absWatts = Math.abs(watts);
    if (absWatts >= 1000) {
        return (watts / 1000).toFixed(2) + ' kW';
    } else {
        return Math.round(watts) + ' W';
    }
}

/**
 * Formátuje energii (Wh → kWh při >= 1000Wh)
 * @param {number} wattHours - Energie ve watthodinách
 * @returns {string} Formátovaný string s jednotkou
 */
function formatEnergy(wattHours) {
    if (wattHours === null || wattHours === undefined || isNaN(wattHours)) return '-- Wh';
    const absWh = Math.abs(wattHours);
    if (absWh >= 1000) {
        return (wattHours / 1000).toFixed(2) + ' kWh';
    } else {
        return Math.round(wattHours) + ' Wh';
    }
}

/**
 * Formátuje relativní čas (před X minutami/hodinami/dny)
 * @param {Date} date - Datum k porovnání
 * @returns {string} Lidsky čitelný relativní čas
 */
function formatRelativeTime(date) {
    if (!date) return '';

    const now = new Date();
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHour = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHour / 24);

    if (diffSec < 10) return 'právě teď';
    if (diffSec < 60) return `před ${diffSec} sekundami`;
    if (diffMin === 1) return 'před minutou';
    if (diffMin < 60) return `před ${diffMin} minutami`;
    if (diffHour === 1) return 'před hodinou';
    if (diffHour < 24) return `před ${diffHour} hodinami`;
    if (diffDay === 1) return 'včera';
    if (diffDay < 7) return `před ${diffDay} dny`;

    return date.toLocaleDateString('cs-CZ');
}

/**
 * Formátuje ČHMÚ datetime (ISO string → lidsky čitelný formát)
 * @param {string} isoString - ISO datetime string
 * @returns {string} Formátovaný čas
 */
function formatChmuDateTime(isoString) {
    if (!isoString) return '';
    try {
        const date = new Date(isoString);
        return date.toLocaleString('cs-CZ', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch (e) {
        return isoString;
    }
}

/**
 * Formátuje číslo s desetinným místem
 * @param {number} value - Hodnota
 * @param {number} decimals - Počet desetinných míst
 * @returns {string} Formátované číslo
 */
function formatNumber(value, decimals = 2) {
    if (value === null || value === undefined || isNaN(value)) return '--';
    return value.toFixed(decimals);
}

/**
 * Formátuje cenu v CZK
 * @param {number} value - Cena
 * @returns {string} Formátovaná cena s jednotkou
 */
function formatCurrency(value) {
    if (value === null || value === undefined || isNaN(value)) return '-- CZK';
    return `${value.toFixed(2)} CZK`;
}

/**
 * Formátuje procenta
 * @param {number} value - Hodnota (0-100)
 * @returns {string} Formátovaná procenta
 */
function formatPercent(value) {
    if (value === null || value === undefined || isNaN(value)) return '-- %';
    return `${Math.round(value)} %`;
}

// ============================================================================
// NOTIFICATION SYSTEM
// ============================================================================

/**
 * Zobrazí notifikaci (toast)
 * @param {string} title - Nadpis notifikace
 * @param {string} message - Text zprávy
 * @param {string} type - Typ: 'success', 'error', 'warning', 'info'
 */
function showNotification(title, message, type = 'success') {
    // Pokus o použití HA notification
    const hass = window.getHass?.();
    if (hass?.callService) {
        try {
            hass.callService('persistent_notification', 'create', {
                title: title,
                message: message,
                notification_id: `oig_dashboard_${Date.now()}`
            });
            return;
        } catch (e) {
            console.warn('[Notification] HA notification failed, using fallback:', e);
        }
    }

    // Fallback: browser console + alert (jen pro error)
    console.log(`[${type.toUpperCase()}] ${title}: ${message}`);
    if (type === 'error') {
        alert(`${title}\n\n${message}`);
    }
}

// ============================================================================
// DEBOUNCE HELPERS
// ============================================================================

/**
 * Vytvoří debounced verzi funkce
 * @param {Function} func - Funkce k debounce
 * @param {number} delay - Delay v ms
 * @returns {Function} Debounced funkce
 */
function debounce(func, delay) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), delay);
    };
}

/**
 * Vytvoří throttled verzi funkce
 * @param {Function} func - Funkce k throttle
 * @param {number} limit - Minimální interval v ms
 * @returns {Function} Throttled funkce
 */
function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// ============================================================================
// DOM HELPERS
// ============================================================================

// Cache pro previousValues (detekce změn)
const previousValues = {};
const _flipPadLengths = {};
const _flipElementTokens = new WeakMap();
let _flipTokenCounter = 0;
const _transientClassTimeouts = new WeakMap();

function _triggerTransientClass(element, className, durationMs) {
    if (!element || !className) return;

    let timeouts = _transientClassTimeouts.get(element);
    if (!timeouts) {
        timeouts = new Map();
        _transientClassTimeouts.set(element, timeouts);
    }

    const existing = timeouts.get(className);
    if (existing) {
        clearTimeout(existing);
    }

    // Restart animation reliably by removing + forcing reflow + adding back.
    element.classList.remove(className);
    // eslint-disable-next-line no-unused-expressions
    element.offsetWidth;
    element.classList.add(className);

    const timeoutId = setTimeout(() => {
        element.classList.remove(className);
        timeouts.delete(className);
    }, durationMs);
    timeouts.set(className, timeoutId);
}

function _splitGraphemes(value) {
    const str = value === null || value === undefined ? '' : String(value);
    try {
        if (typeof Intl !== 'undefined' && Intl.Segmenter) {
            const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
            return Array.from(segmenter.segment(str), (s) => s.segment);
        }
    } catch (e) {
        // Ignore and fall back
    }
    return Array.from(str);
}

function _renderChar(char) {
    return char === '' || char === ' ' ? '\u00A0' : char;
}

function _prefersReducedMotion() {
    try {
        return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) {
        return false;
    }
}

function _animateFlipCell(cell, fromChar, toChar, token, hostElement) {
    const staticTop = cell.querySelector('.oig-flip-static-top');
    const staticBottom = cell.querySelector('.oig-flip-static-bottom');
    const size = cell.querySelector('.oig-flip-size');
    if (!staticTop || !staticBottom || !size) return;

    // Ensure width matches the final character (prevents jitter)
    size.textContent = _renderChar(toChar);

    const animTop = document.createElement('span');
    animTop.className = 'oig-flip-face oig-flip-anim-top';
    animTop.textContent = _renderChar(fromChar);

    const animBottom = document.createElement('span');
    animBottom.className = 'oig-flip-face oig-flip-anim-bottom';
    animBottom.textContent = _renderChar(toChar);

    cell.appendChild(animTop);
    cell.appendChild(animBottom);

    animTop.addEventListener('animationend', () => {
        if (_flipElementTokens.get(hostElement) !== token) return;
        staticTop.textContent = _renderChar(toChar);
        animTop.remove();
    }, { once: true });

    animBottom.addEventListener('animationend', () => {
        if (_flipElementTokens.get(hostElement) !== token) return;
        staticBottom.textContent = _renderChar(toChar);
        animBottom.remove();
    }, { once: true });
}

function _renderSplitFlap(element, cacheKey, oldValue, newValue, forceFlip = false) {
    if (!element) return;
    if (_prefersReducedMotion()) {
        element.textContent = newValue;
        return;
    }

    const disablePad = element.dataset?.flipPad === 'none';

    const oldChars = _splitGraphemes(oldValue);
    const newChars = _splitGraphemes(newValue);

    const targetLen = disablePad
        ? newChars.length
        : Math.max(_flipPadLengths[cacheKey] || 0, oldChars.length, newChars.length);
    if (!disablePad) {
        _flipPadLengths[cacheKey] = targetLen;
    }

    // When padding is disabled, we intentionally do NOT pad with trailing spaces,
    // so shorter values stay visually centered (no "empty cells" on the right).
    if (!disablePad) {
        while (oldChars.length < targetLen) oldChars.push(' ');
        while (newChars.length < targetLen) newChars.push(' ');
    }

    const token = ++_flipTokenCounter;
    _flipElementTokens.set(element, token);

    const board = document.createElement('span');
    board.className = 'oig-flipboard';

    for (let i = 0; i < targetLen; i++) {
        const fromChar = oldChars[i] ?? ' ';
        const toChar = newChars[i] ?? ' ';

        const cell = document.createElement('span');
        cell.className = 'oig-flip-cell';

        // Hidden sizing span keeps layout stable and copy-paste friendly
        const size = document.createElement('span');
        size.className = 'oig-flip-size';
        size.textContent = _renderChar(toChar);

        const staticTop = document.createElement('span');
        staticTop.className = 'oig-flip-face oig-flip-static-top';
        staticTop.textContent = _renderChar(fromChar);

        const staticBottom = document.createElement('span');
        staticBottom.className = 'oig-flip-face oig-flip-static-bottom';
        staticBottom.textContent = _renderChar(fromChar);

        cell.appendChild(size);
        cell.appendChild(staticTop);
        cell.appendChild(staticBottom);
        board.appendChild(cell);

        if (forceFlip || fromChar !== toChar) {
            _animateFlipCell(cell, fromChar, toChar, token, element);
        } else {
            // No animation needed; ensure final character is shown
            staticTop.textContent = _renderChar(toChar);
            staticBottom.textContent = _renderChar(toChar);
        }
    }

    element.textContent = '';
    element.appendChild(board);
}

/**
 * Aktualizuje element jen pokud se hodnota změnila
 * @param {string} elementId - ID elementu
 * @param {string} newValue - Nová hodnota
 * @param {string} cacheKey - Klíč pro cache (optional)
 * @param {boolean} isFallback - True pokud je hodnota fallback (např. '--')
 * @param {boolean} animate - True = krátká vizuální animace při změně
 * @returns {boolean} True pokud se změnilo
 */
function updateElementIfChanged(elementId, newValue, cacheKey, isFallback = false, animate = true) {
    if (!cacheKey) cacheKey = elementId;
    const element = document.getElementById(elementId);
    if (!element) return false;

    const nextValue = newValue === null || newValue === undefined ? '' : String(newValue);

    // Update fallback visualization
    if (isFallback) {
        element.classList.add('fallback-value');
        element.setAttribute('title', 'Data nejsou k dispozici');
    } else {
        element.classList.remove('fallback-value');
        element.removeAttribute('title');
    }

    // Update value if changed
    const hasPrev = previousValues[cacheKey] !== undefined;
    const prevValue = hasPrev ? String(previousValues[cacheKey]) : undefined;
    if (!hasPrev || prevValue !== nextValue) {
        // Remember new value first (so rapid updates don't fight)
        previousValues[cacheKey] = nextValue;

        if (animate && !isFallback) {
            let fromValue = hasPrev ? prevValue : (element.textContent || '');
            // First load: still flip even if the element already contains the same text (tiles render directly).
            if (!hasPrev && fromValue === nextValue) {
                fromValue = '';
            }
            _renderSplitFlap(element, cacheKey, fromValue, nextValue, !hasPrev);
        } else {
            element.textContent = nextValue;
        }
        return true;
    }
    return false;
}

/**
 * Aktualizuje CSS třídu jen pokud se stav změnil
 * @param {HTMLElement} element - DOM element
 * @param {string} className - Název třídy
 * @param {boolean} shouldAdd - True = přidat, False = odebrat
 * @returns {boolean} True pokud se změnilo
 */
function updateClassIfChanged(element, className, shouldAdd) {
    if (!element) return false;
    const hasClass = element.classList.contains(className);
    if (shouldAdd && !hasClass) {
        element.classList.add(className);
        return true;
    } else if (!shouldAdd && hasClass) {
        element.classList.remove(className);
        return true;
    }
    return false;
}

/**
 * Najde element s retry mechanikou
 * @param {string} selector - CSS selector
 * @param {number} maxRetries - Max počet pokusů
 * @param {number} delay - Delay mezi pokusy (ms)
 * @returns {Promise<HTMLElement>} Element nebo null
 */
async function waitForElement(selector, maxRetries = 10, delay = 100) {
    for (let i = 0; i < maxRetries; i++) {
        const element = document.querySelector(selector);
        if (element) return element;
        await new Promise(resolve => setTimeout(resolve, delay));
    }
    return null;
}

// ============================================================================
// VALIDATION HELPERS
// ============================================================================

/**
 * Validuje, zda je hodnota číslo v rozsahu
 * @param {*} value - Hodnota k validaci
 * @param {number} min - Minimální hodnota
 * @param {number} max - Maximální hodnota
 * @returns {boolean} True pokud je validní
 */
function isNumberInRange(value, min, max) {
    const num = parseFloat(value);
    return !isNaN(num) && num >= min && num <= max;
}

/**
 * Validuje entity ID formát (sensor.xxx_yyy)
 * @param {string} entityId - Entity ID
 * @returns {boolean} True pokud je validní
 */
function isValidEntityId(entityId) {
    if (typeof entityId !== 'string') return false;
    return /^[a-z_]+\.[a-z0-9_]+$/.test(entityId);
}

// ============================================================================
// TIME HELPERS
// ============================================================================

/**
 * Vrátí aktuální čas ve formátu HH:MM:SS
 * @returns {string} Formátovaný čas
 */
function getCurrentTimeString() {
    const now = new Date();
    return now.toLocaleTimeString('cs-CZ');
}

/**
 * Převede sekundy na lidsky čitelný formát (1h 23m 45s)
 * @param {number} seconds - Počet sekund
 * @returns {string} Formátovaný čas
 */
function formatDuration(seconds) {
    if (!seconds || seconds < 0) return '0s';

    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    const parts = [];
    if (hours > 0) parts.push(`${hours}h`);
    if (minutes > 0) parts.push(`${minutes}m`);
    if (secs > 0 || parts.length === 0) parts.push(`${secs}s`);

    return parts.join(' ');
}

// ============================================================================
// SHIELD SENSOR UTILITIES
// ============================================================================

/**
 * Find shield sensor ID with support for numeric suffixes
 * Handles: sensor.oig_<SN>_<name> or sensor.oig_<SN>_<name>_2, _3, etc.
 * @param {string} sensorName - Sensor name (without prefix)
 * @returns {string} - Full entity ID
 */
function findShieldSensorId(sensorName) {
    try {
        const hass = getHass();
        if (!hass || !hass.states) {
            console.warn(`[Shield] Cannot find ${sensorName} - hass not available`);
            return `sensor.oig_${INVERTER_SN}_${sensorName}`; // Fallback to basic pattern
        }

        const sensorPrefix = `sensor.oig_${INVERTER_SN}_${sensorName}`;

        // Find matching entity with strict pattern:
        // - sensor.oig_<SN>_<name> (exact match)
        // - sensor.oig_<SN>_<name>_2, _3, etc. (with numeric suffix)
        const entityId = Object.keys(hass.states).find(id => {
            if (id === sensorPrefix) {
                return true; // Exact match
            }
            if (id.startsWith(sensorPrefix + '_')) {
                // Check if suffix is numeric (e.g., _2, _3)
                const suffix = id.substring(sensorPrefix.length + 1);
                return /^\d+$/.test(suffix);
            }
            return false;
        });

        if (!entityId) {
            console.warn(`[Shield] Sensor not found with prefix: ${sensorPrefix}`);
            return `sensor.oig_${INVERTER_SN}_${sensorName}`; // Fallback to basic pattern
        }

        return entityId;
    } catch (e) {
        console.error(`[Shield] Error finding sensor ${sensorName}:`, e);
        return `sensor.oig_${INVERTER_SN}_${sensorName}`; // Fallback to basic pattern
    }
}

// Export utilities
if (typeof window !== 'undefined') {
    window.DashboardUtils = {
        formatPower,
        formatEnergy,
        formatRelativeTime,
        formatChmuDateTime,
        formatNumber,
        formatCurrency,
        formatPercent,
        formatDuration,
        showNotification,
        debounce,
        throttle,
        updateElementIfChanged,
        updateClassIfChanged,
        waitForElement,
        isNumberInRange,
        isValidEntityId,
        getCurrentTimeString,
        findShieldSensorId
    };
}
