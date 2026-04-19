import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { OigTimelineDialog, OigTimelineTile } from '@/ui/features/timeline/dialog';
import type { TimelineDayData, ModeBlock, MetricTile } from '@/ui/features/timeline/types';
import { TIMELINE_MODE_CONFIG } from '@/ui/features/timeline/types';

type TR = { values: unknown[] };

function getPrivate(el: object, key: string): unknown {
  return Reflect.get(el, key);
}

function setPrivate(el: object, key: string, value: unknown): void {
  Reflect.set(el, key, value);
}

function callMethod(el: object, name: string, ...args: unknown[]): unknown {
  const fn = Reflect.get(el, name);
  if (typeof fn !== 'function') throw new Error(`No method '${name}' on ${(el as any).constructor.name}`);
  return Reflect.apply(fn as (...a: unknown[]) => unknown, el, args);
}

function renderValues(el: { render(): unknown }): unknown[] {
  return (el.render() as unknown as TR).values;
}

function makeMetricTile(overrides: Partial<MetricTile> = {}): MetricTile {
  return {
    plan: 100,
    actual: null,
    hasActual: false,
    unit: 'kWh',
    ...overrides,
  };
}

function makeModeBlock(overrides: Partial<ModeBlock> = {}): ModeBlock {
  return {
    modeHistorical: 'HOME I',
    modePlanned: 'HOME I',
    modeMatch: true,
    status: 'completed',
    startTime: '08:00',
    endTime: '10:00',
    durationHours: 2,
    costHistorical: 15,
    costPlanned: 14,
    costDelta: -1,
    solarKwh: 1.5,
    consumptionKwh: 2.0,
    gridImportKwh: 0.5,
    gridExportKwh: 0,
    intervalReasons: [],
    ...overrides,
  };
}

function makeDayData(overrides: Partial<TimelineDayData> = {}): TimelineDayData {
  return {
    date: '2026-04-18',
    modeBlocks: [],
    summary: {
      overallAdherence: 0,
      modeSwitches: 3,
      totalCost: 120,
      metrics: {
        cost: makeMetricTile({ plan: 120, unit: 'Kč' }),
        solar: makeMetricTile({ plan: 5.0, unit: 'kWh' }),
        consumption: makeMetricTile({ plan: 8.0, unit: 'kWh' }),
        grid: makeMetricTile({ plan: 3.0, unit: 'kWh' }),
      },
    },
    ...overrides,
  };
}

// ─── OigTimelineDialog ────────────────────────────────────────────────────────

describe('OigTimelineDialog — property defaults', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    el = new OigTimelineDialog();
  });

  it('open defaults to false', () => {
    expect(el.open).toBe(false);
  });

  it('activeTab defaults to "today"', () => {
    expect(el.activeTab).toBe('today');
  });

  it('data defaults to null', () => {
    expect(el.data).toBeNull();
  });

  it('private autoRefresh defaults to true', () => {
    expect(getPrivate(el, 'autoRefresh')).toBe(true);
  });

  it('private refreshInterval defaults to null', () => {
    expect(getPrivate(el, 'refreshInterval')).toBeNull();
  });
});

describe('OigTimelineDialog — onClose()', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    el = new OigTimelineDialog();
  });

  it('dispatches a "close" CustomEvent', () => {
    const handler = vi.fn();
    el.addEventListener('close', handler);
    callMethod(el, 'onClose');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('close event is a CustomEvent', () => {
    let received: Event | null = null;
    el.addEventListener('close', (e) => { received = e; });
    callMethod(el, 'onClose');
    expect(received).toBeInstanceOf(CustomEvent);
  });

  it('close event bubbles', () => {
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    parent.appendChild(el as unknown as Node);
    const handler = vi.fn();
    parent.addEventListener('close', handler);
    callMethod(el, 'onClose');
    expect(handler).toHaveBeenCalledOnce();
    parent.remove();
  });
});

describe('OigTimelineDialog — onTabClick()', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    el = new OigTimelineDialog();
  });

  it('sets activeTab to the given tab', () => {
    callMethod(el, 'onTabClick', 'yesterday');
    expect(el.activeTab).toBe('yesterday');
  });

  it('dispatches "tab-change" CustomEvent', () => {
    const handler = vi.fn();
    el.addEventListener('tab-change', handler);
    callMethod(el, 'onTabClick', 'tomorrow');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('tab-change event has detail.tab', () => {
    const handler = vi.fn();
    el.addEventListener('tab-change', handler);
    callMethod(el, 'onTabClick', 'history');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toEqual({ tab: 'history' });
  });

  it('tab-change event bubbles', () => {
    const handler = vi.fn();
    el.addEventListener('tab-change', handler);
    callMethod(el, 'onTabClick', 'detail');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.bubbles).toBe(true);
  });

  it('switches through all 5 tabs', () => {
    const tabs = ['yesterday', 'today', 'tomorrow', 'history', 'detail'] as const;
    for (const tab of tabs) {
      callMethod(el, 'onTabClick', tab);
      expect(el.activeTab).toBe(tab);
    }
  });
});

describe('OigTimelineDialog — toggleAutoRefresh()', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    vi.useFakeTimers();
    el = new OigTimelineDialog();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('flips autoRefresh from true to false', () => {
    setPrivate(el, 'autoRefresh', true);
    callMethod(el, 'toggleAutoRefresh');
    expect(getPrivate(el, 'autoRefresh')).toBe(false);
  });

  it('flips autoRefresh from false to true', () => {
    setPrivate(el, 'autoRefresh', false);
    callMethod(el, 'toggleAutoRefresh');
    expect(getPrivate(el, 'autoRefresh')).toBe(true);
  });

  it('stops refresh interval when toggled off', () => {
    setPrivate(el, 'autoRefresh', true);
    setPrivate(el, 'refreshInterval', 42);
    const spy = vi.spyOn(window, 'clearInterval');
    callMethod(el, 'toggleAutoRefresh');
    expect(spy).toHaveBeenCalledWith(42);
  });

  it('starts refresh interval when toggled on', () => {
    setPrivate(el, 'autoRefresh', false);
    const spy = vi.spyOn(window, 'setInterval');
    callMethod(el, 'toggleAutoRefresh');
    expect(spy).toHaveBeenCalled();
  });
});

describe('OigTimelineDialog — auto-refresh lifecycle', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    vi.useFakeTimers();
    el = new OigTimelineDialog();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('connectedCallback starts interval when autoRefresh=true', () => {
    const spy = vi.spyOn(window, 'setInterval');
    callMethod(el, 'connectedCallback');
    expect(spy).toHaveBeenCalled();
  });

  it('connectedCallback does NOT start interval when autoRefresh=false', () => {
    setPrivate(el, 'autoRefresh', false);
    const spy = vi.spyOn(window, 'setInterval');
    callMethod(el, 'connectedCallback');
    expect(spy).not.toHaveBeenCalled();
  });

  it('disconnectedCallback clears any existing interval', () => {
    const spy = vi.spyOn(window, 'clearInterval');
    setPrivate(el, 'refreshInterval', 99);
    callMethod(el, 'disconnectedCallback');
    expect(spy).toHaveBeenCalledWith(99);
  });

  it('disconnectedCallback sets refreshInterval to null', () => {
    setPrivate(el, 'refreshInterval', 99);
    callMethod(el, 'disconnectedCallback');
    expect(getPrivate(el, 'refreshInterval')).toBeNull();
  });

  it('interval callback dispatches "refresh" event when open and autoRefresh', () => {
    el.open = true;
    setPrivate(el, 'autoRefresh', true);
    const handler = vi.fn();
    el.addEventListener('refresh', handler);
    callMethod(el, 'startAutoRefresh');
    vi.advanceTimersByTime(60000);
    expect(handler).toHaveBeenCalledOnce();
  });

  it('interval callback does NOT dispatch "refresh" when dialog is closed', () => {
    el.open = false;
    setPrivate(el, 'autoRefresh', true);
    const handler = vi.fn();
    el.addEventListener('refresh', handler);
    callMethod(el, 'startAutoRefresh');
    vi.advanceTimersByTime(60000);
    expect(handler).not.toHaveBeenCalled();
  });

  it('stopAutoRefresh clears the interval and nulls refreshInterval', () => {
    const clearSpy = vi.spyOn(window, 'clearInterval');
    setPrivate(el, 'refreshInterval', 77);
    callMethod(el, 'stopAutoRefresh');
    expect(clearSpy).toHaveBeenCalledWith(77);
    expect(getPrivate(el, 'refreshInterval')).toBeNull();
  });

  it('stopAutoRefresh does nothing when interval is already null', () => {
    const clearSpy = vi.spyOn(window, 'clearInterval');
    setPrivate(el, 'refreshInterval', null);
    callMethod(el, 'stopAutoRefresh');
    expect(clearSpy).not.toHaveBeenCalled();
  });
});

describe('OigTimelineDialog — fmtPct()', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    el = new OigTimelineDialog();
  });

  it('formats 85.7 as "86%"', () => {
    expect(callMethod(el, 'fmtPct', 85.7)).toBe('86%');
  });

  it('formats 100 as "100%"', () => {
    expect(callMethod(el, 'fmtPct', 100)).toBe('100%');
  });

  it('formats 0 as "0%"', () => {
    expect(callMethod(el, 'fmtPct', 0)).toBe('0%');
  });

  it('truncates to no decimal places', () => {
    expect(callMethod(el, 'fmtPct', 99.9)).toBe('100%');
  });
});

describe('OigTimelineDialog — adherenceColor()', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    el = new OigTimelineDialog();
  });

  it('returns green (#4caf50) for >= 90', () => {
    expect(callMethod(el, 'adherenceColor', 90)).toBe('#4caf50');
    expect(callMethod(el, 'adherenceColor', 100)).toBe('#4caf50');
    expect(callMethod(el, 'adherenceColor', 95)).toBe('#4caf50');
  });

  it('returns orange (#ff9800) for 70–89', () => {
    expect(callMethod(el, 'adherenceColor', 70)).toBe('#ff9800');
    expect(callMethod(el, 'adherenceColor', 80)).toBe('#ff9800');
    expect(callMethod(el, 'adherenceColor', 89)).toBe('#ff9800');
  });

  it('returns red (#f44336) for < 70', () => {
    expect(callMethod(el, 'adherenceColor', 69)).toBe('#f44336');
    expect(callMethod(el, 'adherenceColor', 0)).toBe('#f44336');
    expect(callMethod(el, 'adherenceColor', 50)).toBe('#f44336');
  });
});

describe('OigTimelineDialog — getModeConfig()', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    el = new OigTimelineDialog();
  });

  it('returns correct config for HOME I', () => {
    const cfg = callMethod(el, 'getModeConfig', 'HOME I') as { icon: string; color: string; label: string };
    expect(cfg).toEqual(TIMELINE_MODE_CONFIG['HOME I']);
    expect(cfg.icon).toBe('🏠');
    expect(cfg.color).toBe('#4CAF50');
  });

  it('returns correct config for DO NOTHING', () => {
    const cfg = callMethod(el, 'getModeConfig', 'DO NOTHING') as { icon: string; color: string; label: string };
    expect(cfg.icon).toBe('⏸️');
  });

  it('returns fallback for unknown mode', () => {
    const cfg = callMethod(el, 'getModeConfig', 'UNKNOWN_MODE') as { icon: string; color: string; label: string };
    expect(cfg.icon).toBe('❓');
    expect(cfg.color).toBe('#666');
    expect(cfg.label).toBe('UNKNOWN_MODE');
  });

  it('fallback label is the mode name itself', () => {
    const cfg = callMethod(el, 'getModeConfig', 'CUSTOM MODE') as { icon: string; color: string; label: string };
    expect(cfg.label).toBe('CUSTOM MODE');
  });
});

describe('OigTimelineDialog — renderModeBlock()', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    el = new OigTimelineDialog();
  });

  it('returns a TemplateResult', () => {
    const block = makeModeBlock();
    const result = callMethod(el, 'renderModeBlock', block);
    expect(result).toBeTruthy();
    expect((result as TR).values).toBeDefined();
  });

  it('values[0] is empty string when status is not "current"', () => {
    const block = makeModeBlock({ status: 'completed' });
    const result = callMethod(el, 'renderModeBlock', block) as TR;
    expect(result.values[0]).toBe('');
  });

  it('values[0] is "current" when status is "current"', () => {
    const block = makeModeBlock({ status: 'current' });
    const result = callMethod(el, 'renderModeBlock', block) as TR;
    expect(result.values[0]).toBe('current');
  });

  it('values[6] is null when modeMatch=true (no mismatch indicator)', () => {
    const block = makeModeBlock({ modeMatch: true });
    const result = callMethod(el, 'renderModeBlock', block) as TR;
    expect(result.values[6]).toBeNull();
  });

  it('values[6] is TemplateResult when modeMatch=false (mismatch indicator shown)', () => {
    const block = makeModeBlock({ modeMatch: false });
    const result = callMethod(el, 'renderModeBlock', block) as TR;
    expect(result.values[6]).not.toBeNull();
    expect((result.values[6] as TR).values).toBeDefined();
  });

  it('values[11] is null when costPlanned is null', () => {
    const block = makeModeBlock({ costPlanned: null });
    const result = callMethod(el, 'renderModeBlock', block) as TR;
    expect(result.values[11]).toBeNull();
  });

  it('values[11] is TemplateResult when costPlanned is set', () => {
    const block = makeModeBlock({ costPlanned: 14.5 });
    const result = callMethod(el, 'renderModeBlock', block) as TR;
    expect(result.values[11]).not.toBeNull();
  });

  it('uses modeHistorical when modePlanned is empty string', () => {
    const block = makeModeBlock({ modePlanned: '', modeHistorical: 'HOME II' });
    const result = callMethod(el, 'renderModeBlock', block);
    expect(result).toBeTruthy();
  });
});

describe('OigTimelineDialog — renderMetricTile()', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    el = new OigTimelineDialog();
  });

  it('returns a TemplateResult', () => {
    const tile = makeMetricTile();
    const result = callMethod(el, 'renderMetricTile', 'Solár', tile);
    expect(result).toBeTruthy();
    expect((result as TR).values).toBeDefined();
  });

  it('values[0] is the label', () => {
    const tile = makeMetricTile();
    const result = callMethod(el, 'renderMetricTile', 'Náklady', tile) as TR;
    expect(result.values[0]).toBe('Náklady');
  });

  it('values[2] is null when hasActual=false', () => {
    const tile = makeMetricTile({ hasActual: false });
    const result = callMethod(el, 'renderMetricTile', 'Síť', tile) as TR;
    expect(result.values[2]).toBeNull();
  });

  it('values[2] is TemplateResult when hasActual=true', () => {
    const tile = makeMetricTile({ hasActual: true, actual: 95, plan: 100, unit: 'kWh' });
    const result = callMethod(el, 'renderMetricTile', 'Solár', tile) as TR;
    expect(result.values[2]).not.toBeNull();
  });

  it('actual tile has "better" class for non-cost when actual >= plan', () => {
    const tile = makeMetricTile({ hasActual: true, actual: 6.0, plan: 5.0, unit: 'kWh' });
    const result = callMethod(el, 'renderMetricTile', 'Solár', tile) as TR;
    const inner = result.values[2] as TR;
    expect(inner.values[0]).toBe('better');
  });

  it('actual tile has "worse" class for non-cost when actual < plan', () => {
    const tile = makeMetricTile({ hasActual: true, actual: 3.0, plan: 5.0, unit: 'kWh' });
    const result = callMethod(el, 'renderMetricTile', 'Solár', tile) as TR;
    const inner = result.values[2] as TR;
    expect(inner.values[0]).toBe('worse');
  });

  it('actual tile has "better" class for cost (Kč) when actual <= plan', () => {
    const tile = makeMetricTile({ hasActual: true, actual: 90, plan: 100, unit: 'Kč' });
    const result = callMethod(el, 'renderMetricTile', 'Náklady', tile) as TR;
    const inner = result.values[2] as TR;
    expect(inner.values[0]).toBe('better');
  });

  it('actual tile has "worse" class for cost (Kč) when actual > plan', () => {
    const tile = makeMetricTile({ hasActual: true, actual: 130, plan: 100, unit: 'Kč' });
    const result = callMethod(el, 'renderMetricTile', 'Náklady', tile) as TR;
    const inner = result.values[2] as TR;
    expect(inner.values[0]).toBe('worse');
  });

  it('plan uses formatCurrency for Kč unit', () => {
    const tile = makeMetricTile({ plan: 150, unit: 'Kč', hasActual: false });
    const result = callMethod(el, 'renderMetricTile', 'Náklady', tile) as TR;
    const planStr = result.values[1] as string;
    expect(planStr).not.toBe('150');
  });

  it('plan uses toFixed(1) for non-Kč unit', () => {
    const tile = makeMetricTile({ plan: 5.0, unit: 'kWh', hasActual: false });
    const result = callMethod(el, 'renderMetricTile', 'Solár', tile) as TR;
    const planStr = result.values[1] as string;
    expect(planStr).toContain('5.0');
    expect(planStr).toContain('kWh');
  });
});

describe('OigTimelineDialog — render() with null data', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    el = new OigTimelineDialog();
  });

  it('returns a TemplateResult', () => {
    const result = el.render();
    expect(result).toBeTruthy();
  });

  it('values[1] is autoRefresh boolean (true by default)', () => {
    const values = renderValues(el);
    expect(values[1]).toBe(true);
  });

  it('values[4] is an array of 5 tab TemplateResults', () => {
    const values = renderValues(el);
    expect(Array.isArray(values[4])).toBe(true);
    expect((values[4] as unknown[]).length).toBe(5);
  });

  it('values[5] is empty-state TemplateResult when data is null', () => {
    const values = renderValues(el);
    expect(values[5]).toBeTruthy();
    const emptyTR = values[5] as TR;
    expect(emptyTR.values).toBeDefined();
  });
});

describe('OigTimelineDialog — render() with data', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    el = new OigTimelineDialog();
    el.data = makeDayData();
  });

  it('values[5] is renderDayContent TemplateResult when data is set', () => {
    const values = renderValues(el);
    expect(values[5]).toBeTruthy();
  });

  it('values[1] reflects autoRefresh=false after toggle', () => {
    setPrivate(el, 'autoRefresh', false);
    const values = renderValues(el);
    expect(values[1]).toBe(false);
  });
});

describe('OigTimelineDialog — tab active state in render()', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    el = new OigTimelineDialog();
  });

  it('active tab inner template values[0] is "active" for matching tab', () => {
    el.activeTab = 'today';
    const values = renderValues(el);
    const tabs = values[4] as TR[];
    const todayTR = tabs[1] as TR;
    expect(todayTR.values[0]).toBe('active');
  });

  it('non-active tab inner template values[0] is "" for non-matching tab', () => {
    el.activeTab = 'today';
    const values = renderValues(el);
    const tabs = values[4] as TR[];
    const yesterdayTR = tabs[0] as TR;
    expect(yesterdayTR.values[0]).toBe('');
  });

  it('tab label is rendered in values[2] of each tab template', () => {
    const values = renderValues(el);
    const tabs = values[4] as TR[];
    expect(tabs[1].values[2]).toBe('📆 Dnes');
    expect(tabs[0].values[2]).toBe('📊 Včera');
    expect(tabs[2].values[2]).toBe('📅 Zítra');
  });
});

describe('OigTimelineDialog — renderDayContent() branches', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    el = new OigTimelineDialog();
  });

  function dayContent(data: TimelineDayData): TR {
    el.data = data;
    return callMethod(el, 'renderDayContent') as TR;
  }

  it('adherence values[0] is null when overallAdherence=0', () => {
    const data = makeDayData({ summary: { ...makeDayData().summary, overallAdherence: 0 } });
    const result = dayContent(data);
    expect(result.values[0]).toBeNull();
  });

  it('adherence values[0] is TemplateResult when overallAdherence > 0', () => {
    const data = makeDayData({ summary: { ...makeDayData().summary, overallAdherence: 85 } });
    const result = dayContent(data);
    expect(result.values[0]).not.toBeNull();
    expect((result.values[0] as TR).values).toBeDefined();
  });

  it('progress values[1] is null when progressPct is undefined', () => {
    const data = makeDayData();
    const result = dayContent(data);
    expect(result.values[1]).toBeNull();
  });

  it('progress values[1] is TemplateResult when progressPct is set', () => {
    const baseSummary = makeDayData().summary;
    const data = makeDayData({
      summary: { ...baseSummary, progressPct: 65, actualTotalCost: 78, planTotalCost: 120, vsPlanPct: 65 },
    });
    const result = dayContent(data);
    expect(result.values[1]).not.toBeNull();
  });

  it('eodPrediction values[2] is null when not set', () => {
    const data = makeDayData();
    const result = dayContent(data);
    expect(result.values[2]).toBeNull();
  });

  it('eodPrediction values[2] is TemplateResult when set', () => {
    const baseSummary = makeDayData().summary;
    const data = makeDayData({
      summary: {
        ...baseSummary,
        eodPrediction: { predictedTotal: 200, predictedSavings: 20 },
      },
    });
    const result = dayContent(data);
    expect(result.values[2]).not.toBeNull();
  });

  it('mode blocks values[7] is null when modeBlocks is empty', () => {
    const data = makeDayData({ modeBlocks: [] });
    const result = dayContent(data);
    expect(result.values[7]).toBeNull();
  });

  it('mode blocks values[7] is TemplateResult when modeBlocks has entries', () => {
    const data = makeDayData({ modeBlocks: [makeModeBlock()] });
    const result = dayContent(data);
    expect(result.values[7]).not.toBeNull();
  });

  it('comparison values[8] is null when no comparison', () => {
    const data = makeDayData();
    const result = dayContent(data);
    expect(result.values[8]).toBeNull();
  });

  it('comparison values[8] is TemplateResult when comparison is set', () => {
    const data = makeDayData({
      comparison: { plan: 'autonomy', modeBlocks: [makeModeBlock()] },
    });
    const result = dayContent(data);
    expect(result.values[8]).not.toBeNull();
  });

  it('metrics grid always has 4 tiles (values[3..6])', () => {
    const data = makeDayData();
    const result = dayContent(data);
    for (let i = 3; i <= 6; i++) {
      expect(result.values[i]).toBeTruthy();
    }
  });
});

describe('OigTimelineDialog — open property', () => {
  let el: OigTimelineDialog;

  beforeEach(() => {
    el = new OigTimelineDialog();
  });

  it('can be set to true', () => {
    el.open = true;
    expect(el.open).toBe(true);
  });

  it('defaults to false', () => {
    expect(el.open).toBe(false);
  });
});

// ─── OigTimelineTile ──────────────────────────────────────────────────────────

describe('OigTimelineTile — property defaults', () => {
  let el: OigTimelineTile;

  beforeEach(() => {
    el = new OigTimelineTile();
  });

  it('data defaults to null', () => {
    expect(el.data).toBeNull();
  });

  it('activeTab defaults to "today"', () => {
    expect(el.activeTab).toBe('today');
  });

  it('private autoRefresh defaults to true', () => {
    expect(getPrivate(el, 'autoRefresh')).toBe(true);
  });

  it('private refreshInterval defaults to null', () => {
    expect(getPrivate(el, 'refreshInterval')).toBeNull();
  });
});

describe('OigTimelineTile — onTabClick()', () => {
  let el: OigTimelineTile;

  beforeEach(() => {
    el = new OigTimelineTile();
  });

  it('sets activeTab to the given tab', () => {
    callMethod(el, 'onTabClick', 'yesterday');
    expect(el.activeTab).toBe('yesterday');
  });

  it('dispatches "tab-change" with detail.tab', () => {
    const handler = vi.fn();
    el.addEventListener('tab-change', handler);
    callMethod(el, 'onTabClick', 'detail');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toEqual({ tab: 'detail' });
  });

  it('tab-change event bubbles', () => {
    const handler = vi.fn();
    el.addEventListener('tab-change', handler);
    callMethod(el, 'onTabClick', 'history');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.bubbles).toBe(true);
  });
});

describe('OigTimelineTile — toggleAutoRefresh()', () => {
  let el: OigTimelineTile;

  beforeEach(() => {
    vi.useFakeTimers();
    el = new OigTimelineTile();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('flips autoRefresh from true to false', () => {
    setPrivate(el, 'autoRefresh', true);
    callMethod(el, 'toggleAutoRefresh');
    expect(getPrivate(el, 'autoRefresh')).toBe(false);
  });

  it('flips autoRefresh from false to true', () => {
    setPrivate(el, 'autoRefresh', false);
    callMethod(el, 'toggleAutoRefresh');
    expect(getPrivate(el, 'autoRefresh')).toBe(true);
  });
});

describe('OigTimelineTile — auto-refresh lifecycle', () => {
  let el: OigTimelineTile;

  beforeEach(() => {
    vi.useFakeTimers();
    el = new OigTimelineTile();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('interval dispatches "refresh" when autoRefresh=true', () => {
    setPrivate(el, 'autoRefresh', true);
    const handler = vi.fn();
    el.addEventListener('refresh', handler);
    callMethod(el, 'startAutoRefresh');
    vi.advanceTimersByTime(60000);
    expect(handler).toHaveBeenCalledOnce();
  });

  it('stopAutoRefresh clears interval and sets to null', () => {
    const clearSpy = vi.spyOn(window, 'clearInterval');
    setPrivate(el, 'refreshInterval', 55);
    callMethod(el, 'stopAutoRefresh');
    expect(clearSpy).toHaveBeenCalledWith(55);
    expect(getPrivate(el, 'refreshInterval')).toBeNull();
  });
});

describe('OigTimelineTile — fmtPct()', () => {
  let el: OigTimelineTile;

  beforeEach(() => {
    el = new OigTimelineTile();
  });

  it('formats 50.4 as "50%"', () => {
    expect(callMethod(el, 'fmtPct', 50.4)).toBe('50%');
  });
});

describe('OigTimelineTile — adherenceColor()', () => {
  let el: OigTimelineTile;

  beforeEach(() => {
    el = new OigTimelineTile();
  });

  it('returns green for >= 90', () => {
    expect(callMethod(el, 'adherenceColor', 90)).toBe('#4caf50');
  });

  it('returns orange for 70-89', () => {
    expect(callMethod(el, 'adherenceColor', 75)).toBe('#ff9800');
  });

  it('returns red for < 70', () => {
    expect(callMethod(el, 'adherenceColor', 60)).toBe('#f44336');
  });
});

describe('OigTimelineTile — getModeConfig()', () => {
  let el: OigTimelineTile;

  beforeEach(() => {
    el = new OigTimelineTile();
  });

  it('returns fallback for unknown mode', () => {
    const cfg = callMethod(el, 'getModeConfig', 'MYSTERY') as { icon: string; label: string };
    expect(cfg.icon).toBe('❓');
    expect(cfg.label).toBe('MYSTERY');
  });

  it('returns HOME II config', () => {
    const cfg = callMethod(el, 'getModeConfig', 'HOME II') as { icon: string; color: string };
    expect(cfg.color).toBe('#2196F3');
  });
});

describe('OigTimelineTile — render() with null data', () => {
  let el: OigTimelineTile;

  beforeEach(() => {
    el = new OigTimelineTile();
  });

  it('returns a TemplateResult', () => {
    expect(el.render()).toBeTruthy();
  });

  it('values has array of 5 tab TemplateResults', () => {
    const values = renderValues(el);
    const tabsVal = values.find((v) => Array.isArray(v));
    expect(tabsVal).toBeDefined();
    expect((tabsVal as unknown[]).length).toBe(5);
  });

  it('conditional slot is TemplateResult (empty-state) when data is null', () => {
    const values = renderValues(el);
    const conditional = values[values.length - 1];
    expect(conditional).toBeTruthy();
  });
});

describe('OigTimelineTile — render() with data', () => {
  let el: OigTimelineTile;

  beforeEach(() => {
    el = new OigTimelineTile();
    el.data = makeDayData();
  });

  it('conditional slot is renderDayContent TemplateResult when data is set', () => {
    const values = renderValues(el);
    const conditional = values[values.length - 1];
    expect(conditional).toBeTruthy();
  });
});

describe('OigTimelineTile — renderDayContent() branches', () => {
  let el: OigTimelineTile;

  beforeEach(() => {
    el = new OigTimelineTile();
  });

  function dayContent(data: TimelineDayData): TR {
    el.data = data;
    return callMethod(el, 'renderDayContent') as TR;
  }

  it('adherence values[0] is null when overallAdherence=0', () => {
    const data = makeDayData();
    const result = dayContent(data);
    expect(result.values[0]).toBeNull();
  });

  it('adherence values[0] is TemplateResult when overallAdherence > 0', () => {
    const data = makeDayData({ summary: { ...makeDayData().summary, overallAdherence: 92 } });
    const result = dayContent(data);
    expect(result.values[0]).not.toBeNull();
  });

  it('eodPrediction values[2] is null when not set', () => {
    const data = makeDayData();
    const result = dayContent(data);
    expect(result.values[2]).toBeNull();
  });

  it('eodPrediction values[2] is TemplateResult when set', () => {
    const baseSummary = makeDayData().summary;
    const data = makeDayData({
      summary: {
        ...baseSummary,
        eodPrediction: { predictedTotal: 300, predictedSavings: 0 },
      },
    });
    const result = dayContent(data);
    expect(result.values[2]).not.toBeNull();
  });

  it('mode blocks values[7] is null when modeBlocks is empty', () => {
    const data = makeDayData({ modeBlocks: [] });
    const result = dayContent(data);
    expect(result.values[7]).toBeNull();
  });

  it('mode blocks values[7] is TemplateResult when modeBlocks has entries', () => {
    const data = makeDayData({ modeBlocks: [makeModeBlock()] });
    const result = dayContent(data);
    expect(result.values[7]).not.toBeNull();
  });

  it('comparison values[8] is null when no comparison', () => {
    const result = dayContent(makeDayData());
    expect(result.values[8]).toBeNull();
  });

  it('comparison values[8] is TemplateResult when comparison set', () => {
    const data = makeDayData({
      comparison: { plan: 'hybrid', modeBlocks: [makeModeBlock()] },
    });
    const result = dayContent(data);
    expect(result.values[8]).not.toBeNull();
  });

  it('renderModeBlock is called for each modeBlock', () => {
    const spy = vi.spyOn(el as any, 'renderModeBlock');
    const blocks = [makeModeBlock(), makeModeBlock({ startTime: '10:00', endTime: '12:00' })];
    const data = makeDayData({ modeBlocks: blocks });
    dayContent(data);
    expect(spy).toHaveBeenCalledTimes(2);
  });
});

describe('OigTimelineTile — renderModeBlock()', () => {
  let el: OigTimelineTile;

  beforeEach(() => {
    el = new OigTimelineTile();
  });

  it('returns a TemplateResult', () => {
    const block = makeModeBlock();
    const result = callMethod(el, 'renderModeBlock', block);
    expect(result).toBeTruthy();
  });

  it('values[0] is "current" for current block', () => {
    const block = makeModeBlock({ status: 'current' });
    const result = callMethod(el, 'renderModeBlock', block) as TR;
    expect(result.values[0]).toBe('current');
  });

  it('values[6] is null for matching modes', () => {
    const block = makeModeBlock({ modeMatch: true });
    const result = callMethod(el, 'renderModeBlock', block) as TR;
    expect(result.values[6]).toBeNull();
  });

  it('values[6] is not null for mismatched modes', () => {
    const block = makeModeBlock({ modeMatch: false });
    const result = callMethod(el, 'renderModeBlock', block) as TR;
    expect(result.values[6]).not.toBeNull();
  });
});

describe('OigTimelineTile — renderMetricTile()', () => {
  let el: OigTimelineTile;

  beforeEach(() => {
    el = new OigTimelineTile();
  });

  it('values[0] is the label', () => {
    const tile = makeMetricTile();
    const result = callMethod(el, 'renderMetricTile', 'Spotřeba', tile) as TR;
    expect(result.values[0]).toBe('Spotřeba');
  });

  it('values[2] is null when hasActual=false', () => {
    const tile = makeMetricTile({ hasActual: false });
    const result = callMethod(el, 'renderMetricTile', 'Síť', tile) as TR;
    expect(result.values[2]).toBeNull();
  });

  it('better class when solar actual >= plan', () => {
    const tile = makeMetricTile({ hasActual: true, actual: 10, plan: 8, unit: 'kWh' });
    const result = callMethod(el, 'renderMetricTile', 'Solár', tile) as TR;
    const inner = result.values[2] as TR;
    expect(inner.values[0]).toBe('better');
  });

  it('worse class when cost actual > plan', () => {
    const tile = makeMetricTile({ hasActual: true, actual: 200, plan: 100, unit: 'Kč' });
    const result = callMethod(el, 'renderMetricTile', 'Náklady', tile) as TR;
    const inner = result.values[2] as TR;
    expect(inner.values[0]).toBe('worse');
  });
});
