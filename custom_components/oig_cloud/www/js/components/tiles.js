/* eslint-disable */
/**
 * Dashboard Tile Manager
 * Správa konfigurace dynamických dlaždic na OIG Dashboard
 */

// Global tile manager instance
let tileManager = null;

class DashboardTileManager {
    constructor(hass) {
        this.hass = hass;
        this.config = null; // Bude načteno v init()
        this.listeners = [];
        this.isInitialized = false;
    }

    /**
     * Asynchronní inicializace - načte konfiguraci z HA storage
     * MUSÍ se zavolat před použitím!
     */
    async init() {
        if (this.isInitialized) {
            console.log('⚠️ TileManager already initialized');
            return;
        }

        console.log('🔄 Initializing TileManager...');

        // Pokus načíst z HA storage JAKO PRVNÍ
        const haConfig = await this.loadFromHAStorage();

        if (haConfig) {
            console.log('✅ Using config from HA storage');
            this.config = haConfig;
        } else {
            // Pokud není v HA, zkusit localStorage
            try {
                const stored = localStorage.getItem('oig_dashboard_tiles');
                if (stored) {
                    this.config = JSON.parse(stored);
                    console.log('📦 Using config from localStorage fallback');
                } else {
                    this.config = this.getDefaultConfig();
                    console.log('🆕 Using default config');
                }
            } catch (e) {
                console.error('❌ Failed to load from localStorage:', e);
                this.config = this.getDefaultConfig();
            }
        }

        // Synchronizovat do localStorage jako cache
        try {
            localStorage.setItem('oig_dashboard_tiles', JSON.stringify(this.config));
        } catch (e) {
            console.error('❌ Failed to cache to localStorage:', e);
        }

        this.isInitialized = true;
        console.log('✅ TileManager initialized with config:', this.config);

        // Notifikovat listenery o dokončení načtení
        this.notifyListeners();
    }

    /**
     * Načíst konfiguraci z HA storage (async)
     */
    async loadFromHAStorage() {
        try {
            const hass = window.hass || this.hass;
            if (!hass) {
                console.warn('⚠️ Cannot load from HA storage - no hass connection');
                return null;
            }

            console.log('☁️ Loading config from HA storage...');

            // Použít WebSocket API přímo pro kompatibilitu Safari + Chrome
            const response = await hass.callWS({
                type: 'call_service',
                domain: 'oig_cloud',
                service: 'get_dashboard_tiles',
                service_data: {},
                return_response: true
            });

            if (response && response.response && response.response.config) {
                console.log('✅ Config loaded from HA storage:', response.response.config);
                return response.response.config;
            } else {
                console.log('ℹ️ No config found in HA storage');
                return null;
            }
        } catch (e) {
            console.error('❌ Failed to load from HA storage:', e);
            return null;
        }
    }

    /**
     * Výchozí konfigurace
     */
    getDefaultConfig() {
        return {
            tiles_left: Array(6).fill(null),  // 2×3 nebo 3×2 grid = 6 dlaždic
            tiles_right: Array(6).fill(null), // 2×3 nebo 3×2 grid = 6 dlaždic
            left_count: 6,
            right_count: 6,
            visible: true,  // ZMĚNĚNO: Default je nyní TRUE (viditelné)
            version: 1
        };
    }

    /**
     * Uložit konfiguraci do localStorage a HA storage
     */
    saveConfig() {
        if (!this.isInitialized || !this.config) {
            console.warn('⚠️ Cannot save - TileManager not initialized yet');
            return;
        }

        try {
            // Uložit do localStorage jako cache
            localStorage.setItem('oig_dashboard_tiles', JSON.stringify(this.config));
            console.log('💾 Saved tile config to localStorage cache:', this.config);
            this.notifyListeners();

            // VŽDY synchronizovat do HA storage (debounced)
            this.scheduleSyncToHA();
        } catch (e) {
            console.error('❌ Failed to save tile config to localStorage:', e);
            // I když selže localStorage, zkusíme sync do HA
            this.scheduleSyncToHA();
        }
    }

    /**
     * Nastavit dlaždici
     */
    setTile(side, index, tileConfig) {
        if (!this.isInitialized || !this.config) {
            console.warn('⚠️ Cannot set tile - TileManager not initialized yet');
            return;
        }

        const key = `tiles_${side}`;
        if (!this.config[key]) {
            console.error(`❌ Invalid side: ${side}`);
            return;
        }

        if (index < 0 || index >= this.config[key].length) {
            console.error(`❌ Invalid index: ${index}`);
            return;
        }

        console.log(`🔧 Setting tile [${side}][${index}]:`, tileConfig);
        this.config[key][index] = tileConfig;
        this.saveConfig();
    }

    /**
     * Odebrat dlaždici
     */
    removeTile(side, index) {
        console.log(`🗑️ Removing tile [${side}][${index}]`);
        this.setTile(side, index, null);
    }

    /**
     * Získat dlaždici
     */
    getTile(side, index) {
        if (!this.isInitialized || !this.config) return null;
        const key = `tiles_${side}`;
        if (!this.config[key]) return null;
        return this.config[key][index];
    }

    /**
     * Získat všechny dlaždice na straně
     */
    getTiles(side) {
        if (!this.isInitialized || !this.config) return [];
        const key = `tiles_${side}`;
        return this.config[key] || [];
    }

    /**
     * Resetovat konfiguraci
     */
    reset() {
        console.log('🔄 Resetting tile config to defaults');
        this.config = this.getDefaultConfig();
        this.saveConfig();
    }

    /**
     * Přidat listener pro změny
     */
    addChangeListener(callback) {
        this.listeners.push(callback);
    }

    /**
     * Odebrat listener
     */
    removeChangeListener(callback) {
        this.listeners = this.listeners.filter(l => l !== callback);
    }

    /**
     * Notifikovat listenery o změně
     */
    notifyListeners() {
        this.listeners.forEach(callback => {
            try {
                callback(this.config);
            } catch (e) {
                console.error('❌ Listener error:', e);
            }
        });
    }

    /**
     * Naplánovat sync do HA (debounced)
     */
    scheduleSyncToHA() {
        // Zrušit předchozí timeout
        if (this.syncTimeout) {
            clearTimeout(this.syncTimeout);
        }

        // Naplánovat sync za 2 sekundy
        this.syncTimeout = setTimeout(() => {
            this.syncToHA();
        }, 2000);
    }

    /**
     * Sync konfigurace do Home Assistant
     */
    async syncToHA() {
        // Try multiple methods to get hass
        const hass = (typeof getHass === 'function' ? getHass() : null) ||
                     window.hass ||
                     this.hass;

        if (!hass) {
            console.warn('⚠️ Cannot sync to HA: hass not available');
            return;
        }

        try {
            console.log('☁️ Syncing config to HA...');

            // Volání služby s celou konfigurací jako JSON string
            await hass.callService('oig_cloud', 'save_dashboard_tiles', {
                config: JSON.stringify(this.config)
            });

            console.log('✅ Config synced to HA successfully');
        } catch (e) {
            console.error('❌ Failed to sync to HA:', e);
        }
    }



    /**
     * Helper: Získat barvu podle domény entity
     */
    getColorFromDomain(entityId) {
        if (!entityId) return '#9E9E9E';

        const domain = entityId.split('.')[0];
        const colors = {
            'sensor': '#03A9F4',
            'binary_sensor': '#FF9800',
            'switch': '#4CAF50',
            'light': '#FFC107',
            'climate': '#2196F3',
            'cover': '#9C27B0',
            'fan': '#00BCD4',
            'media_player': '#E91E63'
        };

        return colors[domain] || '#9E9E9E';
    }

    /**
     * Export konfigurace jako JSON (pro backup)
     */
    export() {
        return JSON.stringify(this.config, null, 2);
    }

    /**
     * Import konfigurace z JSON (pro restore)
     */
    import(jsonString) {
        try {
            const imported = JSON.parse(jsonString);
            if (imported.tiles_left && imported.tiles_right) {
                this.config = imported;
                this.saveConfig();
                console.log('✅ Imported config successfully');
                return true;
            } else {
                console.error('❌ Invalid config format');
                return false;
            }
        } catch (e) {
            console.error('❌ Failed to import config:', e);
            return false;
        }
    }

    /**
     * Nastavit počet dlaždic pro stranu
     */
    setTileCount(side, count) {
        const parsedCount = parseInt(count);
        if (isNaN(parsedCount) || parsedCount < 0 || parsedCount > 6) {  // Max 6 pro 2×3 nebo 3×2 grid
            console.error(`❌ Invalid tile count: ${count}`);
            return;
        }

        const key = `${side}_count`;
        console.log(`🔢 Setting tile count for ${side}: ${parsedCount}`);
        this.config[key] = parsedCount;

        // Pokud snížíme počet, ořežeme pole
        const tilesKey = `tiles_${side}`;
        if (this.config[tilesKey].length > parsedCount) {
            this.config[tilesKey] = this.config[tilesKey].slice(0, parsedCount);
        }

        // Pokud zvýšíme počet, doplníme null
        while (this.config[tilesKey].length < parsedCount) {
            this.config[tilesKey].push(null);
        }

        this.saveConfig();
    }

    /**
     * Získat počet dlaždic pro stranu
     */
    getTileCount(side) {
        const key = `${side}_count`;
        return this.config[key] || 6;
    }

    /**
     * Přepnout viditelnost sekce dlaždic
     */
    toggleVisibility() {
        this.config.visible = !this.config.visible;
        console.log(`👁️ Toggling tiles visibility: ${this.config.visible}`);
        this.saveConfig();
    }

    /**
     * Získat viditelnost sekce
     */
    isVisible() {
        return this.config.visible !== false; // Default true
    }
}

// Export pro použití v ostatních souborech
window.DashboardTileManager = DashboardTileManager;

// Track subscribed entities to avoid duplicate subscriptions
let subscribedEntities = new Set();
let tilesWatchedEntities = new Set();
let tilesWatcherUnsub = null;
let tilesRenderTimeout = null;

async function initCustomTiles() {
    console.log('[Tiles] Initializing custom tiles system...');

    // Initialize tile dialog only if not already initialized
    const hass = getHass();
    if (!hass) {
        console.warn('[Tiles] Cannot initialize - no HA connection, retrying...');
        setTimeout(initCustomTiles, 1000); // Retry
        return;
    }

    // Initialize tile manager (only once)
    if (!tileManager) {
        tileManager = new DashboardTileManager(hass);
        window.tileManager = tileManager; // Export for dialog access

        // Listen for config changes - render ONLY tiles, not whole dashboard
        tileManager.addChangeListener(() => {
            console.log('[Tiles] Config changed, re-rendering tiles only...');
            renderAllTiles(); // Local function - renders only tiles
            updateTileControlsUI();
            subscribeToTileEntities(); // Re-subscribe to new entities
        });

        // ASYNCHRONNĚ načíst konfiguraci z HA storage
        console.log('[Tiles] Loading configuration...');
        await tileManager.init();
        console.log('[Tiles] Configuration loaded');
    }

    // Initialize tile dialog (only once)
    if (!tileDialog) {
        tileDialog = new TileConfigDialog(hass, tileManager);
        window.tileDialog = tileDialog; // Export for onclick handlers
    }

    // Initial render
    renderAllTiles();
    updateTileControlsUI();

    // Subscribe to entity state changes for real-time updates
    subscribeToTileEntities();

    console.log('[Tiles] Initialization complete');
}

/**
 * Subscribe to state changes for all entities used in tiles
 * This enables real-time updates without full page refresh
 */
function subscribeToTileEntities() {
    if (!tileManager) return;

    // Collect all entity IDs from tiles (both sides)
    const allEntityIds = new Set();

    ['left', 'right'].forEach(side => {
        const tiles = tileManager.getTiles(side);
        const count = tileManager.getTileCount(side);

        for (let i = 0; i < count; i++) {
            const tile = tiles[i];
            if (tile && tile.type === 'entity' && tile.entity_id) {
                allEntityIds.add(tile.entity_id);

                // Add support entities if present
                if (tile.support_entities) {
                    Object.values(tile.support_entities).forEach(entityId => {
                        if (entityId) allEntityIds.add(entityId);
                    });
                }
            }
        }
    });

    // Only subscribe to new entities (avoid duplicates)
    const newEntities = [...allEntityIds].filter(id => !subscribedEntities.has(id));

    // Update watched set for the callback
    tilesWatchedEntities = allEntityIds;

    const watcher = window.DashboardStateWatcher;
    if (!watcher) {
        console.warn('[Tiles] StateWatcher not available yet, retrying...');
        setTimeout(subscribeToTileEntities, 500);
        return;
    }

    // Ensure watcher is running (idempotent)
    watcher.start({ intervalMs: 1000, prefixes: [] });

    // Ensure we have a single callback registered, and only update the watched entity set above.
    if (!tilesWatcherUnsub) {
        tilesWatcherUnsub = watcher.onEntityChange((entityId) => {
            if (!tilesWatchedEntities || !tilesWatchedEntities.has(entityId)) return;
            if (tilesRenderTimeout) return;
            tilesRenderTimeout = setTimeout(() => {
                tilesRenderTimeout = null;
                console.log(`[Tiles] Entity ${entityId} changed, updating tiles...`);
                renderAllTiles();
            }, 100);
        });
    }

    if (newEntities.length > 0) {
        console.log(`[Tiles] Watching ${newEntities.length} entity updates:`, newEntities);
        watcher.registerEntities(newEntities);

        // Mark as subscribed
        newEntities.forEach(id => subscribedEntities.add(id));
    }
}

/**
 * Update tile count from UI input
 */
function updateTileCount(side, value) {
    if (!tileManager) {
        console.error('[Tiles] Tile manager not initialized');
        return;
    }

    tileManager.setTileCount(side, value);
}

/**
 * Toggle tiles section visibility
 */
function toggleTilesVisibility() {
    if (!tileManager) {
        console.error('[Tiles] Tile manager not initialized');
        return;
    }

    tileManager.toggleVisibility();

    const section = document.querySelector('.custom-tiles-section');
    if (section) {
        section.style.display = tileManager.isVisible() ? 'block' : 'none';
    }
}

/**
 * Reset all tiles to default
 */
function resetAllTiles() {
    if (!tileManager) {
        console.error('[Tiles] Tile manager not initialized');
        return;
    }

    if (!confirm('Opravdu smazat všechny dlaždice a vrátit nastavení na výchozí?')) {
        return;
    }

    tileManager.reset();

    // Reset UI inputs
    document.getElementById('tiles-left-count').value = 6;
    document.getElementById('tiles-right-count').value = 6;
}

/**
 * Update tile controls UI (inputs visibility toggle button)
 */
function updateTileControlsUI() {
    if (!tileManager) return;

    // Update inputs
    const leftInput = document.getElementById('tiles-left-count');
    const rightInput = document.getElementById('tiles-right-count');

    if (leftInput) {
        leftInput.value = tileManager.getTileCount('left');
    }
    if (rightInput) {
        rightInput.value = tileManager.getTileCount('right');
    }

    // Update visibility
    const section = document.querySelector('.custom-tiles-section');
    if (section) {
        const isVisible = tileManager.isVisible();
        section.style.display = isVisible ? 'block' : 'none';
        console.log(`[Tiles] Section visibility updated: ${isVisible}`);
    }

    // Update toggle button text
    const toggleBtn = document.getElementById('btn-tiles-toggle');
    if (toggleBtn && tileManager.isVisible()) {
        toggleBtn.style.background = 'rgba(76, 175, 80, 0.2)';
        toggleBtn.style.borderColor = 'rgba(76, 175, 80, 0.5)';
    } else if (toggleBtn) {
        toggleBtn.style.background = 'var(--button-bg)';
        toggleBtn.style.borderColor = 'var(--button-border)';
    }
}

/**
 * Render all tiles (both blocks)
 */
function renderAllTiles() {
    renderTilesBlock('left');
    renderTilesBlock('right');
}

function _applyFlipToTileValues(side, index) {
    if (typeof updateElementIfChanged !== 'function') return;

    const ids = [
        `tile-${side}-${index}-value`,
        `tile-${side}-${index}-unit`,
        `tile-${side}-${index}-support-top`,
        `tile-${side}-${index}-support-bottom`,
        `tile-${side}-${index}-button-state`
    ];

    ids.forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        updateElementIfChanged(id, el.textContent, id, false, true);
    });
}

/**
 * Render one tiles block
 * @param {string} side - 'left' or 'right'
 */
function renderTilesBlock(side) {
    const blockElement = document.getElementById(`tiles-${side}`);
    if (!blockElement) {
        console.warn(`[Tiles] Block element not found: tiles-${side}`);
        return;
    }

    const gridElement = blockElement.querySelector('.tiles-grid');
    if (!gridElement) {
        console.warn(`[Tiles] Grid element not found in tiles-${side}`);
        return;
    }

    // Get tile count for this side
    const tileCount = tileManager.getTileCount(side);

    // Hide block if count is 0
    if (tileCount === 0) {
        blockElement.style.display = 'none';
        return;
    } else {
        blockElement.style.display = 'block';
    }

    // Get configuration
    const tiles = tileManager.getTiles(side);

    // Debug log pro diagnostiku
    // console.log(`[Tiles] DEBUG ${side} tiles:`, tiles, 'non-null:', tiles.filter(t => t !== null));

    // Render tiles up to count
    gridElement.innerHTML = '';
    for (let i = 0; i < tileCount; i++) {
        const tileConfig = tiles[i];
        const tileElement = renderTile(side, i, tileConfig);
        gridElement.appendChild(tileElement);
        _applyFlipToTileValues(side, i);
    }

    // console.log(`[Tiles] Rendered ${side} block with ${tileCount} slots (${tiles.filter(t => t !== null).length} configured)`);
}

/**
 * Render single tile
 * @param {string} side - 'left' or 'right'
 * @param {number} index - Tile index (0-5)
 * @param {object|null} config - Tile configuration
 * @returns {HTMLElement} - Tile element
 */
function renderTile(side, index, config) {
    const tile = document.createElement('div');
    tile.className = 'dashboard-tile';
    tile.dataset.side = side;
    tile.dataset.index = index.toString();

    if (!config) {
        // Placeholder tile
        tile.classList.add('tile-placeholder');
        tile.innerHTML = `
            <div class="tile-placeholder-content" onclick="window.tileDialog.open(${index}, '${side}')">
                <div class="tile-placeholder-icon">➕</div>
                <div class="tile-placeholder-text">Přidat dlaždici</div>
            </div>
        `;
    } else if (config.type === 'entity') {
        // Entity tile
        tile.classList.add('tile-entity');
        tile.innerHTML = renderEntityTile(config, side, index);
    } else if (config.type === 'button') {
        // Button tile
        tile.classList.add('tile-button');
        tile.innerHTML = renderButtonTile(config, side, index);
    }

    // Add edit button (visible on hover)
    if (config) {
        const editBtn = document.createElement('button');
        editBtn.className = 'tile-edit';
        editBtn.innerHTML = '⚙️';
        editBtn.title = 'Upravit dlaždici';
        editBtn.onclick = (e) => {
            e.stopPropagation();
            window.tileDialog.open(index, side);
        };
        tile.appendChild(editBtn);
    }

    // Add remove button (visible on hover)
    if (config) {
        const removeBtn = document.createElement('button');
        removeBtn.className = 'tile-remove';
        removeBtn.innerHTML = '✕';
        removeBtn.title = 'Odstranit dlaždici';
        removeBtn.onclick = (e) => {
            e.stopPropagation();
            if (confirm('Opravdu odstranit tuto dlaždici?')) {
                tileManager.removeTile(side, index);
            }
        };
        tile.appendChild(removeBtn);
    }

    return tile;
}

/**
 * Render icon - podporuje emoji i MDI ikony
 * @param {string} icon - Icon string (emoji nebo mdi:xxx)
 * @param {string} color - Icon color
 * @returns {string} - HTML string
 */

// Export all tile functions
window.DashboardTiles = Object.assign(window.DashboardTiles || {}, {
    // Existing TileManager
    DashboardTileManager,
    // Add rendering functions
    initCustomTiles,
    renderAllTiles,
    renderTilesBlock,
    renderTile,
    // renderEntityTile, renderButtonTile, executeTileButtonAction are in dashboard-core.js
    updateTileCount,
    toggleTilesVisibility,
    resetAllTiles,
    updateTileControlsUI
});

console.log('[DashboardTiles] Enhanced with rendering functions');
