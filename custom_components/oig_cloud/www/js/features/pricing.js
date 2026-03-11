/* eslint-disable */
// === PRICING CHARTS ===
var loadPricingDataTimer = null;
var updatePlannedConsumptionTimer = null;
var priceCardHandlersAttached = false;  // Flag aby se handlery nastavily JEN JEDNOU
var currentPriceBlocks = {  // Aktuální bloky pro onClick handlery
    cheapest: null,
    expensive: null,
    bestExport: null,
    worstExport: null
};

// Cache for timeline data to prevent re-fetching on tab switch
var pricingPlanMode = null;

var timelineDataCache = {
    perPlan: {
        hybrid: { data: null, timestamp: null, chartsRendered: false, stale: true }
    }
};
const timelineFetchPromises = {
    hybrid: null
};

const PRICING_MODE_CONFIG = {
    'HOME I': { icon: '🏠', color: 'rgba(76, 175, 80, 0.16)', label: 'HOME I' },
    'HOME II': { icon: '⚡', color: 'rgba(33, 150, 243, 0.16)', label: 'HOME II' },
    'HOME III': { icon: '🔋', color: 'rgba(156, 39, 176, 0.16)', label: 'HOME III' },
    'HOME UPS': { icon: '🛡️', color: 'rgba(255, 152, 0, 0.18)', label: 'HOME UPS' },
    'FULL HOME UPS': { icon: '🛡️', color: 'rgba(255, 152, 0, 0.18)', label: 'FULL HOME UPS' },
    'DO NOTHING': { icon: '⏸️', color: 'rgba(158, 158, 158, 0.18)', label: 'DO NOTHING' }
};

const PRICING_MODE_ICON_PLUGIN_ID = 'pricingModeIcons';
let pricingModeIconPluginRegistered = false;

const pricingModeIconPlugin = {
    id: PRICING_MODE_ICON_PLUGIN_ID,
    beforeDatasetsDraw(chart, args, pluginOptions) {
        const segments = pluginOptions?.segments;
        if (!segments || segments.length === 0) {
            return;
        }

        const chartArea = chart.chartArea;
        const xScale = chart.scales?.x;
        if (!chartArea || !xScale) {
            return;
        }

        const ctx = chart.ctx;
        ctx.save();
        ctx.globalAlpha = pluginOptions?.backgroundOpacity ?? 0.12;

        segments.forEach((segment) => {
            const bounds = getPricingModeSegmentBounds(xScale, segment);
            if (!bounds) {
                return;
            }

            ctx.fillStyle = segment.color || 'rgba(255, 255, 255, 0.1)';
            ctx.fillRect(bounds.left, chartArea.top, bounds.width, chartArea.bottom - chartArea.top);
        });

        ctx.restore();
    },
	afterDatasetsDraw(chart, args, pluginOptions) {
		const segments = pluginOptions?.segments;
		if (!segments || segments.length === 0) {
			return;
		}

		const xScale = chart.scales?.x;
		const chartArea = chart.chartArea;
		if (!xScale || !chartArea) {
			return;
		}

		const iconSize = pluginOptions?.iconSize ?? 16;
		const labelSize = pluginOptions?.labelSize ?? 9;
		const iconFont = `${iconSize}px "Inter", "Segoe UI Emoji", "Noto Color Emoji", sans-serif`;
		const labelFont = `${labelSize}px "Inter", sans-serif`;
		const iconColor = pluginOptions?.iconColor || 'rgba(255, 255, 255, 0.95)';
		const labelColor = pluginOptions?.labelColor || 'rgba(255, 255, 255, 0.7)';
		const axisBandPadding = pluginOptions?.axisBandPadding ?? 10;
		const axisBandHeight = pluginOptions?.axisBandHeight ?? (iconSize + labelSize + 10);
			const axisBandColor = pluginOptions?.axisBandColor || 'rgba(6, 10, 18, 0.12)';
		const iconAlignment = pluginOptions?.iconAlignment || 'start';
		const iconStartOffset = pluginOptions?.iconStartOffset ?? 12;
		const iconBaselineOffset = pluginOptions?.iconBaselineOffset ?? 4;
		// Place the band below the X-axis labels (xScale.bottom is below tick labels).
		const axisBandTopRaw = (xScale.bottom || chartArea.bottom) + axisBandPadding;
		const axisBandTop = Math.min(axisBandTopRaw, chart.height - axisBandHeight - 2);
		const axisBandWidth = chartArea.right - chartArea.left;
		const baselineY = axisBandTop + iconBaselineOffset;

		const ctx = chart.ctx;
		// Draw behind axes/labels so we never obscure tick labels even if layout shifts.
		ctx.save();
		ctx.globalCompositeOperation = 'destination-over';
		ctx.fillStyle = axisBandColor;
		ctx.fillRect(chartArea.left, axisBandTop, axisBandWidth, axisBandHeight);
		ctx.restore();

		ctx.save();
		ctx.globalCompositeOperation = 'destination-over';
		ctx.textAlign = 'center';
		ctx.textBaseline = 'top';

		segments.forEach((segment) => {
			const bounds = getPricingModeSegmentBounds(xScale, segment);
			if (!bounds) {
				return;
			}

			let iconX;
			if (iconAlignment === 'start') {
				iconX = bounds.left + iconStartOffset;
				const maxStart = bounds.left + bounds.width - iconSize / 2;
				if (iconX > maxStart) {
					iconX = bounds.left + bounds.width / 2;
				}
			} else {
				iconX = bounds.left + bounds.width / 2;
			}

			ctx.font = iconFont;
			ctx.fillStyle = iconColor;
			ctx.fillText(segment.icon || '❓', iconX, baselineY);

			if (segment.shortLabel) {
				ctx.font = labelFont;
				ctx.fillStyle = labelColor;
				ctx.fillText(segment.shortLabel, iconX, baselineY + iconSize - 2);
			}
		});

		ctx.restore();
	}
};

function ensurePricingModeIconPluginRegistered() {
    if (typeof Chart === 'undefined' || !Chart.register) {
        return;
    }

    if (!pricingModeIconPluginRegistered) {
        Chart.register(pricingModeIconPlugin);
        pricingModeIconPluginRegistered = true;
    }
}

function getPricingModeSegmentBounds(xScale, segment) {
    if (!segment?.start || !segment?.end) {
        return null;
    }

    const xStart = xScale.getPixelForValue(segment.start);
    const xEnd = xScale.getPixelForValue(segment.end);

    if (!isFinite(xStart) || !isFinite(xEnd)) {
        return null;
    }

    const left = Math.min(xStart, xEnd);
    const width = Math.max(Math.abs(xEnd - xStart), 2);

    if (!isFinite(width) || width <= 0) {
        return null;
    }

    return { left, width };
}

function getTimelineCacheBucket(plan) {
    const normalized = plan || 'hybrid';
    if (!timelineDataCache.perPlan[normalized]) {
        timelineDataCache.perPlan[normalized] = { data: null, timestamp: null, chartsRendered: false, stale: true };
    }
    return timelineDataCache.perPlan[normalized];
}

function invalidatePricingTimelineCache(plan) {
    const plans = plan ? [plan] : Object.keys(timelineDataCache.perPlan);
    plans.forEach((key) => {
        const bucket = getTimelineCacheBucket(key);
        bucket.stale = true;
        bucket.chartsRendered = false;
    });
}

window.invalidatePricingTimelineCache = invalidatePricingTimelineCache;

// Debounced loadPricingData() - prevents excessive calls when multiple entities change
function debouncedLoadPricingData() {
    try {
        if (loadPricingDataTimer) clearTimeout(loadPricingDataTimer);
    } catch (e) { }
    try {
        loadPricingDataTimer = setTimeout(() => {
        if (pricingTabActive) {  // Only update if pricing tab is active
            loadPricingData();
        }
        }, 300); // Wait 300ms before executing (allow multiple changes to settle)
    } catch (e) {
        // Firefox can throw NS_ERROR_NOT_INITIALIZED if the document/window is being torn down.
        loadPricingDataTimer = null;
    }
}

// Debounced updatePlannedConsumptionStats() - prevents excessive calls when battery_forecast changes
function debouncedUpdatePlannedConsumption() {
    try {
        if (updatePlannedConsumptionTimer) clearTimeout(updatePlannedConsumptionTimer);
    } catch (e) { }
    try {
        updatePlannedConsumptionTimer = setTimeout(() => {
        if (pricingTabActive) {  // Only update if pricing tab is active
            updatePlannedConsumptionStats();
        }
        }, 300); // Wait 300ms before executing
    } catch (e) {
        // Firefox can throw NS_ERROR_NOT_INITIALIZED if the document/window is being torn down.
        updatePlannedConsumptionTimer = null;
    }
}

var combinedChart = null;

// Helper funkce pro detekci theme a barvy
function isLightTheme() {
    try {
        const haElement = parent.document.querySelector('home-assistant');
        if (haElement) {
            const computedStyle = getComputedStyle(haElement);
            const primaryBg = computedStyle.getPropertyValue('--primary-background-color');
            if (primaryBg) {
                const rgb = primaryBg.match(/\d+/g);
                if (rgb && rgb.length >= 3) {
                    const brightness = (parseInt(rgb[0]) + parseInt(rgb[1]) + parseInt(rgb[2])) / 3;
                    return brightness > 128;
                }
            }
        }
    } catch (e) { }
    return false; // Default: dark theme
}

async function ensurePricingPlanMode(force = false) {
    if (pricingPlanMode && !force) {
        return pricingPlanMode;
    }

    if (window.PlannerState) {
        try {
            const plan = await window.PlannerState.getDefaultPlan(force);
            pricingPlanMode = plan || 'hybrid';
        } catch (error) {
            console.warn('[Pricing] Failed to resolve default plan', error);
            pricingPlanMode = 'hybrid';
        }
    } else {
        pricingPlanMode = 'hybrid';
    }

    updateChartPlanIndicator();
    return pricingPlanMode;
}

function updateChartPlanIndicator() {
    const buttons = document.querySelectorAll('.chart-plan-toggle-btn');
    buttons.forEach((btn) => {
        const plan = btn.getAttribute('data-plan');
        btn.classList.toggle('active', plan === pricingPlanMode);
    });

    const pill = document.getElementById('chart-plan-pill');
    if (pill) {
        const label = window.PLAN_LABELS?.[pricingPlanMode]?.short || 'Plán';
        pill.textContent = label;
        // No dual-plan UI - keep pill in default styling.
    }
}

function initChartPlanToggle() {
    const buttons = document.querySelectorAll('.chart-plan-toggle-btn');
    if (!buttons.length) {
        return;
    }

    buttons.forEach((btn) => {
        btn.addEventListener('click', () => {
            const plan = btn.getAttribute('data-plan') || 'hybrid';
            if (plan === pricingPlanMode) {
                return;
            }
            pricingPlanMode = plan;
            const cacheBucket = getTimelineCacheBucket(plan);
            cacheBucket.chartsRendered = false;
            updateChartPlanIndicator();
            loadPricingData();
        });
    });

    ensurePricingPlanMode();
}

function getTextColor() {
    return isLightTheme() ? '#333333' : '#ffffff';
}

function getGridColor() {
    return isLightTheme() ? 'rgba(0,0,0,0.1)' : 'rgba(255,255,255,0.1)';
}

function resolvePricingMode(point) {
    if (!point) {
        return null;
    }

    const raw =
        point.mode_name ||
        point.mode_planned ||
        point.mode ||
        point.mode_display ||
        null;

    if (!raw || typeof raw !== 'string') {
        return null;
    }

    const normalized = raw.trim();
    return normalized.length ? normalized : null;
}

function getPricingModeShortLabel(modeName) {
    if (!modeName) {
        return '';
    }

    if (modeName.startsWith('HOME ')) {
        return modeName.replace('HOME ', '').trim();
    }

    if (modeName === 'FULL HOME UPS' || modeName === 'HOME UPS') {
        return 'UPS';
    }

    if (modeName === 'DO NOTHING') {
        return 'DN';
    }

    return modeName.substring(0, 3).toUpperCase();
}

function getPricingModeMeta(modeName) {
    if (!modeName) {
        return { icon: '❓', color: 'rgba(158, 158, 158, 0.15)', label: 'Unknown' };
    }

    if (window.DashboardTimeline?.MODE_CONFIG?.[modeName]) {
        const base = window.DashboardTimeline.MODE_CONFIG[modeName];
        return {
            icon: base.icon || '❓',
            color: adjustModeColorAlpha(base.color || 'rgba(158, 158, 158, 0.15)'),
            label: base.label || modeName
        };
    }

    return PRICING_MODE_CONFIG[modeName] || { icon: '❓', color: 'rgba(158, 158, 158, 0.15)', label: modeName };
}

function adjustModeColorAlpha(color, targetAlpha = 0.15) {
    if (typeof color !== 'string') {
        return `rgba(158, 158, 158, ${targetAlpha})`;
    }

    if (color.startsWith('rgba')) {
        const match = color.match(/rgba\(([^)]+)\)/);
        if (match && match[1]) {
            const parts = match[1].split(',').map(part => part.trim());
            if (parts.length === 4) {
                return `rgba(${parts[0]}, ${parts[1]}, ${parts[2]}, ${targetAlpha})`;
            }
        }
    }

    if (color.startsWith('rgb(')) {
        return color.replace('rgb', 'rgba').replace(')', `, ${targetAlpha})`);
    }

    return color;
}

function buildPricingModeSegments(timelineData) {
    if (!Array.isArray(timelineData) || timelineData.length === 0) {
        return [];
    }

    const segments = [];
    let currentSegment = null;

    timelineData.forEach((point) => {
        const modeName = resolvePricingMode(point);
        if (!modeName) {
            currentSegment = null;
            return;
        }

        const startTime = new Date(point.timestamp);
        const endTime = new Date(startTime.getTime() + 15 * 60 * 1000);

        if (!currentSegment || currentSegment.mode !== modeName) {
            currentSegment = {
                mode: modeName,
                start: startTime,
                end: endTime
            };
            segments.push(currentSegment);
        } else {
            currentSegment.end = endTime;
        }
    });

    return segments.map((segment) => {
        const meta = getPricingModeMeta(segment.mode);
        return {
            ...segment,
            icon: meta.icon,
            color: meta.color,
            label: meta.label,
            shortLabel: getPricingModeShortLabel(segment.mode)
        };
    });
}

function buildPricingModeIconOptions(segments) {
    if (!segments || segments.length === 0) {
        return null;
    }

    return {
        segments,
        iconSize: 18,
        labelSize: 10,
        iconAlignment: 'start',
        iconStartOffset: 14,
        iconBaselineOffset: 6,
        iconColor: 'rgba(255, 255, 255, 0.95)',
        labelColor: 'rgba(255, 255, 255, 0.7)',
        backgroundOpacity: 0.14,
        // Keep this compact and below X-axis labels.
        axisBandPadding: 10,
        axisBandHeight: 28,
        axisBandColor: 'rgba(6, 10, 18, 0.12)'
    };
}

function applyPricingModeIconPadding(options, pluginOptions) {
    if (!options) {
        return;
    }

    if (!options.layout) {
        options.layout = {};
    }

    if (!options.layout.padding) {
        options.layout.padding = {};
    }

    const padding = options.layout.padding;
    const axisBandPadding = pluginOptions?.axisBandPadding ?? 10;
    const axisBandHeight = pluginOptions?.axisBandHeight ?? (pluginOptions?.iconSize || 18) + (pluginOptions?.labelSize || 10) + 6;
    const extra = pluginOptions ? axisBandPadding + axisBandHeight + 6 : 12;

    padding.top = padding.top ?? 12;
    padding.bottom = Math.max(padding.bottom || 0, extra);
}

// Convert Date to local ISO string (without timezone conversion to UTC)
function toLocalISOString(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');
    return `${year}-${month}-${day}T${hours}:${minutes}:${seconds}`;
}

function getBoxId() {
    updateChartPlanIndicator();

    const hass = getHass();
    if (!hass || !hass.states) return null;
    for (const entityId in hass.states) {
        const match = entityId.match(/^sensor\.oig_(\d+)_/);
        if (match) return match[1];
    }
    return null;
}

// Reset zoom grafu na původní rozsah
function resetChartZoom() {
    if (combinedChart) {
        // Resetovat zoom pomocí odstranění scale limits
        delete combinedChart.options.scales.x.min;
        delete combinedChart.options.scales.x.max;
        combinedChart.update('none');

        currentZoomRange = null;  // Reset zoom state

        // Odebrat zoom-active z aktivní karty
        if (activeZoomCard) {
            activeZoomCard.classList.remove('zoom-active');
            activeZoomCard = null;
        }

        updateChartDetailLevel(combinedChart);
    }
}

// Přepínání režimu zobrazování datalabels
function toggleDatalabelMode() {
    const modes = ['auto', 'always', 'never'];
    const currentIndex = modes.indexOf(datalabelMode);
    const nextIndex = (currentIndex + 1) % modes.length;
    datalabelMode = modes[nextIndex];

    // Aktualizovat UI
    const btnText = document.getElementById('datalabel-mode-text');
    const btn = document.getElementById('datalabel-toggle-btn');

    if (btnText) {
        const labels = { 'auto': 'Auto', 'always': 'Vždy', 'never': 'Nikdy' };
        btnText.textContent = labels[datalabelMode];
    }

    // Změnit barvu tlačítka podle módu
    if (btn) {
        if (datalabelMode === 'always') {
            btn.style.background = 'rgba(76,175,80,0.3)';
            btn.style.borderColor = 'rgba(76,175,80,0.7)';
        } else if (datalabelMode === 'never') {
            btn.style.background = 'rgba(244,67,54,0.2)';
            btn.style.borderColor = 'rgba(244,67,54,0.5)';
        } else {
            btn.style.background = 'rgba(76,175,80,0.2)';
            btn.style.borderColor = 'rgba(76,175,80,0.5)';
        }
    }

    // Aktualizovat graf
    if (combinedChart) {
        updateChartDetailLevel(combinedChart);
    }

    console.log('[Datalabels] Mode changed to:', datalabelMode);
}

// Sledování aktuálního zoom stavu
var currentZoomRange = null;
var activeZoomCard = null; // Reference na aktuálně aktivní kartu

// Datalabels režim: 'auto' (závislé na zoomu), 'always', 'never'
var datalabelMode = 'auto';

// Toggle zoom: pokud není zoom -> zoom IN, pokud je zoom -> zoom OUT
function zoomToTimeRange(startTime, endTime, cardElement = null) {
    if (!combinedChart) {
        console.log('[Zoom] Chart not available');
        return;
    }

    // Zkontrolovat jestli je už zazoomováno na tento rozsah
    const start = new Date(startTime);
    const end = new Date(endTime);
    const marginMs = 15 * 60 * 1000;
    const zoomStart = start.getTime() - marginMs;
    const zoomEnd = end.getTime() + marginMs;

    // Pokud už je zazoomováno na tento interval -> ZOOM OUT (reset)
    if (currentZoomRange &&
        Math.abs(currentZoomRange.start - zoomStart) < 60000 &&
        Math.abs(currentZoomRange.end - zoomEnd) < 60000) {
        console.log('[Zoom] Already zoomed to this range -> ZOOM OUT');

        // Reset zoom: odstranit scale limits
        delete combinedChart.options.scales.x.min;
        delete combinedChart.options.scales.x.max;
        combinedChart.update('none');

        currentZoomRange = null;

        // Odebrat zoom-active třídu z aktivní karty
        if (activeZoomCard) {
            activeZoomCard.classList.remove('zoom-active');
            activeZoomCard = null;
        }

        updateChartDetailLevel(combinedChart);
        return;
    }

    // ZOOM IN na nový interval
    console.log('[Zoom] ZOOM IN to range:', startTime, '->', endTime);
    console.log('[Zoom] Calculated zoom:', new Date(zoomStart), '->', new Date(zoomEnd));

    try {
        // OPRAVA: zoom() metoda nefunguje správně pro absolutní rozsah
        // Místo toho nastavíme přímo scale limits a zavoláme update()

        // Nastavit min/max na scale
        combinedChart.options.scales.x.min = zoomStart;
        combinedChart.options.scales.x.max = zoomEnd;

        // Aplikovat změny
        combinedChart.update('none'); // 'none' = bez animace, okamžitě

        console.log('[Zoom] Chart X scale after update - min:', combinedChart.scales.x.min, 'max:', combinedChart.scales.x.max);

        // Uložit aktuální zoom
        currentZoomRange = { start: zoomStart, end: zoomEnd };
        console.log('[Zoom] Zoom IN applied successfully');

        // Odebrat zoom-active ze všech karet
        document.querySelectorAll('.stat-card.zoom-active').forEach(card => {
            card.classList.remove('zoom-active');
        });

        // Přidat zoom-active na novou kartu
        if (cardElement) {
            cardElement.classList.add('zoom-active');
            activeZoomCard = cardElement;
        }

        // Aktualizovat detail level
        updateChartDetailLevel(combinedChart);
    } catch (error) {
        console.error('[Zoom] Error:', error);
    }
}

// Adaptivní úprava detailu grafu podle úrovně zoomu
function updateChartDetailLevel(chart) {
    if (!chart || !chart.scales || !chart.scales.x) return;

    const xScale = chart.scales.x;
    const visibleRange = xScale.max - xScale.min; // v milisekundách
    const hoursVisible = visibleRange / (1000 * 60 * 60);

    // Určit úroveň detailu
    let detailLevel = 'overview'; // celkový pohled (>24h)
    if (hoursVisible <= 24) detailLevel = 'day'; // denní pohled (6-24h)
    if (hoursVisible <= 6) detailLevel = 'detail'; // detailní pohled (<6h)

    // Adaptivní nastavení legend
    if (chart.options.plugins.legend) {
        // Overview: kompaktní legenda
        if (detailLevel === 'overview') {
            chart.options.plugins.legend.labels.padding = 10;
            chart.options.plugins.legend.labels.font.size = 11;
        }
        // Detail: větší legenda
        else if (detailLevel === 'detail') {
            chart.options.plugins.legend.labels.padding = 12;
            chart.options.plugins.legend.labels.font.size = 12;
        }
        // Day: střední
        else {
            chart.options.plugins.legend.labels.padding = 10;
            chart.options.plugins.legend.labels.font.size = 11;
        }
    }

    // Adaptivní nastavení os Y
    const yAxes = ['y-price', 'y-solar', 'y-power'];
    yAxes.forEach(axisId => {
        const axis = chart.options.scales[axisId];
        if (!axis) return;

        if (detailLevel === 'overview') {
            // Overview: menší titulky, skrýt některé
            axis.title.display = false; // Skrýt názvy os
            axis.ticks.font.size = 10;
            if (axisId === 'y-solar') axis.display = false; // Skrýt střední osu
        } else if (detailLevel === 'detail') {
            // Detail: plné titulky
            axis.title.display = true;
            axis.title.font.size = 12;
            axis.ticks.font.size = 11;
            axis.display = true;
        } else {
            // Day: střední velikost
            axis.title.display = true;
            axis.title.font.size = 11;
            axis.ticks.font.size = 10;
            axis.display = true;
        }
    });

    // Adaptivní nastavení X osy
    if (chart.options.scales.x) {
        if (detailLevel === 'overview') {
            chart.options.scales.x.ticks.maxTicksLimit = 12;
            chart.options.scales.x.ticks.font.size = 10;
        } else if (detailLevel === 'detail') {
            chart.options.scales.x.ticks.maxTicksLimit = 24;
            chart.options.scales.x.ticks.font.size = 11;
            // V detailu ukázat i minuty
            chart.options.scales.x.time.displayFormats.hour = 'HH:mm';
        } else {
            chart.options.scales.x.ticks.maxTicksLimit = 16;
            chart.options.scales.x.ticks.font.size = 10;
            chart.options.scales.x.time.displayFormats.hour = 'dd.MM HH:mm';
        }
    }

    // Adaptivní zobrazení datalabels podle zoom úrovně a módu
    const shouldShowLabels = (datalabelMode === 'always') ||
        (datalabelMode === 'auto' && hoursVisible <= 6);

    chart.data.datasets.forEach((dataset, idx) => {
        if (!dataset.datalabels) {
            dataset.datalabels = {};
        }

        // Vypnout labely pokud režim = 'never'
        if (datalabelMode === 'never') {
            dataset.datalabels.display = false;
            return;
        }

        // Zobrazit labely pro VŠECHNY datasety při zoomu
        if (shouldShowLabels) {
            // Určit hustotu zobrazování podle zoom úrovně
            let showEveryNth = 1;
            if (hoursVisible > 3 && hoursVisible <= 6) {
                showEveryNth = 2; // 3-6h: každý druhý bod
            } else if (hoursVisible > 6) {
                showEveryNth = 4; // >6h: každý čtvrtý bod
            }
            // <3h: všechny body (showEveryNth = 1)

            dataset.datalabels.display = (context) => {
                const value = context.dataset.data[context.dataIndex];
                if (value == null || value === 0) return false;
                return context.dataIndex % showEveryNth === 0;
            };

            // Nastavení podle typu dat
            const isPrice = dataset.yAxisID === 'y-price';
            const isSolar = dataset.label && (dataset.label.includes('Solární') || dataset.label.includes('String'));
            const isBattery = dataset.label && dataset.label.includes('kapacita');

            dataset.datalabels.align = 'top';
            dataset.datalabels.offset = 6;
            dataset.datalabels.color = '#fff';
            dataset.datalabels.font = { size: 9, weight: 'bold' };

            // Formátování podle typu
            if (isPrice) {
                dataset.datalabels.formatter = (value) => value != null ? value.toFixed(2) + ' Kč' : '';
                dataset.datalabels.backgroundColor = dataset.borderColor || 'rgba(33, 150, 243, 0.8)';
            } else if (isSolar) {
                dataset.datalabels.formatter = (value) => value != null ? value.toFixed(1) + ' kW' : '';
                dataset.datalabels.backgroundColor = dataset.borderColor || 'rgba(255, 193, 7, 0.8)';
            } else if (isBattery) {
                dataset.datalabels.formatter = (value) => value != null ? value.toFixed(1) + ' kWh' : '';
                dataset.datalabels.backgroundColor = dataset.borderColor || 'rgba(120, 144, 156, 0.8)';
            } else {
                // Ostatní datasety
                dataset.datalabels.formatter = (value) => value != null ? value.toFixed(1) : '';
                dataset.datalabels.backgroundColor = dataset.borderColor || 'rgba(33, 150, 243, 0.8)';
            }

            dataset.datalabels.borderRadius = 4;
            dataset.datalabels.padding = { top: 3, bottom: 3, left: 5, right: 5 };
        } else {
            dataset.datalabels.display = false;
        }
    });

    chart.update('none'); // Update bez animace
    console.log(`[Detail] Zoom level: ${hoursVisible.toFixed(1)}h, Labels: ${shouldShowLabels ? 'ON' : 'OFF'}, Mode: ${datalabelMode}`);
}

// Najít extrémní blok cen (nejlevnější/nejdražší 3h období)
function findExtremePriceBlock(prices, findLowest, blockHours = 3) {
    if (!prices || prices.length === 0) return null;

    const blockSize = Math.floor((blockHours * 60) / 15); // 3h = 12 intervalů po 15min
    if (prices.length < blockSize) return null;

    let extremeBlock = null;
    let extremeAvg = findLowest ? Infinity : -Infinity;

    // Sliding window přes všechny možné bloky
    for (let i = 0; i <= prices.length - blockSize; i++) {
        const block = prices.slice(i, i + blockSize);
        const blockValues = block.map(p => p.price);
        const blockAvg = blockValues.reduce((a, b) => a + b, 0) / blockValues.length;

        if ((findLowest && blockAvg < extremeAvg) || (!findLowest && blockAvg > extremeAvg)) {
            extremeAvg = blockAvg;
            extremeBlock = {
                avg: blockAvg,
                min: Math.min(...blockValues),
                max: Math.max(...blockValues),
                start: block[0].timestamp,
                end: block[block.length - 1].timestamp,
                values: blockValues
            };
        }
    }

    return extremeBlock;
}

// Vytvořit mini graf pro cenový blok
function createMiniPriceChart(canvasId, values, color, startTime, endTime) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Chart.js keeps a global registry per canvas. Always destroy any existing instance first
    // to avoid: "Canvas is already in use. Chart with ID ... must be destroyed..."
    try {
        const existing = typeof Chart !== 'undefined' && Chart.getChart ? Chart.getChart(canvas) : null;
        if (existing) {
            existing.destroy();
        }
    } catch (e) {
        // ignore - best effort cleanup
    }

    // Vypočítat statistiky pro detekci razantních změn (potřebujeme před optimalizací)
    const avg = values.reduce((a, b) => a + b, 0) / values.length;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min;
    const threshold = range * 0.25; // Razantní změna = >25% rozsahu

    // Detekovat body s razantní změnou
    const significantPoints = [];
    values.forEach((value, idx) => {
        // Porovnat s průměrem a sousedy
        const prevValue = idx > 0 ? values[idx - 1] : value;
        const nextValue = idx < values.length - 1 ? values[idx + 1] : value;
        const change = Math.max(Math.abs(value - prevValue), Math.abs(value - nextValue));

        // Nebo extrémy (top/bottom 20%)
        const isExtreme = value >= max - threshold || value <= min + threshold;
        const isBigChange = change > threshold;

        if (isExtreme || isBigChange) {
            significantPoints.push(idx);
        }
    });

    // OPTIMALIZACE: Kontrola jestli se data změnila
    const dataKey = JSON.stringify({ values, color, startTime, endTime });
    if (canvas.lastDataKey === dataKey && canvas.chart) {
        // Data se nezměnila, nepřekreslovat
        return;
    }
    canvas.lastDataKey = dataKey;

    // Pokud existuje graf a jen se změnila data (ne struktura), aktualizovat
    if (canvas.chart && canvas.chart.data.datasets[0]) {
        const dataset = canvas.chart.data.datasets[0];
        const labelsChanged = canvas.chart.data.labels.length !== values.length;

        if (!labelsChanged) {
            // Jen aktualizovat data bez destroy
            dataset.data = values;
            dataset.borderColor = color;
            dataset.backgroundColor = color.replace('1)', '0.2)');
            dataset.pointBackgroundColor = values.map((_, i) =>
                significantPoints.includes(i) ? color : 'transparent'
            );
            canvas.chart.update('none'); // Update bez animace
            return;
        }
    }

    // Pokud neexistuje graf nebo se změnila struktura, zničit a vytvořit nový
    if (canvas.chart) {
        canvas.chart.destroy();
    }

    // Vytvořit absolutní časy pro X osu (ne relativní offsety)
    const start = new Date(startTime);
    const timeLabels = values.map((_, i) => {
        const time = new Date(start.getTime() + i * 15 * 60 * 1000);
        return time.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' });
    });

    // Vytvořit nový interaktivní mini graf (bez svislých čar)
    canvas.chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: timeLabels,
            datasets: [{
                data: values,
                borderColor: color,
                backgroundColor: color.replace('1)', '0.2)'),
                borderWidth: 2,
                fill: true,
                tension: 0.3,
                pointRadius: (context) => {
                    // Větší body pro razantní změny
                    return significantPoints.includes(context.dataIndex) ? 4 : 0;
                },
                pointBackgroundColor: color,
                pointBorderColor: '#fff',
                pointBorderWidth: 1,
                pointHoverRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,  // OPRAVA: Používat fixní výšku z HTML (40px)
            plugins: {
                legend: { display: false },
                tooltip: {
                    enabled: true,
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    titleColor: '#fff',
                    bodyColor: '#fff',
                    padding: 8,
                    displayColors: false,
                    callbacks: {
                        title: (items) => items[0].label,  // Zobrazit přesný čas místo "+Xmin"
                        label: (item) => `${item.parsed.y.toFixed(2)} Kč/kWh`
                    }
                },
                datalabels: {
                    display: (context) => {
                        // Ukázat labely jen pro razantní změny
                        return significantPoints.includes(context.dataIndex);
                    },
                    align: 'top',
                    offset: 4,
                    color: '#fff',
                    font: { size: 8, weight: 'bold' },
                    formatter: (value) => value.toFixed(2),
                    backgroundColor: color.replace('1)', '0.8)'),
                    borderRadius: 3,
                    padding: { top: 2, bottom: 2, left: 4, right: 4 }
                },
                zoom: {
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
                        drag: {
                            enabled: true,
                            backgroundColor: 'rgba(33, 150, 243, 0.3)'
                        },
                        mode: 'x'
                    }
                }
            },
            scales: {
                x: { display: false },
                y: {
                    display: true,
                    position: 'right',  // Y osa napravo
                    grace: '10%',  // Trochu prostoru kolem dat
                    ticks: {
                        color: 'rgba(255, 255, 255, 0.6)',
                        font: { size: 8 },
                        callback: function (value) {
                            return value.toFixed(1);  // Zobrazit s 1 desetinným místem
                        },
                        maxTicksLimit: 3  // Max 3 hodnoty (min, střed, max)
                    },
                    grid: {
                        display: false  // Žádné horizontální čáry
                    }
                }
            },
            layout: {
                padding: 0
            },
            interaction: {
                mode: 'nearest',
                intersect: false
            }
        }
    });

    // Uložit časy pro zoom funkci
    canvas.dataset.startTime = startTime;
    canvas.dataset.endTime = endTime;
}

async function loadPricingData() {
    const perfStart = performance.now();
    console.log('[Pricing] === loadPricingData START ===');

    // Start cost tile loading ASAP (non-blocking)
    if (typeof loadCostComparisonTile === 'function') {
        loadCostComparisonTile().catch((error) => {
            console.error('[Pricing] Cost tile preload failed:', error);
        });
    }

    await ensurePricingPlanMode();

    // Show loading overlay
    const loadingOverlay = document.getElementById('pricing-loading-overlay');
    if (loadingOverlay) {
        loadingOverlay.style.display = 'block';
    }

    const hass = getHass();
    if (!hass || !hass.states) {
        if (loadingOverlay) loadingOverlay.style.display = 'none';
        return;
    }
    const boxId = getBoxId();
    if (!boxId) {
        if (loadingOverlay) loadingOverlay.style.display = 'none';
        return;
    }
    const datasets = [];
    let allLabels = [];

    const { data: rawTimelineData, fromCache } = await getTimelineData(pricingPlanMode, boxId);
    const cacheBucket = getTimelineCacheBucket(pricingPlanMode);

    if (fromCache) {
        console.log(`[Pricing] Using cached ${pricingPlanMode} timeline data (age: ${Math.round((Date.now() - cacheBucket.timestamp) / 1000)}s)`);
        if (cacheBucket.chartsRendered) {
            const perfEnd = performance.now();
            console.log(`[Pricing] Charts already rendered, skipping re-render (took ${(perfEnd - perfStart).toFixed(1)}ms)`);

            if (loadingOverlay) loadingOverlay.style.display = 'none';
            return;
        }
    }

    let timelineData = Array.isArray(rawTimelineData) ? [...rawTimelineData] : [];

    // OPRAVA: Filtrovat pouze aktuální a budoucí intervaly
    const nowDate = new Date();
    const bucketStart = new Date(nowDate);
    bucketStart.setMinutes(Math.floor(nowDate.getMinutes() / 15) * 15, 0, 0);
    timelineData = timelineData.filter(point => {
        const pointTime = new Date(point.timestamp);
        return pointTime >= bucketStart;
    });
    console.log(`[Pricing] After filtering future intervals: ${timelineData.length} points`);

    const modeSegments = buildPricingModeSegments(timelineData);
    const modeIconOptions = buildPricingModeIconOptions(modeSegments);
    if (modeIconOptions) {
        ensurePricingModeIconPluginRegistered();
    }

    // Convert timeline to prices format for compatibility with existing code
    const prices = timelineData.map(point => ({
        timestamp: point.timestamp,
        price: point.spot_price_czk || 0
    }));

    const exportPrices = timelineData.map(point => ({
        timestamp: point.timestamp,
        price: point.export_price_czk || 0
    }));

    // Spot prices (15min) - cards and chart
    const spotEntityId = 'sensor.oig_' + boxId + '_spot_price_current_15min';
    const spotSensor = hass.states[spotEntityId];

    // Update current price card from sensor state (not attributes)
    if (spotSensor && spotSensor.state) {
        const currentPrice = parseFloat(spotSensor.state);
        if (!isNaN(currentPrice)) {
            const spotCard = document.getElementById('current-spot-price');
            if (spotCard) {
                spotCard.innerHTML = currentPrice.toFixed(2) + ' <span class="stat-unit">Kč/kWh</span>';
                spotCard.parentElement.style.cursor = 'pointer';
                spotCard.parentElement.onclick = () => openEntityDialog(spotEntityId);
            }
        }
    }

    if (prices.length > 0) {
        const priceValues = prices.map(p => p.price);
        const avg = priceValues.reduce((a, b) => a + b, 0) / priceValues.length;
        const avgCard = document.getElementById('avg-spot-today');
        if (avgCard) {
            avgCard.innerHTML = avg.toFixed(2) + ' <span class="stat-unit">Kč/kWh</span>';
            avgCard.parentElement.style.cursor = 'pointer';
            avgCard.parentElement.onclick = () => openEntityDialog(spotEntityId);
        }

        // Parse timestamps from timeline
        allLabels = prices.map(p => {
            const timeStr = p.timestamp;
            if (!timeStr) return new Date();

            try {
                const [datePart, timePart] = timeStr.split('T');
                if (!datePart || !timePart) return new Date();

                const [year, month, day] = datePart.split('-').map(Number);
                const [hour, minute, second = 0] = timePart.split(':').map(Number);

                return new Date(year, month - 1, day, hour, minute, second);
            } catch (error) {
                console.error('[Pricing] Error parsing timestamp:', timeStr, error);
                return new Date();
            }
        });

            // Uložit kompletní data pro výpočet extrémů (nezávisle na zoomu)
            const spotPriceData = prices.map(p => p.price);
            originalPriceData = spotPriceData;

            // Identifikace top/bottom 10% cen z CELÉHO datasetu
            const sortedPrices = [...priceValues].sort((a, b) => a - b);
            const tenPercentCount = Math.max(1, Math.ceil(sortedPrices.length * 0.1));
            const bottomThreshold = sortedPrices[tenPercentCount - 1];
            const topThreshold = sortedPrices[sortedPrices.length - tenPercentCount];

            // ODSTRANIT tečky u extrémů - čistý graf
            const pointRadii = spotPriceData.map(price => 0);  // Všechny body neviditelné
            const pointColors = spotPriceData.map(price => '#42a5f5');  // Jednotná barva

            // Detekce pozic extrémů pro chytré rozložení labelů
            const extremeIndices = [];
            spotPriceData.forEach((price, idx) => {
                if (price <= bottomThreshold || price >= topThreshold) {
                    extremeIndices.push(idx);
                }
            });

            datasets.push({
                label: '📊 Spotová cena nákupu',
                data: spotPriceData,
                borderColor: '#2196F3',
                backgroundColor: 'rgba(33, 150, 243, 0.15)',
                borderWidth: 3,
                fill: false,
                tension: 0.4,
                type: 'line',
                yAxisID: 'y-price',
                pointRadius: pointRadii,
                pointHoverRadius: 7,
                pointBackgroundColor: pointColors,
                pointBorderColor: pointColors,
                pointBorderWidth: 2,
                order: 1,
                // Datalabels VYPNUTY - cenové labely ruší přehlednost grafu
                datalabels: {
                    display: false
                }
            });

            // === NOVÉ: Najít extrémní bloky pro karty ===
            // Nejlevnější 3h blok
            const cheapestBlock = findExtremePriceBlock(prices, true, 3);
            if (cheapestBlock) {
                // Uložit do globální proměnné pro onClick handler
                currentPriceBlocks.cheapest = cheapestBlock;

                const priceEl = document.getElementById('cheapest-buy-price');
                const timeEl = document.getElementById('cheapest-buy-time');

                if (priceEl && timeEl) {
                    // UPDATE DATA (tohle se děje při každém update)
                    priceEl.innerHTML = cheapestBlock.avg.toFixed(2) + ' <span class="stat-unit">Kč/kWh</span>';
                    const startTime = new Date(cheapestBlock.start);
                    const endTime = new Date(cheapestBlock.end);
                    timeEl.textContent = `${startTime.toLocaleDateString('cs-CZ', { day: '2-digit', month: '2-digit' })} ${startTime.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' })} - ${endTime.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' })}`;
                    createMiniPriceChart('cheapest-buy-chart', cheapestBlock.values, 'rgba(76, 175, 80, 1)', cheapestBlock.start, cheapestBlock.end);
                }
            }

            // Nejdražší 3h blok
            const expensiveBlock = findExtremePriceBlock(prices, false, 3);
            if (expensiveBlock) {
                // Uložit do globální proměnné
                currentPriceBlocks.expensive = expensiveBlock;

                const priceEl = document.getElementById('expensive-buy-price');
                const timeEl = document.getElementById('expensive-buy-time');

                if (priceEl && timeEl) {
                    // UPDATE DATA
                    priceEl.innerHTML = expensiveBlock.avg.toFixed(2) + ' <span class="stat-unit">Kč/kWh</span>';
                    const startTime = new Date(expensiveBlock.start);
                    const endTime = new Date(expensiveBlock.end);
                    timeEl.textContent = `${startTime.toLocaleDateString('cs-CZ', { day: '2-digit', month: '2-digit' })} ${startTime.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' })} - ${endTime.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' })}`;
                    createMiniPriceChart('expensive-buy-chart', expensiveBlock.values, 'rgba(244, 67, 54, 1)', expensiveBlock.start, expensiveBlock.end);
                }
            }
        }

    // Export prices (15min) - from timeline API
    const exportEntityId = 'sensor.oig_' + boxId + '_export_price_current_15min';
    const exportSensor = hass.states[exportEntityId];
    if (exportSensor && exportSensor.state) {
        // Current price from sensor state
        const currentPrice = parseFloat(exportSensor.state);
        if (!isNaN(currentPrice)) {
            const exportCard = document.getElementById('current-export-price');
            if (exportCard) {  // ✅ NULL CHECK - element neexistuje ve nové verzi
                exportCard.innerHTML = currentPrice.toFixed(2) + ' <span class="stat-unit">Kč/kWh</span>';
                // Make card clickable
                exportCard.parentElement.style.cursor = 'pointer';
                exportCard.parentElement.onclick = () => openEntityDialog(exportEntityId);
            }
        }
    }

    // Export prices from timeline API (already fetched)
    if (exportPrices.length > 0) {
        datasets.push({
            label: '💰 Výkupní cena',
            data: exportPrices.map(p => p.price),
            borderColor: '#4CAF50',
            backgroundColor: 'rgba(76, 187, 106, 0.15)',
            borderWidth: 2,
            fill: false,
            type: 'line',
            tension: 0.4,
            yAxisID: 'y-price',
            pointRadius: 0,
            pointHoverRadius: 5,
            order: 1,
            borderDash: [5, 5]
        });

        // === NOVÉ: Extrémní bloky pro EXPORT (prodej) - OBRÁCENÁ LOGIKA ===
        // Nejlepší prodej = NEJVYŠŠÍ cena (findLowest = false)
        console.log('[Pricing] exportPrices count:', exportPrices.length, 'sample:', exportPrices.slice(0, 3));
        const bestExportBlock = findExtremePriceBlock(exportPrices, false, 3);
        console.log('[Pricing] bestExportBlock:', bestExportBlock);

        const priceEl = document.getElementById('best-export-price');
        const timeEl = document.getElementById('best-export-time');

        if (bestExportBlock && bestExportBlock.avg > 0) {
            currentPriceBlocks.bestExport = bestExportBlock;

            if (priceEl && timeEl) {
                priceEl.innerHTML = bestExportBlock.avg.toFixed(2) + ' <span class="stat-unit">Kč/kWh</span>';
                const startTime = new Date(bestExportBlock.start);
                const endTime = new Date(bestExportBlock.end);
                timeEl.textContent = `${startTime.toLocaleDateString('cs-CZ', { day: '2-digit', month: '2-digit' })} ${startTime.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' })} - ${endTime.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' })}`;
                createMiniPriceChart('best-export-chart', bestExportBlock.values, 'rgba(76, 175, 80, 1)', bestExportBlock.start, bestExportBlock.end);
            }
        } else {
            console.warn('[Pricing] No best export block found - all prices are 0 or export pricing not configured');
            if (priceEl && timeEl) {
                priceEl.innerHTML = '<span style="color: var(--text-secondary); font-size: 0.9em;">Není nakonfigurováno</span>';
                timeEl.textContent = 'Nastavte export price sensor v konfiguraci';
            }
        }

        // Nejhorší prodej = NEJNIŽŠÍ cena (findLowest = true)
        const worstExportBlock = findExtremePriceBlock(exportPrices, true, 3);
        if (worstExportBlock) {
            currentPriceBlocks.worstExport = worstExportBlock;

            const priceEl = document.getElementById('worst-export-price');
            const timeEl = document.getElementById('worst-export-time');
            if (priceEl && timeEl) {
                priceEl.innerHTML = worstExportBlock.avg.toFixed(2) + ' <span class="stat-unit">Kč/kWh</span>';
                const startTime = new Date(worstExportBlock.start);
                const endTime = new Date(worstExportBlock.end);
                timeEl.textContent = `${startTime.toLocaleDateString('cs-CZ', { day: '2-digit', month: '2-digit' })} ${startTime.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' })} - ${endTime.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' })}`;
                createMiniPriceChart('worst-export-chart', worstExportBlock.values, 'rgba(255, 167, 38, 1)', worstExportBlock.start, worstExportBlock.end);
            }
        }
    }

    // Solar forecast (hourly) - interpolate to 15min grid
    const solarEntityId = 'sensor.oig_' + boxId + '_solar_forecast';
    const solarSensor = hass.states[solarEntityId];
    if (solarSensor && solarSensor.attributes) {
        const attrs = solarSensor.attributes;
        const todayTotal = attrs.today_total_kwh || 0;
        const solarCard = document.getElementById('today-forecast-total');
        if (solarCard) {  // ✅ NULL CHECK - element neexistuje ve nové verzi
            solarCard.innerHTML = todayTotal.toFixed(2) + ' <span class="stat-unit">kWh</span>';
            // Make card clickable
            solarCard.parentElement.style.cursor = 'pointer';
            solarCard.parentElement.onclick = () => openEntityDialog(solarEntityId);
        }

        const todayTotal_kw = attrs.today_hourly_total_kw || {};
        const tomorrowTotal_kw = attrs.tomorrow_hourly_total_kw || {};
        const todayString1_kw = attrs.today_hourly_string1_kw || {};
        const tomorrowString1_kw = attrs.tomorrow_hourly_string1_kw || {};
        const todayString2_kw = attrs.today_hourly_string2_kw || {};
        const tomorrowString2_kw = attrs.tomorrow_hourly_string2_kw || {};

        // Helper: Linear interpolation between two points
        function interpolate(v1, v2, ratio) {
            if (v1 == null || v2 == null) return v1 || v2 || null;
            return v1 + (v2 - v1) * ratio;
        }

        // Map hourly solar data to 15min price grid with interpolation
        // This now handles today + tomorrow seamlessly
        if (allLabels.length > 0) {
            const string1Data = [];
            const string2Data = [];

            // Merge today and tomorrow solar data into continuous timeline
            const allSolarData = {
                string1: { ...todayString1_kw, ...tomorrowString1_kw },
                string2: { ...todayString2_kw, ...tomorrowString2_kw }
            };

            for (let i = 0; i < allLabels.length; i++) {
                const timeLabel = allLabels[i]; // Now a Date object

                // Create ISO timestamp key for solar data lookup (LOCAL TIME!)
                const isoKey = toLocalISOString(timeLabel);

                // For solar data, we need to interpolate from hourly values
                const hour = timeLabel.getHours();
                const minute = timeLabel.getMinutes();

                // Create current and next hour timestamps for interpolation
                const currentHourDate = new Date(timeLabel);
                currentHourDate.setMinutes(0, 0, 0);
                const currentHourKey = toLocalISOString(currentHourDate);

                const nextHourDate = new Date(currentHourDate);
                nextHourDate.setHours(hour + 1);
                const nextHourKey = toLocalISOString(nextHourDate);

                // Get values for interpolation from merged data
                const s1_current = allSolarData.string1[currentHourKey] || 0;
                const s1_next = allSolarData.string1[nextHourKey] || 0;
                const s2_current = allSolarData.string2[currentHourKey] || 0;
                const s2_next = allSolarData.string2[nextHourKey] || 0;

                // Interpolation ratio (0.0 at :00, 0.25 at :15, 0.5 at :30, 0.75 at :45)
                const ratio = minute / 60;

                string1Data.push(interpolate(s1_current, s1_next, ratio));
                string2Data.push(interpolate(s2_current, s2_next, ratio));
            }

            // Determine solar visualization strategy
            const hasString1 = string1Data.some(v => v != null && v > 0);
            const hasString2 = string2Data.some(v => v != null && v > 0);
            const stringCount = (hasString1 ? 1 : 0) + (hasString2 ? 1 : 0);

            // Jasné sluneční barvy pro lepší viditelnost
            const solarColors = {
                string1: { border: 'rgba(255, 193, 7, 0.8)', bg: 'rgba(255, 193, 7, 0.2)' },  // zlatá žlutá
                string2: { border: 'rgba(255, 152, 0, 0.8)', bg: 'rgba(255, 152, 0, 0.2)' }   // oranžová
            };

            if (stringCount === 1) {
                // Pouze 1 string aktivní - zobrazit jen ten jeden (bez celkového součtu)
                if (hasString1) {
                    datasets.push({
                        label: '☀️ Solární předpověď',
                        data: string1Data,
                        borderColor: solarColors.string1.border,
                        backgroundColor: solarColors.string1.bg,
                        borderWidth: 2,
                        fill: 'origin',
                        tension: 0.4,
                        type: 'line',
                        yAxisID: 'y-power',
                        pointRadius: 0,
                        pointHoverRadius: 5,
                        order: 2
                    });
                } else if (hasString2) {
                    datasets.push({
                        label: '☀️ Solární předpověď',
                        data: string2Data,
                        borderColor: solarColors.string2.border,
                        backgroundColor: solarColors.string2.bg,
                        borderWidth: 2,
                        fill: 'origin',
                        tension: 0.4,
                        type: 'line',
                        yAxisID: 'y-power',
                        pointRadius: 0,
                        pointHoverRadius: 5,
                        order: 2
                    });
                }
            } else if (stringCount === 2) {
                // Oba stringy - zobrazit jako stacked area chart
                datasets.push({
                    label: '☀️ String 2',
                    data: string2Data,
                    borderColor: solarColors.string2.border,
                    backgroundColor: solarColors.string2.bg,
                    borderWidth: 1.5,
                    fill: 'origin',
                    tension: 0.4,
                    type: 'line',
                    yAxisID: 'y-power',
                    stack: 'solar',
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    order: 2
                });

                datasets.push({
                    label: '☀️ String 1',
                    data: string1Data,
                    borderColor: solarColors.string1.border,
                    backgroundColor: solarColors.string1.bg,
                    borderWidth: 1.5,
                    fill: '-1',  // stack on previous dataset
                    tension: 0.4,
                    type: 'line',
                    yAxisID: 'y-power',
                    stack: 'solar',
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    order: 2
                });
                // Bez celkového součtu - stacked area chart ukazuje celkovou výšku
            }
        }
    }

    // Battery forecast (timeline data) - using findShieldSensorId for dynamic suffix support
    const batteryForecastEntityId = findShieldSensorId('battery_forecast');
    const batteryForecastSensor = hass.states[batteryForecastEntityId];

    // console.log('[Pricing] Battery forecast sensor:', batteryForecastEntityId, batteryForecastSensor ? 'FOUND' : 'NOT FOUND');

    // Uchovej timeline rozsah pro výchozí zoom grafu
    let initialZoomStart = null;
    let initialZoomEnd = null;

    if (batteryForecastSensor && batteryForecastSensor.attributes) {
        // Timeline data already loaded from API at function start
        // console.log('[Pricing] Timeline data length:', timelineData.length);
        const maxCapacityKwh = batteryForecastSensor.attributes.max_capacity_kwh || 10;
        const minCapacityKwh = batteryForecastSensor.attributes.min_capacity_kwh || 0;

        if (timelineData.length > 0 && prices.length > 0) {
            // ULOŽIT ROZSAH TIMELINE PRO VÝCHOZÍ ZOOM
            const timelineTimestamps = timelineData.map(t => new Date(t.timestamp));
            initialZoomStart = timelineTimestamps[0].getTime();
            initialZoomEnd = timelineTimestamps[timelineTimestamps.length - 1].getTime();
            // console.log('[Pricing] Timeline range for initial zoom:', new Date(initialZoomStart), 'to', new Date(initialZoomEnd));

            // EXTEND allLabels with battery forecast timestamps (union)
            const batteryTimestamps = timelineTimestamps;
            const priceTimestamps = allLabels; // already Date objects

            // Merge and dedupe timestamps
            const allTimestamps = new Set([...priceTimestamps, ...batteryTimestamps].map(d => d.getTime()));
            allLabels = Array.from(allTimestamps).sort((a, b) => a - b).map(ts => new Date(ts));

            // ZOBRAZENÍ KAPACITY BATERIE:
            // battery_capacity_kwh = SOC baterie na konci intervalu (kWh)
            // solar_charge_kwh = kWh do baterie ze soláru (pre-efficiency)
            // grid_charge_kwh = kWh do baterie ze sítě (pre-efficiency)
            // baseline = battery_capacity_kwh - solar_charge_kwh - grid_charge_kwh

            const batteryCapacityData = [];   // Cílová kapacita (linie navrch)
            const baselineData = [];          // Předchozí kapacita (baseline pro stack)
            const solarStackData = [];        // Solar přírůstek
            const gridStackData = [];         // Grid přírůstek
            const gridNetData = [];           // Netto odběr ze sítě (import - export)
            const consumptionData = [];       // Plánovaná spotřeba (kW)

            for (let i = 0; i < allLabels.length; i++) {
                const timeLabel = allLabels[i];
                const isoKey = toLocalISOString(timeLabel);

                const timelineEntry = timelineData.find(t => t.timestamp === isoKey);

                if (timelineEntry) {
                    // Planner timeline uses: battery_capacity_kwh, solar_charge_kwh, grid_charge_kwh.
                    // Keep compatibility fallbacks for older payloads.
                    const targetCapacity =
                        (timelineEntry.battery_capacity_kwh ?? timelineEntry.battery_soc ?? timelineEntry.battery_start) || 0;
                    const solarCharge = timelineEntry.solar_charge_kwh || 0;
                    const gridCharge = timelineEntry.grid_charge_kwh || 0;
                    const gridNet = typeof timelineEntry.grid_net === 'number'
                        ? timelineEntry.grid_net
                        : (timelineEntry.grid_import || 0) - (timelineEntry.grid_export || 0);
                    const loadKwhRaw =
                        timelineEntry.load_kwh ??
                        timelineEntry.consumption_kwh ??
                        timelineEntry.load ??
                        0;
                    const loadKwh = Number(loadKwhRaw) || 0;
                    const loadKw = loadKwh * 4;

                    // Baseline = odkud vyšli (cílová - přírůstky)
                    const baseline = targetCapacity - solarCharge - gridCharge;

                    batteryCapacityData.push(targetCapacity);
                    baselineData.push(baseline);
                    solarStackData.push(solarCharge);
                    gridStackData.push(gridCharge);
                    gridNetData.push(gridNet);
                    consumptionData.push(loadKw);
                } else {
                    batteryCapacityData.push(null);
                    baselineData.push(null);
                    solarStackData.push(null);
                    gridStackData.push(null);
                    gridNetData.push(null);
                    consumptionData.push(null);
                }
            }

            // Vylepšené barvy pro viditelnost kapacity baterie
            const batteryColors = {
                baseline: { border: '#78909C', bg: 'rgba(120, 144, 156, 0.25)' }, // šedá - zbývající kapacita
                solar: { border: 'transparent', bg: 'rgba(255, 167, 38, 0.6)' },   // výrazná oranžová - solár
                grid: { border: 'transparent', bg: 'rgba(33, 150, 243, 0.6)' }    // výrazná modrá - síť
            };

            if (consumptionData.some(v => v != null && v > 0)) {
                datasets.push({
                    label: '🏠 Spotřeba (plán)',
                    data: consumptionData,
                    borderColor: 'rgba(255, 112, 67, 0.7)',
                    backgroundColor: 'rgba(255, 112, 67, 0.12)',
                    borderWidth: 1.5,
                    type: 'line',
                    fill: false,
                    tension: 0.25,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    yAxisID: 'y-power',
                    stack: 'consumption',
                    borderDash: [6, 4],
                    order: 2
                });
            }

            // POŘADÍ DATASETŮ určuje pořadí ve stacku (první = dole, poslední = nahoře)
            // 1. Grid area (dole) - nabíjení ze sítě, BEZ borderu
            if (gridStackData.some(v => v != null && v > 0)) {
                datasets.push({
                    label: '⚡ Do baterie ze sítě',
                    data: gridStackData,
                    backgroundColor: batteryColors.grid.bg,
                    borderColor: batteryColors.grid.border,
                    borderWidth: 0,
                    type: 'line',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    yAxisID: 'y-solar',
                    stack: 'charging',
                    order: 3
                });
            }

            // 2. Solar area (uprostřed) - nabíjení ze solaru, BEZ borderu
            if (solarStackData.some(v => v != null && v > 0)) {
                datasets.push({
                    label: '☀️ Do baterie ze soláru',
                    data: solarStackData,
                    backgroundColor: batteryColors.solar.bg,
                    borderColor: batteryColors.solar.border,
                    borderWidth: 0,
                    type: 'line',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    yAxisID: 'y-solar',
                    stack: 'charging',
                    order: 3
                });
            }

            // 3. Baseline area (nahoře) - zbývající kapacita s TLUSTOU ČÁROU
            datasets.push({
                label: '🔋 Zbývající kapacita',
                data: baselineData,
                backgroundColor: batteryColors.baseline.bg,
                borderColor: batteryColors.baseline.border,
                borderWidth: 3,  // TLUSTÁ ČÁRA
                type: 'line',
                fill: true,
                tension: 0.4,
                pointRadius: 0,
                pointHoverRadius: 5,
                yAxisID: 'y-solar',
                stack: 'charging',
                order: 3
            });

            if (gridNetData.some(v => v !== null)) {
                datasets.push({
                    label: '📡 Netto odběr ze sítě',
                    data: gridNetData,
                    borderColor: '#00BCD4',
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    type: 'line',
                    fill: false,
                    tension: 0.2,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    yAxisID: 'y-solar',
                    order: 2
                });
            }
        }
    }

    // Create/update combined chart
    const ctx = document.getElementById('combined-chart');

    // OPRAVA: Kontrola jestli je canvas viditelný (pricing tab aktivní)
    // Pokud není, odložit vytvoření grafu
    if (!ctx) {
        console.warn('[Pricing] Canvas element not found, deferring chart creation');
        return;
    }

    const isVisible = ctx.offsetParent !== null;
    if (!isVisible && !combinedChart) {
        console.warn('[Pricing] Canvas not visible yet, deferring chart creation');
        // Zkusit znovu za chvíli
        setTimeout(() => {
            if (pricingTabActive) {
                console.log('[Pricing] Retrying chart creation after visibility delay');
                loadPricingData();
            }
        }, 200);
        return;
    }

    if (combinedChart) {
        // OPTIMALIZACE: Místo přenastavení celého datasetu aktualizujeme jen labely a data
        const labelsChanged = JSON.stringify(combinedChart.data.labels) !== JSON.stringify(allLabels);
        const datasetsChanged = combinedChart.data.datasets.length !== datasets.length;

        // console.log('[Pricing] Updating EXISTING chart - labelsChanged:', labelsChanged, 'datasetsChanged:', datasetsChanged);
        // if (allLabels.length > 0) {
        //     console.log('[Pricing] Update - First label:', allLabels[0], 'Last:', allLabels[allLabels.length - 1]);
        // }

        if (labelsChanged) {
            combinedChart.data.labels = allLabels;
        }

        let updateMode = 'none';
        if (datasetsChanged) {
            // Pokud se změnil počet datasetů, musíme je nahradit
            combinedChart.data.datasets = datasets;
            updateMode = undefined;
        } else {
            // Jinak jen aktualizujeme data v existujících datasetech
            datasets.forEach((newDataset, idx) => {
                if (combinedChart.data.datasets[idx]) {
                    // Zachovat reference na dataset, jen aktualizovat data
                    combinedChart.data.datasets[idx].data = newDataset.data;
                    // Aktualizovat i další properties které se mohly změnit
                    combinedChart.data.datasets[idx].label = newDataset.label;
                    combinedChart.data.datasets[idx].backgroundColor = newDataset.backgroundColor;
                    combinedChart.data.datasets[idx].borderColor = newDataset.borderColor;
                }
            });
        }

        if (!combinedChart.options.plugins) {
            combinedChart.options.plugins = {};
        }

        combinedChart.options.plugins.pricingModeIcons = modeIconOptions || null;
        applyPricingModeIconPadding(combinedChart.options, modeIconOptions);
        combinedChart.update(updateMode); // Update bez animace když se jen mění data
    } else {
        // DETAILNÍ DEBUG PRO ANALÝZU PROBLÉMU S ČASOVOU OSOU
        // console.log('[Pricing] Creating NEW chart with', allLabels.length, 'labels');
        // if (allLabels.length > 0) {
        //     console.log('[Pricing] First label:', allLabels[0]);
        //     console.log('[Pricing] Last label:', allLabels[allLabels.length - 1]);
        //     console.log('[Pricing] Current time:', new Date());
        //     console.log('[Pricing] Time offset (hours):', (new Date() - allLabels[0]) / (1000 * 60 * 60));
        // }

        const chartOptions = {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        labels: {
                            color: '#ffffff',
                            font: { size: 11, weight: '500' },
                            padding: 10,
                            usePointStyle: true,
                            pointStyle: 'circle',
                            boxWidth: 12,
                            boxHeight: 12
                        },
                        position: 'top'
                    },
                    tooltip: {
                        backgroundColor: 'rgba(0,0,0,0.9)',
                        titleColor: '#ffffff',
                        bodyColor: '#ffffff',
                        titleFont: { size: 13, weight: 'bold' },
                        bodyFont: { size: 11 },
                        padding: 10,
                        cornerRadius: 6,
                        displayColors: true,
                        callbacks: {
                            title: function (tooltipItems) {
                                if (tooltipItems.length > 0) {
                                    const date = new Date(tooltipItems[0].parsed.x);
                                    return date.toLocaleString('cs-CZ', {
                                        day: '2-digit',
                                        month: '2-digit',
                                        year: 'numeric',
                                        hour: '2-digit',
                                        minute: '2-digit'
                                    });
                                }
                                return '';
                            },
                            label: function (context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (context.parsed.y !== null) {
                                    // Formátování podle typu datasetu
                                    if (context.dataset.yAxisID === 'y-price') {
                                        label += context.parsed.y.toFixed(2) + ' Kč/kWh';
                                    } else if (context.dataset.yAxisID === 'y-solar') {
                                        label += context.parsed.y.toFixed(2) + ' kWh';
                                    } else if (context.dataset.yAxisID === 'y-power') {
                                        label += context.parsed.y.toFixed(2) + ' kW';
                                    } else {
                                        label += context.parsed.y;
                                    }
                                }
                                return label;
                            }
                        }
                    },
                    datalabels: {
                        display: false // Vypnout globálně, povolit jen pro specifické datasety
                    },
                    zoom: {
                        zoom: {
                            wheel: {
                                enabled: true,
                                modifierKey: null // Zoom kolečkem bez modifikátorů
                            },
                            drag: {
                                enabled: true, // Drag-to-zoom jako v Grafaně
                                backgroundColor: 'rgba(33, 150, 243, 0.3)',
                                borderColor: 'rgba(33, 150, 243, 0.8)',
                                borderWidth: 2
                            },
                            pinch: {
                                enabled: true // Touch zoom pro mobily
                            },
                            mode: 'x', // Zoom jen na X ose (časové ose)
                            onZoomComplete: function ({ chart }) {
                                // Při manuálním zoomu (kolečko/drag) resetovat currentZoomRange
                                // aby další klik na dlaždici fungoval správně
                                currentZoomRange = null;

                                // Odebrat zoom-active z aktivní karty
                                if (activeZoomCard) {
                                    activeZoomCard.classList.remove('zoom-active');
                                    activeZoomCard = null;
                                }

                                updateChartDetailLevel(chart);
                            }
                        },
                        pan: {
                            enabled: true,
                            mode: 'x',
                            modifierKey: 'shift', // Pan s Shift+drag
                            onPanComplete: function ({ chart }) {
                                // Při manuálním panu resetovat currentZoomRange
                                currentZoomRange = null;

                                // Odebrat zoom-active z aktivní karty
                                if (activeZoomCard) {
                                    activeZoomCard.classList.remove('zoom-active');
                                    activeZoomCard = null;
                                }

                                updateChartDetailLevel(chart);
                            }
                        },
                        limits: {
                            x: { minRange: 3600000 } // Min 1 hodina (v milisekundách)
                        }
                    },
                    pricingModeIcons: modeIconOptions || null
                },
                scales: {
                    x: {
                        // KRITICKÁ ZMĚNA: 'timeseries' místo 'time' pro lepší timezone handling
                        // timeseries používá data.labels přímo bez UTC konverze
                        type: 'timeseries',
                        time: {
                            unit: 'hour',
                            displayFormats: {
                                hour: 'dd.MM HH:mm'
                            },
                            tooltipFormat: 'dd.MM.yyyy HH:mm'
                        },
                        ticks: {
                            color: getTextColor(),
                            maxRotation: 45,
                            minRotation: 45,
                            font: { size: 11 },
                            maxTicksLimit: 20
                        },
                        grid: { color: getGridColor(), lineWidth: 1 }
                    },
                    'y-price': {
                        type: 'linear',
                        position: 'left',
                        ticks: {
                            color: '#2196F3',
                            font: { size: 11, weight: '500' },
                            callback: function (value) { return value.toFixed(2) + ' Kč'; }
                        },
                        grid: { color: 'rgba(33, 150, 243, 0.15)', lineWidth: 1 },
                        title: {
                            display: true,
                            text: '💰 Cena (Kč/kWh)',
                            color: '#2196F3',
                            font: { size: 13, weight: 'bold' }
                        }
                    },
                    'y-solar': {
                        type: 'linear',
                        position: 'left',
                        stacked: true,
                        ticks: {
                            color: '#78909C',
                            font: { size: 11, weight: '500' },
                            callback: function (value) { return value.toFixed(1) + ' kWh'; },
                            display: true
                        },
                        grid: {
                            display: true,
                            color: 'rgba(120, 144, 156, 0.15)',
                            lineWidth: 1,
                            drawOnChartArea: true
                        },
                        title: {
                            display: true,
                            text: '🔋 Kapacita baterie (kWh)',
                            color: '#78909C',
                            font: { size: 11, weight: 'bold' }
                        },
                        // Začátek shora, aby se nepřekrývala s y-price
                        beginAtZero: false
                    },
                    'y-power': {
                        type: 'linear',
                        position: 'right',
                        stacked: true,
                        ticks: {
                            color: '#FFA726',
                            font: { size: 11, weight: '500' },
                            callback: function (value) { return value.toFixed(2) + ' kW'; }
                        },
                        grid: { display: false },
                        title: {
                            display: true,
                            text: '☀️ Výkon (kW)',
                            color: '#FFA726',
                            font: { size: 13, weight: 'bold' }
                        }
                    }
                }
        };

        applyPricingModeIconPadding(chartOptions, modeIconOptions);

        combinedChart = new Chart(ctx, {
            type: 'bar', // Changed to 'bar' to support mixed chart (bar + line)
            data: { labels: allLabels, datasets: datasets },
            plugins: [ChartDataLabels], // Registrace datalabels pluginu
            options: chartOptions
        });

        // Inicializace detailu pro nový graf
        updateChartDetailLevel(combinedChart);

        // OPRAVA: Nastavit zoom asynchronně PO dokončení inicializace Chart.js
        // Chart.js zoom plugin se inicializuje asynchronně a přepisuje naše nastavení
        // Použijeme requestAnimationFrame aby se zoom aplikoval až po prvním renderu
        if (initialZoomStart && initialZoomEnd) {
            requestAnimationFrame(() => {
                if (!combinedChart) return; // Safety check

                combinedChart.options.scales.x.min = initialZoomStart;
                combinedChart.options.scales.x.max = initialZoomEnd;
                combinedChart.update('none'); // Aplikovat okamžitě bez animace

                // console.log('[Pricing] Initial zoom applied after first render:', new Date(initialZoomStart), 'to', new Date(initialZoomEnd));
                updateChartDetailLevel(combinedChart);
            });
        }
    }

    // Attach card handlers only once
    setupPriceCardHandlers();

    // Update Battery Health stats (if module is loaded)
    if (typeof updateBatteryHealthStats === 'function') {
        updateBatteryHealthStats();
    }

    // Mark charts as rendered to skip re-rendering on next tab switch
    getTimelineCacheBucket(pricingPlanMode).chartsRendered = true;

    // Single-planner: no dual-plan comparison tile here
    // Hide loading overlay
    if (loadingOverlay) {
        loadingOverlay.style.display = 'none';
    }

    const perfEnd = performance.now();
    const totalTime = (perfEnd - perfStart).toFixed(0);
    console.log(`[Pricing] === loadPricingData COMPLETE in ${totalTime}ms ===`);
}/**
 * Setup onClick handlers for price cards
 * OPRAVENO: Používá event delegation pro spolehlivost
 * Handlery přežijí innerHTML updates a fungují i když elementy ještě neexistují
 */
function setupPriceCardHandlers() {
    if (priceCardHandlersAttached) {
        return; // Už nastaveno
    }

    console.log('[Card] Setting up price card click handlers (event delegation)');

    // Event delegation: jeden handler na document, zachytí všechny kliky na karty
    // Výhoda: Funguje i když se elementy dynamicky mění/přidávají
    document.addEventListener('click', function (e) {
        // Najít nejbližší .stat-card parent
        const card = e.target.closest('.stat-card');
        if (!card) return;

        // Určit který typ karty to je podle ID uvnitř
        let blockData = null;
        let cardType = '';

        if (card.querySelector('#cheapest-buy-price')) {
            blockData = currentPriceBlocks.cheapest;
            cardType = 'Nejlevnější nákup';
        } else if (card.querySelector('#expensive-buy-price')) {
            blockData = currentPriceBlocks.expensive;
            cardType = 'Nejdražší nákup';
        } else if (card.querySelector('#best-export-price')) {
            blockData = currentPriceBlocks.bestExport;
            cardType = 'Nejlepší prodej';
        } else if (card.querySelector('#worst-export-price')) {
            blockData = currentPriceBlocks.worstExport;
            cardType = 'Nejhorší prodej';
        } else {
            return; // Není to jedna z našich cenových karet
        }

        // Pokud máme data o bloku, zoomuj
        if (blockData && blockData.start && blockData.end) {
            console.log(`[Card] ${cardType} clicked, zooming to:`, blockData.start, '->', blockData.end);
            e.stopPropagation();
            zoomToTimeRange(blockData.start, blockData.end, card);
        } else {
            console.warn(`[Card] ${cardType} clicked but no block data available`);
        }
    });

    // Nastavit cursor pointer na všechny cenové karty (pokud existují)
    const cardIds = [
        'cheapest-buy-price',
        'expensive-buy-price',
        'best-export-price',
        'worst-export-price'
    ];

    cardIds.forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            const card = element.closest('.stat-card');
            if (card) {
                card.style.cursor = 'pointer';
            }
        }
    });

    priceCardHandlersAttached = true;
    console.log('[Card] Event delegation handler attached successfully');
}


// Export pricing functions
async function updatePlannedConsumptionStats() {
    const hass = getHass();
    if (!hass) return;

    const forecastSensorId = `sensor.oig_${INVERTER_SN}_battery_forecast`;
    const forecastSensor = hass.states[forecastSensorId];

    // Check if sensor is available
    if (!forecastSensor || forecastSensor.state === 'unavailable' || forecastSensor.state === 'unknown') {
        console.log('[Planned Consumption] Battery forecast sensor not available:', forecastSensorId);
        updateElementIfChanged('planned-consumption-today', '--', 'planned-today');
        updateElementIfChanged('consumption-profile-today', 'Čekám na data...', 'profile-today');
        updateElementIfChanged('planned-consumption-tomorrow', '--', 'planned-tomorrow');
        updateElementIfChanged('consumption-profile-tomorrow', 'Čekám na data...', 'profile-tomorrow');
        return;
    }

    // Get pre-calculated consumption data from battery_forecast attributes
    const attrs = forecastSensor.attributes || {};

    // Display data (already calculated in Python) - načítáme přímo z root atributů
    const todayPlannedKwh = attrs.planned_consumption_today;
    const tomorrowKwh = attrs.planned_consumption_tomorrow;
    const profileToday = attrs.profile_today;
    const profileTomorrow = attrs.profile_tomorrow;

    // Získat již spotřebovanou energii dnes z ac_out_en_day (vrací Wh, převést na kWh)
    const todayConsumedSensorId = `sensor.oig_${INVERTER_SN}_ac_out_en_day`;
    const todayConsumedSensor = hass.states[todayConsumedSensorId];
    const todayConsumedWh = todayConsumedSensor && todayConsumedSensor.state !== 'unavailable'
        ? parseFloat(todayConsumedSensor.state) || 0
        : 0;
    const todayConsumedKwh = todayConsumedWh / 1000; // Převod Wh -> kWh

    // Celková spotřeba dnes (už spotřebováno + ještě plánováno)
    const todayTotalKwh = todayConsumedKwh + (todayPlannedKwh || 0);

    // Celková plánovaná spotřeba (dnes zbývá + zítřek celý)
    const totalPlannedKwh = (todayPlannedKwh || 0) + (tomorrowKwh || 0);

    // Update UI - Hlavní hodnota (plánovaná: dnes zbývá + zítřek)
    if (totalPlannedKwh > 0) {
        updateElementIfChanged('planned-consumption-main', `${totalPlannedKwh.toFixed(1)} kWh`, 'planned-main');
    } else {
        updateElementIfChanged('planned-consumption-main', '--', 'planned-main');
    }

    // Update trend text (porovnání celkem dnes vs zítřek)
    if (todayTotalKwh > 0 && tomorrowKwh !== null && tomorrowKwh !== undefined) {
        const diff = tomorrowKwh - todayTotalKwh;
        const diffPercent = todayTotalKwh > 0 ? ((diff / todayTotalKwh) * 100) : 0;
        let trendText = '';
        let trendIcon = '';

        if (Math.abs(diffPercent) < 5) {
            trendIcon = '➡️';
            trendText = `Zítra podobně`;
        } else if (diff > 0) {
            trendIcon = '📈';
            trendText = `Zítra více (+${Math.abs(diffPercent).toFixed(0)}%)`;
        } else {
            trendIcon = '📉';
            trendText = `Zítra méně (-${Math.abs(diffPercent).toFixed(0)}%)`;
        }

        updateElementIfChanged('planned-consumption-trend', `${trendIcon} ${trendText}`, 'planned-trend');
    } else {
        updateElementIfChanged('planned-consumption-trend', '--', 'planned-trend');
    }

    // Detail řádky - Dnes: spotřebováno + zbývá plán, Zítra: celý den
    if (todayConsumedKwh !== null && todayConsumedKwh !== undefined) {
        updateElementIfChanged('planned-today-consumed-kwh', `${todayConsumedKwh.toFixed(1)} kWh`, 'planned-today-consumed');
    } else {
        updateElementIfChanged('planned-today-consumed-kwh', '--', 'planned-today-consumed');
    }

    if (todayPlannedKwh !== null && todayPlannedKwh !== undefined) {
        updateElementIfChanged('planned-today-remaining-kwh', `${todayPlannedKwh.toFixed(1)} kWh`, 'planned-today-remaining');
    } else {
        updateElementIfChanged('planned-today-remaining-kwh', '--', 'planned-today-remaining');
    }

    if (tomorrowKwh !== null && tomorrowKwh !== undefined) {
        updateElementIfChanged('planned-tomorrow-kwh', `${tomorrowKwh.toFixed(1)} kWh`, 'planned-tomorrow-kwh');
    } else {
        updateElementIfChanged('planned-tomorrow-kwh', '--', 'planned-tomorrow-kwh');
    }

    // Profil display - bez emoji, čistý text (nahoru místo "Zbývá dnes + celý zítřek")
    let profileDisplay = '';
    if (profileToday && profileToday !== 'Žádný profil' && profileToday !== 'Neznámý profil') {
        profileDisplay = profileToday;
    } else {
        profileDisplay = 'Žádný profil';
    }
    updateElementIfChanged('consumption-profile-display', profileDisplay, 'profile-display');

    // Update gradient bar (místo canvas grafu)
    const barToday = document.getElementById('planned-consumption-bar-today');
    const barTomorrow = document.getElementById('planned-consumption-bar-tomorrow');
    const labelToday = document.getElementById('planned-bar-today-label');
    const labelTomorrow = document.getElementById('planned-bar-tomorrow-label');

    if (barToday && barTomorrow && todayTotalKwh > 0 && tomorrowKwh !== null && tomorrowKwh !== undefined) {
        const total = todayTotalKwh + tomorrowKwh;
        const todayPercent = (todayTotalKwh / total) * 100;
        const tomorrowPercent = (tomorrowKwh / total) * 100;

        barToday.style.width = `${todayPercent}%`;
        barTomorrow.style.width = `${tomorrowPercent}%`;

        if (labelToday) labelToday.textContent = `${todayTotalKwh.toFixed(1)}`;
        if (labelTomorrow) labelTomorrow.textContent = `${tomorrowKwh.toFixed(1)}`;
    }
}

/**
 * Update what-if analysis statistics on Pricing tab
 * Reads mode_optimization.alternatives from battery_forecast attributes
 */
async function updateWhatIfAnalysis() {
    const hass = getHass();
    if (!hass) return;

    const forecastSensorId = `sensor.oig_${INVERTER_SN}_battery_forecast`;
    const forecastSensor = hass.states[forecastSensorId];

    // Check if sensor is available
    if (!forecastSensor || forecastSensor.state === 'unavailable' || forecastSensor.state === 'unknown') {
        console.log('[What-if] Battery forecast sensor not available');
        updateElementIfChanged('whatif-optimized-cost', '--', 'whatif-main');
        updateElementIfChanged('whatif-savings-main', '--', 'whatif-savings');
        updateElementIfChanged('whatif-home-i-delta', '--', 'whatif-home-i');
        updateElementIfChanged('whatif-home-ii-delta', '--', 'whatif-home-ii');
        updateElementIfChanged('whatif-home-iii-delta', '--', 'whatif-home-iii');
        updateElementIfChanged('whatif-home-ups-delta', '--', 'whatif-home-ups');
        return;
    }

    // Get mode_optimization data (still in attributes)
    const attrs = forecastSensor.attributes || {};
    const modeOptData = attrs.mode_optimization || {};
    const alternatives = modeOptData.alternatives || {};

    console.log('[What-if Tile] modeOptData:', modeOptData);
    console.log('[What-if Tile] alternatives:', alternatives);

    // Phase 2.8: Use cached totals from mode_optimization instead of summing blocks
    // (mode_recommendations are per-interval, mode_optimization has pre-calculated totals for DNES+ZÍTRA)
    const totalCost = modeOptData.total_cost_czk || 0;
    const totalSavings = modeOptData.total_savings_vs_home_i_czk || 0;

    console.log('[What-if Tile] totalCost:', totalCost, 'totalSavings:', totalSavings);

    // Update optimized cost and savings
    updateElementIfChanged('whatif-optimized-cost', `${totalCost.toFixed(2)} Kč`, 'whatif-main');

    if (totalSavings > 0) {
        updateElementIfChanged('whatif-savings-main', `+${totalSavings.toFixed(2)} Kč`, 'whatif-savings');
    } else if (totalSavings < 0) {
        updateElementIfChanged('whatif-savings-main', `${totalSavings.toFixed(2)} Kč`, 'whatif-savings');
    } else {
        updateElementIfChanged('whatif-savings-main', '0 Kč', 'whatif-savings');
    }

    // Update what-if alternatives comparison - 4 modes only
    // Backend format: alternatives = { "HOME I": {...}, "HOME II": {...}, ... }
    const homeI = alternatives['HOME I'];
    const homeII = alternatives['HOME II'];
    const homeIII = alternatives['HOME III'];
    const homeUps = alternatives['HOME UPS'] || alternatives['FULL HOME UPS'];
    const doNothing = alternatives['DO NOTHING'];

    // Format deltas (delta_czk from backend - positive means alternative is more expensive)
    const formatDelta = (alt) => {
        if (!alt || alt.delta_czk === undefined) return '--';
        const delta = alt.delta_czk;
        if (delta > 0.01) {
            return `+${delta.toFixed(2)} Kč`;
        } else if (delta < -0.01) {
            return `${delta.toFixed(2)} Kč`;
        } else {
            return '~0 Kč';
        }
    };

    // Update values
    updateElementIfChanged('whatif-home-i-delta', formatDelta(homeI), 'whatif-home-i');
    updateElementIfChanged('whatif-home-ii-delta', formatDelta(homeII), 'whatif-home-ii');
    updateElementIfChanged('whatif-home-iii-delta', formatDelta(homeIII), 'whatif-home-iii');
    updateElementIfChanged('whatif-home-ups-delta', formatDelta(homeUps), 'whatif-home-ups');

    // Highlight active mode (DO NOTHING = current mode)
    // Reset all rows first
    const rows = ['whatif-home-i-row', 'whatif-home-ii-row', 'whatif-home-iii-row', 'whatif-home-ups-row'];
    rows.forEach(rowId => {
        const row = document.getElementById(rowId);
        if (row) {
            row.style.background = 'transparent';
            row.style.border = 'none';
        }
    });

    // Highlight the active one (if DO NOTHING exists, check which mode it represents)
    if (doNothing && doNothing.current_mode) {
        // Backend provides current_mode field in DO NOTHING
        const activeMode = doNothing.current_mode;
        let activeRowId = null;

        if (activeMode === 'HOME I') {
            activeRowId = 'whatif-home-i-row';
        } else if (activeMode === 'HOME II') {
            activeRowId = 'whatif-home-ii-row';
        } else if (activeMode === 'HOME III') {
            activeRowId = 'whatif-home-iii-row';
        } else if (activeMode === 'HOME UPS') {
            activeRowId = 'whatif-home-ups-row';
        }

        if (activeRowId) {
            const activeRow = document.getElementById(activeRowId);
            if (activeRow) {
                activeRow.style.background = 'rgba(76, 175, 80, 0.15)';
                activeRow.style.border = '1px solid rgba(76, 175, 80, 0.3)';
            }
        }
    }
}


window.DashboardPricing = {
    debouncedLoadPricingData,
    debouncedUpdatePlannedConsumption,
    loadPricingData,
    updatePlannedConsumptionStats,
    updateWhatIfAnalysis,
    init: function() {
        console.log('[DashboardPricing] Initialized');
        initChartPlanToggle();
    }
};

console.log('[DashboardPricing] Module loaded');
if (window.DashboardPricing && typeof window.DashboardPricing.init === 'function') {
    window.DashboardPricing.init();
}
async function fetchTimelineFromAPI(plan, boxId) {
    const timelineUrl = `/api/oig_cloud/battery_forecast/${boxId}/timeline?type=active`;
    const fetchStart = performance.now();
    console.log(`[Pricing] Fetching ${plan} timeline from API...`);
    const response = await fetch(timelineUrl);
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    const timelineData = data.active || data.timeline || [];
    const fetchEnd = performance.now();
    console.log(`[Pricing] API fetch completed in ${(fetchEnd - fetchStart).toFixed(0)}ms - loaded ${timelineData.length} points for ${plan} plan`);
    return timelineData;
}

async function getTimelineData(plan, boxId, force = false) {
    const cacheBucket = getTimelineCacheBucket(plan);
    const cacheValid = !force &&
        cacheBucket.data &&
        !cacheBucket.stale;

    if (cacheValid) {
        return { data: cacheBucket.data, fromCache: true };
    }

    if (!timelineFetchPromises[plan]) {
        timelineFetchPromises[plan] = fetchTimelineFromAPI(plan, boxId)
            .then((timelineData) => {
                cacheBucket.data = timelineData;
                cacheBucket.timestamp = Date.now();
                cacheBucket.chartsRendered = false;
                cacheBucket.stale = false;
                return timelineData;
            })
            .catch((error) => {
                console.error(`[Pricing] Failed to fetch ${plan} timeline:`, error);
                throw error;
            })
            .finally(() => {
                timelineFetchPromises[plan] = null;
            });
    }

    const data = await timelineFetchPromises[plan];
    return { data, fromCache: false };
}
