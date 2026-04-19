import { describe, it, expect, vi, beforeEach } from 'vitest';
import { OigStatusBadge } from '@/ui/components/status-badge';
import type { AlertLevel } from '@/ui/components/status-badge';

function callPrivate(el: OigStatusBadge, name: string, ...args: unknown[]): unknown {
  const fn = Reflect.get(el, name);
  if (typeof fn !== 'function') throw new Error(`No method '${name}' on OigStatusBadge`);
  return Reflect.apply(fn, el, args);
}

describe('OigStatusBadge — property defaults', () => {
  it('level defaults to "ok"', () => {
    const el = new OigStatusBadge();
    expect(el.level).toBe('ok');
  });

  it('count defaults to 0', () => {
    const el = new OigStatusBadge();
    expect(el.count).toBe(0);
  });

  it('label defaults to empty string', () => {
    const el = new OigStatusBadge();
    expect(el.label).toBe('');
  });

  it('compact defaults to false', () => {
    const el = new OigStatusBadge();
    expect(el.compact).toBe(false);
  });
});

describe('OigStatusBadge — connectedCallback()', () => {
  it('registers a "click" event listener', () => {
    const el = new OigStatusBadge();
    const spy = vi.spyOn(el, 'addEventListener');
    el.connectedCallback();
    expect(spy).toHaveBeenCalledWith('click', expect.any(Function));
  });
});

describe('OigStatusBadge — disconnectedCallback()', () => {
  it('removes the "click" event listener', () => {
    const el = new OigStatusBadge();
    const spy = vi.spyOn(el, 'removeEventListener');
    el.disconnectedCallback();
    expect(spy).toHaveBeenCalledWith('click', expect.any(Function));
  });
});

describe('OigStatusBadge — onClick() event dispatch', () => {
  let el: OigStatusBadge;

  beforeEach(() => {
    el = new OigStatusBadge();
  });

  it('dispatches a "status-click" custom event', () => {
    const handler = vi.fn();
    el.addEventListener('status-click', handler);
    callPrivate(el, 'onClick');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('status-click detail contains default { level, count }', () => {
    const handler = vi.fn();
    el.addEventListener('status-click', handler);
    callPrivate(el, 'onClick');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toEqual({ level: 'ok', count: 0 });
  });

  it('status-click detail reflects current level and count', () => {
    el.level = 'error' as AlertLevel;
    el.count = 7;
    const handler = vi.fn();
    el.addEventListener('status-click', handler);
    callPrivate(el, 'onClick');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toEqual({ level: 'error', count: 7 });
  });

  it('status-click event bubbles', () => {
    const handler = vi.fn();
    el.addEventListener('status-click', handler);
    callPrivate(el, 'onClick');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.bubbles).toBe(true);
  });
});

describe('OigStatusBadge — render() conditional content', () => {
  it('omits count part when count is 0', () => {
    const el = new OigStatusBadge();
    el.count = 0;
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[0]).toBeNull();
  });

  it('includes count part when count > 0', () => {
    const el = new OigStatusBadge();
    el.count = 3;
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[0]).not.toBeNull();
  });

  it('omits label part when label is empty string', () => {
    const el = new OigStatusBadge();
    el.label = '';
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[1]).toBeNull();
  });

  it('includes label part when label is non-empty', () => {
    const el = new OigStatusBadge();
    el.label = 'Warnings';
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[1]).not.toBeNull();
  });

  it('shows both parts when count > 0 and label is non-empty', () => {
    const el = new OigStatusBadge();
    el.count = 2;
    el.label = 'OK';
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[0]).not.toBeNull();
    expect(result.values[1]).not.toBeNull();
  });

  it('hides both parts when count is 0 and label is empty', () => {
    const el = new OigStatusBadge();
    const result = el.render() as unknown as { values: unknown[] };
    expect(result.values[0]).toBeNull();
    expect(result.values[1]).toBeNull();
  });
});
