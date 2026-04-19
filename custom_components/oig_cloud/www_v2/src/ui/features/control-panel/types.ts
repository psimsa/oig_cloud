/**
 * OIG Cloud V2 — Control Panel Types
 *
 * Complete type system for shield integration, box/grid/boiler mode control,
 * queue management, and confirmation dialogs.
 *
 * Port of V1 shield.js type structures.
 */

import type { GridDeliveryStateModel } from '@/data/grid-delivery-model';

// ============================================================================
// BOX MODE
// ============================================================================

export type BoxMode = 'home_1' | 'home_2' | 'home_3' | 'home_ups';

export const BOX_MODE_LABELS: Record<BoxMode, string> = {
  home_1: 'Home 1',
  home_2: 'Home 2',
  home_3: 'Home 3',
  home_ups: 'Home UPS',
};
/** V1 sensor value → BoxMode mapping */
export const BOX_MODE_SENSOR_MAP: Record<string, BoxMode> = {
  'Home 1': 'home_1',
  'Home 2': 'home_2',
  'Home 3': 'home_3',
  'Home UPS': 'home_ups',
  'Mode 0': 'home_1',
  'Mode 1': 'home_2',
  'Mode 2': 'home_3',
  'Mode 3': 'home_ups',
  'HOME I': 'home_1',
  'HOME II': 'home_2',
  'HOME III': 'home_3',
  'HOME UPS': 'home_ups',
  '0': 'home_1',
  '1': 'home_2',
  '2': 'home_3',
  '3': 'home_ups',
};

export const BOX_MODE_SERVICE_MAP: Record<BoxMode, BoxMode> = {
  home_1: 'home_1',
  home_2: 'home_2',
  home_3: 'home_3',
  home_ups: 'home_ups',
};
// ============================================================================
// GRID DELIVERY
// ============================================================================

export type GridDelivery = 'off' | 'on' | 'limited';

export const GRID_DELIVERY_LABELS: Record<GridDelivery, string> = {
  off: 'Vypnuto',
  on: 'Zapnuto',
  limited: 'S omezením',
};

export const GRID_DELIVERY_SERVICE_MAP: Record<GridDelivery, GridDelivery> = {
  off: 'off',
  on: 'on',
  limited: 'limited',
};

export const GRID_DELIVERY_SENSOR_MAP: Record<string, GridDelivery> = {
  'Vypnuto': 'off',
  'Zapnuto': 'on',
  'Omezeno': 'limited',
  'omezeno': 'limited',
  'vypnuto': 'off',
  'zapnuto': 'on',
  'Off': 'off',
  'On': 'on',
  'Limited': 'limited',
  'off': 'off',
  'on': 'on',
  'limited': 'limited',
  '0': 'off',
  '1': 'on',
  '2': 'limited',
};

/**
 * @deprecated Use resolveGridDeliveryLive from data/grid-delivery-model which returns 'unknown'
 * for genuinely unresolvable input instead of silently coercing to 'off'.
 * Kept for legacy test coverage only — not used in production code paths.
 */
export function resolveGridDelivery(raw: string): GridDelivery {
  const trimmed = raw.trim();
  if (trimmed in GRID_DELIVERY_SENSOR_MAP) {
    return GRID_DELIVERY_SENSOR_MAP[trimmed];
  }
  const lower = trimmed.toLowerCase();
  const ciEntry = Object.entries(GRID_DELIVERY_SENSOR_MAP).find(
    ([k]) => k.toLowerCase() === lower,
  );
  if (ciEntry) return ciEntry[1];
  if (lower.startsWith('omez') || lower.includes('limit')) return 'limited';
  if (lower.startsWith('zapn') || lower === 'on') return 'on';
  if (lower.startsWith('vypn') || lower === 'off') return 'off';
  return 'off';
}

export const GRID_DELIVERY_ICONS: Record<GridDelivery, string> = {
  off: '\u{1F6AB}',   // 🚫
  on: '\u{1F4A7}',    // 💧
  limited: '\u{1F6B0}', // 🚰
};

// ============================================================================
// BOILER MODE
// ============================================================================

export type BoilerMode = 'cbb' | 'manual';

export const BOILER_MODE_LABELS: Record<BoilerMode, string> = {
  cbb: 'Inteligentní',
  manual: 'Manuální',
};

export const BOILER_MODE_ICONS: Record<BoilerMode, string> = {
  cbb: '\u{1F916}',    // 🤖
  manual: '\u{1F464}', // 👤
};

/** V1 sensor value → BoilerMode mapping */
export const BOILER_MODE_SENSOR_MAP: Record<string, BoilerMode> = {
  'CBB': 'cbb',
  'Manuální': 'manual',
  'Manual': 'manual',
  'Inteligentní': 'cbb',
};

export const BOILER_MODE_SERVICE_MAP: Record<BoilerMode, BoilerMode> = {
  cbb: 'cbb',
  manual: 'manual',
};

// ============================================================================
// BUTTON STATES
// ============================================================================

export type ButtonState = 'idle' | 'active' | 'pending' | 'processing' | 'disabled-by-service';

// ============================================================================
// SHIELD QUEUE
// ============================================================================

export interface ShieldRequestTarget {
  param: string;
  value: string;
  entityId: string;
  from: string;
  to: string;
  current: string;
}

export interface ShieldRequestParams {
  mode?: string;
  limit?: number | string;
  _grid_delivery_step?: string;
  [key: string]: unknown;
}

export interface ShieldQueueItem {
  id: string;
  type: 'mode_change' | 'grid_delivery' | 'grid_limit' | 'boiler_mode' | 'battery_formating';
  status: 'queued' | 'running';
  service: string;
  targetValue: string;
  changes: string[];
  createdAt: string;
  position: number;
  description?: string;
  params?: ShieldRequestParams;
  targets?: ShieldRequestTarget[];
  traceId?: string;
  gridDeliveryStep?: string;
}

export const QUEUE_STATUS_COLORS: Record<ShieldQueueItem['status'], string> = {
  queued: '#ff9800',
  running: '#2196f3',
};

export const QUEUE_SERVICE_MAP: Record<string, string> = {
  'set_box_mode': '\u{1F3E0} Změna režimu boxu',       // 🏠
  'set_grid_delivery': '\u{1F4A7} Změna nastavení přetoků', // 💧
  'set_grid_delivery_limit': '\u{1F522} Změna limitu přetoků', // 🔢
  'set_boiler_mode': '\u{1F525} Změna nastavení bojleru',   // 🔥
  'set_formating_mode': '\u{1F50B} Změna nabíjení baterie', // 🔋
  'set_battery_capacity': '\u26A1 Změna kapacity baterie',  // ⚡
};

export const QUEUE_VALUE_MAP: Record<string, string> = {
  'CBB': 'Inteligentní',
  'Manual': 'Manuální',
  'Manuální': 'Manuální',
};

// ============================================================================
// SUPPLEMENTARY TOGGLES — box_mode_extended sensor state
// ============================================================================

export interface SupplementaryState {
  /** Whether Home Grid V (home_grid_v) supplementary mode is active */
  home_grid_v: boolean;
  /** Whether Home Grid VI (home_grid_vi) supplementary mode is active */
  home_grid_vi: boolean;
  /** Whether Flexibilita (app=4) is active — blocks all toggle dispatches */
  flexibilita: boolean;
  /** Whether the box_mode_extended sensor is currently available */
  available: boolean;
}

// ============================================================================
// SHIELD STATE — reactive controller state
// ============================================================================

export type ShieldServiceType = 'box_mode' | 'boiler_mode' | 'grid_mode' | 'grid_limit';

export interface ShieldState {
  /** Current shield status: idle | running */
  status: 'idle' | 'running';
  /** Current shield activity text */
  activity: string;
  /** Queue count */
  queueCount: number;
  /** Running + queued requests parsed from sensor attributes */
  runningRequests: ShieldQueueItem[];
  queuedRequests: ShieldQueueItem[];
  /** All requests combined */
  allRequests: ShieldQueueItem[];
  /** Current actual sensor values */
  currentBoxMode: BoxMode;
  /** @deprecated Use gridDeliveryState.currentLiveDelivery or getGridDeliveryDisplayState() */
  currentGridDelivery: GridDelivery;
  /** @deprecated Use gridDeliveryState.currentLiveLimit */
  currentGridLimit: number;
  currentBoilerMode: BoilerMode;
  /** Per-service pending targets (from shield activity sensor attributes) */
  pendingServices: Map<ShieldServiceType, string>;
  /** Which service types are currently being changed */
  changingServices: Set<ShieldServiceType>;
  /** New grid delivery state model with explicit live/pending separation */
  gridDeliveryState: GridDeliveryStateModel;
  /** Supplementary toggles derived from box_mode_extended sensor */
  supplementary: SupplementaryState;
}

export const EMPTY_SHIELD_STATE: ShieldState = {
  status: 'idle',
  activity: '',
  queueCount: 0,
  runningRequests: [],
  queuedRequests: [],
  allRequests: [],
  currentBoxMode: 'home_1',
  currentGridDelivery: 'off',
  currentGridLimit: 0,
  currentBoilerMode: 'cbb',
  pendingServices: new Map(),
  changingServices: new Set(),
  gridDeliveryState: {
    currentLiveDelivery: 'unknown',
    currentLiveLimit: null,
    pendingDeliveryTarget: null,
    pendingLimitTarget: null,
    isTransitioning: false,
    isUnavailable: false,
  },
  supplementary: {
    home_grid_v: false,
    home_grid_vi: false,
    flexibilita: false,
    available: false,
  },
};

// ============================================================================
// BATTERY CHARGE (kept from original)
// ============================================================================

export interface BatteryChargeParams {
  targetSoc: number;
  estimatedCost: number;
  estimatedTime: number;
}

// ============================================================================
// CONFIRM DIALOG
// ============================================================================

export interface ConfirmDialogConfig {
  title: string;
  message: string;
  warning?: string;
  /** If true, shows checkbox that must be checked before confirm */
  requireAcknowledgement?: boolean;
  acknowledgementText?: string;
  confirmText?: string;
  cancelText?: string;
  /** Extra content (e.g. limit input) */
  showLimitInput?: boolean;
  limitValue?: number;
  limitMin?: number;
  limitMax?: number;
  limitStep?: number;
  /**
   * Limit-only variant: skips main warning/acknowledgement sections and replaces
   * the dialog header with a concise label (e.g. "Změnit limit přetoků").
   * The limit number input still renders unchanged. Implies showLimitInput=true.
   */
  limitOnly?: boolean;
}

export interface ConfirmDialogResult {
  confirmed: boolean;
  limit?: number;
}
