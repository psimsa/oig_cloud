/* eslint-disable */
/**
 * OIG Cloud Dashboard - Layout Customization System
 *
 * Drag & drop system pro přizpůsobení pozic energy flow nodes.
 * Podporuje responsive breakpoints (mobile/tablet/desktop).
 * Extrahováno z monolitického dashboard-core.js
 *
 * @module dashboard-layout
 * @version 1.0.0
 * @date 2025-11-02
 */

// ============================================================================
// STATE
// ============================================================================

var editMode = false;
var currentBreakpoint = null;
var draggedNode = null;
var dragStartX = 0;
var dragStartY = 0;
var dragStartTop = 0;
var dragStartLeft = 0;
var resizeTimer = null;
var lastResizeWidth = null;
var lastResizeHeight = null;

// Callbacks pro redraw (registruje core)
var onLayoutChangeCallback = null;

// ============================================================================
// BREAKPOINT DETECTION
// ============================================================================

/**
 * Detekce současného breakpointu
 * @returns {string} 'mobile' | 'tablet' | 'desktop'
 */
function getCurrentBreakpoint() {
    const width = window.innerWidth;
    if (width <= 768) return 'mobile';
    if (width <= 1024) return 'tablet';
    return 'desktop';
}

// ============================================================================
// LAYOUT PERSISTENCE
// ============================================================================

/**
 * Uloží layout pro breakpoint do localStorage
 * @param {string} breakpoint - Breakpoint name
 * @param {object} positions - Node positions
 */
function saveLayout(breakpoint, positions) {
    const key = `oig-layout-${breakpoint}`;
    localStorage.setItem(key, JSON.stringify(positions));
    console.log(`[Layout] Saved ${breakpoint}:`, positions);
}

/**
 * Načte layout pro breakpoint z localStorage
 * @param {string} breakpoint - Breakpoint name
 * @returns {boolean} True pokud byl layout načten
 */
function loadLayout(breakpoint) {
    const key = `oig-layout-${breakpoint}`;
    const saved = localStorage.getItem(key);

    if (saved) {
        try {
            const positions = JSON.parse(saved);
            console.log(`[Layout] Loading ${breakpoint}:`, positions);
            applyCustomPositions(positions);
            return true;
        } catch (e) {
            console.error(`[Layout] Parse error for ${breakpoint}:`, e);
            return false;
        }
    }
    return false;
}

/**
 * Aplikuje custom pozice na nodes
 * @param {object} positions - Node positions
 */
function applyCustomPositions(positions) {
    const nodes = ['solar', 'grid-node', 'battery', 'house', 'inverter'];

    nodes.forEach(nodeClass => {
        const node = document.querySelector(`.${nodeClass}`);
        if (!node || !positions[nodeClass]) return;

        const pos = positions[nodeClass];
        if (pos.top !== undefined) node.style.top = pos.top;
        if (pos.left !== undefined) node.style.left = pos.left;
        if (pos.right !== undefined) node.style.right = pos.right;
        if (pos.bottom !== undefined) node.style.bottom = pos.bottom;
        if (pos.transform !== undefined) node.style.transform = pos.transform;
    });

    // Notify callback
    if (onLayoutChangeCallback) {
        onLayoutChangeCallback();
    }
}

/**
 * Reset layoutu pro breakpoint
 * @param {string} breakpoint - Breakpoint name
 */
function resetLayout(breakpoint) {
    const key = `oig-layout-${breakpoint}`;
    localStorage.removeItem(key);
    console.log(`[Layout] Reset ${breakpoint}`);

    // Odstranit inline styles
    const nodes = document.querySelectorAll('.solar, .grid-node, .battery, .house, .inverter');
    nodes.forEach(node => {
        node.style.top = '';
        node.style.left = '';
        node.style.right = '';
        node.style.bottom = '';
        node.style.transform = '';
    });

    // Notify callback
    if (onLayoutChangeCallback) {
        onLayoutChangeCallback();
    }
}

// ============================================================================
// EDIT MODE
// ============================================================================

/**
 * Toggle edit mode (drag & drop)
 * @returns {boolean} Nový stav edit mode
 */
function toggleEditMode() {
    editMode = !editMode;
    const canvas = document.querySelector('.flow-canvas');
    const btn = document.getElementById('edit-layout-btn');

    if (editMode) {
        canvas?.classList.add('edit-mode');
        btn?.classList.add('active');
        console.log('[Layout] Edit mode ON');
        initializeDragAndDrop();
    } else {
        canvas?.classList.remove('edit-mode');
        btn?.classList.remove('active');
        console.log('[Layout] Edit mode OFF');
    }

    return editMode;
}

/**
 * Vrací současný stav edit mode
 * @returns {boolean} Edit mode state
 */
function isEditMode() {
    return editMode;
}

// ============================================================================
// DRAG & DROP
// ============================================================================

/**
 * Inicializace drag & drop event listenerů
 */
function initializeDragAndDrop() {
    const nodes = document.querySelectorAll('.solar, .grid-node, .battery, .house, .inverter');

    nodes.forEach(node => {
        // Mouse events
        node.addEventListener('mousedown', handleDragStart);
        // Touch events
        node.addEventListener('touchstart', handleTouchStart, { passive: false });
    });

    // Global handlers (již by měly být registrovány, ale pro jistotu)
    document.removeEventListener('mousemove', handleDragMove);
    document.removeEventListener('mouseup', handleDragEnd);
    document.removeEventListener('touchmove', handleTouchMove);
    document.removeEventListener('touchend', handleTouchEnd);

    document.addEventListener('mousemove', handleDragMove);
    document.addEventListener('mouseup', handleDragEnd);
    document.addEventListener('touchmove', handleTouchMove, { passive: false });
    document.addEventListener('touchend', handleTouchEnd);
}

// --- MOUSE HANDLERS ---

function handleDragStart(e) {
    if (!editMode) return;
    e.preventDefault();

    draggedNode = e.target.closest('.node');
    if (!draggedNode) return;

    draggedNode.classList.add('dragging');

    const rect = draggedNode.getBoundingClientRect();
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    dragStartTop = rect.top;
    dragStartLeft = rect.left;

    console.log('[Drag] Start:', draggedNode.className);
}

function handleDragMove(e) {
    if (!draggedNode || !editMode) return;
    e.preventDefault();

    updateNodePosition(e.clientX, e.clientY);

    // Live update
    if (onLayoutChangeCallback) {
        onLayoutChangeCallback();
    }
}

function handleDragEnd(e) {
    if (!draggedNode || !editMode) return;
    e.preventDefault();

    draggedNode.classList.remove('dragging');
    saveCurrentLayout();

    // Final update
    if (onLayoutChangeCallback) {
        onLayoutChangeCallback();
    }

    console.log('[Drag] End');
    draggedNode = null;
}

// --- TOUCH HANDLERS ---

function handleTouchStart(e) {
    if (!editMode) return;
    e.preventDefault();

    draggedNode = e.target.closest('.node');
    if (!draggedNode) return;

    draggedNode.classList.add('dragging');

    const touch = e.touches[0];
    const rect = draggedNode.getBoundingClientRect();

    dragStartX = touch.clientX;
    dragStartY = touch.clientY;
    dragStartTop = rect.top;
    dragStartLeft = rect.left;

    console.log('[Touch] Start:', draggedNode.className);
}

function handleTouchMove(e) {
    if (!draggedNode || !editMode) return;
    e.preventDefault();

    const touch = e.touches[0];
    updateNodePosition(touch.clientX, touch.clientY);

    // Live update
    if (onLayoutChangeCallback) {
        onLayoutChangeCallback();
    }
}

function handleTouchEnd(e) {
    if (!draggedNode || !editMode) return;
    e.preventDefault();

    draggedNode.classList.remove('dragging');
    saveCurrentLayout();

    // Final update
    if (onLayoutChangeCallback) {
        onLayoutChangeCallback();
    }

    console.log('[Touch] End');
    draggedNode = null;
}

// --- POSITION CALCULATION ---

function updateNodePosition(clientX, clientY) {
    if (!draggedNode) return;

    const canvas = document.querySelector('.flow-canvas');
    if (!canvas) return;

    const canvasRect = canvas.getBoundingClientRect();
    const nodeRect = draggedNode.getBoundingClientRect();

    const deltaX = clientX - dragStartX;
    const deltaY = clientY - dragStartY;

    const newLeft = dragStartLeft + deltaX;
    const newTop = dragStartTop + deltaY;

    // Constraints - keep within canvas
    const minLeft = canvasRect.left;
    const maxLeft = canvasRect.right - nodeRect.width;
    const minTop = canvasRect.top;
    const maxTop = canvasRect.bottom - nodeRect.height;

    const constrainedLeft = Math.max(minLeft, Math.min(maxLeft, newLeft));
    const constrainedTop = Math.max(minTop, Math.min(maxTop, newTop));

    // Relativní pozice (%)
    const relativeLeft = ((constrainedLeft - canvasRect.left) / canvasRect.width) * 100;
    const relativeTop = ((constrainedTop - canvasRect.top) / canvasRect.height) * 100;

    draggedNode.style.left = `${relativeLeft}%`;
    draggedNode.style.top = `${relativeTop}%`;
    draggedNode.style.right = 'auto';
    draggedNode.style.bottom = 'auto';
    draggedNode.style.transform = 'none';
}

// --- LAYOUT SAVE ---

function saveCurrentLayout() {
    const breakpoint = getCurrentBreakpoint();
    const canvas = document.querySelector('.flow-canvas');
    if (!canvas) return;

    const canvasRect = canvas.getBoundingClientRect();
    const positions = {};

    const nodes = {
        'solar': document.querySelector('.solar'),
        'grid-node': document.querySelector('.grid-node'),
        'battery': document.querySelector('.battery'),
        'house': document.querySelector('.house'),
        'inverter': document.querySelector('.inverter')
    };

    Object.entries(nodes).forEach(([key, node]) => {
        if (!node) return;

        const rect = node.getBoundingClientRect();
        const relativeLeft = ((rect.left - canvasRect.left) / canvasRect.width) * 100;
        const relativeTop = ((rect.top - canvasRect.top) / canvasRect.height) * 100;

        positions[key] = {
            top: `${relativeTop}%`,
            left: `${relativeLeft}%`,
            right: 'auto',
            bottom: 'auto',
            transform: 'none'
        };
    });

    saveLayout(breakpoint, positions);
}

// ============================================================================
// RESIZE HANDLING
// ============================================================================

/**
 * Resize handler s debouncing
 */
function handleLayoutResize() {
    if (resizeTimer) clearTimeout(resizeTimer);

    resizeTimer = setTimeout(() => {
        // Mobile WebViews (incl. HA app) fire frequent resize events when the browser chrome
        // shows/hides; ignore height-only micro-resizes to avoid infinite redraw loops.
        const w = window.innerWidth;
        const h = window.innerHeight;
        const widthChanged = lastResizeWidth === null ? true : Math.abs(w - lastResizeWidth) >= 24;
        const heightChanged = lastResizeHeight === null ? true : Math.abs(h - lastResizeHeight) >= 180;
        lastResizeWidth = w;
        lastResizeHeight = h;

        const newBreakpoint = getCurrentBreakpoint();
        const breakpointChanged = newBreakpoint !== currentBreakpoint;

        if (breakpointChanged) {
            console.log(`[Layout] Breakpoint: ${currentBreakpoint} → ${newBreakpoint}`);
            currentBreakpoint = newBreakpoint;

            const loaded = loadLayout(newBreakpoint);
            if (!loaded) {
                console.log(`[Layout] No custom ${newBreakpoint} layout`);
            }
        }

        // Notify only on meaningful resizes (breakpoint change, width change, or major height change e.g. rotation).
        if (onLayoutChangeCallback && (breakpointChanged || widthChanged || heightChanged)) {
            onLayoutChangeCallback();
        }
    }, 300);
}

// ============================================================================
// INITIALIZATION
// ============================================================================

/**
 * Inicializace layout systému
 * @param {Function} changeCallback - Callback volaný při změně layoutu
 */
function initLayout(changeCallback) {
    onLayoutChangeCallback = changeCallback;

    // Detekce breakpointu
    currentBreakpoint = getCurrentBreakpoint();
    console.log(`[Layout] Init - breakpoint: ${currentBreakpoint}`);

    // Načíst uložený layout
    loadLayout(currentBreakpoint);

    // Resize listener
    window.addEventListener('resize', handleLayoutResize);

    console.log('[Layout] Initialized');
}

/**
 * Cleanup
 */
function destroyLayout() {
    window.removeEventListener('resize', handleLayoutResize);
    document.removeEventListener('mousemove', handleDragMove);
    document.removeEventListener('mouseup', handleDragEnd);
    document.removeEventListener('touchmove', handleTouchMove);
    document.removeEventListener('touchend', handleTouchEnd);

    onLayoutChangeCallback = null;
    console.log('[Layout] Destroyed');
}

// ============================================================================
// EXPORT DEFAULT (backward compatibility)
// ============================================================================

if (typeof window !== 'undefined') {
    window.DashboardLayout = {
        initLayout,
        destroyLayout,
        getCurrentBreakpoint,
        saveLayout,
        loadLayout,
        resetLayout,
        toggleEditMode,
        isEditMode,
        handleLayoutResize
    };
}
