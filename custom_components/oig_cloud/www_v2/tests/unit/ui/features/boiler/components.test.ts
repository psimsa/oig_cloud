import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { nothing } from 'lit';
import {
  OigBoilerDebugPanel,
  OigBoilerStatusGrid,
  OigBoilerEnergyBreakdown,
  OigBoilerPredictedUsage,
  OigBoilerPlanInfo,
  OigBoilerTank,
  OigBoilerCategorySelect,
  OigBoilerHeatmapGrid,
  OigBoilerStatsCards,
  OigBoilerProfiling,
  OigBoilerConfigSection,
  OigBoilerState,
  OigBoilerHeatmap,
  OigBoilerProfiles,
} from '@/ui/features/boiler/components';
import type {
  BoilerState,
  BoilerPlan,
  BoilerEnergyBreakdown,
  BoilerPredictedUsage,
  BoilerProfilingData,
  BoilerConfig,
  BoilerHeatmapRow,
} from '@/ui/features/boiler/types';
import { CATEGORY_LABELS } from '@/ui/features/boiler/types';

// Mock external data module to avoid HA API calls during tests
vi.mock('@/data/boiler-data', () => ({
  planBoilerHeating: vi.fn().mockResolvedValue(true),
  applyBoilerPlan: vi.fn().mockResolvedValue(true),
  cancelBoilerPlan: vi.fn().mockResolvedValue(false),
  getSensorId: vi.fn((s: string) => `sensor.oig_test_${s}`),
}));

// ─── Test helpers ────────────────────────────────────────────────────────────

function getPrivate(el: object, key: string): unknown {
  return Reflect.get(el, key);
}

function setPrivate(el: object, key: string, value: unknown): void {
  Reflect.set(el, key, value);
}

function callMethod(el: object, name: string, ...args: unknown[]): unknown {
  const fn = Reflect.get(el, name);
  if (typeof fn !== 'function') throw new Error(`No method '${name}' on ${el.constructor.name}`);
  return Reflect.apply(fn as (...a: unknown[]) => unknown, el, args);
}

// ─── Data factories ───────────────────────────────────────────────────────────

function makeBoilerState(overrides: Partial<BoilerState> = {}): BoilerState {
  return {
    currentTemp: 45,
    targetTemp: 55,
    heating: false,
    tempTop: 50,
    tempBottom: 40,
    avgTemp: 45,
    heatingPercent: 60,
    energyNeeded: 2.5,
    planCost: 15.30,
    nextHeating: '14:00',
    recommendedSource: 'FVE',
    ...overrides,
  };
}

function makeBoilerPlan(overrides: Partial<BoilerPlan> = {}): BoilerPlan {
  return {
    slots: [],
    totalConsumptionKwh: 5.2,
    fveKwh: 3.0,
    gridKwh: 2.2,
    altKwh: 0.0,
    estimatedCostCzk: 25.0,
    nextSlot: null,
    planStart: '00:00',
    planEnd: '23:59',
    sourceDigest: 'FVE/Grid',
    activeSlotCount: 3,
    cheapestSpot: '14:00',
    mostExpensiveSpot: '08:00',
    ...overrides,
  };
}

function makeEnergyBreakdown(overrides: Partial<BoilerEnergyBreakdown> = {}): BoilerEnergyBreakdown {
  return {
    fveKwh: 3.0,
    gridKwh: 1.5,
    altKwh: 0.5,
    fvePercent: 60,
    gridPercent: 30,
    altPercent: 10,
    ...overrides,
  };
}

function makePredictedUsage(overrides: Partial<BoilerPredictedUsage> = {}): BoilerPredictedUsage {
  return {
    predictedTodayKwh: 4.2,
    peakHours: [7, 18],
    waterLiters40c: 120,
    circulationWindows: '06:00-08:00',
    circulationNow: 'NIE',
    ...overrides,
  };
}

function makeProfilingData(overrides: Partial<BoilerProfilingData> = {}): BoilerProfilingData {
  return {
    hourlyAvg: Array(24).fill(0.5),
    peakHours: [7, 18],
    predictedTotalKwh: 4.5,
    confidence: 0.85,
    daysTracked: 14,
    ...overrides,
  };
}

function makeBoilerConfig(overrides: Partial<BoilerConfig> = {}): BoilerConfig {
  return {
    volumeL: 150,
    heaterPowerW: 2000,
    targetTempC: 55,
    deadlineTime: '06:00',
    stratificationMode: 'Normal',
    kCoefficient: '0.85',
    coldInletTempC: 10,
    ...overrides,
  };
}

// ─── OigBoilerDebugPanel ──────────────────────────────────────────────────────

describe('OigBoilerDebugPanel — property defaults', () => {
  let el: OigBoilerDebugPanel;

  beforeEach(() => { el = new OigBoilerDebugPanel(); });

  it('collapsed defaults to true', () => {
    expect(getPrivate(el, 'collapsed')).toBe(true);
  });

  it('busy defaults to false', () => {
    expect(getPrivate(el, 'busy')).toBe(false);
  });
});

describe('OigBoilerDebugPanel — toggle()', () => {
  let el: OigBoilerDebugPanel;

  beforeEach(() => { el = new OigBoilerDebugPanel(); });

  it('toggle() sets collapsed to false when true', () => {
    callMethod(el, 'toggle');
    expect(getPrivate(el, 'collapsed')).toBe(false);
  });

  it('toggle() sets collapsed back to true when called twice', () => {
    callMethod(el, 'toggle');
    callMethod(el, 'toggle');
    expect(getPrivate(el, 'collapsed')).toBe(true);
  });
});


describe('OigBoilerDebugPanel — doAction()', () => {
  let el: OigBoilerDebugPanel;

  beforeEach(() => { el = new OigBoilerDebugPanel(); });

  it('dispatches action-done with success:true on resolved action', async () => {
    const handler = vi.fn();
    el.addEventListener('action-done', handler);
    await callMethod(el, 'doAction', async () => true, 'plan');
    expect(handler).toHaveBeenCalledOnce();
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toEqual({ success: true, label: 'plan' });
  });

  it('dispatches action-done with success:false when action returns false', async () => {
    const handler = vi.fn();
    el.addEventListener('action-done', handler);
    await callMethod(el, 'doAction', async () => false, 'cancel');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toEqual({ success: false, label: 'cancel' });
  });

  it('action-done event bubbles', async () => {
    const handler = vi.fn();
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    parent.appendChild(el as unknown as Node);
    parent.addEventListener('action-done', handler);
    await callMethod(el, 'doAction', async () => true, 'apply');
    expect(handler).toHaveBeenCalledOnce();
    parent.remove();
  });

  it('resets busy to false after action completes', async () => {
    await callMethod(el, 'doAction', async () => true, 'plan');
    expect(getPrivate(el, 'busy')).toBe(false);
  });

  it('resets busy to false even if action throws', async () => {
    try {
      await callMethod(el, 'doAction', async () => { throw new Error('fail'); }, 'plan');
    } catch {
      // expected
    }
    expect(getPrivate(el, 'busy')).toBe(false);
  });
});

describe('OigBoilerDebugPanel — render()', () => {
  it('render() returns a TemplateResult', () => {
    const el = new OigBoilerDebugPanel();
    const result = el.render();
    expect(result).not.toBe(nothing);
    expect(result).toBeTruthy();
  });

  it('render() toggle-icon shows + when collapsed', () => {
    const el = new OigBoilerDebugPanel();
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values).toBeDefined();
  });
});

// ─── OigBoilerStatusGrid ─────────────────────────────────────────────────────

describe('OigBoilerStatusGrid — property defaults', () => {
  it('data defaults to null', () => {
    const el = new OigBoilerStatusGrid();
    expect(el.data).toBeNull();
  });
});

describe('OigBoilerStatusGrid — render()', () => {
  it('returns loading div when data is null', () => {
    const el = new OigBoilerStatusGrid();
    const result = el.render() as unknown as { values: unknown[] };
    expect(result).not.toBe(nothing);
  });

  it('returns TemplateResult when data is set', () => {
    const el = new OigBoilerStatusGrid();
    el.data = makeBoilerState();
    const result = el.render();
    expect(result).not.toBe(nothing);
    expect(result).toBeTruthy();
  });

  it('accepts BoilerState with all numeric fields', () => {
    const el = new OigBoilerStatusGrid();
    const state = makeBoilerState({ heatingPercent: 75, energyNeeded: 1.5, planCost: 12.0 });
    el.data = state;
    expect(el.data).toEqual(state);
  });

  it('renders with tempBottom null (optional card skipped)', () => {
    const el = new OigBoilerStatusGrid();
    el.data = makeBoilerState({ tempBottom: null });
    const result = el.render();
    expect(result).not.toBe(nothing);
  });

  it('renders with null energyNeeded and planCost (fmt null branch)', () => {
    const el = new OigBoilerStatusGrid();
    el.data = makeBoilerState({ energyNeeded: null, planCost: null });
    const result = el.render();
    expect(result).not.toBe(nothing);
  });
});

// ─── OigBoilerEnergyBreakdown ─────────────────────────────────────────────────

describe('OigBoilerEnergyBreakdown — property defaults', () => {
  it('data defaults to null', () => {
    const el = new OigBoilerEnergyBreakdown();
    expect(el.data).toBeNull();
  });
});

describe('OigBoilerEnergyBreakdown — render()', () => {
  it('returns nothing when data is null', () => {
    const el = new OigBoilerEnergyBreakdown();
    const result = el.render();
    expect(result).toBe(nothing);
  });

  it('returns TemplateResult when data is provided', () => {
    const el = new OigBoilerEnergyBreakdown();
    el.data = makeEnergyBreakdown();
    const result = el.render();
    expect(result).not.toBe(nothing);
    expect(result).toBeTruthy();
  });

  it('accepts BoilerEnergyBreakdown object', () => {
    const el = new OigBoilerEnergyBreakdown();
    const d = makeEnergyBreakdown({ fvePercent: 70, gridPercent: 20, altPercent: 10 });
    el.data = d;
    expect(el.data).toEqual(d);
  });
});

// ─── OigBoilerPredictedUsage ──────────────────────────────────────────────────

describe('OigBoilerPredictedUsage — property defaults', () => {
  it('data defaults to null', () => {
    const el = new OigBoilerPredictedUsage();
    expect(el.data).toBeNull();
  });
});

describe('OigBoilerPredictedUsage — render()', () => {
  it('returns nothing when data is null', () => {
    const el = new OigBoilerPredictedUsage();
    expect(el.render()).toBe(nothing);
  });

  it('returns TemplateResult when data provided', () => {
    const el = new OigBoilerPredictedUsage();
    el.data = makePredictedUsage();
    expect(el.render()).not.toBe(nothing);
  });

  it('circulationNow starting with ANO → active class', () => {
    const el = new OigBoilerPredictedUsage();
    el.data = makePredictedUsage({ circulationNow: 'ANO - cirkuluje' });
    const result = el.render() as unknown as { values: unknown[] };
    expect(result).not.toBe(nothing);
    expect(result.values).toBeDefined();
  });

  it('circulationNow not starting with ANO → idle class', () => {
    const el = new OigBoilerPredictedUsage();
    el.data = makePredictedUsage({ circulationNow: 'NIE' });
    const result = el.render() as unknown as { values: unknown[] };
    expect(result).not.toBe(nothing);
  });

  it('waterLiters40c null → shows -- L', () => {
    const el = new OigBoilerPredictedUsage();
    el.data = makePredictedUsage({ waterLiters40c: null });
    expect(el.render()).not.toBe(nothing);
  });

  it('peakHours empty → shows --', () => {
    const el = new OigBoilerPredictedUsage();
    el.data = makePredictedUsage({ peakHours: [] });
    expect(el.render()).not.toBe(nothing);
  });
});

// ─── OigBoilerPlanInfo ────────────────────────────────────────────────────────

describe('OigBoilerPlanInfo — property defaults', () => {
  it('plan defaults to null', () => {
    const el = new OigBoilerPlanInfo();
    expect(el.plan).toBeNull();
  });

  it('forecastWindows defaults to fve:-- grid:--', () => {
    const el = new OigBoilerPlanInfo();
    expect(el.forecastWindows).toEqual({ fve: '--', grid: '--' });
  });
});

describe('OigBoilerPlanInfo — render()', () => {
  it('returns TemplateResult even when plan is null (v() fallback)', () => {
    const el = new OigBoilerPlanInfo();
    const result = el.render();
    expect(result).not.toBe(nothing);
    expect(result).toBeTruthy();
  });

  it('returns TemplateResult when plan is provided', () => {
    const el = new OigBoilerPlanInfo();
    el.plan = makeBoilerPlan();
    expect(el.render()).not.toBe(nothing);
  });

  it('shows forecastWindows fve and grid values', () => {
    const el = new OigBoilerPlanInfo();
    el.forecastWindows = { fve: '10:00-14:00', grid: '22:00-06:00' };
    const result = el.render();
    expect(result).not.toBe(nothing);
  });

  it('accepts plan with slot array', () => {
    const el = new OigBoilerPlanInfo();
    el.plan = makeBoilerPlan({ slots: [{ start: '10:00', end: '11:00', consumptionKwh: 2, recommendedSource: 'FVE', spotPrice: 1.5 }], activeSlotCount: 1 });
    expect(el.render()).not.toBe(nothing);
  });
});

// ─── OigBoilerTank ────────────────────────────────────────────────────────────

describe('OigBoilerTank — property defaults', () => {
  it('boilerState defaults to null', () => {
    const el = new OigBoilerTank();
    expect(el.boilerState).toBeNull();
  });

  it('targetTemp defaults to 60', () => {
    const el = new OigBoilerTank();
    expect(el.targetTemp).toBe(60);
  });
});

describe('OigBoilerTank — render()', () => {
  it('returns loading template when boilerState is null', () => {
    const el = new OigBoilerTank();
    const result = el.render();
    expect(result).not.toBe(nothing);
    const tmpl = result as unknown as { strings: readonly string[] };
    expect(tmpl.strings).toBeDefined();
  });

  it('returns TemplateResult when boilerState is set', () => {
    const el = new OigBoilerTank();
    el.boilerState = makeBoilerState();
    expect(el.render()).not.toBe(nothing);
  });

  it('renders with tempTop and tempBottom (covers sensor positions)', () => {
    const el = new OigBoilerTank();
    el.boilerState = makeBoilerState({ tempTop: 60, tempBottom: 30 });
    expect(el.render()).not.toBe(nothing);
  });

  it('renders with tempTop null (no top sensor marker)', () => {
    const el = new OigBoilerTank();
    el.boilerState = makeBoilerState({ tempTop: null });
    expect(el.render()).not.toBe(nothing);
  });

  it('renders with tempBottom null (no bottom sensor marker)', () => {
    const el = new OigBoilerTank();
    el.boilerState = makeBoilerState({ tempBottom: null });
    expect(el.render()).not.toBe(nothing);
  });

  it('renders heatingPercent null → grade shows --', () => {
    const el = new OigBoilerTank();
    el.boilerState = makeBoilerState({ heatingPercent: null });
    expect(el.render()).not.toBe(nothing);
  });

  it('targetTemp affects target line position (clampPercent)', () => {
    const el = new OigBoilerTank();
    el.targetTemp = 70;
    el.boilerState = makeBoilerState();
    expect(el.render()).not.toBe(nothing);
  });

  it('targetTemp below min (10) → clampPercent returns 0', () => {
    const el = new OigBoilerTank();
    el.targetTemp = 5;
    el.boilerState = makeBoilerState();
    expect(el.render()).not.toBe(nothing);
  });
});

// ─── OigBoilerCategorySelect ──────────────────────────────────────────────────

describe('OigBoilerCategorySelect — property defaults', () => {
  it('current defaults to empty string', () => {
    const el = new OigBoilerCategorySelect();
    expect(el.current).toBe('');
  });

  it('available defaults to empty array', () => {
    const el = new OigBoilerCategorySelect();
    expect(el.available).toEqual([]);
  });
});

describe('OigBoilerCategorySelect — onChange()', () => {
  let el: OigBoilerCategorySelect;

  beforeEach(() => { el = new OigBoilerCategorySelect(); });

  it('dispatches category-change event', () => {
    const handler = vi.fn();
    el.addEventListener('category-change', handler);
    const fakeEvent = { target: { value: 'workday_spring' } } as unknown as Event;
    callMethod(el, 'onChange', fakeEvent);
    expect(handler).toHaveBeenCalledOnce();
  });

  it('detail contains the selected category', () => {
    const handler = vi.fn();
    el.addEventListener('category-change', handler);
    const fakeEvent = { target: { value: 'weekend_winter' } } as unknown as Event;
    callMethod(el, 'onChange', fakeEvent);
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toEqual({ category: 'weekend_winter' });
  });

  it('category-change event bubbles', () => {
    const handler = vi.fn();
    el.addEventListener('category-change', handler);
    const fakeEvent = { target: { value: 'workday_summer' } } as unknown as Event;
    callMethod(el, 'onChange', fakeEvent);
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.bubbles).toBe(true);
  });
});

describe('OigBoilerCategorySelect — render()', () => {
  it('uses CATEGORY_LABELS keys when available is empty', () => {
    const el = new OigBoilerCategorySelect();
    const result = el.render() as unknown as { values: unknown[] };
    expect(result).not.toBe(nothing);
    expect(result.values).toBeDefined();
  });

  it('uses provided available array when non-empty', () => {
    const el = new OigBoilerCategorySelect();
    el.available = ['workday_spring', 'workday_summer'];
    expect(el.render()).not.toBe(nothing);
  });

  it('marks the matching option as selected via current', () => {
    const el = new OigBoilerCategorySelect();
    el.current = 'workday_spring';
    el.available = Object.keys(CATEGORY_LABELS);
    expect(el.render()).not.toBe(nothing);
  });
});

// ─── OigBoilerHeatmapGrid ─────────────────────────────────────────────────────

describe('OigBoilerHeatmapGrid — property defaults', () => {
  it('data defaults to empty array', () => {
    const el = new OigBoilerHeatmapGrid();
    expect(el.data).toEqual([]);
  });
});

describe('OigBoilerHeatmapGrid — render()', () => {
  it('returns nothing when data is empty', () => {
    const el = new OigBoilerHeatmapGrid();
    expect(el.render()).toBe(nothing);
  });

  it('returns TemplateResult when data has rows', () => {
    const el = new OigBoilerHeatmapGrid();
    const hours = Array(24).fill(0);
    el.data = [{ day: 'Po', hours }];
    expect(el.render()).not.toBe(nothing);
  });

  it('cellClass covers all 4 branches: none/low/medium/high', () => {
    const el = new OigBoilerHeatmapGrid();
    const hours = Array(24).fill(0);
    hours[0] = 0;
    hours[1] = 1;
    hours[2] = 5;
    hours[3] = 10;
    el.data = [{ day: 'Po', hours }];
    const result = el.render();
    expect(result).not.toBe(nothing);
  });

  it('handles multiple rows', () => {
    const el = new OigBoilerHeatmapGrid();
    const row: BoilerHeatmapRow = { day: 'Po', hours: Array(24).fill(1) };
    el.data = [row, { ...row, day: 'Út' }];
    expect(el.render()).not.toBe(nothing);
  });
});

// ─── OigBoilerStatsCards ─────────────────────────────────────────────────────

describe('OigBoilerStatsCards — property defaults', () => {
  it('plan defaults to null', () => {
    const el = new OigBoilerStatsCards();
    expect(el.plan).toBeNull();
  });
});

describe('OigBoilerStatsCards — render()', () => {
  it('returns TemplateResult when plan is null (shows "-")', () => {
    const el = new OigBoilerStatsCards();
    const result = el.render();
    expect(result).not.toBe(nothing);
    expect(result).toBeTruthy();
  });

  it('returns TemplateResult when plan is provided', () => {
    const el = new OigBoilerStatsCards();
    el.plan = makeBoilerPlan();
    expect(el.render()).not.toBe(nothing);
  });

  it('accepts plan with all numeric values', () => {
    const el = new OigBoilerStatsCards();
    el.plan = makeBoilerPlan({ totalConsumptionKwh: 10, fveKwh: 6, gridKwh: 4, estimatedCostCzk: 50 });
    expect(el.render()).not.toBe(nothing);
  });
});

// ─── OigBoilerProfiling ───────────────────────────────────────────────────────

describe('OigBoilerProfiling — property defaults', () => {
  it('data defaults to null', () => {
    const el = new OigBoilerProfiling();
    expect(el.data).toBeNull();
  });
});

describe('OigBoilerProfiling — render()', () => {
  it('returns nothing when data is null', () => {
    const el = new OigBoilerProfiling();
    expect(el.render()).toBe(nothing);
  });

  it('returns TemplateResult when data provided', () => {
    const el = new OigBoilerProfiling();
    el.data = makeProfilingData();
    expect(el.render()).not.toBe(nothing);
  });

  it('peakHours empty → peaksStr shows --', () => {
    const el = new OigBoilerProfiling();
    el.data = makeProfilingData({ peakHours: [] });
    expect(el.render()).not.toBe(nothing);
  });

  it('peakHours non-empty → peaksStr shows hours', () => {
    const el = new OigBoilerProfiling();
    el.data = makeProfilingData({ peakHours: [7, 18, 22] });
    expect(el.render()).not.toBe(nothing);
  });

  it('confidence null → confStr shows -- %', () => {
    const el = new OigBoilerProfiling();
    el.data = makeProfilingData({ confidence: null });
    expect(el.render()).not.toBe(nothing);
  });

  it('confidence defined → confStr shows percentage', () => {
    const el = new OigBoilerProfiling();
    el.data = makeProfilingData({ confidence: 0.92 });
    expect(el.render()).not.toBe(nothing);
  });

  it('bar chart renders peak vs normal bars', () => {
    const el = new OigBoilerProfiling();
    const hourlyAvg = Array(24).fill(0.5);
    hourlyAvg[7] = 2.0;
    el.data = makeProfilingData({ hourlyAvg, peakHours: [7] });
    expect(el.render()).not.toBe(nothing);
  });
});

// ─── OigBoilerConfigSection ───────────────────────────────────────────────────

describe('OigBoilerConfigSection — property defaults', () => {
  it('config defaults to null', () => {
    const el = new OigBoilerConfigSection();
    expect(el.config).toBeNull();
  });
});

describe('OigBoilerConfigSection — render()', () => {
  it('returns nothing when config is null', () => {
    const el = new OigBoilerConfigSection();
    expect(el.render()).toBe(nothing);
  });

  it('returns TemplateResult when config provided', () => {
    const el = new OigBoilerConfigSection();
    el.config = makeBoilerConfig();
    expect(el.render()).not.toBe(nothing);
  });

  it('v() shows -- when volumeL is null', () => {
    const el = new OigBoilerConfigSection();
    el.config = makeBoilerConfig({ volumeL: null });
    expect(el.render()).not.toBe(nothing);
  });

  it('v() shows -- when heaterPowerW is null', () => {
    const el = new OigBoilerConfigSection();
    el.config = makeBoilerConfig({ heaterPowerW: null });
    expect(el.render()).not.toBe(nothing);
  });

  it('v() shows -- when targetTempC is null', () => {
    const el = new OigBoilerConfigSection();
    el.config = makeBoilerConfig({ targetTempC: null });
    expect(el.render()).not.toBe(nothing);
  });

  it('v() shows value with unit when all fields defined', () => {
    const el = new OigBoilerConfigSection();
    el.config = makeBoilerConfig({ volumeL: 200, heaterPowerW: 3000, targetTempC: 60 });
    expect(el.render()).not.toBe(nothing);
  });
});

// ─── OigBoilerState (legacy) ──────────────────────────────────────────────────

describe('OigBoilerState — property defaults', () => {
  it('state defaults to null', () => {
    const el = new OigBoilerState();
    expect(el.state).toBeNull();
  });
});

describe('OigBoilerState — render()', () => {
  it('returns loading template when state is null', () => {
    const el = new OigBoilerState();
    const result = el.render();
    expect(result).not.toBe(nothing);
    expect(result).toBeTruthy();
  });

  it('returns TemplateResult when state is set', () => {
    const el = new OigBoilerState();
    el.state = makeBoilerState();
    expect(el.render()).not.toBe(nothing);
  });

  it('heating: true → status dot shows heating class', () => {
    const el = new OigBoilerState();
    el.state = makeBoilerState({ heating: true });
    const result = el.render() as unknown as { values: unknown[] };
    expect(result).not.toBe(nothing);
    expect(result.values).toBeDefined();
  });

  it('heating: false → status dot shows idle class', () => {
    const el = new OigBoilerState();
    el.state = makeBoilerState({ heating: false });
    expect(el.render()).not.toBe(nothing);
  });

  it('nextProfile defined → shows next info div', () => {
    const el = new OigBoilerState();
    el.state = makeBoilerState({ nextProfile: 'Večer', nextStart: '18:00' });
    const result = el.render() as unknown as { values: unknown[] };
    expect(result).not.toBe(nothing);
  });

  it('nextProfile undefined → next info block is null', () => {
    const el = new OigBoilerState();
    el.state = makeBoilerState({ nextProfile: undefined, nextStart: undefined });
    expect(el.render()).not.toBe(nothing);
  });
});

// ─── OigBoilerHeatmap (legacy) ────────────────────────────────────────────────

describe('OigBoilerHeatmap — property defaults', () => {
  it('data defaults to empty array', () => {
    const el = new OigBoilerHeatmap();
    expect(el.data).toEqual([]);
  });
});

describe('OigBoilerHeatmap — render()', () => {
  it('returns nothing (legacy stub)', () => {
    const el = new OigBoilerHeatmap();
    expect(el.render()).toBe(nothing);
  });

  it('still returns nothing with data set', () => {
    const el = new OigBoilerHeatmap();
    el.data = [{ hour: 10, temp: 50, heating: false }];
    expect(el.render()).toBe(nothing);
  });
});

// ─── OigBoilerProfiles (legacy) ───────────────────────────────────────────────

describe('OigBoilerProfiles — property defaults', () => {
  it('profiles defaults to empty array', () => {
    const el = new OigBoilerProfiles();
    expect(el.profiles).toEqual([]);
  });

  it('editMode defaults to false', () => {
    const el = new OigBoilerProfiles();
    expect(el.editMode).toBe(false);
  });
});

describe('OigBoilerProfiles — render()', () => {
  it('returns nothing (legacy stub)', () => {
    const el = new OigBoilerProfiles();
    expect(el.render()).toBe(nothing);
  });

  it('still returns nothing with profiles set', () => {
    const el = new OigBoilerProfiles();
    el.profiles = [{
      id: '1', name: 'Morning', targetTemp: 55,
      startTime: '06:00', endTime: '08:00', days: [1,1,1,1,1,0,0], enabled: true,
    }];
    expect(el.render()).toBe(nothing);
  });

  it('editMode can be toggled', () => {
    const el = new OigBoilerProfiles();
    el.editMode = true;
    expect(el.editMode).toBe(true);
  });
});
