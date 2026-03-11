/* eslint-disable */
/**
 * OIG Cloud Dashboard - State Watcher (no extra WebSocket subscriptions)
 *
 * Uses the parent HA frontend's `hass.states` (already kept up to date by HA)
 * and polls only selected entities for `last_updated` changes.
 *
 * This avoids creating additional `subscribeEvents('state_changed')` streams which
 * can overload mobile clients (Safari/iOS) and trigger HA "pending messages" protection.
 */

(function () {
    const callbacks = new Set();
    const watched = new Set();
    const lastUpdated = new Map();

    let timer = null;
    let rescanTimer = null;
    let running = false;

    function _getHassSafe() {
        try {
            return getHass?.() || null;
        } catch (e) {
            return null;
        }
    }

    function registerEntities(entityIds) {
        if (!entityIds) return;
        for (const id of entityIds) {
            if (typeof id === 'string' && id.length > 0) watched.add(id);
        }
    }

    function registerPrefix(prefix) {
        const hass = _getHassSafe();
        if (!hass || !hass.states || typeof prefix !== 'string') return;

        const ids = Object.keys(hass.states);
        const runtime = window.OIG_RUNTIME || {};
        const shouldChunk = !!(runtime.isHaApp || runtime.isMobile || ids.length > 800);

        if (!shouldChunk) {
            registerEntities(ids.filter((eid) => eid.startsWith(prefix)));
            return;
        }

        let index = 0;
        const chunkSize = runtime.isHaApp || runtime.isMobile ? 200 : 400;

        const step = (deadline) => {
            const timeBudget = deadline && typeof deadline.timeRemaining === 'function'
                ? deadline.timeRemaining()
                : 0;
            const useTimeBudget = timeBudget > 0;
            const start = index;
            while (index < ids.length) {
                const id = ids[index];
                if (id.startsWith(prefix)) watched.add(id);
                index += 1;
                if (index - start >= chunkSize) break;
                if (useTimeBudget && deadline.timeRemaining() < 3) break;
            }

            if (index < ids.length) {
                schedule();
            }
        };

        const schedule = () => {
            if (typeof window.requestIdleCallback === 'function') {
                window.requestIdleCallback(step, { timeout: 250 });
            } else {
                setTimeout(step, 16);
            }
        };

        schedule();
    }

    function onEntityChange(cb) {
        if (typeof cb !== 'function') return () => {};
        callbacks.add(cb);
        return () => callbacks.delete(cb);
    }

    function _tick() {
        const hass = _getHassSafe();
        if (!hass || !hass.states) return;

        for (const entityId of watched) {
            const st = hass.states[entityId];
            if (!st) continue;
            const lu = st.last_updated;
            const prev = lastUpdated.get(entityId);
            if (prev === lu) continue;
            lastUpdated.set(entityId, lu);
            for (const cb of callbacks) {
                try {
                    cb(entityId, st);
                } catch (e) {
                    // keep watcher resilient
                }
            }
        }
    }

    function start(options = {}) {
        if (running) return;
        running = true;

        const runtime = window.OIG_RUNTIME || {};
        const baseInterval = Number(options.intervalMs || 1000);
        const intervalMs = (runtime.isHaApp || runtime.isMobile)
            ? Math.max(2000, baseInterval)
            : baseInterval;
        const prefixes = Array.isArray(options.prefixes) ? options.prefixes : [];

        // Initial registration
        prefixes.forEach(registerPrefix);

        // Polling tick
        timer = setInterval(_tick, Math.max(250, intervalMs));

        // Rescan prefixes occasionally (new entities, reloads)
        const rescanInterval = (runtime.isHaApp || runtime.isMobile) ? 60000 : 30000;
        rescanTimer = setInterval(() => {
            prefixes.forEach(registerPrefix);
        }, rescanInterval);

        console.log('[StateWatcher] Started', { intervalMs, prefixes, watched: watched.size });
    }

    function stop() {
        running = false;
        if (timer) clearInterval(timer);
        if (rescanTimer) clearInterval(rescanTimer);
        timer = null;
        rescanTimer = null;
        console.log('[StateWatcher] Stopped');
    }

    window.DashboardStateWatcher = {
        start,
        stop,
        registerEntities,
        registerPrefix,
        onEntityChange,
    };
})();
