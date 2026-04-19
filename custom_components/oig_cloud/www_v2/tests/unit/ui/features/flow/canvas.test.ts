import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ─── Module mocks (hoisted above imports by vitest) ───────────────────────────

vi.mock('@/core/bootstrap', () => ({
  OIG_RUNTIME: { reduceMotion: false, isHaApp: false, isMobile: false },
}));

vi.mock('@/data/flow-data', () => ({
  calculateFlowParams: vi.fn().mockReturnValue({
    active: true,
    intensity: 50,
    count: 2,
    speed: 1000,
    size: 10,
    opacity: 0.8,
  }),
}));

// Prevent side effects from importing node.ts (haClient, shieldController, etc.)
vi.mock('@/ui/features/flow/node', () => ({}));

// ─── Imports ──────────────────────────────────────────────────────────────────

import { OigFlowCanvas } from '@/ui/features/flow/canvas';
import { EMPTY_FLOW_DATA, FLOW_COLORS, NODE_COLORS } from '@/ui/features/flow/types';
import type { FlowData } from '@/ui/features/flow/types';
import { OIG_RUNTIME } from '@/core/bootstrap';
import { calculateFlowParams } from '@/data/flow-data';

// ─── Test helpers ─────────────────────────────────────────────────────────────

function getPrivate(el: object, key: string): unknown {
  return Reflect.get(el, key);
}

function setPrivate(el: object, key: string, value: unknown): void {
  Reflect.set(el, key, value);
}

function callMethod(el: object, name: string, ...args: unknown[]): unknown {
  const fn = Reflect.get(el, name);
  if (typeof fn !== 'function') {
    throw new Error(`No method '${name}' on ${(el as any).constructor.name}`);
  }
  return Reflect.apply(fn as (...a: unknown[]) => unknown, el, args);
}

// ─── Data factories ───────────────────────────────────────────────────────────

function makeFlowData(overrides: Partial<FlowData> = {}): FlowData {
  return { ...EMPTY_FLOW_DATA, ...overrides };
}

// ─── OigFlowCanvas ────────────────────────────────────────────────────────────

describe('OigFlowCanvas', () => {
  let el: OigFlowCanvas;

  beforeEach(() => {
    el = new OigFlowCanvas();
    (OIG_RUNTIME as any).reduceMotion = false;
    vi.clearAllMocks();
    vi.mocked(ResizeObserver).mockImplementation(() => ({
      observe: vi.fn(),
      unobserve: vi.fn(),
      disconnect: vi.fn(),
    }));
    vi.mocked(calculateFlowParams).mockReturnValue({
      active: true, intensity: 50, count: 2, speed: 1000, size: 10, opacity: 0.8,
    });
  });

  afterEach(() => {
    try {
      Object.defineProperty(document, 'hidden', {
        get: () => false,
        configurable: true,
      });
    } catch {
      void 0;
    }
    vi.restoreAllMocks();
  });

  // ─── Property defaults ────────────────────────────────────────────────────

  describe('property defaults', () => {
    it('data defaults to EMPTY_FLOW_DATA', () => {
      expect(el.data).toEqual(EMPTY_FLOW_DATA);
    });

    it('particlesEnabled defaults to true', () => {
      expect(el.particlesEnabled).toBe(true);
    });

    it('active defaults to true', () => {
      expect(el.active).toBe(true);
    });

    it('editMode defaults to false', () => {
      expect(el.editMode).toBe(false);
    });

    it('animationId private field defaults to null', () => {
      expect(getPrivate(el, 'animationId')).toBeNull();
    });

    it('particleCount private field defaults to 0', () => {
      expect(getPrivate(el, 'particleCount')).toBe(0);
    });

    it('MAX_PARTICLES is 50', () => {
      expect(getPrivate(el, 'MAX_PARTICLES')).toBe(50);
    });
  });

  // ─── updateLines() ────────────────────────────────────────────────────────

  describe('updateLines()', () => {
    it('always generates exactly 4 flow lines', () => {
      el.data = makeFlowData();
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as unknown[];
      expect(lines).toHaveLength(4);
    });

    it('line IDs are solar-inverter, battery-inverter, grid-inverter, inverter-house', () => {
      el.data = makeFlowData();
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string }>;
      expect(lines.map(l => l.id)).toEqual([
        'solar-inverter',
        'battery-inverter',
        'grid-inverter',
        'inverter-house',
      ]);
    });

    it('solar inactive when solarPower <= 50', () => {
      el.data = makeFlowData({ solarPower: 50 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; active: boolean; power: number }>;
      const solar = lines.find(l => l.id === 'solar-inverter')!;
      expect(solar.active).toBe(false);
      expect(solar.power).toBe(0);
    });

    it('solar active when solarPower > 50', () => {
      el.data = makeFlowData({ solarPower: 1000 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; active: boolean; power: number; color: string }>;
      const solar = lines.find(l => l.id === 'solar-inverter')!;
      expect(solar.active).toBe(true);
      expect(solar.power).toBe(1000);
      expect(solar.color).toBe(FLOW_COLORS.solar);
    });

    it('solar active calls calculateFlowParams', () => {
      el.data = makeFlowData({ solarPower: 2000 });
      callMethod(el, 'updateLines');
      expect(vi.mocked(calculateFlowParams)).toHaveBeenCalledWith(2000, expect.any(Number), 'solar');
    });

    it('battery inactive when |batteryPower| <= 50', () => {
      el.data = makeFlowData({ batteryPower: 50 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; active: boolean; from: string; to: string }>;
      const battery = lines.find(l => l.id === 'battery-inverter')!;
      expect(battery.active).toBe(false);
      expect(battery.from).toBe('battery');
      expect(battery.to).toBe('inverter');
    });

    it('battery charging (positive power): from=inverter, to=battery', () => {
      el.data = makeFlowData({ batteryPower: 500 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; from: string; to: string; active: boolean }>;
      const battery = lines.find(l => l.id === 'battery-inverter')!;
      expect(battery.active).toBe(true);
      expect(battery.from).toBe('inverter');
      expect(battery.to).toBe('battery');
    });

    it('battery discharging (negative power): from=battery, to=inverter', () => {
      el.data = makeFlowData({ batteryPower: -500 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; from: string; to: string; active: boolean }>;
      const battery = lines.find(l => l.id === 'battery-inverter')!;
      expect(battery.active).toBe(true);
      expect(battery.from).toBe('battery');
      expect(battery.to).toBe('inverter');
    });

    it('battery power is absolute value on the line', () => {
      el.data = makeFlowData({ batteryPower: -800 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; power: number }>;
      const battery = lines.find(l => l.id === 'battery-inverter')!;
      expect(battery.power).toBe(800);
    });

    it('grid inactive when |gridPower| <= 50', () => {
      el.data = makeFlowData({ gridPower: 30 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; active: boolean; from: string; to: string }>;
      const grid = lines.find(l => l.id === 'grid-inverter')!;
      expect(grid.active).toBe(false);
      expect(grid.from).toBe('grid');
      expect(grid.to).toBe('inverter');
    });

    it('grid import (positive power): from=grid, to=inverter, color=grid_import', () => {
      el.data = makeFlowData({ gridPower: 1000 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; active: boolean; from: string; to: string; color: string }>;
      const grid = lines.find(l => l.id === 'grid-inverter')!;
      expect(grid.active).toBe(true);
      expect(grid.from).toBe('grid');
      expect(grid.to).toBe('inverter');
      expect(grid.color).toBe(FLOW_COLORS.grid_import);
    });

    it('grid export (negative power): from=inverter, to=grid, color=grid_export', () => {
      el.data = makeFlowData({ gridPower: -500 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; active: boolean; from: string; to: string; color: string }>;
      const grid = lines.find(l => l.id === 'grid-inverter')!;
      expect(grid.active).toBe(true);
      expect(grid.from).toBe('inverter');
      expect(grid.to).toBe('grid');
      expect(grid.color).toBe(FLOW_COLORS.grid_export);
    });

    it('grid inactive color defaults to grid_import', () => {
      el.data = makeFlowData({ gridPower: 0 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; color: string }>;
      const grid = lines.find(l => l.id === 'grid-inverter')!;
      expect(grid.color).toBe(FLOW_COLORS.grid_import);
    });

    it('house inactive when housePower <= 50', () => {
      el.data = makeFlowData({ housePower: 50 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; active: boolean; power: number }>;
      const house = lines.find(l => l.id === 'inverter-house')!;
      expect(house.active).toBe(false);
      expect(house.power).toBe(0);
    });

    it('house active when housePower > 50', () => {
      el.data = makeFlowData({ housePower: 2000 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; active: boolean; power: number; from: string; to: string; color: string }>;
      const house = lines.find(l => l.id === 'inverter-house')!;
      expect(house.active).toBe(true);
      expect(house.power).toBe(2000);
      expect(house.from).toBe('inverter');
      expect(house.to).toBe('house');
      expect(house.color).toBe(FLOW_COLORS.house);
    });

    it('inactive line has default params with active=false', () => {
      el.data = makeFlowData({ solarPower: 0 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; params: { active: boolean; intensity: number } }>;
      const solar = lines.find(l => l.id === 'solar-inverter')!;
      expect(solar.params.active).toBe(false);
      expect(solar.params.intensity).toBe(0);
    });

    it('stores result in this.lines', () => {
      el.data = makeFlowData({ solarPower: 500, housePower: 300 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as unknown[];
      expect(lines).toHaveLength(4);
    });
  });

  // ─── calcEdgePoint() ──────────────────────────────────────────────────────

  describe('calcEdgePoint()', () => {
    it('returns center when dx === 0 and dy === 0', () => {
      const center = { x: 100, y: 150 };
      const result = callMethod(el, 'calcEdgePoint', center, center, 50, 50) as { x: number; y: number };
      expect(result).toEqual({ x: 100, y: 150 });
    });

    it('pure horizontal right: clamps to right edge (halfW)', () => {
      const center = { x: 100, y: 100 };
      const target = { x: 300, y: 100 };
      const result = callMethod(el, 'calcEdgePoint', center, target, 50, 30) as { x: number; y: number };
      // absDx=200, absDy=0; 200*30 > 0*50 → scale = 50/200 = 0.25; x = 100+200*0.25 = 150
      expect(result.x).toBeCloseTo(150);
      expect(result.y).toBeCloseTo(100);
    });

    it('pure horizontal left: clamps to left edge', () => {
      const center = { x: 200, y: 100 };
      const target = { x: 0, y: 100 };
      const result = callMethod(el, 'calcEdgePoint', center, target, 50, 30) as { x: number; y: number };
      // dx=-200, scale=50/200=0.25; x = 200+(-200*0.25) = 150
      expect(result.x).toBeCloseTo(150);
      expect(result.y).toBeCloseTo(100);
    });

    it('pure vertical down: clamps to bottom edge (halfH)', () => {
      const center = { x: 100, y: 100 };
      const target = { x: 100, y: 300 };
      const result = callMethod(el, 'calcEdgePoint', center, target, 50, 30) as { x: number; y: number };
      // absDx * halfH = 0 * 30 = 0 <= absDy * halfW = 200 * 50 → scale = halfH / absDy = 30/200 = 0.15
      expect(result.x).toBeCloseTo(100);
      expect(result.y).toBeCloseTo(130); // 100 + 200 * 0.15
    });

    it('pure vertical up: clamps to top edge', () => {
      const center = { x: 100, y: 200 };
      const target = { x: 100, y: 0 };
      const result = callMethod(el, 'calcEdgePoint', center, target, 50, 30) as { x: number; y: number };
      // dy = -200, scale = 30/200 = 0.15
      expect(result.x).toBeCloseTo(100);
      expect(result.y).toBeCloseTo(170); // 200 + (-200 * 0.15)
    });

    it('diagonal: uses horizontal scale when dx dominates', () => {
      // absDx * halfH > absDy * halfW → horizontal dominates
      const center = { x: 0, y: 0 };
      const target = { x: 100, y: 10 }; // absDx=100, absDy=10; 100*25 > 10*50 → use halfW/absDx
      const result = callMethod(el, 'calcEdgePoint', center, target, 50, 25) as { x: number; y: number };
      const scale = 50 / 100; // 0.5
      expect(result.x).toBeCloseTo(50);
      expect(result.y).toBeCloseTo(5); // 10 * 0.5
    });

    it('diagonal: uses vertical scale when dy dominates', () => {
      // absDy * halfW > absDx * halfH → vertical dominates
      const center = { x: 0, y: 0 };
      const target = { x: 10, y: 100 }; // absDx=10, absDy=100; 10*25 < 100*50 → use halfH/absDy
      const result = callMethod(el, 'calcEdgePoint', center, target, 50, 25) as { x: number; y: number };
      const scale = 25 / 100; // 0.25
      expect(result.x).toBeCloseTo(2.5); // 10 * 0.25
      expect(result.y).toBeCloseTo(25); // 100 * 0.25
    });
  });

  // ─── positionOverlayLayer() ───────────────────────────────────────────────

  describe('positionOverlayLayer()', () => {
    it('sets correct left offset (gridRect.left - canvasRect.left)', () => {
      const layer = document.createElement('div');
      const gridRect = { left: 100, top: 50, width: 300, height: 200 } as DOMRect;
      const canvasRect = { left: 20, top: 10, width: 500, height: 400 } as DOMRect;
      callMethod(el, 'positionOverlayLayer', layer, gridRect, canvasRect);
      expect(layer.style.left).toBe('80px');
    });

    it('sets correct top offset (gridRect.top - canvasRect.top)', () => {
      const layer = document.createElement('div');
      const gridRect = { left: 100, top: 50, width: 300, height: 200 } as DOMRect;
      const canvasRect = { left: 20, top: 10, width: 500, height: 400 } as DOMRect;
      callMethod(el, 'positionOverlayLayer', layer, gridRect, canvasRect);
      expect(layer.style.top).toBe('40px');
    });

    it('sets width from gridRect.width', () => {
      const layer = document.createElement('div');
      const gridRect = { left: 0, top: 0, width: 350, height: 200 } as DOMRect;
      const canvasRect = { left: 0, top: 0, width: 500, height: 400 } as DOMRect;
      callMethod(el, 'positionOverlayLayer', layer, gridRect, canvasRect);
      expect(layer.style.width).toBe('350px');
    });

    it('sets height from gridRect.height', () => {
      const layer = document.createElement('div');
      const gridRect = { left: 0, top: 0, width: 350, height: 240 } as DOMRect;
      const canvasRect = { left: 0, top: 0, width: 500, height: 400 } as DOMRect;
      callMethod(el, 'positionOverlayLayer', layer, gridRect, canvasRect);
      expect(layer.style.height).toBe('240px');
    });

    it('handles SVGSVGElement — sets style properties correctly', () => {
      const svgEl = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      const gridRect = { left: 5, top: 10, width: 200, height: 150 } as DOMRect;
      const canvasRect = { left: 0, top: 0, width: 400, height: 300 } as DOMRect;
      callMethod(el, 'positionOverlayLayer', svgEl, gridRect, canvasRect);
      expect(svgEl.style.left).toBe('5px');
      expect(svgEl.style.top).toBe('10px');
    });
  });

  // ─── connectedCallback / disconnectedCallback ─────────────────────────────

  describe('connectedCallback()', () => {
    it('adds visibilitychange listener to document', () => {
      const spy = vi.spyOn(document, 'addEventListener');
      el.connectedCallback();
      expect(spy).toHaveBeenCalledWith('visibilitychange', expect.any(Function));
    });

    it('adds layout-changed listener to element', () => {
      const spy = vi.spyOn(el, 'addEventListener');
      el.connectedCallback();
      expect(spy).toHaveBeenCalledWith('layout-changed', expect.any(Function));
    });
  });

  describe('disconnectedCallback()', () => {
    it('removes visibilitychange listener from document', () => {
      const spy = vi.spyOn(document, 'removeEventListener');
      el.disconnectedCallback();
      expect(spy).toHaveBeenCalledWith('visibilitychange', expect.any(Function));
    });

    it('removes layout-changed listener from element', () => {
      const spy = vi.spyOn(el, 'removeEventListener');
      el.disconnectedCallback();
      expect(spy).toHaveBeenCalledWith('layout-changed', expect.any(Function));
    });

    it('calls stopAnimation on disconnect', () => {
      const spy = vi.spyOn(el as any, 'stopAnimation');
      el.disconnectedCallback();
      expect(spy).toHaveBeenCalled();
    });
  });

  // ─── updateAnimationState() ───────────────────────────────────────────────

  describe('updateAnimationState()', () => {
    it('starts animation when all conditions are met', () => {
      const startSpy = vi.spyOn(el as any, 'startAnimation');
      el.particlesEnabled = true;
      el.active = true;
      (OIG_RUNTIME as any).reduceMotion = false;
      callMethod(el, 'updateAnimationState');
      expect(startSpy).toHaveBeenCalled();
    });

    it('stops animation when particlesEnabled is false', () => {
      const stopSpy = vi.spyOn(el as any, 'stopAnimation');
      el.particlesEnabled = false;
      el.active = true;
      callMethod(el, 'updateAnimationState');
      expect(stopSpy).toHaveBeenCalled();
    });

    it('stops animation when active is false', () => {
      const stopSpy = vi.spyOn(el as any, 'stopAnimation');
      el.particlesEnabled = true;
      el.active = false;
      callMethod(el, 'updateAnimationState');
      expect(stopSpy).toHaveBeenCalled();
    });

    it('stops animation when OIG_RUNTIME.reduceMotion is true', () => {
      const stopSpy = vi.spyOn(el as any, 'stopAnimation');
      el.particlesEnabled = true;
      el.active = true;
      (OIG_RUNTIME as any).reduceMotion = true;
      callMethod(el, 'updateAnimationState');
      expect(stopSpy).toHaveBeenCalled();
    });

    it('stops animation when document.hidden is true', () => {
      const stopSpy = vi.spyOn(el as any, 'stopAnimation');
      el.particlesEnabled = true;
      el.active = true;
      Object.defineProperty(document, 'hidden', { get: () => true, configurable: true });
      callMethod(el, 'updateAnimationState');
      expect(stopSpy).toHaveBeenCalled();
      Object.defineProperty(document, 'hidden', { get: () => false, configurable: true });
    });

    it('also calls spawnParticles when starting', () => {
      const spawnSpy = vi.spyOn(el as any, 'spawnParticles');
      el.particlesEnabled = true;
      el.active = true;
      callMethod(el, 'updateAnimationState');
      expect(spawnSpy).toHaveBeenCalled();
    });
  });

  // ─── startAnimation / stopAnimation ──────────────────────────────────────

  describe('startAnimation()', () => {
    it('sets animationId via requestAnimationFrame', () => {
      const rafSpy = vi.spyOn(window, 'requestAnimationFrame').mockReturnValue(42);
      callMethod(el, 'startAnimation');
      expect(getPrivate(el, 'animationId')).toBe(42);
      rafSpy.mockRestore();
    });

    it('is a no-op if already running (animationId !== null)', () => {
      setPrivate(el, 'animationId', 99);
      const rafSpy = vi.spyOn(window, 'requestAnimationFrame');
      callMethod(el, 'startAnimation');
      expect(rafSpy).not.toHaveBeenCalled();
      rafSpy.mockRestore();
    });

    it('rAF callback re-registers itself', () => {
      let capturedCallback: FrameRequestCallback | null = null;
      const rafSpy = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
        capturedCallback = cb;
        return 1;
      });

      callMethod(el, 'startAnimation');
      expect(capturedCallback).not.toBeNull();

      rafSpy.mockReturnValue(2);
      const spawnSpy = vi.spyOn(el as any, 'spawnParticles');
      capturedCallback!(0);

      expect(spawnSpy).toHaveBeenCalled();
      expect(rafSpy).toHaveBeenCalledTimes(2);
      rafSpy.mockRestore();
    });
  });

  describe('stopAnimation()', () => {
    it('cancels animationFrame and sets animationId to null', () => {
      const cafSpy = vi.spyOn(window, 'cancelAnimationFrame');
      setPrivate(el, 'animationId', 123);
      callMethod(el, 'stopAnimation');
      expect(cafSpy).toHaveBeenCalledWith(123);
      expect(getPrivate(el, 'animationId')).toBeNull();
      cafSpy.mockRestore();
    });

    it('is a no-op if animationId is null', () => {
      const cafSpy = vi.spyOn(window, 'cancelAnimationFrame');
      setPrivate(el, 'animationId', null);
      callMethod(el, 'stopAnimation');
      expect(cafSpy).not.toHaveBeenCalled();
      cafSpy.mockRestore();
    });
  });

  // ─── onVisibilityChange / onLayoutChanged ─────────────────────────────────

  describe('onVisibilityChange()', () => {
    it('calls updateAnimationState', () => {
      const spy = vi.spyOn(el as any, 'updateAnimationState');
      const handler = getPrivate(el, 'onVisibilityChange') as () => void;
      handler.call(el);
      expect(spy).toHaveBeenCalled();
    });
  });

  describe('onLayoutChanged()', () => {
    it('calls drawConnectionsDeferred', () => {
      const spy = vi.spyOn(el as any, 'drawConnectionsDeferred');
      const handler = getPrivate(el, 'onLayoutChanged') as () => void;
      handler.call(el);
      expect(spy).toHaveBeenCalled();
    });
  });

  // ─── drawConnectionsDeferred() ────────────────────────────────────────────

  describe('drawConnectionsDeferred()', () => {
    it('calls requestAnimationFrame', () => {
      const rafSpy = vi.spyOn(window, 'requestAnimationFrame').mockReturnValue(1);
      callMethod(el, 'drawConnectionsDeferred');
      expect(rafSpy).toHaveBeenCalled();
      rafSpy.mockRestore();
    });

    it('rAF callback calls drawConnectionsSVG', () => {
      let capturedCb: FrameRequestCallback | null = null;
      vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
        capturedCb = cb;
        return 1;
      });
      const drawSpy = vi.spyOn(el as any, 'drawConnectionsSVG');
      callMethod(el, 'drawConnectionsDeferred');
      capturedCb!(0);
      expect(drawSpy).toHaveBeenCalled();
    });
  });

  // ─── drawConnectionsSVG() ─────────────────────────────────────────────────

  describe('drawConnectionsSVG()', () => {
    it('does not throw when svgEl is not found (unattached element)', () => {
      expect(() => callMethod(el, 'drawConnectionsSVG')).not.toThrow();
    });

    it('does not throw when getGridMetrics returns null', () => {
      expect(() => callMethod(el, 'drawConnectionsSVG')).not.toThrow();
    });
  });

  // ─── getGridMetrics() ─────────────────────────────────────────────────────

  describe('getGridMetrics()', () => {
    it('returns null when renderRoot has no oig-flow-node', () => {
      const result = callMethod(el, 'getGridMetrics');
      expect(result).toBeNull();
    });
  });

  // ─── getParticlesLayer() ──────────────────────────────────────────────────

  describe('getParticlesLayer()', () => {
    it('returns falsy when not attached to DOM', () => {
      const result = callMethod(el, 'getParticlesLayer');
      expect(result).toBeFalsy();
    });
  });

  // ─── spawnParticles() ─────────────────────────────────────────────────────

  describe('spawnParticles()', () => {
    it('returns early when particleCount >= MAX_PARTICLES', () => {
      setPrivate(el, 'particleCount', 50);
      const getLayerSpy = vi.spyOn(el as any, 'getParticlesLayer');
      callMethod(el, 'spawnParticles');
      expect(getLayerSpy).not.toHaveBeenCalled();
    });

    it('does not reach getGridMetrics when particlesLayer is null', () => {
      setPrivate(el, 'particleCount', 0);
      const getMetricsSpy = vi.spyOn(el as any, 'getGridMetrics');
      callMethod(el, 'spawnParticles');
      expect(getMetricsSpy).not.toHaveBeenCalled();
    });
  });

  // ─── createParticle() ─────────────────────────────────────────────────────

  describe('createParticle()', () => {
    it('appends particle div to layer', () => {
      const layer = document.createElement('div');
      document.body.appendChild(layer);
      const from = { x: 10, y: 20 };
      const to = { x: 100, y: 200 };
      const params = { active: true, intensity: 50, count: 1, speed: 500, size: 8, opacity: 0.7 };
      callMethod(el, 'createParticle', layer, from, to, '#ff9800', params, 0);
      expect(layer.children.length).toBe(1);
      expect(layer.children[0].className).toBe('particle');
      document.body.removeChild(layer);
    });

    it('sets particle initial position from from.x, from.y', () => {
      const layer = document.createElement('div');
      document.body.appendChild(layer);
      const from = { x: 42, y: 84 };
      const to = { x: 200, y: 200 };
      const params = { active: true, intensity: 50, count: 1, speed: 500, size: 8, opacity: 0.7 };
      callMethod(el, 'createParticle', layer, from, to, '#ffd54f', params, 0);
      const particle = layer.children[0] as HTMLElement;
      expect(particle.style.left).toBe('42px');
      expect(particle.style.top).toBe('84px');
      document.body.removeChild(layer);
    });

    it('increments particleCount when particle is created', () => {
      const layer = document.createElement('div');
      document.body.appendChild(layer);
      const from = { x: 0, y: 0 };
      const to = { x: 100, y: 100 };
      const params = { active: true, intensity: 50, count: 1, speed: 100, size: 6, opacity: 0.5 };
      const before = getPrivate(el, 'particleCount') as number;
      callMethod(el, 'createParticle', layer, from, to, '#4caf50', params, 0);
      expect(getPrivate(el, 'particleCount')).toBe(before + 1);
      document.body.removeChild(layer);
    });

    it('sets particle size from params.size', () => {
      const layer = document.createElement('div');
      document.body.appendChild(layer);
      const from = { x: 0, y: 0 };
      const to = { x: 100, y: 100 };
      const params = { active: true, intensity: 50, count: 1, speed: 500, size: 12, opacity: 0.5 };
      callMethod(el, 'createParticle', layer, from, to, '#42a5f5', params, 0);
      const particle = layer.children[0] as HTMLElement;
      expect(particle.style.width).toBe('12px');
      expect(particle.style.height).toBe('12px');
      document.body.removeChild(layer);
    });

    it('sets particle box-shadow with color glow', () => {
      const layer = document.createElement('div');
      document.body.appendChild(layer);
      const from = { x: 0, y: 0 };
      const to = { x: 100, y: 100 };
      const params = { active: true, intensity: 50, count: 1, speed: 500, size: 8, opacity: 0.5 };
      callMethod(el, 'createParticle', layer, from, to, '#ff0000', params, 0);
      const particle = layer.children[0] as HTMLElement;
      expect(particle.style.boxShadow).toContain('#ff0000');
      document.body.removeChild(layer);
    });
  });

  // ─── updated() ────────────────────────────────────────────────────────────

  describe('updated()', () => {
    it('calls updateLines when data has changed', () => {
      const spy = vi.spyOn(el as any, 'updateLines');
      const spy2 = vi.spyOn(el as any, 'drawConnectionsDeferred').mockImplementation(() => {});
      callMethod(el, 'updated', new Map([['data', undefined]]));
      expect(spy).toHaveBeenCalled();
      spy2.mockRestore();
    });

    it('calls updateAnimationState when active has changed', () => {
      const spy = vi.spyOn(el as any, 'updateAnimationState');
      const spy2 = vi.spyOn(el as any, 'drawConnectionsDeferred').mockImplementation(() => {});
      callMethod(el, 'updated', new Map([['active', false]]));
      expect(spy).toHaveBeenCalled();
      spy2.mockRestore();
    });

    it('calls updateAnimationState when particlesEnabled has changed', () => {
      const spy = vi.spyOn(el as any, 'updateAnimationState');
      const spy2 = vi.spyOn(el as any, 'drawConnectionsDeferred').mockImplementation(() => {});
      callMethod(el, 'updated', new Map([['particlesEnabled', false]]));
      expect(spy).toHaveBeenCalled();
      spy2.mockRestore();
    });

    it('always calls drawConnectionsDeferred', () => {
      const spy = vi.spyOn(el as any, 'drawConnectionsDeferred').mockImplementation(() => {});
      callMethod(el, 'updated', new Map([['editMode', false]]));
      expect(spy).toHaveBeenCalled();
      spy.mockRestore();
    });

    it('calls spawnParticles when data changed and animationId is running', () => {
      setPrivate(el, 'animationId', 1);
      const spy = vi.spyOn(el as any, 'spawnParticles');
      vi.spyOn(el as any, 'drawConnectionsDeferred').mockImplementation(() => {});
      callMethod(el, 'updated', new Map([['data', undefined]]));
      expect(spy).toHaveBeenCalled();
    });

    it('does not call spawnParticles when data changed but animation not running', () => {
      setPrivate(el, 'animationId', null);
      const spy = vi.spyOn(el as any, 'spawnParticles');
      vi.spyOn(el as any, 'drawConnectionsDeferred').mockImplementation(() => {});
      callMethod(el, 'updated', new Map([['data', undefined]]));
      expect(spy).not.toHaveBeenCalled();
    });

    it('does not call updateLines when only active has changed', () => {
      const spy = vi.spyOn(el as any, 'updateLines');
      vi.spyOn(el as any, 'drawConnectionsDeferred').mockImplementation(() => {});
      callMethod(el, 'updated', new Map([['active', true]]));
      expect(spy).not.toHaveBeenCalled();
    });
  });

  // ─── firstUpdated() ───────────────────────────────────────────────────────

  describe('firstUpdated()', () => {
    beforeEach(() => {
      vi.mocked(ResizeObserver).mockImplementation(() => ({
        observe: vi.fn(),
        unobserve: vi.fn(),
        disconnect: vi.fn(),
      }));
    });

    it('calls updateLines', () => {
      const spy = vi.spyOn(el as any, 'updateLines');
      vi.spyOn(el as any, 'updateAnimationState').mockImplementation(() => {});
      vi.spyOn(el as any, 'drawConnectionsDeferred').mockImplementation(() => {});
      callMethod(el, 'firstUpdated');
      expect(spy).toHaveBeenCalled();
    });

    it('calls updateAnimationState', () => {
      const spy = vi.spyOn(el as any, 'updateAnimationState');
      vi.spyOn(el as any, 'drawConnectionsDeferred').mockImplementation(() => {});
      callMethod(el, 'firstUpdated');
      expect(spy).toHaveBeenCalled();
    });

    it('creates ResizeObserver and observes element', () => {
      vi.spyOn(el as any, 'updateAnimationState').mockImplementation(() => {});
      vi.spyOn(el as any, 'drawConnectionsDeferred').mockImplementation(() => {});
      callMethod(el, 'firstUpdated');
      expect(ResizeObserver).toHaveBeenCalled();
      const roInstance = vi.mocked(ResizeObserver).mock.results[0].value;
      expect(roInstance.observe).toHaveBeenCalledWith(el);
    });
  });

  // ─── render() ─────────────────────────────────────────────────────────────

  describe('render()', () => {
    it('returns a TemplateResult (object with strings and values)', () => {
      const result = el.render() as unknown as { strings: TemplateStringsArray; values: unknown[] };
      expect(result).toBeDefined();
      expect(result.values).toBeDefined();
    });

    it('binds this.data as first value', () => {
      const customData = makeFlowData({ solarPower: 999 });
      el.data = customData;
      const result = el.render() as unknown as { values: unknown[] };
      expect(result.values[0]).toBe(customData);
    });

    it('binds this.editMode as second value', () => {
      el.editMode = true;
      const result = el.render() as unknown as { values: unknown[] };
      expect(result.values[1]).toBe(true);
    });

    it('editMode false is reflected in template', () => {
      el.editMode = false;
      const result = el.render() as unknown as { values: unknown[] };
      expect(result.values[1]).toBe(false);
    });
  });

  // ─── resetLayout() ────────────────────────────────────────────────────────

  describe('resetLayout()', () => {
    it('does not throw when shadowRoot is null (unattached element)', () => {
      expect(() => el.resetLayout()).not.toThrow();
    });

    it('delegates to child oig-flow-node resetLayout if present', () => {
      const mockResetLayout = vi.fn();
      Object.defineProperty(el, 'shadowRoot', {
        get: () => ({
          querySelector: (_sel: string) => ({ resetLayout: mockResetLayout }),
        }),
        configurable: true,
      });
      el.resetLayout();
      expect(mockResetLayout).toHaveBeenCalled();
    });

    it('no-op when oig-flow-node has no resetLayout method', () => {
      Object.defineProperty(el, 'shadowRoot', {
        get: () => ({
          querySelector: (_sel: string) => ({ someOtherMethod: vi.fn() }),
        }),
        configurable: true,
      });
      expect(() => el.resetLayout()).not.toThrow();
    });
  });

  // ─── getGradientColors integration via updateLines ─────────────────────────

  describe('gradient colors in flow lines', () => {
    it('solar line has expected color from FLOW_COLORS.solar', () => {
      el.data = makeFlowData({ solarPower: 1500 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; color: string }>;
      const solar = lines.find(l => l.id === 'solar-inverter')!;
      expect(solar.color).toBe(FLOW_COLORS.solar);
    });

    it('battery line has expected color from FLOW_COLORS.battery', () => {
      el.data = makeFlowData({ batteryPower: 500 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; color: string }>;
      const battery = lines.find(l => l.id === 'battery-inverter')!;
      expect(battery.color).toBe(FLOW_COLORS.battery);
    });

    it('house line has expected color from FLOW_COLORS.house', () => {
      el.data = makeFlowData({ housePower: 2000 });
      callMethod(el, 'updateLines');
      const lines = getPrivate(el, 'lines') as Array<{ id: string; color: string }>;
      const house = lines.find(l => l.id === 'inverter-house')!;
      expect(house.color).toBe(FLOW_COLORS.house);
    });
  });
});
