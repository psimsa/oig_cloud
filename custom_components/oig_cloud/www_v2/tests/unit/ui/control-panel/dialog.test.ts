import { describe, it, expect, vi, beforeEach } from 'vitest';
import { OigBatteryChargeDialog } from '@/ui/features/control-panel/dialog';
import type { BatteryChargeParams } from '@/ui/features/control-panel/types';

function getPrivate(el: OigBatteryChargeDialog, key: string): unknown {
  return Reflect.get(el, key);
}

function setPrivate(el: OigBatteryChargeDialog, key: string, value: unknown): void {
  Reflect.set(el, key, value);
}

function callMethod(el: OigBatteryChargeDialog, name: string, ...args: unknown[]): unknown {
  const method = Reflect.get(el, name);
  if (typeof method !== 'function') throw new Error(`No method on dialog: ${name}`);
  return Reflect.apply(method, el, args);
}

describe('OigBatteryChargeDialog — property defaults', () => {
  let el: OigBatteryChargeDialog;

  beforeEach(() => {
    el = new OigBatteryChargeDialog();
  });

  it('open defaults to false', () => {
    expect(el.open).toBe(false);
  });

  it('currentSoc defaults to 0', () => {
    expect(el.currentSoc).toBe(0);
  });

  it('maxSoc defaults to 100', () => {
    expect(el.maxSoc).toBe(100);
  });

  it('estimate defaults to null', () => {
    expect(el.estimate).toBeNull();
  });

  it('private targetSoc starts at 80', () => {
    expect(getPrivate(el, 'targetSoc')).toBe(80);
  });
});

describe('OigBatteryChargeDialog — onClose()', () => {
  let el: OigBatteryChargeDialog;

  beforeEach(() => {
    el = new OigBatteryChargeDialog();
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

describe('OigBatteryChargeDialog — onSliderInput()', () => {
  let el: OigBatteryChargeDialog;

  beforeEach(() => {
    el = new OigBatteryChargeDialog();
  });

  it('updates targetSoc from slider value string', () => {
    const fakeEvent = { target: { value: '90' } } as unknown as Event;
    callMethod(el, 'onSliderInput', fakeEvent);
    expect(getPrivate(el, 'targetSoc')).toBe(90);
  });

  it('dispatches soc-change with updated targetSoc in detail', () => {
    const handler = vi.fn();
    el.addEventListener('soc-change', handler);
    const fakeEvent = { target: { value: '75' } } as unknown as Event;
    callMethod(el, 'onSliderInput', fakeEvent);
    expect(handler).toHaveBeenCalledOnce();
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toEqual({ targetSoc: 75 });
  });

  it('parses slider value with radix 10 (not octal)', () => {
    const fakeEvent = { target: { value: '060' } } as unknown as Event;
    callMethod(el, 'onSliderInput', fakeEvent);
    expect(getPrivate(el, 'targetSoc')).toBe(60);
  });

  it('dispatches soc-change event that bubbles', () => {
    const handler = vi.fn();
    el.addEventListener('soc-change', handler);
    const fakeEvent = { target: { value: '55' } } as unknown as Event;
    callMethod(el, 'onSliderInput', fakeEvent);
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.bubbles).toBe(true);
  });
});

describe('OigBatteryChargeDialog — onConfirm()', () => {
  let el: OigBatteryChargeDialog;

  beforeEach(() => {
    el = new OigBatteryChargeDialog();
  });

  it('dispatches "confirm" event with current targetSoc', () => {
    const handler = vi.fn();
    el.addEventListener('confirm', handler);
    setPrivate(el, 'targetSoc', 85);
    callMethod(el, 'onConfirm');
    expect(handler).toHaveBeenCalledOnce();
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toEqual({ targetSoc: 85 });
  });

  it('confirm event carries targetSoc updated by slider', () => {
    const handler = vi.fn();
    el.addEventListener('confirm', handler);
    callMethod(el, 'onSliderInput', { target: { value: '95' } } as unknown as Event);
    callMethod(el, 'onConfirm');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail.targetSoc).toBe(95);
  });

  it('confirm event bubbles', () => {
    const handler = vi.fn();
    el.addEventListener('confirm', handler);
    callMethod(el, 'onConfirm');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.bubbles).toBe(true);
  });
});

describe('OigBatteryChargeDialog — estimate property', () => {
  let el: OigBatteryChargeDialog;

  beforeEach(() => {
    el = new OigBatteryChargeDialog();
  });

  it('accepts a BatteryChargeParams object', () => {
    const params: BatteryChargeParams = {
      targetSoc: 90,
      estimatedCost: 12.5,
      estimatedTime: 3600,
    };
    el.estimate = params;
    expect(el.estimate).toEqual(params);
  });

  it('can be reset to null', () => {
    el.estimate = { targetSoc: 80, estimatedCost: 5, estimatedTime: 1800 };
    el.estimate = null;
    expect(el.estimate).toBeNull();
  });

  it('estimatedTime reflects seconds value (not minutes)', () => {
    const params: BatteryChargeParams = {
      targetSoc: 70,
      estimatedCost: 20,
      estimatedTime: 7200,
    };
    el.estimate = params;
    expect(el.estimate!.estimatedTime).toBe(7200);
  });
});
