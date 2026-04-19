import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { nothing } from 'lit';

// ============================================================================
// MOCKS — hoisted before imports
// ============================================================================

vi.mock('chart.js', () => {
  const Chart = vi.fn().mockImplementation((_canvas: unknown, config: any) => ({
    data: {
      datasets: config?.data?.datasets ?? [],
      labels: config?.data?.labels ?? [],
    },
    update: vi.fn(),
    destroy: vi.fn(),
    resize: vi.fn(),
    scales: { x: { min: 0, max: 86400000 } }, // 24h default
    options: {
      plugins: {
        legend: { labels: { padding: 10, font: { size: 11 } } },
        pricingModeIcons: null,
      },
      scales: {
        x: {
          ticks: { maxTicksLimit: 20, font: { size: 11 } },
          time: { displayFormats: { hour: 'dd.MM HH:mm' } },
        },
        'y-price': {
          title: { display: true, font: { size: 13 } },
          ticks: { font: { size: 11 } },
          display: true,
        },
        'y-solar': {
          title: { display: true, font: { size: 11 } },
          ticks: { font: { size: 11 } },
          display: true,
        },
        'y-power': {
          title: { display: true, font: { size: 13 } },
          ticks: { font: { size: 11 } },
          display: true,
        },
      },
    },
  }));
  (Chart as any).register = vi.fn();
  return {
    Chart,
    CategoryScale: {},
    LinearScale: {},
    TimeSeriesScale: {},
    TimeScale: {},
    PointElement: {},
    LineElement: {},
    BarElement: {},
    Filler: {},
    Legend: {},
    Title: {},
    Tooltip: {},
    LineController: {},
    BarController: {},
  };
});

vi.mock('chartjs-adapter-date-fns', () => ({}));
vi.mock('chartjs-plugin-zoom', () => ({ default: { id: 'zoom' } }));
vi.mock('chartjs-plugin-datalabels', () => ({ default: { id: 'datalabels' } }));
vi.mock('@/ui/features/pricing/mode-icon-plugin', () => ({
  pricingModeIconPlugin: { id: 'pricingModeIcons' },
  applyModeIconPadding: vi.fn(),
}));

// ============================================================================
// IMPORTS
// ============================================================================

import { OigPricingChart } from '@/ui/features/pricing/chart';
import { Chart } from 'chart.js';
import { applyModeIconPadding } from '@/ui/features/pricing/mode-icon-plugin';
import type {
  PricingData,
  SolarForecastData,
  BatteryForecastArrays,
} from '@/ui/features/pricing/types';

// ============================================================================
// HELPERS
// ============================================================================

function getP<T>(el: object, key: string): T {
  return Reflect.get(el, key) as T;
}

function setP(el: object, key: string, value: unknown): void {
  Reflect.set(el, key, value);
}

function callP(el: object, name: string, ...args: unknown[]): unknown {
  const m = Reflect.get(el, name);
  if (typeof m !== 'function') throw new Error(`No method: ${name}`);
  return Reflect.apply(m as (...a: unknown[]) => unknown, el, args);
}

function injectCanvas(el: OigPricingChart): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  Object.defineProperty(el, 'canvas', { get: () => canvas, configurable: true });
  return canvas;
}

/** Get the most recently created Chart mock instance */
function lastChartInstance(): any {
  const results = vi.mocked(Chart).mock.results;
  return results[results.length - 1]?.value;
}

// ============================================================================
// DATA FACTORIES
// ============================================================================

function makeTimeline(n = 4) {
  return Array.from({ length: n }, (_, i) => ({
    timestamp: `2025-01-15T${String(i).padStart(2, '0')}:00:00`,
    spot_price_czk: 1.5 + i * 0.1,
    export_price_czk: 0.8 + i * 0.05,
  }));
}

function makeData(overrides: Partial<PricingData> = {}): PricingData {
  return {
    timeline: makeTimeline(),
    labels: [new Date('2025-01-15T00:00:00'), new Date('2025-01-15T01:00:00')],
    prices: [{ timestamp: '2025-01-15T00:00:00', price: 1.5 }],
    exportPrices: [{ timestamp: '2025-01-15T00:00:00', price: 0.8 }],
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

function makeSolar(overrides: Partial<SolarForecastData> = {}): SolarForecastData {
  return {
    string1: [0.5, 1.0, 1.5, 2.0],
    string2: [0.3, 0.8, 1.2, 1.8],
    todayTotal: 5.5,
    hasString1: true,
    hasString2: false,
    ...overrides,
  };
}

function makeBattery(overrides: Partial<BatteryForecastArrays> = {}): BatteryForecastArrays {
  return {
    baseline: [10, 12, 14, 16],
    solarCharge: [0, 1, 2, 3],
    gridCharge: [1, 0, 0, 0],
    gridNet: [0.5, null, 0.2, null],
    consumption: [2, 2, 2, 2],
    ...overrides,
  };
}

// ============================================================================
// TESTS
// ============================================================================

describe('OigPricingChart — property and state defaults', () => {
  let el: OigPricingChart;

  beforeEach(() => {
    el = new OigPricingChart();
  });

  it('data defaults to null', () => {
    expect(el.data).toBeNull();
  });

  it('datalabelMode defaults to "auto"', () => {
    expect(el.datalabelMode).toBe('auto');
  });

  it('private chart starts as null', () => {
    expect(getP(el, 'chart')).toBeNull();
  });

  it('private resizeObserver starts as null', () => {
    expect(getP(el, 'resizeObserver')).toBeNull();
  });

  it('zoomState starts as { start: null, end: null }', () => {
    expect(getP(el, 'zoomState')).toEqual({ start: null, end: null });
  });

  it('currentDetailLevel starts as "overview"', () => {
    expect(getP(el, 'currentDetailLevel')).toBe('overview');
  });
});

// ============================================================================
// render()
// ============================================================================

describe('OigPricingChart — render(): no data', () => {
  it('returns no-data div when data is null', () => {
    const el = new OigPricingChart();
    const result = el.render() as unknown as { values: unknown[] };
    const noDataTemplate = result.values[1] as { strings: readonly string[] };
    expect(noDataTemplate.strings.join('')).toContain('no-data');
  });

  it('does not render chart-hint when data is null', () => {
    const el = new OigPricingChart();
    const result = el.render() as unknown as { values: unknown[] };
    // values[2] is the chart-hint conditional
    expect(result.values[2]).toBeNull();
  });

  it('returns no-data when data has empty timeline', () => {
    const el = new OigPricingChart();
    el.data = makeData({ timeline: [] });
    const result = el.render() as unknown as { strings: readonly string[] };
    expect(result.strings.join('')).toContain('chart-container');
  });
});

describe('OigPricingChart — render(): with data', () => {
  it('renders canvas when data has timeline', () => {
    const el = new OigPricingChart();
    el.data = makeData();
    const result = el.render() as unknown as { values: unknown[] };
    // values[1] should be the canvas template (not nothing/no-data div)
    expect(result.values[1]).not.toBeNull();
  });

  it('renders chart-hint when data has timeline', () => {
    const el = new OigPricingChart();
    el.data = makeData();
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[2]).not.toBeNull();
  });
});

// ============================================================================
// renderControls()
// ============================================================================

describe('OigPricingChart — renderControls()', () => {
  it('returns a TemplateResult', () => {
    const el = new OigPricingChart();
    const result = callP(el, 'renderControls');
    expect(result).toBeTruthy();
    expect(result).not.toBe(nothing);
  });

  it('reset-btn slot is null when not zoomed', () => {
    const el = new OigPricingChart();
    const result = callP(el, 'renderControls') as unknown as { values: unknown[] };
    expect(result.values[6]).toBeNull();
  });

  it('reset-btn slot is shown when zoomed', () => {
    const el = new OigPricingChart();
    setP(el, 'zoomState', { start: 1000, end: 2000 });
    const result = callP(el, 'renderControls') as unknown as { values: unknown[] };
    expect(result.values[6]).not.toBeNull();
  });

  it('isZoomed returns false when both start and end are null', () => {
    const el = new OigPricingChart();
    expect(getP(el, 'isZoomed')).toBe(false);
  });

  it('isZoomed returns true when start is set', () => {
    const el = new OigPricingChart();
    setP(el, 'zoomState', { start: 1000, end: null });
    expect(getP(el, 'isZoomed')).toBe(true);
  });

  it('isZoomed returns true when end is set', () => {
    const el = new OigPricingChart();
    setP(el, 'zoomState', { start: null, end: 2000 });
    expect(getP(el, 'isZoomed')).toBe(true);
  });

  it('modeClass shows "active" for matching datalabelMode', () => {
    const el = new OigPricingChart();
    el.datalabelMode = 'always';
    const result = callP(el, 'renderControls') as unknown as { values: unknown[] };
    expect(String(result.values[2])).toContain('active');
  });

  it('modeClass includes mode-always class when mode is always', () => {
    const el = new OigPricingChart();
    el.datalabelMode = 'always';
    const result = callP(el, 'renderControls') as unknown as { values: unknown[] };
    expect(String(result.values[2])).toContain('mode-always');
  });

  it('modeClass includes mode-never class when mode is never', () => {
    const el = new OigPricingChart();
    el.datalabelMode = 'never';
    const result = callP(el, 'renderControls') as unknown as { values: unknown[] };
    expect(String(result.values[4])).toContain('mode-never');
  });
});

// ============================================================================
// setDatalabelMode()
// ============================================================================

describe('OigPricingChart — setDatalabelMode()', () => {
  let el: OigPricingChart;

  beforeEach(() => {
    el = new OigPricingChart();
  });

  it('updates datalabelMode property', () => {
    callP(el, 'setDatalabelMode', 'always');
    expect(el.datalabelMode).toBe('always');
  });

  it('dispatches datalabel-mode-change event', () => {
    const handler = vi.fn();
    el.addEventListener('datalabel-mode-change', handler);
    callP(el, 'setDatalabelMode', 'never');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('event detail contains the new mode', () => {
    const handler = vi.fn();
    el.addEventListener('datalabel-mode-change', handler);
    callP(el, 'setDatalabelMode', 'always');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toEqual({ mode: 'always' });
  });

  it('event bubbles', () => {
    const handler = vi.fn();
    el.addEventListener('datalabel-mode-change', handler);
    callP(el, 'setDatalabelMode', 'auto');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.bubbles).toBe(true);
  });

  it('event is composed', () => {
    const handler = vi.fn();
    el.addEventListener('datalabel-mode-change', handler);
    callP(el, 'setDatalabelMode', 'auto');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.composed).toBe(true);
  });
});

// ============================================================================
// getChart()
// ============================================================================

describe('OigPricingChart — getChart()', () => {
  it('returns null when no chart has been created', () => {
    const el = new OigPricingChart();
    expect(el.getChart()).toBeNull();
  });

  it('returns the chart instance after createChart()', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    expect(el.getChart()).not.toBeNull();
  });
});

// ============================================================================
// destroyChart()
// ============================================================================

describe('OigPricingChart — destroyChart()', () => {
  let el: OigPricingChart;

  beforeEach(() => {
    el = new OigPricingChart();
  });

  it('does not throw when chart is null', () => {
    expect(() => callP(el, 'destroyChart')).not.toThrow();
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

// ============================================================================
// setupResizeObserver()
// ============================================================================

describe('OigPricingChart — setupResizeObserver()', () => {
  let el: OigPricingChart;

  beforeEach(() => {
    el = new OigPricingChart();
    vi.mocked(ResizeObserver).mockClear();
  });

  it('creates a ResizeObserver instance', () => {
    callP(el, 'setupResizeObserver');
    expect(ResizeObserver).toHaveBeenCalledOnce();
  });

  it('stores resizeObserver reference', () => {
    callP(el, 'setupResizeObserver');
    expect(getP(el, 'resizeObserver')).not.toBeNull();
  });

  it('calls observe(el) on the ResizeObserver', () => {
    callP(el, 'setupResizeObserver');
    const mockObserver = vi.mocked(ResizeObserver).mock.results[0].value;
    expect(mockObserver.observe).toHaveBeenCalledWith(el);
  });

  it('ResizeObserver callback calls chart.resize()', () => {
    const mockResize = vi.fn();
    setP(el, 'chart', { resize: mockResize });

    // Get the callback passed to ResizeObserver
    callP(el, 'setupResizeObserver');
    const ctor = vi.mocked(ResizeObserver);
    const resizeCallback = ctor.mock.calls[ctor.mock.calls.length - 1][0];
    resizeCallback([] as any, {} as any);
    expect(mockResize).toHaveBeenCalledOnce();
  });
});

// ============================================================================
// disconnectedCallback()
// ============================================================================

describe('OigPricingChart — disconnectedCallback()', () => {
  let el: OigPricingChart;

  beforeEach(() => {
    el = new OigPricingChart();
  });

  it('does not throw when chart and resizeObserver are null', () => {
    expect(() => el.disconnectedCallback()).not.toThrow();
  });

  it('destroys chart on disconnect', () => {
    const mockDestroy = vi.fn();
    setP(el, 'chart', { destroy: mockDestroy });
    el.disconnectedCallback();
    expect(mockDestroy).toHaveBeenCalledOnce();
  });

  it('chart is null after disconnect', () => {
    setP(el, 'chart', { destroy: vi.fn() });
    el.disconnectedCallback();
    expect(getP(el, 'chart')).toBeNull();
  });

  it('disconnects resizeObserver on disconnect', () => {
    const mockDisconnect = vi.fn();
    setP(el, 'resizeObserver', { disconnect: mockDisconnect });
    el.disconnectedCallback();
    expect(mockDisconnect).toHaveBeenCalledOnce();
  });

  it('resizeObserver is null after disconnect', () => {
    setP(el, 'resizeObserver', { disconnect: vi.fn() });
    el.disconnectedCallback();
    expect(getP(el, 'resizeObserver')).toBeNull();
  });
});

// ============================================================================
// getTextColor() / getGridColor()
// ============================================================================

describe('OigPricingChart — getTextColor()', () => {
  it('returns fallback color when CSS variable is empty', () => {
    const el = new OigPricingChart();
    const color = callP(el, 'getTextColor') as string;
    expect(color).toBe('#e0e0e0');
  });

  it('does not throw', () => {
    const el = new OigPricingChart();
    expect(() => callP(el, 'getTextColor')).not.toThrow();
  });
});

describe('OigPricingChart — getGridColor()', () => {
  it('returns fallback color when CSS variable is empty', () => {
    const el = new OigPricingChart();
    const color = callP(el, 'getGridColor') as string;
    expect(color).toBe('rgba(255,255,255,0.1)');
  });

  it('does not throw', () => {
    const el = new OigPricingChart();
    expect(() => callP(el, 'getGridColor')).not.toThrow();
  });
});

// ============================================================================
// createChart()
// ============================================================================

describe('OigPricingChart — createChart() — guard conditions', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('does not create chart when canvas is null', () => {
    const el = new OigPricingChart();
    el.data = makeData();
    callP(el, 'createChart');
    expect(vi.mocked(Chart)).not.toHaveBeenCalled();
  });

  it('does not create chart when data is null', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    callP(el, 'createChart');
    expect(vi.mocked(Chart)).not.toHaveBeenCalled();
  });

  it('does not create chart when timeline is empty', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ timeline: [] });
    callP(el, 'createChart');
    expect(vi.mocked(Chart)).not.toHaveBeenCalled();
  });
});

describe('OigPricingChart — createChart() — happy path', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('creates a Chart.js instance', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    expect(vi.mocked(Chart)).toHaveBeenCalledOnce();
  });

  it('creates chart with "bar" type', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    expect(config.type).toBe('bar');
  });

  it('creates chart with the injected canvas', () => {
    const el = new OigPricingChart();
    const canvas = injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    expect(vi.mocked(Chart).mock.calls[0][0]).toBe(canvas);
  });

  it('stores chart instance in this.chart', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    expect(getP(el, 'chart')).not.toBeNull();
  });

  it('destroys existing chart before creating new one', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    const mockDestroy = vi.fn();
    setP(el, 'chart', { destroy: mockDestroy });
    callP(el, 'createChart');
    expect(mockDestroy).toHaveBeenCalledOnce();
  });

  it('chart config has responsive = true', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    expect(config.options.responsive).toBe(true);
  });

  it('chart config has interaction mode "index"', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    expect(config.options.interaction.mode).toBe('index');
  });

  it('chart config has animation duration 0', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    expect(config.options.animation.duration).toBe(0);
  });

  it('chart config has zoom plugin with wheel enabled', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    expect(config.options.plugins.zoom.zoom.wheel.enabled).toBe(true);
  });

  it('chart config has pan plugin with shift modifier', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    expect(config.options.plugins.zoom.pan.modifierKey).toBe('shift');
  });

  it('chart config has x-axis of timeseries type', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    expect(config.options.scales.x.type).toBe('timeseries');
  });

  it('chart config has three y-axes', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    expect(config.options.scales['y-price']).toBeDefined();
    expect(config.options.scales['y-solar']).toBeDefined();
    expect(config.options.scales['y-power']).toBeDefined();
  });

  it('calls applyModeIconPadding', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    expect(applyModeIconPadding).toHaveBeenCalled();
  });

  it('tooltip title callback returns formatted date string', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const title = config.options.plugins.tooltip.callbacks.title;
    const result = title([{ parsed: { x: new Date('2025-01-15T14:00:00').getTime() } }]);
    expect(typeof result).toBe('string');
    expect(result.length).toBeGreaterThan(0);
  });

  it('tooltip title callback returns empty string for empty array', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const title = config.options.plugins.tooltip.callbacks.title;
    expect(title([])).toBe('');
  });

  it('tooltip label callback appends Kč/kWh for y-price axis', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const label = config.options.plugins.tooltip.callbacks.label;
    const result = label({
      dataset: { label: 'Spot price', yAxisID: 'y-price' },
      parsed: { y: 1.5 },
    });
    expect(result).toContain('Kč/kWh');
    expect(result).toContain('1.50');
  });

  it('tooltip label callback appends kWh for y-solar axis', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const label = config.options.plugins.tooltip.callbacks.label;
    const result = label({
      dataset: { label: 'Battery', yAxisID: 'y-solar' },
      parsed: { y: 10.5 },
    });
    expect(result).toContain('kWh');
    expect(result).toContain('10.50');
  });

  it('tooltip label callback appends kW for y-power axis', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const label = config.options.plugins.tooltip.callbacks.label;
    const result = label({
      dataset: { label: 'Solar', yAxisID: 'y-power' },
      parsed: { y: 2.5 },
    });
    expect(result).toContain('kW');
    expect(result).toContain('2.50');
  });

  it('tooltip label callback returns raw value for unknown axis', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const label = config.options.plugins.tooltip.callbacks.label;
    const result = label({
      dataset: { label: 'Test', yAxisID: 'y-unknown' },
      parsed: { y: 42 },
    });
    expect(result).toContain('42');
  });

  it('zoom onZoomComplete callback resets zoomState', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    setP(el, 'zoomState', { start: 1000, end: 2000 });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const onZoomComplete = config.options.plugins.zoom.zoom.onZoomComplete;
    onZoomComplete({ chart: lastChartInstance() });
    expect(getP(el, 'zoomState')).toEqual({ start: null, end: null });
  });

  it('pan onPanComplete callback resets zoomState', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    setP(el, 'zoomState', { start: 1000, end: 2000 });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const onPanComplete = config.options.plugins.zoom.pan.onPanComplete;
    onPanComplete({ chart: lastChartInstance() });
    expect(getP(el, 'zoomState')).toEqual({ start: null, end: null });
  });
});

describe('OigPricingChart — createChart() with initialZoom', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('calls requestAnimationFrame for initial zoom when set', () => {
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame').mockReturnValue(0 as any);
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({
      initialZoomStart: 1000,
      initialZoomEnd: 5000,
    });
    callP(el, 'createChart');
    expect(rafSpy).toHaveBeenCalledOnce();
  });

  it('applies initialZoomStart/End via RAF callback', () => {
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
      cb(0);
      return 0 as any;
    });
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({
      initialZoomStart: 1000000,
      initialZoomEnd: 5000000,
    });
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    expect(chartInst.options.scales.x.min).toBe(1000000);
    expect(chartInst.options.scales.x.max).toBe(5000000);
  });

  it('chart.update("none") is called after initial zoom applied', () => {
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
      cb(0);
      return 0 as any;
    });
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ initialZoomStart: 1000, initialZoomEnd: 2000 });
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    expect(chartInst.update).toHaveBeenCalledWith('none');
  });
});

describe('OigPricingChart — createChart() error handling', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('does not throw when new Chart() throws', () => {
    vi.mocked(Chart).mockImplementationOnce(() => {
      throw new Error('Chart init failed');
    });
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    expect(() => callP(el, 'createChart')).not.toThrow();
  });

  it('chart remains null when new Chart() throws', () => {
    vi.mocked(Chart).mockImplementationOnce(() => {
      throw new Error('Chart init failed');
    });
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    expect(getP(el, 'chart')).toBeNull();
  });
});

// ============================================================================
// buildSpotPriceDataset (via createChart)
// ============================================================================

describe('buildSpotPriceDataset (via createChart)', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('creates spot price dataset when prices.length > 0', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ prices: [{ timestamp: '2025-01-15T00:00:00', price: 1.5 }] });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const spotDs = config.data.datasets.find((ds: any) => ds.label?.includes('Spotová'));
    expect(spotDs).toBeDefined();
  });

  it('does NOT create spot price dataset when prices is empty', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ prices: [] });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const spotDs = config.data.datasets.find((ds: any) => ds.label?.includes('Spotová'));
    expect(spotDs).toBeUndefined();
  });

  it('spot price dataset has yAxisID "y-price"', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const spotDs = config.data.datasets.find((ds: any) => ds.label?.includes('Spotová'));
    expect(spotDs.yAxisID).toBe('y-price');
  });

  it('spot price dataset has blue border color', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const spotDs = config.data.datasets.find((ds: any) => ds.label?.includes('Spotová'));
    expect(spotDs.borderColor).toBe('#2196F3');
  });

  it('spot price dataset has data mapped from timeline spot_price_czk', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const spotDs = config.data.datasets.find((ds: any) => ds.label?.includes('Spotová'));
    expect(Array.isArray(spotDs.data)).toBe(true);
    expect(spotDs.data.length).toBe(makeData().timeline.length);
  });

  it('spot price dataset has order 1', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const spotDs = config.data.datasets.find((ds: any) => ds.label?.includes('Spotová'));
    expect(spotDs.order).toBe(1);
  });
});

// ============================================================================
// buildExportPriceDataset (via createChart)
// ============================================================================

describe('buildExportPriceDataset (via createChart)', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('creates export price dataset when exportPrices.length > 0', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const exportDs = config.data.datasets.find((ds: any) => ds.label?.includes('Výkupní'));
    expect(exportDs).toBeDefined();
  });

  it('does NOT create export dataset when exportPrices is empty', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ exportPrices: [] });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const exportDs = config.data.datasets.find((ds: any) => ds.label?.includes('Výkupní'));
    expect(exportDs).toBeUndefined();
  });

  it('export dataset has borderDash for dashed style', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const exportDs = config.data.datasets.find((ds: any) => ds.label?.includes('Výkupní'));
    expect(Array.isArray(exportDs.borderDash)).toBe(true);
    expect(exportDs.borderDash.length).toBe(2);
  });

  it('export dataset has green border color', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const exportDs = config.data.datasets.find((ds: any) => ds.label?.includes('Výkupní'));
    expect(exportDs.borderColor).toBe('#4CAF50');
  });
});

// ============================================================================
// buildSolarDatasets (via createChart)
// ============================================================================

describe('buildSolarDatasets (via createChart)', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('returns no solar datasets when solar is null', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ solar: null });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const solarDs = config.data.datasets.filter((ds: any) =>
      ds.label?.includes('Solární') || ds.label?.includes('String')
    );
    expect(solarDs.length).toBe(0);
  });

  it('returns one dataset when only string1 is present (hasString1=true, hasString2=false)', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({
      solar: makeSolar({ hasString1: true, hasString2: false }),
    });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const solarDs = config.data.datasets.filter((ds: any) =>
      ds.label?.includes('Solární') || ds.label?.includes('String')
    );
    expect(solarDs.length).toBe(1);
  });

  it('single solar dataset has label containing "Solární"', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ solar: makeSolar({ hasString1: true, hasString2: false }) });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const solarDs = config.data.datasets.find((ds: any) => ds.label?.includes('Solární'));
    expect(solarDs).toBeDefined();
  });

  it('returns one dataset when only string2 present (hasString1=false, hasString2=true)', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({
      solar: makeSolar({ hasString1: false, hasString2: true }),
    });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const solarDs = config.data.datasets.filter((ds: any) =>
      ds.label?.includes('Solární') || ds.label?.includes('String')
    );
    expect(solarDs.length).toBe(1);
  });

  it('returns two datasets when both string1 and string2 are present', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({
      solar: makeSolar({ hasString1: true, hasString2: true }),
    });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const solarDs = config.data.datasets.filter((ds: any) =>
      ds.label?.includes('String')
    );
    expect(solarDs.length).toBe(2);
  });

  it('two-string datasets use "solar" stack', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ solar: makeSolar({ hasString1: true, hasString2: true }) });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const solarDs = config.data.datasets.filter((ds: any) => ds.label?.includes('String'));
    solarDs.forEach((ds: any) => expect(ds.stack).toBe('solar'));
  });

  it('solar datasets use y-power axis', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ solar: makeSolar({ hasString1: true, hasString2: false }) });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const solarDs = config.data.datasets.find((ds: any) => ds.label?.includes('Solární'));
    expect(solarDs.yAxisID).toBe('y-power');
  });
});

// ============================================================================
// buildBatteryDatasets (via createChart)
// ============================================================================

describe('buildBatteryDatasets (via createChart)', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('returns no battery datasets when battery is null', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ battery: null });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const battDs = config.data.datasets.filter((ds: any) =>
      ds.label?.includes('kapacita') || ds.label?.includes('baterie')
    );
    expect(battDs.length).toBe(0);
  });

  it('always creates baseline dataset when battery is provided', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({
      battery: makeBattery({
        consumption: [0, 0, 0, 0],
        gridCharge: [0, 0, 0, 0],
        solarCharge: [0, 0, 0, 0],
        gridNet: [null, null, null, null],
      }),
    });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const baseDs = config.data.datasets.find((ds: any) => ds.label?.includes('kapacita'));
    expect(baseDs).toBeDefined();
  });

  it('creates consumption dataset when consumption has positive values', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ battery: makeBattery({ consumption: [2, 2, 2, 2] }) });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const consumDs = config.data.datasets.find((ds: any) => ds.label?.includes('Spotřeba'));
    expect(consumDs).toBeDefined();
  });

  it('does NOT create consumption dataset when all consumption values are zero', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ battery: makeBattery({ consumption: [0, 0, 0, 0] }) });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const consumDs = config.data.datasets.find((ds: any) => ds.label?.includes('Spotřeba'));
    expect(consumDs).toBeUndefined();
  });

  it('creates gridCharge dataset when gridCharge has positive values', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ battery: makeBattery({ gridCharge: [1, 0, 0, 0] }) });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const gridDs = config.data.datasets.find((ds: any) => ds.label?.includes('sítě'));
    expect(gridDs).toBeDefined();
  });

  it('does NOT create gridCharge dataset when all values are zero', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ battery: makeBattery({ gridCharge: [0, 0, 0, 0] }) });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    // "ze sítě" appears in both gridCharge ("Do baterie ze sítě") and gridNet ("Netto odběr ze sítě")
    // gridCharge dataset has "Do baterie ze sítě", filter specifically
    const gridChargeDs = config.data.datasets.find((ds: any) =>
      ds.label?.includes('Do baterie ze sítě')
    );
    expect(gridChargeDs).toBeUndefined();
  });

  it('creates solarCharge dataset when solarCharge has positive values', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ battery: makeBattery({ solarCharge: [0, 1, 2, 3] }) });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const solarChargeDs = config.data.datasets.find((ds: any) =>
      ds.label?.includes('soláru')
    );
    expect(solarChargeDs).toBeDefined();
  });

  it('does NOT create solarCharge dataset when all values are zero', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ battery: makeBattery({ solarCharge: [0, 0, 0, 0] }) });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const solarChargeDs = config.data.datasets.find((ds: any) =>
      ds.label?.includes('soláru')
    );
    expect(solarChargeDs).toBeUndefined();
  });

  it('creates gridNet dataset when gridNet has non-null values', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ battery: makeBattery({ gridNet: [0.5, null, 0.2, null] }) });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const netDs = config.data.datasets.find((ds: any) => ds.label?.includes('Netto'));
    expect(netDs).toBeDefined();
  });

  it('does NOT create gridNet dataset when all values are null', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ battery: makeBattery({ gridNet: [null, null, null, null] }) });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const netDs = config.data.datasets.find((ds: any) => ds.label?.includes('Netto'));
    expect(netDs).toBeUndefined();
  });

  it('baseline dataset always uses y-solar axis', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ battery: makeBattery() });
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const baseDs = config.data.datasets.find((ds: any) => ds.label?.includes('kapacita'));
    expect(baseDs.yAxisID).toBe('y-solar');
  });
});

// ============================================================================
// updateChartData()
// ============================================================================

describe('OigPricingChart — updateChartData()', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('returns early when chart is null', () => {
    const el = new OigPricingChart();
    el.data = makeData();
    // chart is null, should not throw
    expect(() => callP(el, 'updateChartData')).not.toThrow();
  });

  it('returns early when data is null', () => {
    const el = new OigPricingChart();
    setP(el, 'chart', { data: { datasets: [], labels: [] }, options: { plugins: {}, scales: {} }, update: vi.fn() });
    expect(() => callP(el, 'updateChartData')).not.toThrow();
  });

  it('calls chart.update() when updating', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.update.mockClear();
    callP(el, 'updateChartData');
    expect(chartInst.update).toHaveBeenCalled();
  });

  it('calls applyModeIconPadding during update', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    vi.mocked(applyModeIconPadding).mockClear();
    callP(el, 'updateChartData');
    expect(applyModeIconPadding).toHaveBeenCalled();
  });

  it('updates dataset data in-place when count matches', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    // Same data → same count → in-place update
    const originalDatasets = chartInst.data.datasets;
    callP(el, 'updateChartData');
    // In-place: same array reference
    expect(chartInst.data.datasets).toBe(originalDatasets);
  });

  it('replaces datasets when count changes', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData(); // 2 datasets (spot + export)
    callP(el, 'createChart');
    const chartInst = lastChartInstance();

    // Change data to add solar → 3 datasets
    el.data = makeData({ solar: makeSolar({ hasString1: true, hasString2: false }) });
    callP(el, 'updateChartData');
    // Datasets should now be replaced
    expect(chartInst.data.datasets.length).toBeGreaterThan(2);
  });

  it('updates chart labels when label count changes', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ labels: [new Date(), new Date()] }); // 2 labels
    callP(el, 'createChart');
    const chartInst = lastChartInstance();

    el.data = makeData({ labels: [new Date(), new Date(), new Date()] }); // 3 labels
    callP(el, 'updateChartData');
    expect(chartInst.data.labels).toHaveLength(3);
  });
});

// ============================================================================
// zoomToTimeRange()
// ============================================================================

describe('OigPricingChart — zoomToTimeRange()', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('does nothing when chart is null', () => {
    const el = new OigPricingChart();
    expect(() => el.zoomToTimeRange('2025-01-15T02:00:00', '2025-01-15T05:00:00')).not.toThrow();
  });

  it('sets options.scales.x.min/max based on time range', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();

    el.zoomToTimeRange('2025-01-15T02:00:00', '2025-01-15T05:00:00');
    expect(chartInst.options.scales.x.min).toBeDefined();
    expect(chartInst.options.scales.x.max).toBeDefined();
  });

  it('min is set to start - 15 minutes', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');

    const startMs = new Date('2025-01-15T02:00:00').getTime();
    const marginMs = 15 * 60 * 1000;
    el.zoomToTimeRange('2025-01-15T02:00:00', '2025-01-15T05:00:00');
    const chartInst = lastChartInstance();
    expect(chartInst.options.scales.x.min).toBe(startMs - marginMs);
  });

  it('max is set to end + 15 minutes', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');

    const endMs = new Date('2025-01-15T05:00:00').getTime();
    const marginMs = 15 * 60 * 1000;
    el.zoomToTimeRange('2025-01-15T02:00:00', '2025-01-15T05:00:00');
    const chartInst = lastChartInstance();
    expect(chartInst.options.scales.x.max).toBe(endMs + marginMs);
  });

  it('updates zoomState with start/end', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');

    el.zoomToTimeRange('2025-01-15T02:00:00', '2025-01-15T05:00:00');
    const zoomState = getP<{ start: number | null; end: number | null }>(el, 'zoomState');
    expect(zoomState.start).not.toBeNull();
    expect(zoomState.end).not.toBeNull();
  });

  it('dispatches "zoom-change" event', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');

    const handler = vi.fn();
    el.addEventListener('zoom-change', handler);
    el.zoomToTimeRange('2025-01-15T02:00:00', '2025-01-15T05:00:00');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('zoom-change event detail has start, end, level', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');

    const handler = vi.fn();
    el.addEventListener('zoom-change', handler);
    el.zoomToTimeRange('2025-01-15T02:00:00', '2025-01-15T05:00:00');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toHaveProperty('start');
    expect(evt.detail).toHaveProperty('end');
    expect(evt.detail).toHaveProperty('level');
  });

  it('calling same range twice resets zoom (toggle behavior)', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');

    const chartInst = lastChartInstance();
    el.zoomToTimeRange('2025-01-15T02:00:00', '2025-01-15T05:00:00');
    // First call sets zoom
    expect(getP<any>(el, 'zoomState').start).not.toBeNull();

    el.zoomToTimeRange('2025-01-15T02:00:00', '2025-01-15T05:00:00');
    // Second call to same range → resets
    expect(getP<any>(el, 'zoomState').start).toBeNull();
    expect(chartInst.options.scales.x.min).toBeUndefined();
  });

  it('calls chart.update("none")', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.update.mockClear();

    el.zoomToTimeRange('2025-01-15T02:00:00', '2025-01-15T05:00:00');
    expect(chartInst.update).toHaveBeenCalledWith('none');
  });
});

// ============================================================================
// resetZoom()
// ============================================================================

describe('OigPricingChart — resetZoom()', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('does nothing when chart is null', () => {
    const el = new OigPricingChart();
    expect(() => el.resetZoom()).not.toThrow();
  });

  it('deletes options.scales.x.min', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.options.scales.x.min = 1000;

    el.resetZoom();
    expect(chartInst.options.scales.x.min).toBeUndefined();
  });

  it('deletes options.scales.x.max', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.options.scales.x.max = 2000;

    el.resetZoom();
    expect(chartInst.options.scales.x.max).toBeUndefined();
  });

  it('resets zoomState to { start: null, end: null }', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    setP(el, 'zoomState', { start: 1000, end: 2000 });

    el.resetZoom();
    expect(getP(el, 'zoomState')).toEqual({ start: null, end: null });
  });

  it('dispatches "zoom-reset" event', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');

    const handler = vi.fn();
    el.addEventListener('zoom-reset', handler);
    el.resetZoom();
    expect(handler).toHaveBeenCalledOnce();
  });

  it('zoom-reset event bubbles', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');

    const handler = vi.fn();
    el.addEventListener('zoom-reset', handler);
    el.resetZoom();
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.bubbles).toBe(true);
  });

  it('calls chart.update("none")', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.update.mockClear();

    el.resetZoom();
    expect(chartInst.update).toHaveBeenCalledWith('none');
  });
});

// ============================================================================
// computeDetailLevel (via mock scales manipulation)
// ============================================================================

describe('computeDetailLevel (tested via zoomToTimeRange/resetZoom)', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('returns "detail" when visible range ≤ 6 hours', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 2 * 3600000 } }; // 2h

    el.resetZoom(); // calls computeDetailLevel
    expect(getP(el, 'currentDetailLevel')).toBe('detail');
  });

  it('returns "day" when visible range is between 6 and 24 hours', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 12 * 3600000 } }; // 12h

    el.resetZoom();
    expect(getP(el, 'currentDetailLevel')).toBe('day');
  });

  it('returns "overview" when visible range > 24 hours', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 48 * 3600000 } }; // 48h

    el.resetZoom();
    expect(getP(el, 'currentDetailLevel')).toBe('overview');
  });

  it('returns "overview" when chart scales.x is missing (guard)', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = {}; // No x scale

    // resetZoom calls computeDetailLevel; without x, returns 'overview'
    // But updateChartDetailLevel guard also checks chart.scales.x
    // so it returns early — currentDetailLevel should remain unchanged
    el.resetZoom();
    // Default is 'overview', so this should still be 'overview'
    expect(getP(el, 'currentDetailLevel')).toBe('overview');
  });
});

// ============================================================================
// updateChartDetailLevel (via updated/datalabelMode changes)
// ============================================================================

describe('updateChartDetailLevel — datalabelMode "never"', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('sets all dataset datalabels.display to false', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();

    el.datalabelMode = 'never';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    chartInst.data.datasets.forEach((ds: any) => {
      if (!ds.datalabels) ds.datalabels = {};
      expect(ds.datalabels.display).toBe(false);
    });
  });
});

describe('updateChartDetailLevel — datalabelMode "always"', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('sets datalabels.display as function for each dataset', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();

    el.datalabelMode = 'always';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    const priceDs = chartInst.data.datasets.find((ds: any) => ds.yAxisID === 'y-price') as any;
    if (priceDs) {
      expect(typeof priceDs.datalabels.display).toBe('function');
    }
  });

  it('does not call updateChartDetailLevel when chart is null', () => {
    const el = new OigPricingChart();
    el.datalabelMode = 'always';
    // No chart created, should not throw
    expect(() => callP(el, 'updated', new Map([['datalabelMode', 'auto']]))).not.toThrow();
  });
});

describe('updateChartDetailLevel — overview level (> 24h)', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('sets y-solar display to false in overview mode', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 48 * 3600000 } }; // 48h → overview

    el.datalabelMode = 'never';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    expect(chartInst.options.scales['y-solar'].display).toBe(false);
  });

  it('hides y-price axis title in overview mode', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 48 * 3600000 } }; // 48h → overview

    el.datalabelMode = 'never';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    expect(chartInst.options.scales['y-price'].title.display).toBe(false);
  });

  it('sets x-axis maxTicksLimit to 12 in overview mode', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 48 * 3600000 } };

    el.datalabelMode = 'never';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    expect(chartInst.options.scales.x.ticks.maxTicksLimit).toBe(12);
  });
});

describe('updateChartDetailLevel — detail level (≤ 6h)', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('shows all y-axes in detail mode', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 3 * 3600000 } }; // 3h → detail

    el.datalabelMode = 'never';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    expect(chartInst.options.scales['y-solar'].display).toBe(true);
    expect(chartInst.options.scales['y-price'].title.display).toBe(true);
  });

  it('sets x-axis maxTicksLimit to 24 in detail mode', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 3 * 3600000 } }; // 3h

    el.datalabelMode = 'never';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    expect(chartInst.options.scales.x.ticks.maxTicksLimit).toBe(24);
  });

  it('sets x-axis displayFormats.hour to HH:mm in detail mode', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 3 * 3600000 } };

    el.datalabelMode = 'never';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    expect(chartInst.options.scales.x.time.displayFormats.hour).toBe('HH:mm');
  });
});

describe('updateChartDetailLevel — auto mode with hoursVisible > 6', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('hides datalabels when auto mode and > 6 hours visible', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 24 * 3600000 } }; // 24h

    el.datalabelMode = 'auto';
    callP(el, 'updated', new Map([['datalabelMode', 'never']]));

    chartInst.data.datasets.forEach((ds: any) => {
      if (ds.datalabels) {
        expect(ds.datalabels.display).toBe(false);
      }
    });
  });
});

// ============================================================================
// formatDatalabelValue (via formatter functions set in updateChartDetailLevel)
// ============================================================================

describe('formatDatalabelValue (via price dataset formatter)', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('formats null as empty string', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 3 * 3600000 } }; // detail level

    el.datalabelMode = 'always';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    const priceDs = chartInst.data.datasets.find((ds: any) => ds.yAxisID === 'y-price') as any;
    if (priceDs?.datalabels?.formatter) {
      expect(priceDs.datalabels.formatter(null)).toBe('');
    }
  });

  it('price formatter appends Kč unit', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 3 * 3600000 } };

    el.datalabelMode = 'always';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    const priceDs = chartInst.data.datasets.find((ds: any) => ds.yAxisID === 'y-price') as any;
    if (priceDs?.datalabels?.formatter) {
      expect(priceDs.datalabels.formatter(1.5)).toBe('1.50 Kč');
    }
  });

  it('price formatter uses 2 decimal places', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 3 * 3600000 } };

    el.datalabelMode = 'always';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    const priceDs = chartInst.data.datasets.find((ds: any) => ds.yAxisID === 'y-price') as any;
    if (priceDs?.datalabels?.formatter) {
      expect(priceDs.datalabels.formatter(1)).toBe('1.00 Kč');
    }
  });
});

describe('formatDatalabelValue (via solar dataset formatter)', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('solar formatter appends kW unit', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ solar: makeSolar({ hasString1: true, hasString2: false }) });
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 3 * 3600000 } };

    el.datalabelMode = 'always';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    const solarDs = chartInst.data.datasets.find((ds: any) =>
      ds.label?.includes('Solární') || ds.label?.includes('String')
    ) as any;
    if (solarDs?.datalabels?.formatter) {
      expect(solarDs.datalabels.formatter(2.5)).toBe('2.5 kW');
    }
  });
});

describe('formatDatalabelValue (via battery dataset formatter)', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('battery formatter appends kWh unit', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ battery: makeBattery() });
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 3 * 3600000 } };

    el.datalabelMode = 'always';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    const battDs = chartInst.data.datasets.find((ds: any) =>
      ds.label?.includes('kapacita')
    ) as any;
    if (battDs?.datalabels?.formatter) {
      expect(battDs.datalabels.formatter(10.5)).toBe('10.5 kWh');
    }
  });
});

describe('formatDatalabelValue (via generic dataset formatter)', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('generic formatter (gridNet) uses 1 decimal without unit', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData({ battery: makeBattery({ gridNet: [0.5, 1.0, null, 0.2] }) });
    callP(el, 'createChart');
    const chartInst = lastChartInstance();
    chartInst.scales = { x: { min: 0, max: 3 * 3600000 } };

    el.datalabelMode = 'always';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    const netDs = chartInst.data.datasets.find((ds: any) =>
      ds.label?.includes('Netto')
    ) as any;
    if (netDs?.datalabels?.formatter) {
      expect(netDs.datalabels.formatter(2.0)).toBe('2.0');
      expect(netDs.datalabels.formatter(null)).toBe('');
    }
  });
});

// ============================================================================
// firstUpdated()
// ============================================================================

describe('OigPricingChart — firstUpdated()', () => {
  beforeEach(() => {
    // Re-establish ResizeObserver mock before each test so vi.clearAllMocks()
    // in afterEach doesn't leave it broken for subsequent tests.
    vi.mocked(ResizeObserver).mockClear();
    vi.mocked(ResizeObserver).mockImplementation(() => ({
      observe: vi.fn(),
      unobserve: vi.fn(),
      disconnect: vi.fn(),
    }));
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('calls setupResizeObserver', () => {
    const el = new OigPricingChart();
    vi.mocked(ResizeObserver).mockClear();
    callP(el, 'firstUpdated');
    expect(ResizeObserver).toHaveBeenCalledOnce();
  });

  it('does not call requestAnimationFrame when data is null', () => {
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame');
    const el = new OigPricingChart();
    callP(el, 'firstUpdated');
    expect(rafSpy).not.toHaveBeenCalled();
  });

  it('does not call requestAnimationFrame when timeline is empty', () => {
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame');
    const el = new OigPricingChart();
    el.data = makeData({ timeline: [] });
    callP(el, 'firstUpdated');
    expect(rafSpy).not.toHaveBeenCalled();
  });

  it('calls requestAnimationFrame when data and timeline are present', () => {
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame').mockReturnValue(0 as any);
    const el = new OigPricingChart();
    el.data = makeData();
    callP(el, 'firstUpdated');
    expect(rafSpy).toHaveBeenCalledOnce();
  });

  it('RAF callback calls createChart', () => {
    vi.mocked(Chart).mockClear();
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
      cb(0);
      return 0 as any;
    });
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'firstUpdated');
    expect(vi.mocked(Chart)).toHaveBeenCalled();
  });
});

// ============================================================================
// updated()
// ============================================================================

describe('OigPricingChart — updated()', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('does nothing when data key not in changed map', () => {
    const el = new OigPricingChart();
    el.data = makeData();
    expect(() => callP(el, 'updated', new Map([['otherProp', null]]))).not.toThrow();
    expect(vi.mocked(Chart)).not.toHaveBeenCalled();
  });

  it('calls requestAnimationFrame to createChart when data changed and no chart', () => {
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame').mockReturnValue(0 as any);
    const el = new OigPricingChart();
    el.data = makeData();
    callP(el, 'updated', new Map([['data', null]]));
    expect(rafSpy).toHaveBeenCalled();
  });

  it('calls updateChartData when data changed and chart already exists', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = Reflect.get(el, 'chart') as any;
    chartInst.update.mockClear();

    el.data = makeData({ currentSpotPrice: 2.0 });
    callP(el, 'updated', new Map([['data', null]]));

    expect(chartInst.update).toHaveBeenCalled();
  });

  it('does not create chart when data changed but timeline is empty', () => {
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame');
    const el = new OigPricingChart();
    el.data = makeData({ timeline: [] });
    callP(el, 'updated', new Map([['data', null]]));
    expect(rafSpy).not.toHaveBeenCalled();
  });

  it('calls updateChartDetailLevel when datalabelMode changed and chart exists', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const chartInst = Reflect.get(el, 'chart') as any;
    chartInst.update.mockClear();

    el.datalabelMode = 'never';
    callP(el, 'updated', new Map([['datalabelMode', 'auto']]));

    expect(chartInst.update).toHaveBeenCalledWith('none');
  });

  it('does not crash when datalabelMode changed but chart is null', () => {
    const el = new OigPricingChart();
    el.datalabelMode = 'never';
    expect(() => callP(el, 'updated', new Map([['datalabelMode', 'auto']]))).not.toThrow();
  });

  it('does not call createChart when data is null', () => {
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame');
    const el = new OigPricingChart();
    // data is null, changed.has('data') is true but this.data is null
    callP(el, 'updated', new Map([['data', null]]));
    expect(rafSpy).not.toHaveBeenCalled();
  });
});

// ============================================================================
// y-axis tick callbacks
// ============================================================================

describe('y-axis tick callbacks in chartOptions', () => {
  beforeEach(() => {
    vi.mocked(Chart).mockClear();
  });

  it('y-price tick callback appends Kč', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const callback = config.options.scales['y-price'].ticks.callback;
    expect(callback(1.5)).toBe('1.50 Kč');
  });

  it('y-solar tick callback appends kWh', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const callback = config.options.scales['y-solar'].ticks.callback;
    expect(callback(10.5)).toBe('10.5 kWh');
  });

  it('y-power tick callback appends kW', () => {
    const el = new OigPricingChart();
    injectCanvas(el);
    el.data = makeData();
    callP(el, 'createChart');
    const config = vi.mocked(Chart).mock.calls[0][1] as any;
    const callback = config.options.scales['y-power'].ticks.callback;
    expect(callback(2.5)).toBe('2.50 kW');
  });
});
