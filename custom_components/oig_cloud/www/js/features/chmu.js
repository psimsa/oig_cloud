/* eslint-disable */
// === ČHMÚ WEATHER WARNING FUNCTIONS ===

var chmuWarningData = null;

// Update ČHMÚ warning badge
function updateChmuWarningBadge() {
    const hass = getHass();
    if (!hass) return;

    const localSensorId = `sensor.oig_${INVERTER_SN}_chmu_warning_level`;
    const globalSensorId = `sensor.oig_${INVERTER_SN}_chmu_warning_level_global`;

    const localSensor = hass.states[localSensorId];
    const globalSensor = hass.states[globalSensorId];

    if (!localSensor) {
        console.log('[ČHMÚ] Local sensor not found:', localSensorId);
        return;
    }

    const badge = document.getElementById('chmu-warning-badge');
    const icon = document.getElementById('chmu-icon');
    const text = document.getElementById('chmu-text');

    if (!badge || !icon || !text) return;

    const severity = parseInt(localSensor.state) || 0;
    const attrs = localSensor.attributes || {};
    const warningsCount = attrs.warnings_count || 0;
    const eventType = attrs.event_type || '';

    // OPRAVENO: Pokud je warnings_count=0 nebo event_type obsahuje "Žádná výstraha", zobraz jako severity 0
    const effectiveSeverity = (warningsCount === 0 || eventType.includes('Žádná výstraha')) ? 0 : severity;

    // Store data for modal
    chmuWarningData = {
        local: localSensor,
        global: globalSensor,
        severity: effectiveSeverity
    };

    // Remove all severity classes
    badge.className = 'chmu-warning-badge';
    badge.classList.add(`severity-${effectiveSeverity}`);

    // Update icon and text based on effective severity
    if (effectiveSeverity === 0) {
        icon.textContent = '✓';
        text.textContent = 'Bez výstrah';
    } else {
        if (effectiveSeverity >= 3) {
            icon.textContent = '🚨';
        } else {
            icon.textContent = '⚠️';
        }

        // Show event type instead of generic "Oranžové varování"
        text.textContent = eventType;

        // If multiple warnings, show count
        if (warningsCount > 1) {
            text.textContent = `${eventType} +${warningsCount - 1}`;
        }
    }
}

/**
 * Update battery efficiency statistics on Pricing tab
 * Loads data from battery_efficiency sensor and displays monthly stats
 */
function toggleChmuWarningModal() {
    const modal = document.getElementById('chmu-modal');
    if (!modal) return;

    if (modal.classList.contains('active')) {
        closeChmuWarningModal();
    } else {
        openChmuWarningModal();
    }
}

// Open ČHMÚ warning modal
function openChmuWarningModal() {
    const modal = document.getElementById('chmu-modal');
    const modalBody = document.getElementById('chmu-modal-body');

    if (!modal || !modalBody || !chmuWarningData) return;

    modal.classList.add('active');

    // Render modal content
    renderChmuWarningModal(modalBody);
}

// Close ČHMÚ warning modal
function closeChmuWarningModal(event) {
    const modal = document.getElementById('chmu-modal');
    if (!modal) return;

    // If event is provided, check if we clicked outside the content
    if (event && event.target !== modal) return;

    modal.classList.remove('active');
}

// Render ČHMÚ warning modal content
function renderChmuWarningModal(container) {
    if (!chmuWarningData || !container) return;

    const { local, global } = chmuWarningData;
    const attrs = local.attributes || {};
    const severity = parseInt(local.state) || 0;

    // If no warnings
    if (severity === 0) {
        container.innerHTML = `
            <div class="chmu-no-warnings">
                <div class="chmu-no-warnings-icon">☀️</div>
                <h4>Žádná meteorologická výstraha</h4>
                <p>V současné době nejsou aktivní žádná varování pro váš region.</p>
            </div>
        `;
        return;
    }

    // Get warnings from new structure
    const allWarningsDetails = attrs.all_warnings_details || [];
    const topEventType = attrs.event_type;
    const topSeverity = attrs.severity;
    const topDescription = attrs.description;
    const topInstruction = attrs.instruction;
    const topOnset = attrs.onset;
    const topExpires = attrs.expires;
    const topEtaHours = attrs.eta_hours;

    if (allWarningsDetails.length === 0) {
        container.innerHTML = `
            <div class="chmu-no-warnings">
                <div class="chmu-no-warnings-icon">❓</div>
                <h4>Data nejsou k dispozici</h4>
                <p>Varování byla detekována, ale detaily nejsou dostupné.</p>
            </div>
        `;
        return;
    }

    const icon = getWarningIcon(topEventType);
    const severityLabel = getSeverityLabel(severity);
    const onset = topOnset ? formatChmuDateTime(topOnset) : '--';
    const expires = topExpires ? formatChmuDateTime(topExpires) : '--';

    let etaText = '';
    if (topEtaHours !== null && topEtaHours !== undefined) {
        if (topEtaHours <= 0) {
            etaText = '<div class="chmu-info-item"><div class="chmu-info-icon">⏱️</div><div class="chmu-info-content"><div class="chmu-info-label">Status</div><div class="chmu-info-value" style="color: #ef4444; font-weight: 700;">PROBÍHÁ NYNÍ</div></div></div>';
        } else if (topEtaHours < 24) {
            etaText = `<div class="chmu-info-item"><div class="chmu-info-icon">⏱️</div><div class="chmu-info-content"><div class="chmu-info-label">Začátek za</div><div class="chmu-info-value">${Math.round(topEtaHours)} hodin</div></div></div>`;
        }
    }

    // TOP WARNING (hlavní sekce)
    let html = `
        <div class="chmu-warning-item chmu-warning-top severity-${severity}">
            <div class="chmu-warning-header">
                <div class="chmu-warning-icon">${icon}</div>
                <div class="chmu-warning-title">
                    <h4>${topEventType}</h4>
                    <span class="chmu-warning-severity severity-${severity}">${severityLabel}</span>
                </div>
            </div>

            <div class="chmu-warning-info">
                <div class="chmu-info-item">
                    <div class="chmu-info-icon">⏰</div>
                    <div class="chmu-info-content">
                        <div class="chmu-info-label">Začátek</div>
                        <div class="chmu-info-value">${onset}</div>
                    </div>
                </div>
                <div class="chmu-info-item">
                    <div class="chmu-info-icon">⏳</div>
                    <div class="chmu-info-content">
                        <div class="chmu-info-label">Konec</div>
                        <div class="chmu-info-value">${expires}</div>
                    </div>
                </div>
                ${etaText}
            </div>

            ${topDescription ? `
                <div class="chmu-warning-description">
                    <strong>📋 Popis</strong>
                    <p>${topDescription}</p>
                </div>
            ` : ''}

            ${topInstruction ? `
                <div class="chmu-warning-description">
                    <strong>💡 Doporučení</strong>
                    <p>${topInstruction}</p>
                </div>
            ` : ''}
        </div>
    `;

    // ALL WARNINGS (seznam všech aktivních)
    if (allWarningsDetails.length > 1) {
        html += '<div class="chmu-all-warnings-header"><h5>📋 Všechny aktivní výstrahy</h5></div>';

        allWarningsDetails.forEach((warning, index) => {
            const wEventType = warning.event || 'Varování';
            const wSeverity = getSeverityLevelFromName(warning.severity);
            const wOnset = warning.onset ? formatChmuDateTime(warning.onset) : '--';
            const wExpires = warning.expires ? formatChmuDateTime(warning.expires) : '--';
            const wRegions = (warning.regions || []).join(', ') || 'Celá ČR';
            const wIcon = getWarningIcon(wEventType);
            const wSeverityLabel = warning.severity || 'Neznámá';

            html += `
                <div class="chmu-warning-item chmu-warning-compact severity-${wSeverity}">
                    <div class="chmu-warning-header">
                        <div class="chmu-warning-icon">${wIcon}</div>
                        <div class="chmu-warning-title">
                            <h5>${wEventType}</h5>
                            <span class="chmu-warning-severity severity-${wSeverity}">${wSeverityLabel}</span>
                        </div>
                    </div>
                    <div class="chmu-warning-info-compact">
                        <div class="chmu-info-row">
                            <span class="chmu-info-label">📍 Regiony:</span>
                            <span class="chmu-info-value">${wRegions}</span>
                        </div>
                        <div class="chmu-info-row">
                            <span class="chmu-info-label">⏰ Platnost:</span>
                            <span class="chmu-info-value">${wOnset} – ${wExpires}</span>
                        </div>
                    </div>
                </div>
            `;
        });
    }

    container.innerHTML = html;
}

// Helper: Convert severity name to level
function getSeverityLevelFromName(severityName) {
    const map = {
        'Minor': 1,
        'Moderate': 2,
        'Severe': 3,
        'Extreme': 4
    };
    return map[severityName] || 1;
}

// Get icon for warning type
function getWarningIcon(eventType) {
    const icons = {
        'Vítr': '🌪️',
        'Silný vítr': '💨',
        'Déšť': '🌧️',
        'Silný déšť': '⛈️',
        'Sníh': '❄️',
        'Sněžení': '🌨️',
        'Bouřky': '⛈️',
        'Mráz': '🥶',
        'Vedro': '🌡️',
        'Mlha': '🌫️',
        'Náledí': '🧊',
        'Laviny': '⚠️'
    };

    for (const [key, icon] of Object.entries(icons)) {
        if (eventType.includes(key)) return icon;
    }

    return '⚠️';
}

// Get severity label
function getSeverityLabel(severity) {
    const labels = {
        1: 'Minor',
        2: 'Moderate',
        3: 'Severe',
        4: 'Extreme'
    };
    return labels[severity] || 'Unknown';
}

// Format ČHMÚ datetime
function formatChmuDateTime(isoString) {
    if (!isoString) return '--';

    try {
        const date = new Date(isoString);
        const day = date.getDate().toString().padStart(2, '0');
        const month = (date.getMonth() + 1).toString().padStart(2, '0');
        const hours = date.getHours().toString().padStart(2, '0');
        const minutes = date.getMinutes().toString().padStart(2, '0');

        return `${day}.${month}. ${hours}:${minutes}`;
    } catch (e) {
        return isoString;
    }
}

// ========================================================================
// MODE TIMELINE DIALOG - Phase 2.7
// ========================================================================

// === TIMELINE (moved to dashboard-timeline.js) ===
// MODE_CONFIG is already defined in dashboard-timeline.js as const
// No need to re-declare it here

// Export ČHMÚ functions
window.DashboardChmu = {
    updateChmuWarningBadge,
    toggleChmuWarningModal,
    openChmuWarningModal,
    closeChmuWarningModal,
    renderChmuWarningModal,
    init: function() {
        console.log('[DashboardChmu] Initialized');
    }
};

console.log('[DashboardChmu] Module loaded');
