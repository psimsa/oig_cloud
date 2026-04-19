import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { nothing } from 'lit';

vi.mock('chart.js', () => {
  const Chart = vi.fn().mockImplementation(() => ({
    data: { datasets: [], labels: [] },
    update: vi.fn(),
    destroy: vi.fn(),
  }));
  (Chart as any).register = vi.fn();
  return {
    Chart,
    CategoryScale: {},
    LinearScale: {},
    PointElement: {},
    LineElement: {},
    Filler: {},
    Tooltip: {},
    LineController: {},
  };
});

import { OigMiniSparkline, OigStatsCard, OigPricingStats } from '@/ui/features/pricing/stats';
import { Chart } from 'chart.js';
import type { PricingData, PriceBlock, PlannedConsumption } from '@/ui/features/pricing/types';

function getP<T>(el: object, key: string): T {
  return Reflect.get(el, key) as T;
}

function setP(el: object, key: string, value: unknown): void {
  Reflect.set(el, key, value);
}

function callP(el: object, name: string, ...args: unknown[]): unknown {
  const m = Reflect.get(el, name);
  if (typeof m !== 'function') throw new Error(`No method: ${name}`);
  return Reflect.apply(m, el, args);
}

function makeBlock(overrides: Partial<PriceBlock> = {}): PriceBlock {
  return {
    start: '2025-01-15T02:00:00',
    end: '2025-01-15T05:00:00',
    avg: 0.5,
    min: 0.3,
    max: 0.8,
    values: [0.3, 0.5, 0.8, 0.4, 0.6],
    type: 'cheapest-buy',
    ...overrides,
  };
}

function makeData(overrides: Partial<PricingData> = {}): PricingData {
  return {
    timeline: [{ timestamp: '2025-01-15T14:00:00' }],
    labels: [],
    prices: [],
    exportPrices: [],
    modeSegments: [],
    cheapestBuyBlock: null,
    expensiveBuyBlock: null,
    bestExportBlock: null,
    worstExportBlock: null,
    solar: null,
    battery: null,
    initialZoomStart: null,
    initialZoomEnd: null,
    currentSpotPrice: 1.5,
    currentExportPrice: 0.8,
    avgSpotPrice: 1.2,
    plannedConsumption: null,
    whatIf: null,
    solarForecastTotal: 0,
    ...overrides,
  };
}

function makePlannedConsumption(overrides: Partial<PlannedConsumption> = {}): PlannedConsumption {
  return {
    todayConsumedKwh: 5.2,
    todayPlannedKwh: 8.5,
    todayTotalKwh: 10.0,
    tomorrowKwh: 12.0,
    totalPlannedKwh: 20.5,
    profile: 'Standard',
    trendText: '↑ +10%',
    ...overrides,
  };
}

function injectCanvas(el: OigMiniSparkline): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  Object.defineProperty(el, 'canvas', { get: () => canvas, configurable: true });
  return canvas;
}

describe('OigMiniSparkline — property defaults', () => {
  let el: OigMiniSparkline;

  beforeEach(() => {
    el = new OigMiniSparkline();
  });

  it('values defaults to []', () => {
    expect(el.values).toEqual([]);
  });

  it('color defaults to rgba green', () => {
    expect(el.color).toBe('rgba(76, 175, 80, 1)');
  });

  it('startTime defaults to empty string', () => {
    expect(el.startTime).toBe('');
  });

  it('endTime defaults to empty string', () => {
    expect(el.endTime).toBe('');
  });
});

describe('OigMiniSparkline — private state defaults', () => {
  let el: OigMiniSparkline;

  beforeEach(() => {
    el = new OigMiniSparkline();
  });

  it('chart starts as null', () => {
    expect(getP(el, 'chart')).toBeNull();
  });

  it('lastDataKey starts as empty string', () => {
    expect(getP(el, 'lastDataKey')).toBe('');
  });

  it('initializing starts as false', () => {
    expect(getP(el, 'initializing')).toBe(false);
  });
});

describe('OigMiniSparkline — render()', () => {
  it('returns a template with a canvas element', () => {
    const el = new OigMiniSparkline();
    const result = el.render() as unknown as { strings: TemplateStringsArray };
    expect(result).toBeDefined();
    expect(result.strings.join('')).toContain('canvas');
  });
});

describe('OigMiniSparkline — destroyChart()', () => {
  let el: OigMiniSparkline;

  beforeEach(() => {
    el = new OigMiniSparkline();
  });

  it('does nothing when chart is null', () => {
    expect(() => callP(el, 'destroyChart')).not.toThrow();
    expect(getP(el, 'chart')).toBeNull();
  });

  it('calls chart.destroy() when chart exists', () => {
    const mockDestroy = vi.fn();
    setP(el, 'chart', { destroy: mockDestroy });
    callP(el, 'destroyChart');
    expect(mockDestroy).toHaveBeenCalledOnce();
  });

  it('sets chart to null after destruction', () => {
    setP(el, 'chart', { destroy: vi.fn() });
    callP(el, 'destroyChart');
    expect(getP(el, 'chart')).toBeNull();
  });
});

describe('OigMiniSparkline — disconnectedCallback()', () => {
  let el: OigMiniSparkline;

  beforeEach(() => {
    el = new OigMiniSparkline();
  });

  it('sets chart to null (calls destroyChart internally)', () => {
    setP(el, 'chart', { destroy: vi.fn() });
    el.disconnectedCallback();
    expect(getP(el, 'chart')).toBeNull();
  });

  it('does not throw when chart is null', () => {
    expect(() => el.disconnectedCallback()).not.toThrow();
  });
});

describe('OigMiniSparkline — updateOrCreateSparkline()', () => {
  let el: OigMiniSparkline;

  beforeEach(() => {
    el = new OigMiniSparkline();
    vi.mocked(Chart).mockClear();
  });

  it('returns early when canvas is null (no chart created)', () => {
    el.values = [1, 2, 3];
    callP(el, 'updateOrCreateSparkline');
    expect(vi.mocked(Chart)).not.toHaveBeenCalled();
  });

  it('returns early when values is empty', () => {
    injectCanvas(el);
    el.values = [];
    callP(el, 'updateOrCreateSparkline');
    expect(vi.mocked(Chart)).not.toHaveBeenCalled();
  });

  it('returns early if dataKey matches existing chart', () => {
    injectCanvas(el);
    el.values = [1, 2, 3];
    el.color = 'rgba(76, 175, 80, 1)';
    const dataKey = JSON.stringify({ v: [1, 2, 3], c: 'rgba(76, 175, 80, 1)' });
    setP(el, 'lastDataKey', dataKey);
    setP(el, 'chart', { data: { datasets: [{}], labels: [] }, update: vi.fn(), destroy: vi.fn() });
    callP(el, 'updateOrCreateSparkline');
    expect(vi.mocked(Chart)).not.toHaveBeenCalled();
  });

  it('creates a new Chart when canvas and values are present', () => {
    injectCanvas(el);
    el.values = [1.0, 2.0, 3.0];
    callP(el, 'updateOrCreateSparkline');
    expect(vi.mocked(Chart)).toHaveBeenCalledOnce();
  });

  it('sets lastDataKey after creation', () => {
    injectCanvas(el);
    el.values = [1.0, 2.0];
    el.color = 'rgba(76, 175, 80, 1)';
    callP(el, 'updateOrCreateSparkline');
    const expectedKey = JSON.stringify({ v: [1.0, 2.0], c: 'rgba(76, 175, 80, 1)' });
    expect(getP(el, 'lastDataKey')).toBe(expectedKey);
  });

  it('updates chart in-place when labels count matches', () => {
    injectCanvas(el);
    el.values = [1.0, 2.0, 3.0];
    el.color = 'rgba(76, 175, 80, 1)';

    const mockUpdate = vi.fn();
    const mockDataset = { data: [], borderColor: '', backgroundColor: '' };
    const mockChartInstance = {
      data: { datasets: [mockDataset], labels: ['a', 'b', 'c'] },
      update: mockUpdate,
      destroy: vi.fn(),
    };
    setP(el, 'chart', mockChartInstance);
    setP(el, 'lastDataKey', '');

    callP(el, 'updateOrCreateSparkline');
    expect(mockUpdate).toHaveBeenCalledWith('none');
    expect(mockDataset.data).toEqual([1.0, 2.0, 3.0]);
  });

  it('destroys and recreates chart when label count changes', () => {
    injectCanvas(el);
    el.values = [1.0, 2.0, 3.0, 4.0];
    el.color = 'rgba(76, 175, 80, 1)';

    const mockDestroy = vi.fn();
    const mockChartInstance = {
      data: { datasets: [{ data: [], borderColor: '', backgroundColor: '' }], labels: ['a', 'b', 'c'] },
      update: vi.fn(),
      destroy: mockDestroy,
    };
    setP(el, 'chart', mockChartInstance);
    setP(el, 'lastDataKey', '');

    callP(el, 'updateOrCreateSparkline');
    expect(mockDestroy).toHaveBeenCalled();
    expect(vi.mocked(Chart)).toHaveBeenCalled();
  });
});

describe('OigMiniSparkline — createSparkline()', () => {
  let el: OigMiniSparkline;

  beforeEach(() => {
    el = new OigMiniSparkline();
    vi.mocked(Chart).mockClear();
  });

  it('returns early when canvas is null', () => {
    el.values = [1, 2, 3];
    callP(el, 'createSparkline');
    expect(vi.mocked(Chart)).not.toHaveBeenCalled();
  });

  it('returns early when values is empty', () => {
    injectCanvas(el);
    callP(el, 'createSparkline');
    expect(vi.mocked(Chart)).not.toHaveBeenCalled();
  });

  it('creates a Chart instance with canvas and values', () => {
    const canvas = injectCanvas(el);
    el.values = [1.0, 2.5, 0.8];
    el.startTime = '2025-01-15T02:00:00';
    callP(el, 'createSparkline');
    expect(vi.mocked(Chart)).toHaveBeenCalledOnce();
    expect(vi.mocked(Chart)).toHaveBeenCalledWith(canvas, expect.objectContaining({ type: 'line' }));
  });

  it('assigns chart to this.chart', () => {
    injectCanvas(el);
    el.values = [1.0, 2.0];
    callP(el, 'createSparkline');
    expect(getP(el, 'chart')).not.toBeNull();
  });

  it('destroys existing chart before creating new one', () => {
    injectCanvas(el);
    el.values = [1.0, 2.0];
    const mockDestroy = vi.fn();
    setP(el, 'chart', { destroy: mockDestroy });
    callP(el, 'createSparkline');
    expect(mockDestroy).toHaveBeenCalled();
  });

  it('passes color to chart dataset configuration', () => {
    injectCanvas(el);
    el.values = [1.0, 2.0];
    el.color = 'rgba(244, 67, 54, 1)';
    callP(el, 'createSparkline');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    expect(config.data.datasets[0].borderColor).toBe('rgba(244, 67, 54, 1)');
  });

  it('generates time labels based on startTime', () => {
    injectCanvas(el);
    el.values = [1.0, 2.0];
    el.startTime = '2025-01-15T02:00:00';
    callP(el, 'createSparkline');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    expect(config.data.labels).toHaveLength(2);
  });
});

describe('OigMiniSparkline — firstUpdated()', () => {
  let el: OigMiniSparkline;

  beforeEach(() => {
    el = new OigMiniSparkline();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('does nothing when values is empty', () => {
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame');
    el.values = [];
    callP(el, 'firstUpdated');
    expect(rafSpy).not.toHaveBeenCalled();
    expect(getP(el, 'initializing')).toBe(false);
  });

  it('sets initializing=true and calls requestAnimationFrame when values present', () => {
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame').mockReturnValue(0 as any);
    el.values = [1, 2, 3];
    callP(el, 'firstUpdated');
    expect(getP(el, 'initializing')).toBe(true);
    expect(rafSpy).toHaveBeenCalledOnce();
  });

  it('rAF callback resets initializing to false', () => {
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
      cb(0);
      return 0 as any;
    });
    el.values = [1, 2, 3];
    callP(el, 'firstUpdated');
    expect(getP(el, 'initializing')).toBe(false);
  });
});

describe('OigMiniSparkline — updated()', () => {
  let el: OigMiniSparkline;

  beforeEach(() => {
    el = new OigMiniSparkline();
  });

  it('returns early when initializing is true', () => {
    setP(el, 'initializing', true);
    const updateSpy = vi.spyOn(el as any, 'updateOrCreateSparkline');
    callP(el, 'updated', new Map([['values', []]]));
    expect(updateSpy).not.toHaveBeenCalled();
  });

  it('calls updateOrCreateSparkline when values changed', () => {
    setP(el, 'initializing', false);
    const updateSpy = vi.spyOn(el as any, 'updateOrCreateSparkline');
    callP(el, 'updated', new Map([['values', []]]));
    expect(updateSpy).toHaveBeenCalledOnce();
  });

  it('calls updateOrCreateSparkline when color changed', () => {
    setP(el, 'initializing', false);
    const updateSpy = vi.spyOn(el as any, 'updateOrCreateSparkline');
    callP(el, 'updated', new Map([['color', 'old-color']]));
    expect(updateSpy).toHaveBeenCalledOnce();
  });

  it('does not call updateOrCreateSparkline when unrelated prop changed', () => {
    setP(el, 'initializing', false);
    const updateSpy = vi.spyOn(el as any, 'updateOrCreateSparkline');
    callP(el, 'updated', new Map([['startTime', '']]));
    expect(updateSpy).not.toHaveBeenCalled();
  });
});

describe('OigStatsCard — property defaults', () => {
  let el: OigStatsCard;

  beforeEach(() => {
    el = new OigStatsCard();
  });

  it('title defaults to empty string', () => {
    expect(el.title).toBe('');
  });

  it('time defaults to empty string', () => {
    expect(el.time).toBe('');
  });

  it('valueText defaults to empty string', () => {
    expect(el.valueText).toBe('');
  });

  it('value defaults to 0', () => {
    expect(el.value).toBe(0);
  });

  it('unit defaults to Kč/kWh', () => {
    expect(el.unit).toBe('Kč/kWh');
  });

  it('variant defaults to "default"', () => {
    expect(el.variant).toBe('default');
  });

  it('clickable defaults to false', () => {
    expect(el.clickable).toBe(false);
  });

  it('startTime defaults to empty string', () => {
    expect(el.startTime).toBe('');
  });

  it('endTime defaults to empty string', () => {
    expect(el.endTime).toBe('');
  });

  it('sparklineValues defaults to []', () => {
    expect(el.sparklineValues).toEqual([]);
  });

  it('sparklineColor defaults to rgba green', () => {
    expect(el.sparklineColor).toBe('rgba(76, 175, 80, 1)');
  });
});

describe('OigStatsCard — connectedCallback()', () => {
  let el: OigStatsCard;

  beforeEach(() => {
    el = new OigStatsCard();
  });

  it('adds click listener when clickable=true', () => {
    el.clickable = true;
    const addSpy = vi.spyOn(el, 'addEventListener');
    el.connectedCallback();
    expect(addSpy).toHaveBeenCalledWith('click', expect.any(Function));
  });

  it('does not add click listener when clickable=false', () => {
    el.clickable = false;
    const addSpy = vi.spyOn(el, 'addEventListener');
    el.connectedCallback();
    expect(addSpy).not.toHaveBeenCalled();
  });
});

describe('OigStatsCard — disconnectedCallback()', () => {
  let el: OigStatsCard;

  beforeEach(() => {
    el = new OigStatsCard();
  });

  it('removes click listener', () => {
    const removeSpy = vi.spyOn(el, 'removeEventListener');
    el.disconnectedCallback();
    expect(removeSpy).toHaveBeenCalledWith('click', expect.any(Function));
  });
});

describe('OigStatsCard — handleClick (private arrow fn)', () => {
  let el: OigStatsCard;

  beforeEach(() => {
    el = new OigStatsCard();
  });

  it('does not dispatch when clickable=false', () => {
    el.clickable = false;
    const handler = vi.fn();
    el.addEventListener('card-click', handler);
    callP(el, 'handleClick');
    expect(handler).not.toHaveBeenCalled();
  });

  it('dispatches card-click when clickable=true', () => {
    el.clickable = true;
    const handler = vi.fn();
    el.addEventListener('card-click', handler);
    callP(el, 'handleClick');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('card-click event detail contains startTime, endTime, value', () => {
    el.clickable = true;
    el.startTime = '2025-01-15T02:00:00';
    el.endTime = '2025-01-15T05:00:00';
    el.value = 0.75;
    const handler = vi.fn();
    el.addEventListener('card-click', handler);
    callP(el, 'handleClick');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toEqual({
      startTime: '2025-01-15T02:00:00',
      endTime: '2025-01-15T05:00:00',
      value: 0.75,
    });
  });

  it('card-click event bubbles', () => {
    el.clickable = true;
    const handler = vi.fn();
    el.addEventListener('card-click', handler);
    callP(el, 'handleClick');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.bubbles).toBe(true);
  });

  it('card-click event is composed', () => {
    el.clickable = true;
    const handler = vi.fn();
    el.addEventListener('card-click', handler);
    callP(el, 'handleClick');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.composed).toBe(true);
  });
});

describe('OigStatsCard — render(): template values', () => {
  it('values[0] is title', () => {
    const el = new OigStatsCard();
    el.title = 'Spot price';
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[0]).toBe('Spot price');
  });

  it('values[1] is variant class', () => {
    const el = new OigStatsCard();
    el.variant = 'success';
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[1]).toBe('success');
  });

  it('values[3] is nothing when time is empty', () => {
    const el = new OigStatsCard();
    el.time = '';
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[3]).toBe(nothing);
  });

  it('values[3] is a template when time is set', () => {
    const el = new OigStatsCard();
    el.time = '02:00 - 05:00';
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[3]).not.toBe(nothing);
    expect(result.values[3]).not.toBeNull();
  });

  it('values[4] is nothing when sparklineValues is empty', () => {
    const el = new OigStatsCard();
    el.sparklineValues = [];
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[4]).toBe(nothing);
  });

  it('values[4] is a template when sparklineValues has items', () => {
    const el = new OigStatsCard();
    el.sparklineValues = [1, 2, 3];
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[4]).not.toBe(nothing);
    expect(result.values[4]).not.toBeNull();
  });

  it('displayValue uses valueText when set', () => {
    const el = new OigStatsCard();
    el.valueText = 'Custom text';
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[2]).toBe('Custom text');
  });

  it('displayValue formats value.toFixed(2) when valueText is empty', () => {
    const el = new OigStatsCard();
    el.value = 1.5;
    el.unit = 'Kč/kWh';
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[2]).toContain('1.50');
    expect(result.values[2]).toContain('Kč/kWh');
  });
});

describe('OigPricingStats — property defaults', () => {
  let el: OigPricingStats;

  beforeEach(() => {
    el = new OigPricingStats();
  });

  it('data defaults to null', () => {
    expect(el.data).toBeNull();
  });

  it('topOnly defaults to false', () => {
    expect(el.topOnly).toBe(false);
  });
});

describe('OigPricingStats — render() with no data', () => {
  it('returns loading div when data is null and topOnly=false', () => {
    const el = new OigPricingStats();
    el.data = null;
    el.topOnly = false;
    const result = el.render() as unknown as { strings: TemplateStringsArray; values: unknown[] };
    expect(result.strings.join('')).toContain('Načítání cenových dat');
  });

  it('returns nothing when data is null and topOnly=true', () => {
    const el = new OigPricingStats();
    el.data = null;
    el.topOnly = true;
    expect(el.render()).toBe(nothing);
  });

  it('returns loading div when data has empty timeline and topOnly=false', () => {
    const el = new OigPricingStats();
    el.data = makeData({ timeline: [] });
    el.topOnly = false;
    const result = el.render() as unknown as { strings: TemplateStringsArray; values: unknown[] };
    expect(result.strings.join('')).toContain('Načítání cenových dat');
  });

  it('returns nothing when data has empty timeline and topOnly=true', () => {
    const el = new OigPricingStats();
    el.data = makeData({ timeline: [] });
    el.topOnly = true;
    expect(el.render()).toBe(nothing);
  });
});

describe('OigPricingStats — render() with data', () => {
  it('returns top-row template when topOnly=true and data has timeline', () => {
    const el = new OigPricingStats();
    el.data = makeData();
    el.topOnly = true;
    const result = el.render() as unknown as { strings: TemplateStringsArray };
    expect(result.strings.join('')).toContain('top-row');
  });

  it('wraps renderPlannedConsumption result when topOnly=false and data has timeline', () => {
    const el = new OigPricingStats();
    el.data = makeData();
    el.topOnly = false;
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[0]).toBe(nothing);
  });

  it('returns planned section template when plannedConsumption is set', () => {
    const el = new OigPricingStats();
    el.data = makeData({ plannedConsumption: makePlannedConsumption() });
    el.topOnly = false;
    const outer = el.render() as unknown as { values: unknown[] };
    const inner = outer.values[0] as { strings: TemplateStringsArray };
    expect(inner.strings.join('')).toContain('planned-section');
  });
});

describe('OigPricingStats — onCardClick()', () => {
  let el: OigPricingStats;

  beforeEach(() => {
    el = new OigPricingStats();
  });

  it('dispatches zoom-to-block event', () => {
    const handler = vi.fn();
    el.addEventListener('zoom-to-block', handler);
    const detail = { startTime: '2025-01-15T02:00:00', endTime: '2025-01-15T05:00:00', value: 0.5 };
    const fakeCardClick = new CustomEvent('card-click', { detail });
    callP(el, 'onCardClick', fakeCardClick);
    expect(handler).toHaveBeenCalledOnce();
  });

  it('zoom-to-block carries same detail as card-click', () => {
    const handler = vi.fn();
    el.addEventListener('zoom-to-block', handler);
    const detail = { startTime: 'T02', endTime: 'T05', value: 1.23 };
    const fakeCardClick = new CustomEvent('card-click', { detail });
    callP(el, 'onCardClick', fakeCardClick);
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toEqual(detail);
  });

  it('zoom-to-block event bubbles', () => {
    const handler = vi.fn();
    el.addEventListener('zoom-to-block', handler);
    callP(el, 'onCardClick', new CustomEvent('card-click', { detail: {} }));
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.bubbles).toBe(true);
  });
});

describe('OigPricingStats — renderPriceTiles()', () => {
  it('returns nothing when data is null', () => {
    const el = new OigPricingStats();
    el.data = null;
    expect(callP(el, 'renderPriceTiles')).toBe(nothing);
  });

  it('returns template when data is set', () => {
    const el = new OigPricingStats();
    el.data = makeData({ currentSpotPrice: 1.5, currentExportPrice: 0.8, solarForecastTotal: 0 });
    const result = callP(el, 'renderPriceTiles') as { strings: TemplateStringsArray };
    expect(result.strings.join('')).toContain('price-tile');
  });

  it('shows "Předpověď" when solarForecastTotal > 0', () => {
    const el = new OigPricingStats();
    el.data = makeData({ solarForecastTotal: 5.5 });
    const result = callP(el, 'renderPriceTiles') as unknown as { values: unknown[] };
    expect(result.values[3]).toBe('Předpověď');
  });

  it('shows "Nedostupná" when solarForecastTotal is 0', () => {
    const el = new OigPricingStats();
    el.data = makeData({ solarForecastTotal: 0 });
    const result = callP(el, 'renderPriceTiles') as unknown as { values: unknown[] };
    expect(result.values[3]).toBe('Nedostupná');
  });
});

describe('OigPricingStats — renderBlockCard()', () => {
  it('returns nothing when block is null', () => {
    const el = new OigPricingStats();
    const result = callP(el, 'renderBlockCard', 'Test', null, 'success', 'rgba(76, 175, 80, 1)');
    expect(result).toBe(nothing);
  });

  it('returns stats-card template when block is set', () => {
    const el = new OigPricingStats();
    const block = makeBlock();
    const result = callP(el, 'renderBlockCard', 'Nejlevnější', block, 'success', 'rgba(76, 175, 80, 1)') as { strings: TemplateStringsArray };
    expect(result.strings.join('')).toContain('oig-stats-card');
  });

  it('passes title to stats-card template', () => {
    const el = new OigPricingStats();
    const block = makeBlock();
    const result = callP(el, 'renderBlockCard', 'Custom Title', block, 'danger', 'rgba(244, 67, 54, 1)') as unknown as { values: unknown[] };
    expect(result.values[0]).toBe('Custom Title');
  });
});

describe('OigPricingStats — renderExtremeBlocks()', () => {
  it('returns nothing when data is null', () => {
    const el = new OigPricingStats();
    el.data = null;
    expect(callP(el, 'renderExtremeBlocks')).toBe(nothing);
  });

  it('returns template with 4 block cards when data is set', () => {
    const el = new OigPricingStats();
    el.data = makeData({
      cheapestBuyBlock: makeBlock({ type: 'cheapest-buy' }),
      expensiveBuyBlock: makeBlock({ type: 'expensive-buy' }),
      bestExportBlock: makeBlock({ type: 'best-export' }),
      worstExportBlock: makeBlock({ type: 'worst-export' }),
    });
    const result = callP(el, 'renderExtremeBlocks') as unknown as { values: unknown[] };
    expect(result.values).toHaveLength(4);
  });
});

describe('OigPricingStats — renderPlannedConsumption()', () => {
  it('returns nothing when plannedConsumption is null', () => {
    const el = new OigPricingStats();
    el.data = makeData({ plannedConsumption: null });
    expect(callP(el, 'renderPlannedConsumption')).toBe(nothing);
  });

  it('returns nothing when data is null', () => {
    const el = new OigPricingStats();
    el.data = null;
    expect(callP(el, 'renderPlannedConsumption')).toBe(nothing);
  });

  it('returns planned-section template when plannedConsumption is set', () => {
    const el = new OigPricingStats();
    el.data = makeData({ plannedConsumption: makePlannedConsumption() });
    const result = callP(el, 'renderPlannedConsumption') as { strings: TemplateStringsArray };
    expect(result.strings.join('')).toContain('planned-section');
  });

  it('shows trendText in template when trendText is set', () => {
    const el = new OigPricingStats();
    el.data = makeData({ plannedConsumption: makePlannedConsumption({ trendText: '↑ +15%' }) });
    const result = callP(el, 'renderPlannedConsumption') as unknown as { values: unknown[] };
    expect(result.values).not.toContain(nothing);
  });

  it('shows nothing for trendText slot when trendText is null', () => {
    const el = new OigPricingStats();
    el.data = makeData({ plannedConsumption: makePlannedConsumption({ trendText: null }) });
    const result = callP(el, 'renderPlannedConsumption') as unknown as { values: unknown[] };
    expect(result.values.includes(nothing)).toBe(true);
  });

  it('renders bar section when todayTotalKwh > 0', () => {
    const el = new OigPricingStats();
    el.data = makeData({
      plannedConsumption: makePlannedConsumption({ todayTotalKwh: 10, tomorrowKwh: 5 }),
    });
    const result = callP(el, 'renderPlannedConsumption') as unknown as { values: unknown[] };
    const lastValue = result.values[result.values.length - 1];
    expect(lastValue).not.toBe(nothing);
  });

  it('shows nothing for bar section when total is 0', () => {
    const el = new OigPricingStats();
    el.data = makeData({
      plannedConsumption: makePlannedConsumption({ todayTotalKwh: 0, tomorrowKwh: 0, totalPlannedKwh: 0 }),
    });
    const result = callP(el, 'renderPlannedConsumption') as unknown as { values: unknown[] };
    const lastValue = result.values[result.values.length - 1];
    expect(lastValue).toBe(nothing);
  });

  it('shows "--" for todayPlannedKwh when null', () => {
    const el = new OigPricingStats();
    el.data = makeData({
      plannedConsumption: makePlannedConsumption({ todayPlannedKwh: null }),
    });
    const result = callP(el, 'renderPlannedConsumption') as unknown as { values: unknown[] };
    expect(result.values).toContain('--');
  });

  it('formats todayConsumedKwh with 1 decimal place', () => {
    const el = new OigPricingStats();
    el.data = makeData({
      plannedConsumption: makePlannedConsumption({ todayConsumedKwh: 5.25 }),
    });
    const result = callP(el, 'renderPlannedConsumption') as unknown as { values: unknown[] };
    const stringValues = result.values.filter((v) => typeof v === 'string');
    expect(stringValues.some((v) => (v as string).includes('5.3'))).toBe(true);
  });

  it('sets profile text in template values', () => {
    const el = new OigPricingStats();
    el.data = makeData({
      plannedConsumption: makePlannedConsumption({ profile: 'High Usage' }),
    });
    const result = callP(el, 'renderPlannedConsumption') as unknown as { values: unknown[] };
    expect(result.values).toContain('High Usage');
  });
});

describe('OigPricingStats — formatBlockTimeRange (via renderBlockCard)', () => {
  it('formats block time range as date + time range', () => {
    const el = new OigPricingStats();
    const block: PriceBlock = {
      start: '2025-01-15T02:00:00',
      end: '2025-01-15T05:00:00',
      avg: 0.5,
      min: 0.3,
      max: 0.8,
      values: [0.3, 0.5],
      type: 'cheapest-buy',
    };
    const result = callP(el, 'renderBlockCard', 'Test', block, 'success', 'rgba(76, 175, 80, 1)') as unknown as { values: unknown[] };
    const timeValue = result.values[2] as string;
    expect(typeof timeValue).toBe('string');
    expect(timeValue.length).toBeGreaterThan(0);
    expect(timeValue).toMatch(/[\d:.-]/);
  });
});
