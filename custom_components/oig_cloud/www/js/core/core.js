/* eslint-disable */
// === INVERTER SN (from api.js) ===
// INVERTER_SN is defined in dashboard-api.js (loaded before this file)

// === LAYOUT (using dashboard-layout.js module) ===
// Import layout functions (var allows re-declaration if script re-runs)
var getCurrentBreakpoint = window.DashboardLayout?.getCurrentBreakpoint;
var saveLayout = window.DashboardLayout?.saveLayout;
var loadLayout = window.DashboardLayout?.loadLayout;
var resetLayout = window.DashboardLayout?.resetLayout;
var toggleEditMode = window.DashboardLayout?.toggleEditMode;

// === GLOBAL VARIABLES FOR CHART DATA ===
// Store complete dataset for extremes calculation regardless of zoom
var originalPriceData = null;

// === TOOLTIP POSITIONING ===

// === CONTROL PANEL FUNCTIONS ===

// Toggle control panel
function toggleControlPanel() {
    const panel = document.getElementById('control-panel');
    const icon = document.getElementById('panel-toggle-icon');
    panel.classList.toggle('minimized');
    icon.textContent = panel.classList.contains('minimized') ? '+' : '−';
}

function runWhenIdle(task, timeoutMs = 2000, fallbackDelayMs = 600) {
    if (typeof window.requestIdleCallback === 'function') {
        window.requestIdleCallback(() => task(), { timeout: timeoutMs });
        return;
    }
    setTimeout(task, fallbackDelayMs);
}

function detectHaApp() {
    try {
        const ua = window.navigator?.userAgent || '';
        return /Home Assistant|HomeAssistant/i.test(ua);
    } catch (e) {
        return false;
    }
}

function detectMobile() {
    try {
        const ua = window.navigator?.userAgent || '';
        const mobileUA = /Android|iPhone|iPad|iPod|Mobile/i.test(ua);
        const smallViewport = window.innerWidth <= 768 || window.matchMedia?.('(max-width: 768px)')?.matches;
        return mobileUA || !!smallViewport;
    } catch (e) {
        return false;
    }
}

window.OIG_RUNTIME = window.OIG_RUNTIME || {};
if (window.OIG_RUNTIME.isHaApp === undefined) {
    window.OIG_RUNTIME.isHaApp = detectHaApp();
}
if (window.OIG_RUNTIME.isMobile === undefined) {
    window.OIG_RUNTIME.isMobile = detectMobile();
}
if (window.OIG_RUNTIME.reduceMotion === undefined) {
    const prefersReduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    window.OIG_RUNTIME.reduceMotion = !!(prefersReduced || window.OIG_RUNTIME.isHaApp || window.OIG_RUNTIME.isMobile);
}
if (window.OIG_RUNTIME.initialLoadComplete === undefined) {
    window.OIG_RUNTIME.initialLoadComplete = false;
}

// === SHIELD (moved to dashboard-shield.js) ===
// Import shield functions
var subscribeToShield = window.DashboardShield?.subscribeToShield;
var startShieldQueueLiveUpdate = window.DashboardShield?.startShieldQueueLiveUpdate;
var stopShieldQueueLiveUpdate = window.DashboardShield?.stopShieldQueueLiveUpdate;
var loadShieldData = window.DashboardShield?.loadShieldData;
var debouncedShieldMonitor = window.DashboardShield?.debouncedShieldMonitor;
var setShieldMode = window.DashboardShield?.setShieldMode;
var setShieldModeWithConfirmation = window.DashboardShield?.setShieldModeWithConfirmation;
var cancelShieldAction = window.DashboardShield?.cancelShieldAction;
var loadControlPanelStatus = window.DashboardShield?.loadControlPanelStatus;

// === FLOW DIAGRAM (moved to dashboard-flow.js) ===
// Import functions from DashboardFlow module
var getSensorId = window.DashboardFlow?.getSensorId;
var updateTime = window.DashboardFlow?.updateTime;
var debouncedDrawConnections = window.DashboardFlow?.debouncedDrawConnections;
var drawConnections = window.DashboardFlow?.drawConnections;
var getNodeCenters = window.DashboardFlow?.getNodeCenters;
var updateNode = window.DashboardFlow?.updateNode;
var updateNodeDetails = window.DashboardFlow?.updateNodeDetails;
var loadData = window.DashboardFlow?.loadData;
var loadNodeDetails = window.DashboardFlow?.loadNodeDetails;
var forceFullRefresh = window.DashboardFlow?.forceFullRefresh;
var debouncedLoadData = window.DashboardFlow?.debouncedLoadData;
var debouncedLoadNodeDetails = window.DashboardFlow?.debouncedLoadNodeDetails;

// Import findShieldSensorId from utils
var findShieldSensorId = window.DashboardUtils?.findShieldSensorId;

// === THEME DETECTION ===

/**
 * Detekuje aktuální téma Home Assistantu a aplikuje správné styly
 */
function detectAndApplyTheme() {
    try {
        const hass = getHass();
        const bodyElement = document.body;
        let isLightTheme = false;

        if (hass && hass.themes) {
            // Metoda 1: Přímý přístup k HA theme konfiguraci (nejspolehlivější)
            const selectedTheme = hass.selectedTheme || hass.themes.default_theme;
            const darkMode = hass.themes.darkMode;

            // console.log('[Theme] HA theme info:', {
            //     selectedTheme,
            //     darkMode,
            //     themes: hass.themes
            // });

            // HA má explicitní dark mode flag
            if (darkMode !== undefined) {
                isLightTheme = !darkMode;
                // console.log('[Theme] Using HA darkMode flag:', darkMode, '-> light theme:', isLightTheme);
            } else if (selectedTheme) {
                // Fallback: některá témata mají v názvu "light" nebo "dark"
                const themeName = selectedTheme.toLowerCase();
                if (themeName.includes('light')) {
                    isLightTheme = true;
                } else if (themeName.includes('dark')) {
                    isLightTheme = false;
                }
                // console.log('[Theme] Detected from theme name:', selectedTheme, '-> light:', isLightTheme);
            }
        } else {
            console.warn('[Theme] Cannot access hass.themes, trying CSS detection');
        }

        // Metoda 2: Fallback - detekce z CSS proměnných
        if (!hass || !hass.themes) {
            try {
                const haElement = parent.document.querySelector('home-assistant');
                if (haElement) {
                    const computedStyle = getComputedStyle(haElement);
                    const primaryBg = computedStyle.getPropertyValue('--primary-background-color');

                    if (primaryBg) {
                        const rgb = primaryBg.match(/\d+/g);
                        if (rgb && rgb.length >= 3) {
                            const brightness = (parseInt(rgb[0]) + parseInt(rgb[1]) + parseInt(rgb[2])) / 3;
                            isLightTheme = brightness > 128;
                            console.log('[Theme] CSS detection - brightness:', brightness, '-> light:', isLightTheme);
                        }
                    }
                }
            } catch (e) {
                console.warn('[Theme] CSS detection failed:', e);
            }
        }

// Aplikovat třídu na body
        if (isLightTheme) {
            bodyElement.classList.add('light-theme');
            bodyElement.classList.remove('dark-theme');
            // console.log('[Theme] ✓ Light theme applied');
        } else {
            bodyElement.classList.add('dark-theme');
            bodyElement.classList.remove('light-theme');
            // console.log('[Theme] ✓ Dark theme applied');
        }

    } catch (error) {
        console.error('[Theme] Error detecting theme:', error);
        // Výchozí: tmavé téma
        document.body.classList.add('dark-theme');
        document.body.classList.remove('light-theme');
    }
}

// === NUMBER ROLLING EFFECT ===
// Přidá animaci podobnou split-flap při změně textContent u vybraných prvků
function initRollingNumbers() {
    const selectors = [
        '.stat-value',
        '.day-stat-value',
        '.card .value',
        '.tile-value',
        '.price-value',
    ];

    const targets = Array.from(document.querySelectorAll(selectors.join(',')));
    if (!targets.length) {
        return;
    }

    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.type === 'characterData') {
                const el = mutation.target.parentElement;
                if (!el) return;
                el.classList.remove('rolling-change');
                // force reflow to restart animation
                void el.offsetWidth;
                el.classList.add('rolling-change');
            } else if (mutation.type === 'childList' && mutation.target) {
                const el = /** @type {HTMLElement} */ (mutation.target);
                el.classList.remove('rolling-change');
                void el.offsetWidth;
                el.classList.add('rolling-change');
            }
        });
    });

    targets.forEach((el) => {
        observer.observe(el, {
            characterData: true,
            subtree: true,
            childList: true,
        });
    });
}

// === TOOLTIP SYSTEM ===

/**
 * Globální tooltip systém - používá dedikované DOM elementy mimo flow
 * Toto řešení zaručuje správné pozicování bez ohledu na CSS transformace rodičů
 */
function initTooltips() {
    const tooltip = document.getElementById('global-tooltip');
    const arrow = document.getElementById('global-tooltip-arrow');
    const entityValues = document.querySelectorAll('.entity-value[data-tooltip], .entity-value[data-tooltip-html], .detail-value[data-tooltip-html], #battery-grid-charging-indicator[data-tooltip], #battery-grid-charging-indicator[data-tooltip-html], #balancing-planned-time-short[data-tooltip-html], #battery-balancing-indicator[data-tooltip-html]');

    if (!tooltip || !arrow) {
        console.error('[Tooltips] Global tooltip elements not found!');
        return;
    }

    entityValues.forEach(element => {
        element.addEventListener('mouseenter', function () {
            const tooltipText = this.getAttribute('data-tooltip');
            const tooltipHtml = this.getAttribute('data-tooltip-html');

            if (!tooltipText && !tooltipHtml) return;

            // Nastavit text nebo HTML
            if (tooltipHtml) {
                tooltip.innerHTML = tooltipHtml;
            } else {
                tooltip.textContent = tooltipText;
            }

            // Získat pozici elementu v rámci viewportu
            const rect = this.getBoundingClientRect();

            // Nejprve zobrazit tooltip pro změření jeho skutečné velikosti
            tooltip.style.visibility = 'hidden';
            tooltip.style.opacity = '1';

            const tooltipRect = tooltip.getBoundingClientRect();
            const tooltipWidth = tooltipRect.width;
            const tooltipHeight = tooltipRect.height;
            const padding = 10;
            const arrowSize = 5;

            // Vypočítat pozici tooltipu
            let tooltipTop = rect.top - tooltipHeight - arrowSize - padding;
            let tooltipLeft = rect.left + (rect.width / 2) - (tooltipWidth / 2);

            // Zajistit že tooltip není mimo viewport (horizontálně)
            const viewportWidth = window.innerWidth;
            if (tooltipLeft < padding) {
                tooltipLeft = padding;
            }
            if (tooltipLeft + tooltipWidth > viewportWidth - padding) {
                tooltipLeft = viewportWidth - tooltipWidth - padding;
            }

            // Kontrola zda se tooltip vejde nad element
            let isBelow = false;
            if (tooltipTop < padding) {
                // Nedostatek místa nahoře - zobrazit dole
                tooltipTop = rect.bottom + arrowSize + padding;
                isBelow = true;
            }

            // Pozice šipky - vždy uprostřed původního elementu
            const arrowLeft = rect.left + (rect.width / 2) - arrowSize;
            const arrowTop = isBelow
                ? rect.bottom + padding
                : rect.top - arrowSize - padding;

            // Aplikovat vypočítané pozice
            tooltip.style.top = `${tooltipTop}px`;
            tooltip.style.left = `${tooltipLeft}px`;
            tooltip.style.visibility = 'visible';

            arrow.style.top = `${arrowTop}px`;
            arrow.style.left = `${arrowLeft}px`;

            // Nastavit směr šipky
            if (isBelow) {
                arrow.classList.add('below');
            } else {
                arrow.classList.remove('below');
            }

            // Zobrazit tooltip a šipku
            tooltip.classList.add('visible');
            arrow.classList.add('visible');
        });

        element.addEventListener('mouseleave', function () {
            // Skrýt tooltip a šipku
            tooltip.classList.remove('visible');
            arrow.classList.remove('visible');

            // Po animaci schovat mimo obrazovku
            setTimeout(() => {
                if (!tooltip.classList.contains('visible')) {
                    tooltip.style.top = '-9999px';
                    tooltip.style.left = '-9999px';
                    arrow.style.top = '-9999px';
                    arrow.style.left = '-9999px';
                }
            }, 200); // délka CSS transition
        });
    });

    // console.log('[Tooltips] Initialized for', entityValues.length, 'elements');
}

// === GRID CHARGING (moved to dashboard-grid-charging.js) ===
var openGridChargingDialog = window.DashboardGridCharging?.openGridChargingDialog;
var closeGridChargingDialog = window.DashboardGridCharging?.closeGridChargingDialog;

// === INITIALIZATION ===
function init() {
    console.log('[Dashboard] Initializing...');
    const isConstrainedRuntime = !!(window.OIG_RUNTIME?.isHaApp || window.OIG_RUNTIME?.isMobile);
    if (window.OIG_RUNTIME?.reduceMotion) {
        document.body.classList.add('oig-reduce-motion');
        const particles = document.getElementById('particles');
        if (particles) {
            particles.style.display = 'none';
        }
    }

    // Detekovat a aplikovat téma z Home Assistantu
    detectAndApplyTheme();

    // === LAYOUT CUSTOMIZATION INITIALIZATION ===
    currentBreakpoint = getCurrentBreakpoint();
    console.log(`[Layout] Initial breakpoint: ${currentBreakpoint}`);

    // Načíst custom layout pokud existuje
    const loaded = loadLayout(currentBreakpoint);
    if (loaded) {
        console.log(`[Layout] Custom ${currentBreakpoint} layout loaded`);
    } else {
        console.log(`[Layout] Using default ${currentBreakpoint} layout`);
    }

    // Resize listener pro breakpoint changes
    window.addEventListener('resize', handleLayoutResize);

    // Auto-collapse control panel on mobile
    if (window.innerWidth <= 768) {
        const panel = document.getElementById('control-panel');
        const icon = document.getElementById('panel-toggle-icon');
        if (panel && icon) {
            panel.classList.add('minimized');
            icon.textContent = '+';
        }
    }

    // Initialize tooltip system
    initTooltips();

    // Start number rolling animation observer
    initRollingNumbers();

    // Optional: legacy performance chart (removed)
    if (typeof initPerformanceChart === 'function') {
        initPerformanceChart();
    }

    // OPRAVA: Počkat na dokončení layout načtení před voláním loadData()
    // Pokud byl načten custom layout, particles byly zastaveny
    // a needsFlowReinitialize je TRUE, takže loadData() je restartuje
    setTimeout(() => {
        // Initial full load (defer heavy work in HA app to avoid UI freeze)
        const startHeavyLoad = () => {
            forceFullRefresh();
        };
        if (isConstrainedRuntime) {
            setTimeout(() => runWhenIdle(startHeavyLoad, 3500, 1200), 200);
        } else {
            startHeavyLoad();
        }

        updateTime();

        // NOVÉ: Load extended timeline for Today Plan Tile
        runWhenIdle(buildExtendedTimeline, isConstrainedRuntime ? 3500 : 2500, isConstrainedRuntime ? 1200 : 900);

        // OPRAVA: Načíst pricing data pokud je pricing tab aktivní při načtení stránky
        const pricingTab = document.getElementById('pricing-tab');
        if (pricingTab && pricingTab.classList.contains('active')) {
            console.log('[Init] Pricing tab is active, loading initial pricing data...');
            pricingTabActive = true;
            setTimeout(() => {
                loadPricingData();
            }, 200);
        }
    }, 50);

    // Subscribe to shield state changes for real-time updates (defer on mobile/HA app)
    const startShieldSubscription = () => {
        subscribeToShield();
    };
    if (isConstrainedRuntime) {
        setTimeout(() => runWhenIdle(startShieldSubscription, 4000, 1500), 300);
    } else {
        startShieldSubscription();
    }

    // Initial shield UI update with retry logic (wait for sensors after HA restart)
    let retryCount = 0;
    const maxRetries = 10;
    const retryInterval = 2000; // 2s between retries

    function tryInitialShieldLoad() {
        console.log(`[Shield] Attempting initial load (attempt ${retryCount + 1}/${maxRetries})...`);

        // Check if shield sensors are available
        const hass = getHass();
        if (!hass || !hass.states) {
            console.warn('[Shield] HA connection not ready, will retry...');
            retryCount++;
            if (retryCount < maxRetries) {
                setTimeout(tryInitialShieldLoad, retryInterval);
            } else {
                console.error('[Shield] Failed to load after', maxRetries, 'attempts');
                console.warn('[Shield] Falling back to 20s polling as backup');
                // Fallback: Enable backup polling if initial load fails
                setInterval(() => {
                    console.log('[Shield] Backup polling triggered');
                    monitorShieldActivity();
                    updateShieldQueue();
                    updateShieldUI();
                    updateButtonStates();
                }, 20000);
            }
            return;
        }

        const activitySensorId = findShieldSensorId('service_shield_activity');
        if (!activitySensorId || !hass.states[activitySensorId]) {
            console.warn('[Shield] Shield sensors not ready yet, will retry...');
            retryCount++;
            if (retryCount < maxRetries) {
                setTimeout(tryInitialShieldLoad, retryInterval);
            } else {
                console.error('[Shield] Shield sensors not available after', maxRetries, 'attempts');
                console.warn('[Shield] Falling back to 20s polling as backup');
                // Fallback: Enable backup polling if sensors not available
                setInterval(() => {
                    console.log('[Shield] Backup polling triggered');
                    monitorShieldActivity();
                    updateShieldQueue();
                    updateShieldUI();
                    updateButtonStates();
                }, 20000);
            }
            return;
        }

        // Sensors are ready, load UI
        console.log('[Shield] Sensors ready, loading initial UI...');
        updateButtonStates(); // Set initial active states (green highlighting)
        updateShieldQueue();  // Load initial queue state
        updateShieldUI();     // Load initial shield status
        monitorShieldActivity(); // Start activity monitoring
    }

    // Start initial load with delay
    setTimeout(tryInitialShieldLoad, 1000);

    // === EVENT-DRIVEN ARCHITECTURE ===
    // Veškeré updates jsou řízeny přes StateWatcher (polling hass.states), bez dalších `state_changed` WS subscription.
    // - Data sensors -> debouncedLoadData() (200ms debounce)
    // - Detail sensors -> debouncedLoadNodeDetails() (500ms debounce)
    // - Pricing sensors -> debouncedLoadPricingData() (300ms debounce)
    // - Shield sensors -> debouncedShieldMonitor() (100ms debounce)

    // REMOVED: Polling-based updates (replaced by WebSocket events)
    // setInterval(loadData, 5000);  ❌ Nahrazeno event-driven
    // setInterval(loadNodeDetails, 30000);  ❌ Nahrazeno event-driven
    // setInterval(detectAndApplyTheme, 5000);  ❌ Nahrazeno event-driven

    // Theme detection - pouze event listeners (NO POLLING)
    // 1. Parent window theme changes
    try {
        if (parent && parent.addEventListener) {
            parent.addEventListener('theme-changed', () => {
                console.log('[Theme] Theme changed event detected');
                detectAndApplyTheme();
            });
        }
    } catch (e) {
        console.warn('[Theme] Cannot listen to parent events:', e);
    }

    // 2. System preference changes
    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
            console.log('[Theme] System preference changed');
            detectAndApplyTheme();
        });
    }

    // 3. Fallback: Check theme on visibility change (tab switch)
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            console.log('[Theme] Tab became visible, checking theme');
            detectAndApplyTheme();
        }
    });

    // REMOVED: Backup shield monitoring - WebSocket events handle all updates in real-time
    // setInterval(() => {
    //     monitorShieldActivity();
    //     updateShieldQueue();
    // }, 10000);

    // Time update every second
    setInterval(updateTime, 1000);

    // Redraw lines on resize with debounce.
    // Mobile WebViews (incl. HA app) fire frequent resize events when browser chrome shows/hides.
    // Avoid stopping/reinitializing particles on height-only micro-resizes.
    let resizeTimer;
    let lastResizeWidth = window.innerWidth;
    let lastResizeHeight = window.innerHeight;
    let lastResizeBreakpoint = (window.innerWidth <= 768) ? 'mobile' : (window.innerWidth <= 1024 ? 'tablet' : 'desktop');
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        // Clear cache on resize
        cachedNodeCenters = null;
        lastLayoutHash = null;
        resizeTimer = setTimeout(() => {
            const w = window.innerWidth;
            const h = window.innerHeight;
            const breakpoint = (w <= 768) ? 'mobile' : (w <= 1024 ? 'tablet' : 'desktop');

            const dw = Math.abs(w - lastResizeWidth);
            const dh = Math.abs(h - lastResizeHeight);
            const breakpointChanged = breakpoint !== lastResizeBreakpoint;

            // "Meaningful" resize: width changes (rotation / split-screen) or breakpoint changes.
            // Height-only changes often happen continuously on mobile due to browser UI.
            const meaningfulResize = breakpointChanged || dw >= 24 || dh >= 180;

            lastResizeWidth = w;
            lastResizeHeight = h;
            lastResizeBreakpoint = breakpoint;

            // OPRAVA: Při resize na flow tabu musíme reinicializovat particles
            const flowTab = document.querySelector('#flow-tab');
            const isFlowTabActive = flowTab && flowTab.classList.contains('active');

            if (isFlowTabActive) {
                if (meaningfulResize) {
                    console.log('[Resize] Flow tab meaningful resize, reinitializing particles...');
                    stopAllParticleFlows();
                    drawConnections();
                    needsFlowReinitialize = true;
                    // Trigger a data refresh (debounced) to kick animations with updated positions.
                    if (typeof debouncedLoadData === 'function') {
                        debouncedLoadData();
                    } else {
                        loadData();
                    }
                } else {
                    // Lightweight update: just redraw connections; particle flows will self-correct on next data tick.
                    drawConnections();
                }
            } else {
                // Jen překreslit connections pokud nejsme na flow tabu
                drawConnections();
            }
        }, 100);
    });

    // FIX: Force layout stabilization after initial render
    // Problém: Po restartu HA se někdy načítají CSS/HTML v jiném pořadí
    // Řešení: Opakované překreslení po různých intervalech
    // OPRAVA BUG #3: Inicializovat cache před prvním kreslením
    const scheduleConnectionsDraw = (delay) => {
        setTimeout(() => { getNodeCenters(); drawConnections(); }, delay);
    };
    if (isConstrainedRuntime) {
        scheduleConnectionsDraw(200);   // První pokus po 200ms (mobile/HA app)
        scheduleConnectionsDraw(1200);  // Finální po 1.2s
    } else {
        scheduleConnectionsDraw(100);   // První pokus po 100ms
        scheduleConnectionsDraw(500);   // Druhý pokus po 500ms
        scheduleConnectionsDraw(1000);  // Třetí pokus po 1s
        scheduleConnectionsDraw(2000);  // Finální po 2s
    }

    // Mobile: Toggle node details on click (collapsed by default)
    if (window.innerWidth <= 768) {
        const nodes = document.querySelectorAll('.node');
        nodes.forEach(node => {
            node.addEventListener('click', function (e) {
                // Ignore clicks on buttons inside nodes
                if (e.target.tagName === 'BUTTON' || e.target.closest('button')) {
                    return;
                }
                this.classList.toggle('expanded');
            });

            // Add cursor pointer to indicate clickability
            node.style.cursor = 'pointer';
        });
    }

    // === CUSTOM TILES INITIALIZATION ===
    initCustomTiles();

    // === PERIODICKÝ CLEANUP PARTICLES (PREVENCE ÚNIK PAMĚTI) ===
    // Každých 30 sekund zkontrolujeme počet particles
    // Pokud NEJSME na tab Toky, NEMAŽ particles (budou potřeba po návratu)
    // Pokud JSME na tab Toky a je > 40 kuliček, proveď cleanup
    setInterval(() => {
        const flowTab = document.querySelector('#flow-tab');
        const isFlowTabActive = flowTab && flowTab.classList.contains('active');
        const particlesContainer = document.getElementById('particles');

        if (!isFlowTabActive) {
            // OPRAVA: NEMAŽ particles když nejsi na tabu - budou potřeba při návratu
            // Jen zkontroluj count pro monitoring
            if (particlesContainer) {
                const particleCount = particlesContainer.children.length;
                if (particleCount > 50) {
                    console.log(`[Particles] ⚠️ High particle count while tab inactive: ${particleCount} (will cleanup on tab switch)`);
                }
            }
        } else if (particlesContainer) {
            // Jsme na tab flow (toky) -> cleanup jen pokud je > 40 kuliček
            const particleCount = particlesContainer.children.length;
            if (particleCount > 40) {
                console.log(`[Particles] ⏰ Periodic cleanup (${particleCount} particles exceeded threshold)`);
                stopAllParticleFlows();
                // Po cleanup restartovat animace s aktuálními daty
                setTimeout(() => {
                    needsFlowReinitialize = true;
                    loadData();
                }, 200);
            }
        }
    }, 30000); // 30 sekund

    console.log('[Particles] ✓ Periodic cleanup timer started (30s interval)');
}

// Wait for DOM
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// === TAB SWITCHING ===
var pricingTabActive = false;
var needsFlowReinitialize = false; // Flag pro vynucené restartování flow animací

function switchTab(tabName) {
    // Zapamatuj si předchozí tab PŘED změnou
    const previousActiveContent = document.querySelector('.tab-content.active');
    const previousTab = previousActiveContent ? previousActiveContent.id.replace('-tab', '') : null;

    console.log(`[Tab] Switching from '${previousTab}' to '${tabName}'`);

    // Remove active from all tabs and contents
    document.querySelectorAll('.dashboard-tab').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

    // Add active to clicked tab (find by checking which one was clicked via event)
    const clickedTab = event ? event.target : document.querySelector('.dashboard-tab');
    if (clickedTab) {
        clickedTab.classList.add('active');
    }

    // Add active to corresponding content
    const tabContent = document.getElementById(tabName + '-tab');
    if (tabContent) {
        tabContent.classList.add('active');
    }

    // Track active tab for event-driven updates
    pricingTabActive = (tabName === 'pricing');

    // OPRAVA: Při ODCHODU z tab flow (toky), zastavit particles (cleanup)
    if (previousTab === 'flow' && tabName !== 'flow') {
        console.log('[Tab] ========== LEAVING FLOW TAB - CLEANUP ==========');
        stopAllParticleFlows();
    }

    // OPRAVA: Při přepnutí NA tab flow (toky), překreslit connections a FORCE restart particles
    if (tabName === 'flow') {
        console.log('[Tab] ========== SWITCHING TO FLOW TAB ==========');

        // DŮLEŽITÉ: Počkat až se tab zobrazí a DOM se vykreslí
        setTimeout(() => {
            console.log('[Tab] --- Timeout fired, starting redraw ---');

            const flowTab = document.getElementById('flow-tab');
            console.log('[Tab] Flow tab visible?', flowTab && flowTab.classList.contains('active'));
            console.log('[Tab] Flow tab offsetHeight:', flowTab?.offsetHeight);

            // OPRAVA: Zkontrolovat jestli je tab skutečně viditelný
            if (!flowTab || !flowTab.classList.contains('active')) {
                console.warn('[Tab] ✗ Flow tab not visible yet, aborting redraw');
                return;
            }

            // 3. Invalidovat cache pozic
            cachedNodeCenters = null;
            lastLayoutHash = null;
            console.log('[Tab] ✓ Cache invalidated');

            // 4. Force browser reflow aby DOM byl stabilní
            if (flowTab) {
                const reflow = flowTab.offsetHeight; // Trigger reflow
                console.log('[Tab] ✓ Browser reflow triggered:', reflow, 'px');
            }

            // 5. Načíst fresh pozice node elementů
            console.log('[Tab] Getting node centers...');
            const centers = getNodeCenters();
            console.log('[Tab] Node centers result:', centers);

            // OPRAVA: Zkontrolovat jestli se pozice načetly správně
            if (!centers || Object.keys(centers).length === 0) {
                console.error('[Tab] ✗ Failed to get node centers (DOM not ready), retrying...');
                // Zkusit znovu s delším timeout
                setTimeout(() => {
                    cachedNodeCenters = null;
                    lastLayoutHash = null;
                    const retryCenters = getNodeCenters();
                    console.log('[Tab] Retry node centers result:', retryCenters);

                    if (!retryCenters || Object.keys(retryCenters).length === 0) {
                        console.error('[Tab] ✗ Retry also failed, giving up');
                        return;
                    }

                    console.log('[Tab] ✓ Node centers loaded on retry:', Object.keys(retryCenters).length);
                    drawConnections();
                    needsFlowReinitialize = true;
                    loadData();
                    console.log('[Tab] ✓ Retry complete');
                }, 200);
                return;
            }

            // 6. Překreslit čáry (teď už máme správné pozice)
            console.log('[Tab] ✓ Node centers cached:', Object.keys(centers).length);
            console.log('[Tab] Drawing connections...');
            drawConnections();
            console.log('[Tab] ✓ Connections drawn');

            // 7. Nastavit flag pro vynucené restartování animací
            needsFlowReinitialize = true;
            console.log('[Tab] Flag needsFlowReinitialize set to TRUE');

            // 8. Načíst aktuální data a restartovat particles
            console.log('[Tab] Loading fresh data for animations...');
            loadData(); // Načte data a zavolá animateFlow() s aktuálními hodnotami
            console.log('[Tab] ========== TOKY TAB SWITCH COMPLETE ==========');
        }, 150); // Delší timeout aby se DOM stihl vykreslit
    }

    // Load data when entering pricing tab
    if (tabName === 'pricing') {
        const tabSwitchStart = performance.now();
        console.log('[Tab] ========== SWITCHING TO PRICING TAB ==========');
        // Počkat až se tab zobrazí a canvas bude viditelný
        setTimeout(() => {
            const afterTimeout = performance.now();
            console.log(`[Pricing] Tab visible after ${(afterTimeout - tabSwitchStart).toFixed(0)}ms timeout, loading pricing data...`);
            loadPricingData();

            // Subscribe to Battery Health updates (once)
            if (typeof subscribeBatteryHealthUpdates === 'function') {
                subscribeBatteryHealthUpdates();
            }
        }, 150); // Stejný timeout jako u Toky pro konzistenci
    }

    // Load boiler dashboard when entering boiler tab
    if (tabName === 'boiler') {
        console.log('[Tab] ========== SWITCHING TO BOILER TAB ==========');
        setTimeout(() => {
            console.log('[Boiler] Tab visible, initializing boiler dashboard...');
            if (typeof initBoilerDashboard === 'function') {
                initBoilerDashboard();
            } else {
                console.error('[Boiler] initBoilerDashboard function not found');
            }
        }, 150);
    }

}

// === BOILER (enhanced in dashboard-boiler.js) ===
var loadPricingData = window.DashboardPricing.loadPricingData;
var updatePlannedConsumptionStats = window.DashboardPricing.updatePlannedConsumptionStats;
var tileDialog = null;

// === CUSTOM TILES (moved to dashboard-tiles.js) ===
var initCustomTiles = window.DashboardTiles.initCustomTiles;
var renderAllTiles = window.DashboardTiles.renderAllTiles;
var updateTileCount = window.DashboardTiles.updateTileCount;
var toggleTilesVisibility = window.DashboardTiles.toggleTilesVisibility;
var resetAllTiles = window.DashboardTiles.resetAllTiles;

/**
 * Render icon - podporuje emoji i MDI ikony
 * @param {string} icon - Icon string (emoji nebo mdi:xxx)
 * @param {string} color - Icon color
 * @returns {string} - HTML string
 */
function renderIcon(icon, color) {
    if (!icon) return '';

    // MDI ikona (formát mdi:xxx) - použít emoji fallback protože ha-icon nefunguje v iframe
    if (icon.startsWith('mdi:')) {
        const iconName = icon.substring(4); // Odstranit 'mdi:' prefix

        // Emoji mapa - stejná jako v dashboard-dialog.js
        const emojiMap = {
            // Spotřebiče
            'fridge': '❄️', 'fridge-outline': '❄️', 'dishwasher': '🍽️', 'washing-machine': '🧺',
            'tumble-dryer': '🌪️', 'stove': '🔥', 'microwave': '📦', 'coffee-maker': '☕',
            'kettle': '🫖', 'toaster': '🍞',
            // Osvětlení
            'lightbulb': '💡', 'lightbulb-outline': '💡', 'lamp': '🪔', 'ceiling-light': '💡',
            'floor-lamp': '🪔', 'led-strip': '✨', 'led-strip-variant': '✨', 'wall-sconce': '💡',
            'chandelier': '💡',
            // Vytápění
            'thermometer': '🌡️', 'thermostat': '🌡️', 'radiator': '♨️', 'radiator-disabled': '❄️',
            'heat-pump': '♨️', 'air-conditioner': '❄️', 'fan': '🌀', 'hvac': '♨️', 'fire': '🔥',
            'snowflake': '❄️',
            // Energie
            'lightning-bolt': '⚡', 'flash': '⚡', 'battery': '🔋', 'battery-charging': '🔋',
            'battery-50': '🔋', 'solar-panel': '☀️', 'solar-power': '☀️', 'meter-electric': '⚡',
            'power-plug': '🔌', 'power-socket': '🔌',
            // Auto
            'car': '🚗', 'car-electric': '🚘', 'car-battery': '🔋', 'ev-station': '🔌',
            'ev-plug-type2': '🔌', 'garage': '🏠', 'garage-open': '🏠',
            // Zabezpečení
            'door': '🚪', 'door-open': '🚪', 'lock': '🔒', 'lock-open': '🔓', 'shield-home': '🛡️',
            'cctv': '📹', 'camera': '📹', 'motion-sensor': '👁️', 'alarm-light': '🚨', 'bell': '🔔',
            // Okna
            'window-closed': '🪟', 'window-open': '🪟', 'blinds': '🪟', 'blinds-open': '🪟',
            'curtains': '🪟', 'roller-shade': '🪟',
            // Média
            'television': '📺', 'speaker': '🔊', 'speaker-wireless': '🔊', 'music': '🎵',
            'volume-high': '🔊', 'cast': '📡', 'chromecast': '📡',
            // Síť
            'router-wireless': '📡', 'wifi': '📶', 'access-point': '📡', 'lan': '🌐',
            'network': '🌐', 'home-assistant': '🏠',
            // Voda
            'water': '💧', 'water-percent': '💧', 'water-boiler': '♨️', 'water-pump': '💧',
            'shower': '🚿', 'toilet': '🚽', 'faucet': '🚰', 'pipe': '🔧',
            // Počasí
            'weather-sunny': '☀️', 'weather-cloudy': '☁️', 'weather-night': '🌙',
            'weather-rainy': '🌧️', 'weather-snowy': '❄️', 'weather-windy': '💨',
            // Ostatní
            'information': 'ℹ️', 'help-circle': '❓', 'alert-circle': '⚠️',
            'checkbox-marked-circle': '✅', 'toggle-switch': '🔘', 'power': '⚡', 'sync': '🔄'
        };

        const emoji = emojiMap[iconName] || '⚙️';
        return `<span style="font-size: 28px; color: ${color};">${emoji}</span>`;
    }

    // Emoji nebo jiný text
    return icon;
}/**
 * Render entity tile content
 * @param {object} config - Entity tile config
 * @param {string} side - Tile side (left/right)
 * @param {number} index - Tile index
 * @returns {string} - HTML string
 */
function renderEntityTile(config, side, index) {
    const hass = getHass();
    if (!hass || !hass.states) {
        return '<div class="tile-error">HA nedostupné</div>';
    }

    const state = hass.states[config.entity_id];
    if (!state) {
        return `<div class="tile-error">Entita nenalezena:<br>${config.entity_id}</div>`;
    }

    const label = config.label || state.attributes.friendly_name || config.entity_id;
    // Použij POUZE ikonu z config, pokud není nastavena, použij výchozí - nikdy ne z HA state
    const icon = config.icon || '📊';
    let value = state.state;
    let unit = state.attributes.unit_of_measurement || '';
    const color = config.color || '#03A9F4';

    // Konverze W/Wh na kW/kWh pokud >= 1000
    if (unit === 'W' || unit === 'Wh') {
        const numValue = parseFloat(value);
        if (!isNaN(numValue)) {
            if (Math.abs(numValue) >= 1000) {
                value = (numValue / 1000).toFixed(1);
                unit = unit === 'W' ? 'kW' : 'kWh';
            } else {
                value = Math.round(numValue);
            }
        }
    }

    // Podporné entity
    let supportHtml = '';
    if (config.support_entities) {
        // Top right
        if (config.support_entities.top_right) {
            const topRightState = hass.states[config.support_entities.top_right];
            if (topRightState) {
                let topRightValue = topRightState.state;
                let topRightUnit = topRightState.attributes.unit_of_measurement || '';
                const topRightIcon = topRightState.attributes.icon || '';

                // Konverze W/Wh na kW/kWh
                if (topRightUnit === 'W' || topRightUnit === 'Wh') {
                    const numValue = parseFloat(topRightValue);
                    if (!isNaN(numValue)) {
                        if (Math.abs(numValue) >= 1000) {
                            topRightValue = (numValue / 1000).toFixed(1);
                            topRightUnit = topRightUnit === 'W' ? 'kW' : 'kWh';
                        } else {
                            topRightValue = Math.round(numValue);
                        }
                    }
                }

                supportHtml += `
                    <div class="tile-support tile-support-top-right" onclick="event.stopPropagation(); openEntityDialog('${config.support_entities.top_right}')">
                        <span class="support-icon">${topRightIcon}</span>
                        <span class="support-value" id="tile-${side}-${index}-support-top">${topRightValue}${topRightUnit}</span>
                    </div>
                `;
            }
        }

        // Bottom right
        if (config.support_entities.bottom_right) {
            const bottomRightState = hass.states[config.support_entities.bottom_right];
            if (bottomRightState) {
                let bottomRightValue = bottomRightState.state;
                let bottomRightUnit = bottomRightState.attributes.unit_of_measurement || '';
                const bottomRightIcon = bottomRightState.attributes.icon || '';

                // Konverze W/Wh na kW/kWh
                if (bottomRightUnit === 'W' || bottomRightUnit === 'Wh') {
                    const numValue = parseFloat(bottomRightValue);
                    if (!isNaN(numValue)) {
                        if (Math.abs(numValue) >= 1000) {
                            bottomRightValue = (numValue / 1000).toFixed(1);
                            bottomRightUnit = bottomRightUnit === 'W' ? 'kW' : 'kWh';
                        } else {
                            bottomRightValue = Math.round(numValue);
                        }
                    }
                }

                supportHtml += `
                    <div class="tile-support tile-support-bottom-right" onclick="event.stopPropagation(); openEntityDialog('${config.support_entities.bottom_right}')">
                        <span class="support-icon">${bottomRightIcon}</span>
                        <span class="support-value" id="tile-${side}-${index}-support-bottom">${bottomRightValue}${bottomRightUnit}</span>
                    </div>
                `;
            }
        }
    }

    // Detekce neaktivního stavu (0 W nebo 0 hodnota)
    const numericValue = parseFloat(state.state);
    const isInactive = !isNaN(numericValue) && numericValue === 0;
    const inactiveClass = isInactive ? ' tile-inactive' : '';

    return `
        <div class="tile-content tile-content-horizontal${inactiveClass}" style="border-left: 3px solid ${color};">
            <div class="tile-main-content">
                <div class="tile-icon-large" style="color: ${color};">${renderIcon(icon, color)}</div>
                <div class="tile-value-large" onclick="openEntityDialog('${config.entity_id}')" style="cursor: pointer;"><span id="tile-${side}-${index}-value">${value}</span><span class="tile-unit" id="tile-${side}-${index}-unit">${unit}</span></div>
            </div>
            ${supportHtml}
            <div class="tile-label-hover">${label}</div>
        </div>
    `;
}

/**
 * Render button tile content
 * @param {object} config - Button tile config
 * @param {string} side - Tile side (left/right)
 * @param {number} index - Tile index
 * @returns {string} - HTML string
 */
function renderButtonTile(config, side, index) {
    const hass = getHass();
    if (!hass || !hass.states) {
        return '<div class="tile-error">HA nedostupné</div>';
    }

    const state = hass.states[config.entity_id];
    if (!state) {
        return `<div class="tile-error">Entita nenalezena:<br>${config.entity_id}</div>`;
    }

    const label = config.label || state.attributes.friendly_name || config.entity_id;
    // Použij POUZE ikonu z config, pokud není nastavena, použij výchozí - nikdy ne z HA state
    const icon = config.icon || '🔘';
    const color = config.color || '#FFC107';
    const action = config.action || 'toggle';
    const isOn = state.state === 'on';

    const buttonClass = isOn ? 'tile-button-active' : 'tile-button-inactive';

    // Popis akce pro uživatele
    const actionLabels = {
        'toggle': 'Přepnout',
        'turn_on': 'Zapnout',
        'turn_off': 'Vypnout'
    };
    const actionLabel = actionLabels[action] || 'Ovládat';

    // Podporné entity
    let supportHtml = '';
    if (config.support_entities) {
        // Top right
        if (config.support_entities.top_right) {
            const topRightState = hass.states[config.support_entities.top_right];
            if (topRightState) {
                let topRightValue = topRightState.state;
                let topRightUnit = topRightState.attributes.unit_of_measurement || '';
                const topRightIcon = topRightState.attributes.icon || '';

                // Konverze W/Wh na kW/kWh
                if (topRightUnit === 'W' || topRightUnit === 'Wh') {
                    const numValue = parseFloat(topRightValue);
                    if (!isNaN(numValue)) {
                        if (Math.abs(numValue) >= 1000) {
                            topRightValue = (numValue / 1000).toFixed(1);
                            topRightUnit = topRightUnit === 'W' ? 'kW' : 'kWh';
                        } else {
                            topRightValue = Math.round(numValue);
                        }
                    }
                }

                supportHtml += `
                    <div class="tile-support tile-support-top-right" onclick="event.stopPropagation(); openEntityDialog('${config.support_entities.top_right}')">
                        <span class="support-icon">${topRightIcon}</span>
                        <span class="support-value" id="tile-${side}-${index}-support-top">${topRightValue}${topRightUnit}</span>
                    </div>
                `;
            }
        }

        // Bottom right
        if (config.support_entities.bottom_right) {
            const bottomRightState = hass.states[config.support_entities.bottom_right];
            if (bottomRightState) {
                let bottomRightValue = bottomRightState.state;
                let bottomRightUnit = bottomRightState.attributes.unit_of_measurement || '';
                const bottomRightIcon = bottomRightState.attributes.icon || '';

                // Konverze W/Wh na kW/kWh
                if (bottomRightUnit === 'W' || bottomRightUnit === 'Wh') {
                    const numValue = parseFloat(bottomRightValue);
                    if (!isNaN(numValue)) {
                        if (Math.abs(numValue) >= 1000) {
                            bottomRightValue = (numValue / 1000).toFixed(1);
                            bottomRightUnit = bottomRightUnit === 'W' ? 'kW' : 'kWh';
                        } else {
                            bottomRightValue = Math.round(numValue);
                        }
                    }
                }

                supportHtml += `
                    <div class="tile-support tile-support-bottom-right" onclick="event.stopPropagation(); openEntityDialog('${config.support_entities.bottom_right}')">
                        <span class="support-icon">${bottomRightIcon}</span>
                        <span class="support-value" id="tile-${side}-${index}-support-bottom">${bottomRightValue}${bottomRightUnit}</span>
                    </div>
                `;
            }
        }
    }

    return `
        <div class="tile-content tile-content-horizontal ${buttonClass}"
             style="border-left: 3px solid ${color};"
             onclick="executeTileButtonAction('${config.entity_id}', '${action}')">
            <div class="tile-main-content">
                <div class="tile-icon-large" style="color: ${color};">${renderIcon(icon, color)}</div>
                <div class="tile-button-state" id="tile-${side}-${index}-button-state">${isOn ? 'ON' : 'OFF'}</div>
            </div>
            ${supportHtml}
            <div class="tile-label-hover">${label} • ${actionLabel}</div>
        </div>
    `;
}

/**
 * Execute button action
 * @param {string} entityId - Entity ID
 * @param {string} action - Action (toggle, turn_on, turn_off)
 */
function executeTileButtonAction(entityId, action) {
    const hass = getHass();
    if (!hass) {
        console.error('[Tiles] Cannot execute action - no HA connection');
        return;
    }

    const domain = entityId.split('.')[0];
    const service = action === 'toggle' ? 'toggle' : action;

    console.log(`[Tiles] Calling ${domain}.${service} on ${entityId}`);

    hass.callService(domain, service, { entity_id: entityId })
        .then(() => {
            console.log(`[Tiles] Service call successful`);
            // Re-render tiles after state change (debounced)
            setTimeout(renderAllTiles, 500);
        })
        .catch((err) => {
            console.error(`[Tiles] Service call failed:`, err);
            alert(`Chyba při volání služby: ${err.message}`);
        });
}

// === ČHMÚ (moved to dashboard-chmu.js) ===
var updateChmuWarningBadge = window.DashboardChmu?.updateChmuWarningBadge;
var toggleChmuWarningModal = window.DashboardChmu?.toggleChmuWarningModal;
var openChmuWarningModal = window.DashboardChmu?.openChmuWarningModal;
var closeChmuWarningModal = window.DashboardChmu?.closeChmuWarningModal;

// === BATTERY & PRICING ANALYTICS (moved to modules) ===
var updateBatteryEfficiencyBar = window.DashboardAnalytics?.updateBatteryEfficiencyBar;
var updateWhatIfAnalysis = window.DashboardPricing?.updateWhatIfAnalysis;
var updateModeRecommendations = window.DashboardPricing?.updateModeRecommendations;

// === ANALYTICS (moved to dashboard-analytics.js) ===
var initPerformanceChart = window.DashboardAnalytics?.initPerformanceChart;
var updatePerformanceChart = window.DashboardAnalytics?.updatePerformanceChart;
var buildYesterdayAnalysis = window.DashboardAnalytics?.buildYesterdayAnalysis;
var renderYesterdayAnalysis = window.DashboardAnalytics?.renderYesterdayAnalysis;

// === EXPORT TILE RENDERING FUNCTIONS FOR TILES.JS ===
window.renderEntityTile = renderEntityTile;
window.renderButtonTile = renderButtonTile;
window.executeTileButtonAction = executeTileButtonAction;
window.renderAllTiles = renderAllTiles;
