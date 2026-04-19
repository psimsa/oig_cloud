import { describe, it, expect, beforeEach } from 'vitest';
import { OigFlowConnection } from '@/ui/features/flow/connection';
import { CSS_VARS } from '@/ui/theme';
import { NODE_COLORS } from '@/ui/features/flow/types';
import type { FlowConnection, FlowNode } from '@/ui/features/flow/types';

function callMethod(el: OigFlowConnection, name: string, ...args: unknown[]): unknown {
  const method = Reflect.get(el, name);
  if (typeof method !== 'function') throw new Error(`No method on connection: ${name}`);
  return Reflect.apply(method, el, args);
}

const makeNode = (overrides: Partial<FlowNode> = {}): FlowNode => ({
  id: 'solar',
  type: 'solar',
  x: 0,
  y: 0,
  width: 100,
  height: 80,
  label: 'Solar',
  power: 0,
  data: {},
  ...overrides,
});

const makeConn = (overrides: Partial<FlowConnection> = {}): FlowConnection => ({
  id: 'solar-inverter',
  from: 'solar',
  to: 'inverter',
  power: 0,
  direction: 'forward',
  ...overrides,
});

describe('OigFlowConnection — formatPower()', () => {
  let el: OigFlowConnection;

  beforeEach(() => {
    el = new OigFlowConnection();
    el.fromNode = makeNode();
    el.toNode = makeNode({ id: 'inverter', type: 'inverter', x: 200 });
    el.connection = makeConn();
  });

  it('rounds small watt values to nearest integer string', () => {
    el.connection = makeConn({ power: 350 });
    expect(callMethod(el, 'formatPower')).toBe('350');
  });

  it('converts values >= 1000 W to kW with one decimal', () => {
    el.connection = makeConn({ power: 3500 });
    expect(callMethod(el, 'formatPower')).toBe('3.5k');
  });

  it('formats exactly 1000 W as "1.0k"', () => {
    el.connection = makeConn({ power: 1000 });
    expect(callMethod(el, 'formatPower')).toBe('1.0k');
  });

  it('formats negative power preserving sign', () => {
    el.connection = makeConn({ power: -2500 });
    expect(callMethod(el, 'formatPower')).toBe('-2.5k');
  });

  it('formats zero power as "0"', () => {
    el.connection = makeConn({ power: 0 });
    expect(callMethod(el, 'formatPower')).toBe('0');
  });
});

describe('OigFlowConnection — getStrokeColor()', () => {
  let el: OigFlowConnection;

  beforeEach(() => {
    el = new OigFlowConnection();
    el.fromNode = makeNode();
    el.toNode = makeNode({ id: 'inverter', type: 'inverter', x: 200 });
    el.connection = makeConn();
  });

  it('returns solar node color when power > 0 and fromNode is solar', () => {
    el.connection = makeConn({ power: 1000 });
    el.fromNode = makeNode({ type: 'solar' });
    expect(callMethod(el, 'getStrokeColor')).toBe(NODE_COLORS.solar);
  });

  it('returns battery node color when power > 0 and fromNode is battery', () => {
    el.connection = makeConn({ power: 500 });
    el.fromNode = makeNode({ type: 'battery' });
    expect(callMethod(el, 'getStrokeColor')).toBe(NODE_COLORS.battery);
  });

  it('returns grid color when power < 0 regardless of fromNode type', () => {
    el.connection = makeConn({ power: -500 });
    el.fromNode = makeNode({ type: 'solar' });
    expect(callMethod(el, 'getStrokeColor')).toBe(NODE_COLORS.grid);
  });

  it('returns divider color when power is exactly zero', () => {
    el.connection = makeConn({ power: 0 });
    expect(callMethod(el, 'getStrokeColor')).toBe(CSS_VARS.divider);
  });
});

describe('OigFlowConnection — getPath()', () => {
  let el: OigFlowConnection;

  beforeEach(() => {
    el = new OigFlowConnection();
    el.connection = makeConn();
  });

  it('generates correct cubic bezier path between horizontal nodes', () => {
    el.fromNode = makeNode({ x: 0, y: 0, width: 100, height: 80 });
    el.toNode = makeNode({ x: 200, y: 0, width: 100, height: 80 });
    const path = callMethod(el, 'getPath') as string;
    expect(path).toBe('M 50 40 C 150 40, 150 40, 250 40');
  });

  it('starts at fromNode center (x + width/2, y + height/2)', () => {
    el.fromNode = makeNode({ x: 20, y: 10, width: 120, height: 60 });
    el.toNode = makeNode({ x: 300, y: 10, width: 120, height: 60 });
    const path = callMethod(el, 'getPath') as string;
    expect(path).toMatch(/^M 80 40 C/);
  });

  it('ends at toNode center when nodes are vertically offset', () => {
    el.fromNode = makeNode({ x: 0, y: 0, width: 100, height: 80 });
    el.toNode = makeNode({ x: 200, y: 100, width: 100, height: 80 });
    const path = callMethod(el, 'getPath') as string;
    expect(path).toContain('250 140');
  });
});

describe('OigFlowConnection — getLabelPosition()', () => {
  let el: OigFlowConnection;

  beforeEach(() => {
    el = new OigFlowConnection();
    el.connection = makeConn();
  });

  it('x is midpoint between both node centers', () => {
    el.fromNode = makeNode({ x: 0, y: 0, width: 100, height: 80 });
    el.toNode = makeNode({ x: 200, y: 0, width: 100, height: 80 });
    const pos = callMethod(el, 'getLabelPosition') as { x: number; y: number };
    expect(pos.x).toBe(150);
  });

  it('y is midpoint minus 8px vertical offset', () => {
    el.fromNode = makeNode({ x: 0, y: 0, width: 100, height: 80 });
    el.toNode = makeNode({ x: 200, y: 0, width: 100, height: 80 });
    const pos = callMethod(el, 'getLabelPosition') as { x: number; y: number };
    expect(pos.y).toBe(32);
  });

  it('handles vertically offset nodes correctly', () => {
    el.fromNode = makeNode({ x: 0, y: 0, width: 100, height: 80 });
    el.toNode = makeNode({ x: 0, y: 200, width: 100, height: 80 });
    const pos = callMethod(el, 'getLabelPosition') as { x: number; y: number };
    expect(pos.x).toBe(50);
    expect(pos.y).toBe(132);
  });
});
