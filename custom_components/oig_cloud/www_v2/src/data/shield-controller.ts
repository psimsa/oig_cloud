/**
 * OIG Cloud V2 — Shield Controller
 *
 * Reactive data layer for the shield integration:
 * - Reads service_shield_activity sensor for queue state
 * - Parses running_requests[] and queued_requests[] from sensor attributes
 * - Calls hass services (set_box_mode, set_grid_delivery, set_boiler_mode)
 * - Manages per-button states (active/pending/processing/disabled)
 * - Provides reactive ShieldState for UI components
 *
 * Port of V1 shield.js monitoring + service call logic.
 */

import { getEntityStore } from '@/data/entity-store';
import { haClient } from '@/data/ha-client';
import { stateWatcher } from '@/data/state-watcher';
import { oigLog } from '@/core/logger';
import {
  ShieldState,
  ShieldQueueItem,
  ShieldRequestParams,
  ShieldRequestTarget,
  ShieldServiceType,
  BoxMode,
  GridDelivery,
  BoilerMode,
  BOX_MODE_SENSOR_MAP,
  BOILER_MODE_SENSOR_MAP,
  EMPTY_SHIELD_STATE,
  SupplementaryState,
} from '@/ui/features/control-panel/types';
import {
  GridDeliveryRawValues,
  ShieldPendingData,
  resolveGridDeliveryState,
  resolveGridDeliveryLive,
  isGridDeliveryTransition,
  getGridDeliveryDisplayState,
} from '@/data/grid-delivery-model';

// ============================================================================
// TYPES
// ============================================================================

export type ShieldListener = (state: ShieldState) => void;

// ============================================================================
// SHIELD CONTROLLER
// ============================================================================

export class ShieldController {
  private state: ShieldState = {
    ...EMPTY_SHIELD_STATE,
    pendingServices: new Map(),
    changingServices: new Set(),
  };
  private listeners = new Set<ShieldListener>();
  private watcherUnsub: (() => void) | null = null;
  private queueUpdateInterval: number | null = null;
  private started = false;

  // --------------------------------------------------------------------------
  // Lifecycle
  // --------------------------------------------------------------------------

  start(): void {
    if (this.started) return;
    this.started = true;

    // Subscribe to relevant sensor changes via the state watcher
    this.watcherUnsub = stateWatcher.onEntityChange((entityId, _newState) => {
      if (!entityId) return;
      if (this.shouldRefreshShield(entityId)) {
        this.refresh();
      }
    });

    // Initial read
    this.refresh();

    // Live queue duration updates every second
    this.queueUpdateInterval = window.setInterval(() => {
      if (this.state.allRequests.length > 0) {
        this.notify(); // triggers re-render with updated durations
      }
    }, 1000);

    oigLog.debug('ShieldController started');
  }

  stop(): void {
    this.watcherUnsub?.();
    this.watcherUnsub = null;

    if (this.queueUpdateInterval !== null) {
      clearInterval(this.queueUpdateInterval);
      this.queueUpdateInterval = null;
    }

    this.started = false;
    oigLog.debug('ShieldController stopped');
  }

  // --------------------------------------------------------------------------
  // Subscriptions
  // --------------------------------------------------------------------------

  subscribe(listener: ShieldListener): () => void {
    this.listeners.add(listener);
    // Fire immediately with current state
    listener(this.state);
    return () => this.listeners.delete(listener);
  }

  getState(): ShieldState {
    return this.state;
  }

  // --------------------------------------------------------------------------
  // Sensor matching (from V1 shouldRefreshShield)
  // --------------------------------------------------------------------------

  private shouldRefreshShield(entityId: string): boolean {
    const fragments = [
      'service_shield_',
      'box_prms_mode',
      'boiler_manual_mode',
      'invertor_prms_to_grid',
      'invertor_prm1_p_max_feed_grid',
      'box_mode_extended',
    ];
    return fragments.some((f) => entityId.includes(f));
  }

  // --------------------------------------------------------------------------
  // State refresh — reads all shield sensors
  // --------------------------------------------------------------------------

  refresh(): void {
    const store = getEntityStore();
    if (!store) return;

    try {
      // --- Shield activity sensor (handles _2, _3 suffixes) ---
      const activitySensorId = store.findSensorId('service_shield_activity');
      const activityEntity = store.get(activitySensorId);
      const attrs = (activityEntity?.attributes ?? {}) as Record<string, any>;
      const rawRunning: any[] = attrs.running_requests ?? [];
      const rawQueued: any[] = attrs.queued_requests ?? [];

      // --- Shield status/queue sensors ---
      const statusSensorId = store.findSensorId('service_shield_status');
      const queueSensorId = store.findSensorId('service_shield_queue');
      const statusStr = store.getString(statusSensorId).value;
      const queueCount = store.getNumeric(queueSensorId).value;

      // --- Current actual values ---
      const boxModeRaw = store.getString(store.findSensorId('box_prms_mode')).value;
      const gridModeRaw = store.getString(store.findSensorId('invertor_prms_to_grid')).value;
      const gridLimit = store.getNumeric(store.findSensorId('invertor_prm1_p_max_feed_grid')).value;
      const boilerModeRaw = store.getString(store.findSensorId('boiler_manual_mode')).value;

      // Normalize current values
      const currentBoxMode = BOX_MODE_SENSOR_MAP[boxModeRaw.trim()] ?? 'home_1';
      const currentBoilerMode = BOILER_MODE_SENSOR_MAP[boilerModeRaw.trim()] ?? 'cbb';

      // Parse requests
      const runningRequests = rawRunning.map((r, i) => this.parseRequest(r, i, true));
      const queuedRequests = rawQueued.map((r, i) => this.parseRequest(r, i + rawRunning.length, false));
      const allRequests = [...runningRequests, ...queuedRequests];

      // Compute pending services from active requests
      const pendingServices = new Map<ShieldServiceType, string>();
      const changingServices = new Set<ShieldServiceType>();

      for (const req of allRequests) {
        const parsed = this.parseServiceRequest(req);
        if (parsed && !pendingServices.has(parsed.type)) {
          pendingServices.set(parsed.type, parsed.targetValue);
          changingServices.add(parsed.type);
        }
      }

      const isRunning = statusStr === 'Running' || statusStr === 'running';

      const shieldPending: ShieldPendingData = {
        pendingServices,
        changingServices,
        shieldStatus: isRunning ? 'running' : 'idle',
      };
      const rawValues: GridDeliveryRawValues = {
        gridModeRaw,
        gridLimit,
      };
      const gridDeliveryState = resolveGridDeliveryState(rawValues, shieldPending);

      const currentGridDelivery: GridDelivery =
        (isGridDeliveryTransition(gridModeRaw) || gridDeliveryState.currentLiveDelivery === 'unknown')
          ? this.state.currentGridDelivery
          : gridDeliveryState.currentLiveDelivery;

      const extendedSensorId = store.findSensorId('box_mode_extended');
      const extendedEntity = store.get(extendedSensorId);
      const extAttrs = (extendedEntity?.attributes ?? {}) as Record<string, unknown>;
      const supplementary: SupplementaryState = {
        home_grid_v: Boolean(extAttrs['home_grid_v']),
        home_grid_vi: Boolean(extAttrs['home_grid_vi']),
        flexibilita: Boolean(extAttrs['flexibilita']),
        available: extendedEntity != null && extendedEntity.state !== 'unavailable' && extendedEntity.state !== 'unknown',
      };

      this.state = {
        status: isRunning ? 'running' : 'idle',
        activity: activityEntity?.state ?? '',
        queueCount,
        runningRequests,
        queuedRequests,
        allRequests,
        currentBoxMode,
        currentGridDelivery,
        currentGridLimit: gridDeliveryState.currentLiveLimit ?? 0,
        currentBoilerMode,
        pendingServices,
        changingServices,
        gridDeliveryState,
        supplementary,
      };

      this.notify();
    } catch (e) {
      oigLog.error('ShieldController refresh failed', e as Error);
    }
  }

  // --------------------------------------------------------------------------
  // Request parsing (from V1 shield.js)
  // --------------------------------------------------------------------------

  private parseRequest(raw: any, index: number, isRunning: boolean): ShieldQueueItem {
    const safeRaw = raw || {};
    const service = safeRaw.service ?? '';
    const rawChanges = Array.isArray(safeRaw.changes) ? safeRaw.changes : [];
    const changes = rawChanges.map((c: unknown) => (typeof c === 'string' ? c : String(c ?? ''))).filter((c: string) => c.length > 0);
    const timestamp = safeRaw.started_at ?? safeRaw.queued_at ?? safeRaw.created_at ?? safeRaw.timestamp ?? safeRaw.created ?? '';
    const targets = Array.isArray(safeRaw.targets)
      ? safeRaw.targets.map((target: any): ShieldRequestTarget => ({
        param: String(target?.param ?? ''),
        value: String(target?.value ?? target?.to ?? ''),
        entityId: String(target?.entity_id ?? target?.entityId ?? ''),
        from: String(target?.from ?? ''),
        to: String(target?.to ?? target?.value ?? ''),
        current: String(target?.current ?? ''),
      }))
      : [];
    const params = this.extractRequestParams(safeRaw.params);
    const gridDeliveryStep = this.extractGridDeliveryStep(safeRaw, params);
    const targetValue = this.resolveRequestTargetValue(safeRaw, targets, params, gridDeliveryStep);

    let type: ShieldQueueItem['type'] = 'mode_change';
    if (service.includes('set_box_mode')) type = 'mode_change';
    else if (service.includes('set_grid_delivery') && !service.includes('limit')) type = 'grid_delivery';
    else if (service.includes('grid_delivery_limit') || service.includes('set_grid_delivery')) type = 'grid_limit';
    else if (service.includes('set_boiler_mode')) type = 'boiler_mode';
    else if (service.includes('set_formating_mode')) type = 'battery_formating';

    return {
      id: `${service}_${index}_${timestamp}`,
      type,
      status: isRunning ? 'running' : 'queued',
      service,
      targetValue,
      changes,
      createdAt: timestamp,
      position: index + 1,
      description: typeof safeRaw.description === 'string' ? safeRaw.description : undefined,
      params,
      targets,
      traceId: typeof safeRaw.trace_id === 'string' ? safeRaw.trace_id : undefined,
      gridDeliveryStep,
    };
  }

  private parseServiceRequest(req: ShieldQueueItem): { type: ShieldServiceType; targetValue: string } | null {
    const service = req.service;
    if (!service) return null;

    const changeStr = req.changes.length > 0 ? req.changes[0] : '';
    const params = req.params;
    const gridDeliveryStep = req.gridDeliveryStep;
    const structuredTarget = this.extractStructuredTarget(req);

    if (service.includes('set_grid_delivery') && structuredTarget) {
      return structuredTarget;
    }

    if (service.includes('set_grid_delivery') && changeStr.includes('p_max_feed_grid')) {
      const numericMatch = changeStr.match(/→\s*'?(\d+)'?/);
      const limitValue = numericMatch ? numericMatch[1] : req.targetValue;
      return limitValue ? { type: 'grid_limit', targetValue: limitValue } : null;
    }

    const arrowMatch = changeStr.match(/→\s*'([^']+)'/);
    const target = arrowMatch ? arrowMatch[1] : (req.targetValue || '');

    if (service.includes('set_box_mode')) {
      return { type: 'box_mode', targetValue: target };
    }
    if (service.includes('set_boiler_mode')) {
      return { type: 'boiler_mode', targetValue: target };
    }
    if (service.includes('set_grid_delivery') && changeStr.includes('prms_to_grid')) {
      return { type: 'grid_mode', targetValue: target };
    }
    if (service.includes('set_grid_delivery')) {
      if (gridDeliveryStep === 'limit') {
        const limitValue = this.normalizeNumericTargetValue(params?.limit ?? req.targetValue);
        return limitValue ? { type: 'grid_limit', targetValue: limitValue } : null;
      }
      if (gridDeliveryStep === 'mode') {
        const modeValue = this.normalizeModeTargetValue(params?.mode ?? req.targetValue);
        return modeValue ? { type: 'grid_mode', targetValue: modeValue } : null;
      }

      const numericMatch = changeStr.match(/→\s*'?(\d+)'?/);
      if (numericMatch) {
        return { type: 'grid_limit', targetValue: numericMatch[1] };
      }
      if (req.targetValue && /^\d+$/.test(req.targetValue.trim())) {
        return { type: 'grid_limit', targetValue: req.targetValue };
      }
      return { type: 'grid_mode', targetValue: target };
    }

    return null;
  }

  private extractRequestParams(rawParams: unknown): ShieldRequestParams | undefined {
    if (!rawParams || typeof rawParams !== 'object' || Array.isArray(rawParams)) {
      return undefined;
    }
    return rawParams as ShieldRequestParams;
  }

  private extractGridDeliveryStep(raw: any, params?: ShieldRequestParams): string | undefined {
    const step = raw?.grid_delivery_step ?? params?._grid_delivery_step;
    return typeof step === 'string' ? step : undefined;
  }

  private resolveRequestTargetValue(
    raw: any,
    targets: ShieldRequestTarget[],
    params: ShieldRequestParams | undefined,
    gridDeliveryStep: string | undefined,
  ): string {
    const structuredTarget = this.extractStructuredTarget({
      service: raw?.service ?? '',
      targetValue: '',
      params,
      targets,
      gridDeliveryStep,
    });
    if (structuredTarget?.targetValue) {
      return structuredTarget.targetValue;
    }
    const directTarget = raw.target_value ?? raw.target_display;
    return typeof directTarget === 'string' ? directTarget : '';
  }

  private extractStructuredTarget(req: Pick<ShieldQueueItem, 'service' | 'params' | 'targets' | 'gridDeliveryStep' | 'targetValue'>):
    { type: ShieldServiceType; targetValue: string } | null {
    if (!req.service.includes('set_grid_delivery')) {
      return null;
    }

    const gridDeliveryStep = req.gridDeliveryStep;
    const params = req.params;
    const targets = req.targets ?? [];

    if (gridDeliveryStep === 'limit') {
      const limitTarget = this.findTargetValue(targets, ['limit']);
      const limitValue = this.normalizeNumericTargetValue(limitTarget ?? params?.limit ?? req.targetValue);
      return limitValue ? { type: 'grid_limit', targetValue: limitValue } : null;
    }

    if (gridDeliveryStep === 'mode') {
      const modeTarget = this.findTargetValue(targets, ['mode']);
      const modeValue = this.normalizeModeTargetValue(modeTarget ?? params?.mode ?? req.targetValue);
      return modeValue ? { type: 'grid_mode', targetValue: modeValue } : null;
    }

    const limitTarget = this.findTargetValue(targets, ['limit']);
    if (limitTarget) {
      const limitValue = this.normalizeNumericTargetValue(limitTarget);
      if (limitValue) {
        return { type: 'grid_limit', targetValue: limitValue };
      }
    }

    const modeTarget = this.findTargetValue(targets, ['mode']);
    if (modeTarget) {
      const modeValue = this.normalizeModeTargetValue(modeTarget);
      if (modeValue) {
        return { type: 'grid_mode', targetValue: modeValue };
      }
    }

    return null;
  }

  private findTargetValue(targets: ShieldRequestTarget[], params: string[]): string | undefined {
    const wanted = new Set(params);
    const target = targets.find((item) => wanted.has(item.param));
    return target?.to || target?.value || undefined;
  }

  private normalizeNumericTargetValue(value: unknown): string {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return String(Math.round(value));
    }
    if (typeof value !== 'string') {
      return '';
    }
    const match = value.trim().match(/(\d+)/);
    return match ? match[1] : '';
  }

  private normalizeModeTargetValue(value: unknown): string {
    if (typeof value !== 'string') {
      return '';
    }
    const trimmed = value.trim();
    switch (trimmed.toLowerCase()) {
      case 'off':
        return 'Vypnuto';
      case 'on':
        return 'Zapnuto';
      case 'limited':
        return 'Omezeno';
      default:
        return trimmed;
    }
  }

  private isLimitedGridDeliveryActiveOrPending(): boolean {
    const state = this.state.gridDeliveryState;

    if (state.pendingDeliveryTarget === 'limited') {
      return true;
    }

    if (state.pendingLimitTarget !== null) {
      return true;
    }

    if (state.currentLiveDelivery === 'limited') {
      return true;
    }

    if (state.currentLiveDelivery === 'unknown') {
      const displayState = getGridDeliveryDisplayState(state);
      if (displayState === 'limited') {
        return true;
      }
      if (this.state.currentGridDelivery === 'limited') {
        return true;
      }
    }

    const store = getEntityStore();
    if (store) {
      const rawGridMode = store.getString(store.findSensorId('invertor_prms_to_grid')).value;
      if (!isGridDeliveryTransition(rawGridMode)) {
        const resolved = resolveGridDeliveryLive(rawGridMode);
        if (resolved === 'limited') {
          return true;
        }
      }
    }

    return false;
  }

  private needsGridModeChangeForLimitedRequest(): boolean {
    return !this.isLimitedGridDeliveryActiveOrPending();
  }

  // --------------------------------------------------------------------------
  // Button state helpers (for use by selector components)
  // --------------------------------------------------------------------------

  getBoxModeButtonState(mode: BoxMode): 'active' | 'pending' | 'processing' | 'disabled-by-service' | 'idle' {
    const pendingTarget = this.state.pendingServices.get('box_mode');
    if (pendingTarget) {
      const pendingMode = BOX_MODE_SENSOR_MAP[pendingTarget];
      if (pendingMode === mode) {
        return this.state.status === 'running' ? 'processing' : 'pending';
      }
      return 'disabled-by-service';
    }
    return this.state.currentBoxMode === mode ? 'active' : 'idle';
  }

  /**
   * Get button state for grid delivery using explicit live+pending fields.
   * @deprecated Use getGridDeliveryButtonStateV2 which accepts explicit state model
   */
  getGridDeliveryButtonState(delivery: GridDelivery): 'active' | 'pending' | 'processing' | 'disabled-by-service' | 'idle' {
    return this.getGridDeliveryButtonStateV2(delivery);
  }

  private getGridDeliveryButtonStateV2(delivery: GridDelivery): 'active' | 'pending' | 'processing' | 'disabled-by-service' | 'idle' {
    const state = this.state.gridDeliveryState;
    const isRunning = this.state.status === 'running';
    const transitionState = isRunning ? 'processing' : 'pending';

    const pendingDelivery = state.pendingDeliveryTarget;
    const pendingLimit = state.pendingLimitTarget;
    const liveDelivery = state.currentLiveDelivery;

    if (pendingDelivery !== null) {
      if (pendingDelivery === delivery) {
        return transitionState;
      }

      if (delivery === 'limited' && liveDelivery === 'limited') {
        return 'active';
      }

      if (delivery === 'limited' && liveDelivery === 'unknown' && this.state.currentGridDelivery === 'limited') {
        return 'active';
      }

      return 'disabled-by-service';
    }

    if (pendingLimit !== null) {
      if (delivery === 'limited') {
        return transitionState;
      }
      return 'disabled-by-service';
    }

    return liveDelivery === delivery ? 'active' : 'idle';
  }

  getBoilerModeButtonState(mode: BoilerMode): 'active' | 'pending' | 'processing' | 'disabled-by-service' | 'idle' {
    const pendingTarget = this.state.pendingServices.get('boiler_mode');
    if (pendingTarget) {
      const pendingMode = BOILER_MODE_SENSOR_MAP[pendingTarget];
      if (pendingMode === mode) {
        return this.state.status === 'running' ? 'processing' : 'pending';
      }
      return 'disabled-by-service';
    }
    return this.state.currentBoilerMode === mode ? 'active' : 'idle';
  }

  isAnyServiceChanging(): boolean {
    return this.state.changingServices.size > 0;
  }

  // --------------------------------------------------------------------------
  // Service calls — with queue warning check
  // --------------------------------------------------------------------------

  /**
   * Check if queue has >=3 items and optionally warn the user.
   * Returns true if we should proceed.
   */
  shouldProceedWithQueue(): boolean {
    if (this.state.queueCount < 3) return true;
    return window.confirm(
      `\u26A0\uFE0F VAROV\u00C1N\u00CD: Fronta ji\u017E obsahuje ${this.state.queueCount} \u00FAkol\u016F!\n\n` +
      `Ka\u017Ed\u00E1 zm\u011Bna m\u016F\u017Ee trvat a\u017E 10 minut.\n` +
      `Opravdu chcete p\u0159idat dal\u0161\u00ED \u00FAkol?`
    );
  }

  /** Set box mode via HA service */
  async setBoxMode(mode: BoxMode): Promise<boolean> {
    // Check if already active
    if (this.state.currentBoxMode === mode && !this.state.changingServices.has('box_mode')) {
      return false;
    }

    const success = await haClient.callService('oig_cloud', 'set_box_mode', {
      mode: mode,
      acknowledgement: true,
    });

    if (success) {
      this.refresh();
    }
    return success;
  }

  /** Set grid delivery via HA service */
  async setGridDelivery(delivery: GridDelivery, limit?: number): Promise<boolean> {
    const data: Record<string, any> = {
      acknowledgement: true,
      warning: true,
    };

    // If limited with a limit value, send both mode + limit
    if (delivery === 'limited' && limit != null) {
      if (this.needsGridModeChangeForLimitedRequest()) {
        data.mode = delivery;
      }
      data.limit = limit;
    } else if (limit != null) {
      // Only changing limit (grid delivery is already limited)
      data.limit = limit;
    } else {
      data.mode = delivery;
    }

    const success = await haClient.callService('oig_cloud', 'set_grid_delivery', data);

    if (success) {
      this.refresh();
    }
    return success;
  }

  /** Set boiler mode via HA service */
  async setBoilerMode(mode: BoilerMode): Promise<boolean> {
    // Check if already active
    if (this.state.currentBoilerMode === mode && !this.state.changingServices.has('boiler_mode')) {
      return false;
    }

    const success = await haClient.callService('oig_cloud', 'set_boiler_mode', {
      mode: mode,
      acknowledgement: true,
    });

    if (success) {
      this.refresh();
    }
    return success;
  }

  /** Toggle supplementary mode (home_grid_v / home_grid_vi) via set_box_mode — no mode param */
  async toggleSupplementary(field: 'home_grid_v' | 'home_grid_vi', value: boolean): Promise<boolean> {
    const success = await haClient.callService('oig_cloud', 'set_box_mode', {
      [field]: value,
      acknowledgement: true,
    });

    if (success) {
      this.refresh();
    }
    return success;
  }

  /** Remove item from shield queue by position */
  async removeFromQueue(position: number): Promise<boolean> {
    const success = await haClient.callService('oig_cloud', 'shield_remove_from_queue', {
      position,
    });

    if (success) {
      this.refresh();
    }
    return success;
  }

  // --------------------------------------------------------------------------
  // Internal
  // --------------------------------------------------------------------------

  private notify(): void {
    for (const listener of this.listeners) {
      try {
        listener(this.state);
      } catch (e) {
        oigLog.error('ShieldController listener error', e as Error);
      }
    }
  }
}

// ============================================================================
// SINGLETON
// ============================================================================

export const shieldController = new ShieldController();
