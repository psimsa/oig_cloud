import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { OigTileDialog } from '@/ui/features/tiles/tile-dialog';
import type { TileConfig } from '@/data/tiles-data';
import type { HassState } from '@/data/state-watcher';

// ─── Module mocks ─────────────────────────────────────────────────────────────

vi.mock('@/data/entity-store', () => ({
  getEntityStore: vi.fn().mockReturnValue(null),
}));

vi.mock('@/utils/format', () => ({
  getIconEmoji: vi.fn().mockImplementation((icon: string) => {
    if (!icon) return '⚙️';
    const key = icon.replace(/^mdi:/, '');
    const map: Record<string, string> = {
      'thermometer': '🌡️',
      'lightbulb': '💡',
      'fan': '🌀',
    };
    return map[key] ?? '⚙️';
  }),
}));

import { getEntityStore } from '@/data/entity-store';
import { getIconEmoji } from '@/utils/format';

// ─── Test helpers ─────────────────────────────────────────────────────────────

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

type TR = { values: unknown[] };

function renderValues(el: OigTileDialog): unknown[] {
  return (el.render() as unknown as TR).values;
}

// ─── State factory helpers ────────────────────────────────────────────────────

function makeHassState(overrides: Partial<HassState> & { entity_id: string }): HassState {
  return {
    entity_id: overrides.entity_id,
    state: overrides.state ?? 'on',
    attributes: overrides.attributes ?? {},
    last_updated: overrides.last_updated ?? '2026-01-01T00:00:00.000Z',
    last_changed: overrides.last_changed ?? '2026-01-01T00:00:00.000Z',
  } as unknown as HassState;
}

function makeMockStore(entities: Record<string, HassState>) {
  return {
    getAll: vi.fn().mockReturnValue(entities),
    get: vi.fn((id: string) => entities[id] ?? null),
  };
}

// ─── Property defaults ────────────────────────────────────────────────────────

describe('OigTileDialog — property defaults', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
  });

  it('isOpen defaults to false', () => {
    expect(el.isOpen).toBe(false);
  });

  it('tileIndex defaults to -1', () => {
    expect(el.tileIndex).toBe(-1);
  });

  it('tileSide defaults to "left"', () => {
    expect(el.tileSide).toBe('left');
  });

  it('existingConfig defaults to null', () => {
    expect(el.existingConfig).toBeNull();
  });

  it('private currentTab defaults to "entity"', () => {
    expect(getPrivate(el, 'currentTab')).toBe('entity');
  });

  it('private entitySearchText defaults to empty string', () => {
    expect(getPrivate(el, 'entitySearchText')).toBe('');
  });

  it('private buttonSearchText defaults to empty string', () => {
    expect(getPrivate(el, 'buttonSearchText')).toBe('');
  });

  it('private selectedEntityId defaults to empty string', () => {
    expect(getPrivate(el, 'selectedEntityId')).toBe('');
  });

  it('private selectedButtonEntityId defaults to empty string', () => {
    expect(getPrivate(el, 'selectedButtonEntityId')).toBe('');
  });

  it('private label defaults to empty string', () => {
    expect(getPrivate(el, 'label')).toBe('');
  });

  it('private icon defaults to empty string', () => {
    expect(getPrivate(el, 'icon')).toBe('');
  });

  it('private color defaults to #03A9F4', () => {
    expect(getPrivate(el, 'color')).toBe('#03A9F4');
  });

  it('private action defaults to "toggle"', () => {
    expect(getPrivate(el, 'action')).toBe('toggle');
  });

  it('private supportEntity1 defaults to empty string', () => {
    expect(getPrivate(el, 'supportEntity1')).toBe('');
  });

  it('private supportEntity2 defaults to empty string', () => {
    expect(getPrivate(el, 'supportEntity2')).toBe('');
  });

  it('private iconPickerOpen defaults to false', () => {
    expect(getPrivate(el, 'iconPickerOpen')).toBe(false);
  });
});

// ─── loadTileConfig() ────────────────────────────────────────────────────────

describe('OigTileDialog — loadTileConfig() with entity type', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
  });

  it('sets currentTab to "entity"', () => {
    const config: TileConfig = { type: 'entity', entity_id: 'sensor.temp' };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'currentTab')).toBe('entity');
  });

  it('sets selectedEntityId', () => {
    const config: TileConfig = { type: 'entity', entity_id: 'sensor.temp' };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'selectedEntityId')).toBe('sensor.temp');
  });

  it('does not set selectedButtonEntityId for entity type', () => {
    const config: TileConfig = { type: 'entity', entity_id: 'sensor.temp' };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'selectedButtonEntityId')).toBe('');
  });

  it('sets label from config', () => {
    const config: TileConfig = { type: 'entity', entity_id: 'sensor.temp', label: 'My Temp' };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'label')).toBe('My Temp');
  });

  it('sets label to empty string when undefined', () => {
    const config: TileConfig = { type: 'entity', entity_id: 'sensor.temp' };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'label')).toBe('');
  });

  it('sets icon from config', () => {
    const config: TileConfig = { type: 'entity', entity_id: 'sensor.temp', icon: 'mdi:thermometer' };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'icon')).toBe('mdi:thermometer');
  });

  it('sets color from config', () => {
    const config: TileConfig = { type: 'entity', entity_id: 'sensor.temp', color: '#FF0000' };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'color')).toBe('#FF0000');
  });

  it('sets color to default when not provided', () => {
    const config: TileConfig = { type: 'entity', entity_id: 'sensor.temp' };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'color')).toBe('#03A9F4');
  });

  it('sets supportEntity1 from top_right', () => {
    const config: TileConfig = {
      type: 'entity',
      entity_id: 'sensor.temp',
      support_entities: { top_right: 'sensor.humidity' },
    };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'supportEntity1')).toBe('sensor.humidity');
  });

  it('sets supportEntity2 from bottom_right', () => {
    const config: TileConfig = {
      type: 'entity',
      entity_id: 'sensor.temp',
      support_entities: { bottom_right: 'sensor.pressure' },
    };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'supportEntity2')).toBe('sensor.pressure');
  });

  it('sets supportEntity1 to empty when no support_entities', () => {
    const config: TileConfig = { type: 'entity', entity_id: 'sensor.temp' };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'supportEntity1')).toBe('');
  });
});

describe('OigTileDialog — loadTileConfig() with button type', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
  });

  it('sets currentTab to "button"', () => {
    const config: TileConfig = { type: 'button', entity_id: 'switch.light', action: 'toggle' };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'currentTab')).toBe('button');
  });

  it('sets selectedButtonEntityId', () => {
    const config: TileConfig = { type: 'button', entity_id: 'switch.light' };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'selectedButtonEntityId')).toBe('switch.light');
  });

  it('does not set selectedEntityId for button type', () => {
    const config: TileConfig = { type: 'button', entity_id: 'switch.light' };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'selectedEntityId')).toBe('');
  });

  it('sets action from config', () => {
    const config: TileConfig = { type: 'button', entity_id: 'switch.light', action: 'turn_on' };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'action')).toBe('turn_on');
  });

  it('sets action to "toggle" when not provided', () => {
    const config: TileConfig = { type: 'button', entity_id: 'switch.light' };
    el.loadTileConfig(config);
    expect(getPrivate(el, 'action')).toBe('toggle');
  });
});

// ─── resetForm() ─────────────────────────────────────────────────────────────

describe('OigTileDialog — resetForm()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
    setPrivate(el, 'currentTab', 'button');
    setPrivate(el, 'selectedEntityId', 'sensor.temp');
    setPrivate(el, 'selectedButtonEntityId', 'switch.light');
    setPrivate(el, 'label', 'My Label');
    setPrivate(el, 'icon', 'mdi:lightbulb');
    setPrivate(el, 'color', '#FF0000');
    setPrivate(el, 'action', 'turn_on');
    setPrivate(el, 'supportEntity1', 'sensor.humidity');
    setPrivate(el, 'supportEntity2', 'sensor.pressure');
    setPrivate(el, 'supportSearch1', 'humi');
    setPrivate(el, 'supportSearch2', 'pres');
    setPrivate(el, 'showSupportList1', true);
    setPrivate(el, 'showSupportList2', true);
    setPrivate(el, 'iconPickerOpen', true);
  });

  it('resets currentTab to "entity"', () => {
    callMethod(el, 'resetForm');
    expect(getPrivate(el, 'currentTab')).toBe('entity');
  });

  it('resets selectedEntityId to empty string', () => {
    callMethod(el, 'resetForm');
    expect(getPrivate(el, 'selectedEntityId')).toBe('');
  });

  it('resets selectedButtonEntityId to empty string', () => {
    callMethod(el, 'resetForm');
    expect(getPrivate(el, 'selectedButtonEntityId')).toBe('');
  });

  it('resets label to empty string', () => {
    callMethod(el, 'resetForm');
    expect(getPrivate(el, 'label')).toBe('');
  });

  it('resets icon to empty string', () => {
    callMethod(el, 'resetForm');
    expect(getPrivate(el, 'icon')).toBe('');
  });

  it('resets color to default #03A9F4', () => {
    callMethod(el, 'resetForm');
    expect(getPrivate(el, 'color')).toBe('#03A9F4');
  });

  it('resets action to "toggle"', () => {
    callMethod(el, 'resetForm');
    expect(getPrivate(el, 'action')).toBe('toggle');
  });

  it('resets supportEntity1 to empty string', () => {
    callMethod(el, 'resetForm');
    expect(getPrivate(el, 'supportEntity1')).toBe('');
  });

  it('resets supportEntity2 to empty string', () => {
    callMethod(el, 'resetForm');
    expect(getPrivate(el, 'supportEntity2')).toBe('');
  });

  it('resets supportSearch1 to empty string', () => {
    callMethod(el, 'resetForm');
    expect(getPrivate(el, 'supportSearch1')).toBe('');
  });

  it('resets supportSearch2 to empty string', () => {
    callMethod(el, 'resetForm');
    expect(getPrivate(el, 'supportSearch2')).toBe('');
  });

  it('resets showSupportList1 to false', () => {
    callMethod(el, 'resetForm');
    expect(getPrivate(el, 'showSupportList1')).toBe(false);
  });

  it('resets showSupportList2 to false', () => {
    callMethod(el, 'resetForm');
    expect(getPrivate(el, 'showSupportList2')).toBe(false);
  });

  it('resets iconPickerOpen to false', () => {
    callMethod(el, 'resetForm');
    expect(getPrivate(el, 'iconPickerOpen')).toBe(false);
  });
});

// ─── handleClose() ────────────────────────────────────────────────────────────

describe('OigTileDialog — handleClose()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
    el.isOpen = true;
    setPrivate(el, 'label', 'dirty');
  });

  it('sets isOpen to false', () => {
    callMethod(el, 'handleClose');
    expect(el.isOpen).toBe(false);
  });

  it('resets the form (clears dirty state)', () => {
    callMethod(el, 'handleClose');
    expect(getPrivate(el, 'label')).toBe('');
  });

  it('dispatches a "close" CustomEvent', () => {
    const handler = vi.fn();
    el.addEventListener('close', handler);
    callMethod(el, 'handleClose');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('close event is a CustomEvent', () => {
    let received: Event | null = null;
    el.addEventListener('close', (e) => { received = e; });
    callMethod(el, 'handleClose');
    expect(received).toBeInstanceOf(CustomEvent);
  });

  it('close event bubbles', () => {
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    parent.appendChild(el as unknown as Node);
    const handler = vi.fn();
    parent.addEventListener('close', handler);
    callMethod(el, 'handleClose');
    expect(handler).toHaveBeenCalledOnce();
    parent.remove();
  });
});

// ─── getEntities() ────────────────────────────────────────────────────────────

describe('OigTileDialog — getEntities()', () => {
  let el: OigTileDialog;

  afterEach(() => {
    vi.mocked(getEntityStore).mockReturnValue(null);
  });

  beforeEach(() => {
    el = new OigTileDialog();
  });

  it('returns {} when store is null', () => {
    vi.mocked(getEntityStore).mockReturnValue(null);
    const result = callMethod(el, 'getEntities');
    expect(result).toEqual({});
  });

  it('returns entities from store when available', () => {
    const fakeState = makeHassState({ entity_id: 'sensor.temp', state: '21.5' });
    const store = makeMockStore({ 'sensor.temp': fakeState });
    vi.mocked(getEntityStore).mockReturnValue(store as any);
    const result = callMethod(el, 'getEntities') as Record<string, HassState>;
    expect(result['sensor.temp']).toBeDefined();
    expect(result['sensor.temp'].state).toBe('21.5');
  });
});

// ─── getEntityItems() ────────────────────────────────────────────────────────

describe('OigTileDialog — getEntityItems()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
    const entities = {
      'sensor.temperature': makeHassState({
        entity_id: 'sensor.temperature',
        state: '21.5',
        attributes: { friendly_name: 'Temperature', unit_of_measurement: '°C', icon: 'mdi:thermometer' },
      }),
      'binary_sensor.motion': makeHassState({
        entity_id: 'binary_sensor.motion',
        state: 'on',
        attributes: { friendly_name: 'Motion Sensor' },
      }),
      'switch.light': makeHassState({
        entity_id: 'switch.light',
        state: 'off',
        attributes: { friendly_name: 'Main Light' },
      }),
    };
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore(entities) as any);
  });

  afterEach(() => {
    vi.mocked(getEntityStore).mockReturnValue(null);
  });

  it('filters entities to specified domains', () => {
    const items = callMethod(el, 'getEntityItems', ['sensor.', 'binary_sensor.'], '') as unknown[];
    const ids = (items as any[]).map(i => i.id);
    expect(ids).toContain('sensor.temperature');
    expect(ids).toContain('binary_sensor.motion');
    expect(ids).not.toContain('switch.light');
  });

  it('returns empty array when no matching domain entities', () => {
    const items = callMethod(el, 'getEntityItems', ['fan.'], '') as unknown[];
    expect(items).toHaveLength(0);
  });

  it('filters by search text on friendly_name', () => {
    const items = callMethod(el, 'getEntityItems', ['sensor.', 'binary_sensor.'], 'temp') as unknown[];
    const ids = (items as any[]).map(i => i.id);
    expect(ids).toContain('sensor.temperature');
    expect(ids).not.toContain('binary_sensor.motion');
  });

  it('filters by search text on entity id', () => {
    const items = callMethod(el, 'getEntityItems', ['sensor.', 'binary_sensor.'], 'motion') as unknown[];
    const ids = (items as any[]).map(i => i.id);
    expect(ids).toContain('binary_sensor.motion');
    expect(ids).not.toContain('sensor.temperature');
  });

  it('returns all matching entities when search is empty', () => {
    const items = callMethod(el, 'getEntityItems', ['sensor.', 'binary_sensor.'], '') as unknown[];
    expect((items as any[]).length).toBe(2);
  });

  it('includes name, value, unit, icon, state in each item', () => {
    const items = callMethod(el, 'getEntityItems', ['sensor.'], '') as any[];
    const item = items[0];
    expect(item).toHaveProperty('id');
    expect(item).toHaveProperty('name');
    expect(item).toHaveProperty('value');
    expect(item).toHaveProperty('unit');
    expect(item).toHaveProperty('icon');
    expect(item).toHaveProperty('state');
  });

  it('uses entity_id as name when friendly_name is absent', () => {
    const entities = {
      'sensor.no_name': makeHassState({ entity_id: 'sensor.no_name', state: '5', attributes: {} }),
    };
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore(entities) as any);
    const items = callMethod(el, 'getEntityItems', ['sensor.'], '') as any[];
    expect(items[0].name).toBe('sensor.no_name');
  });

  it('sorts results alphabetically by name', () => {
    const entities = {
      'sensor.zebra': makeHassState({ entity_id: 'sensor.zebra', state: '1', attributes: { friendly_name: 'Zebra' } }),
      'sensor.apple': makeHassState({ entity_id: 'sensor.apple', state: '2', attributes: { friendly_name: 'Apple' } }),
    };
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore(entities) as any);
    const items = callMethod(el, 'getEntityItems', ['sensor.'], '') as any[];
    expect(items[0].name).toBe('Apple');
    expect(items[1].name).toBe('Zebra');
  });
});

// ─── getSupportEntities() ────────────────────────────────────────────────────

describe('OigTileDialog — getSupportEntities()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
    const entities = {
      'sensor.humidity': makeHassState({
        entity_id: 'sensor.humidity',
        state: '65',
        attributes: { friendly_name: 'Humidity', unit_of_measurement: '%' },
      }),
    };
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore(entities) as any);
  });

  afterEach(() => {
    vi.mocked(getEntityStore).mockReturnValue(null);
  });

  it('returns empty array when search is empty', () => {
    const result = callMethod(el, 'getSupportEntities', '') as unknown[];
    expect(result).toHaveLength(0);
  });

  it('returns empty array when search is whitespace only', () => {
    const result = callMethod(el, 'getSupportEntities', '   ') as unknown[];
    expect(result).toHaveLength(0);
  });

  it('returns matching entities when search is provided', () => {
    const result = callMethod(el, 'getSupportEntities', 'humi') as any[];
    expect(result.length).toBeGreaterThan(0);
    expect(result[0].id).toBe('sensor.humidity');
  });

  it('limits results to 20 items', () => {
    const entities: Record<string, HassState> = {};
    for (let i = 0; i < 30; i++) {
      const id = `sensor.temp_${i}`;
      entities[id] = makeHassState({ entity_id: id, state: `${i}`, attributes: { friendly_name: `Temp ${i}` } });
    }
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore(entities) as any);
    const result = callMethod(el, 'getSupportEntities', 'temp') as unknown[];
    expect(result.length).toBeLessThanOrEqual(20);
  });
});

// ─── getDisplayIcon() ─────────────────────────────────────────────────────────

describe('OigTileDialog — getDisplayIcon()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
  });

  it('returns getIconEmoji("") for empty string', () => {
    callMethod(el, 'getDisplayIcon', '');
    expect(vi.mocked(getIconEmoji)).toHaveBeenCalledWith('');
  });

  it('passes MDI icons to getIconEmoji', () => {
    callMethod(el, 'getDisplayIcon', 'mdi:thermometer');
    expect(vi.mocked(getIconEmoji)).toHaveBeenCalledWith('mdi:thermometer');
  });

  it('returns non-MDI icons as-is without calling getIconEmoji', () => {
    vi.mocked(getIconEmoji).mockClear();
    const result = callMethod(el, 'getDisplayIcon', '🌡️');
    expect(result).toBe('🌡️');
    expect(vi.mocked(getIconEmoji)).not.toHaveBeenCalled();
  });
});

// ─── getColorForEntity() ─────────────────────────────────────────────────────

describe('OigTileDialog — getColorForEntity()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
  });

  it('returns #03A9F4 for sensor domain', () => {
    expect(callMethod(el, 'getColorForEntity', 'sensor.temp')).toBe('#03A9F4');
  });

  it('returns #4CAF50 for binary_sensor domain', () => {
    expect(callMethod(el, 'getColorForEntity', 'binary_sensor.motion')).toBe('#4CAF50');
  });

  it('returns #FFC107 for switch domain', () => {
    expect(callMethod(el, 'getColorForEntity', 'switch.outlet')).toBe('#FFC107');
  });

  it('returns #FF9800 for light domain', () => {
    expect(callMethod(el, 'getColorForEntity', 'light.bedroom')).toBe('#FF9800');
  });

  it('returns #00BCD4 for fan domain', () => {
    expect(callMethod(el, 'getColorForEntity', 'fan.ceiling')).toBe('#00BCD4');
  });

  it('returns #9C27B0 for input_boolean domain', () => {
    expect(callMethod(el, 'getColorForEntity', 'input_boolean.vacation')).toBe('#9C27B0');
  });

  it('returns #03A9F4 for unknown domain', () => {
    expect(callMethod(el, 'getColorForEntity', 'automation.daily')).toBe('#03A9F4');
  });
});

// ─── getAttributeValue() ─────────────────────────────────────────────────────

describe('OigTileDialog — getAttributeValue()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
  });

  it('returns empty string when attribute is missing', () => {
    const state = makeHassState({ entity_id: 'sensor.temp', attributes: {} });
    expect(callMethod(el, 'getAttributeValue', state, 'friendly_name')).toBe('');
  });

  it('returns empty string when attribute is null', () => {
    const state = makeHassState({ entity_id: 'sensor.temp', attributes: { friendly_name: null } });
    expect(callMethod(el, 'getAttributeValue', state, 'friendly_name')).toBe('');
  });

  it('returns empty string when attribute is undefined', () => {
    const state = makeHassState({ entity_id: 'sensor.temp', attributes: { friendly_name: undefined } });
    expect(callMethod(el, 'getAttributeValue', state, 'friendly_name')).toBe('');
  });

  it('returns string value for string attribute', () => {
    const state = makeHassState({ entity_id: 'sensor.temp', attributes: { friendly_name: 'My Sensor' } });
    expect(callMethod(el, 'getAttributeValue', state, 'friendly_name')).toBe('My Sensor');
  });

  it('converts numeric attribute to string', () => {
    const state = makeHassState({ entity_id: 'sensor.temp', attributes: { brightness: 128 } });
    expect(callMethod(el, 'getAttributeValue', state, 'brightness')).toBe('128');
  });
});

// ─── applyEntityDefaults() ───────────────────────────────────────────────────

describe('OigTileDialog — applyEntityDefaults()', () => {
  let el: OigTileDialog;

  afterEach(() => {
    vi.mocked(getEntityStore).mockReturnValue(null);
  });

  beforeEach(() => {
    el = new OigTileDialog();
  });

  it('does nothing when entityId is empty', () => {
    callMethod(el, 'applyEntityDefaults', '');
    expect(getPrivate(el, 'label')).toBe('');
  });

  it('does nothing when entity is not in store', () => {
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({}) as any);
    callMethod(el, 'applyEntityDefaults', 'sensor.nonexistent');
    expect(getPrivate(el, 'label')).toBe('');
    expect(getPrivate(el, 'icon')).toBe('');
  });

  it('sets label from friendly_name when label is empty', () => {
    const state = makeHassState({
      entity_id: 'sensor.temp',
      state: '21',
      attributes: { friendly_name: 'Room Temp' },
    });
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({ 'sensor.temp': state }) as any);
    callMethod(el, 'applyEntityDefaults', 'sensor.temp');
    expect(getPrivate(el, 'label')).toBe('Room Temp');
  });

  it('does not override existing label', () => {
    const state = makeHassState({
      entity_id: 'sensor.temp',
      state: '21',
      attributes: { friendly_name: 'Room Temp' },
    });
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({ 'sensor.temp': state }) as any);
    setPrivate(el, 'label', 'Custom Label');
    callMethod(el, 'applyEntityDefaults', 'sensor.temp');
    expect(getPrivate(el, 'label')).toBe('Custom Label');
  });

  it('sets icon from entity icon attribute when icon is empty', () => {
    const state = makeHassState({
      entity_id: 'sensor.temp',
      state: '21',
      attributes: { icon: 'mdi:thermometer' },
    });
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({ 'sensor.temp': state }) as any);
    callMethod(el, 'applyEntityDefaults', 'sensor.temp');
    expect(getPrivate(el, 'icon')).toBe('mdi:thermometer');
  });

  it('does not override existing icon', () => {
    const state = makeHassState({
      entity_id: 'sensor.temp',
      state: '21',
      attributes: { icon: 'mdi:thermometer' },
    });
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({ 'sensor.temp': state }) as any);
    setPrivate(el, 'icon', 'mdi:fire');
    callMethod(el, 'applyEntityDefaults', 'sensor.temp');
    expect(getPrivate(el, 'icon')).toBe('mdi:fire');
  });

  it('sets color based on entity domain', () => {
    const state = makeHassState({
      entity_id: 'switch.light',
      state: 'on',
      attributes: {},
    });
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({ 'switch.light': state }) as any);
    callMethod(el, 'applyEntityDefaults', 'switch.light');
    expect(getPrivate(el, 'color')).toBe('#FFC107');
  });
});

// ─── handleEntitySelect() ────────────────────────────────────────────────────

describe('OigTileDialog — handleEntitySelect()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({}) as any);
  });

  afterEach(() => {
    vi.mocked(getEntityStore).mockReturnValue(null);
  });

  it('sets selectedEntityId', () => {
    callMethod(el, 'handleEntitySelect', 'sensor.temp');
    expect(getPrivate(el, 'selectedEntityId')).toBe('sensor.temp');
  });

  it('calls applyEntityDefaults with the entity id', () => {
    const spy = vi.spyOn(el as any, 'applyEntityDefaults');
    callMethod(el, 'handleEntitySelect', 'sensor.temp');
    expect(spy).toHaveBeenCalledWith('sensor.temp');
  });
});

// ─── handleButtonEntitySelect() ──────────────────────────────────────────────

describe('OigTileDialog — handleButtonEntitySelect()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({}) as any);
  });

  afterEach(() => {
    vi.mocked(getEntityStore).mockReturnValue(null);
  });

  it('sets selectedButtonEntityId', () => {
    callMethod(el, 'handleButtonEntitySelect', 'switch.light');
    expect(getPrivate(el, 'selectedButtonEntityId')).toBe('switch.light');
  });

  it('calls applyEntityDefaults with the entity id', () => {
    const spy = vi.spyOn(el as any, 'applyEntityDefaults');
    callMethod(el, 'handleButtonEntitySelect', 'switch.light');
    expect(spy).toHaveBeenCalledWith('switch.light');
  });
});

// ─── handleSupportInput() ────────────────────────────────────────────────────

describe('OigTileDialog — handleSupportInput()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
  });

  it('index 1: sets supportSearch1 to the input value', () => {
    callMethod(el, 'handleSupportInput', 1, 'humi');
    expect(getPrivate(el, 'supportSearch1')).toBe('humi');
  });

  it('index 1: shows support list when non-empty value', () => {
    callMethod(el, 'handleSupportInput', 1, 'humi');
    expect(getPrivate(el, 'showSupportList1')).toBe(true);
  });

  it('index 1: hides support list when empty value', () => {
    setPrivate(el, 'showSupportList1', true);
    callMethod(el, 'handleSupportInput', 1, '');
    expect(getPrivate(el, 'showSupportList1')).toBe(false);
  });

  it('index 1: clears supportEntity1 when value is empty', () => {
    setPrivate(el, 'supportEntity1', 'sensor.humidity');
    callMethod(el, 'handleSupportInput', 1, '');
    expect(getPrivate(el, 'supportEntity1')).toBe('');
  });

  it('index 1: does not clear supportEntity1 when value is non-empty', () => {
    setPrivate(el, 'supportEntity1', 'sensor.humidity');
    callMethod(el, 'handleSupportInput', 1, 'humi');
    expect(getPrivate(el, 'supportEntity1')).toBe('sensor.humidity');
  });

  it('index 2: sets supportSearch2 to the input value', () => {
    callMethod(el, 'handleSupportInput', 2, 'press');
    expect(getPrivate(el, 'supportSearch2')).toBe('press');
  });

  it('index 2: shows support list when non-empty value', () => {
    callMethod(el, 'handleSupportInput', 2, 'press');
    expect(getPrivate(el, 'showSupportList2')).toBe(true);
  });

  it('index 2: hides support list when empty value', () => {
    setPrivate(el, 'showSupportList2', true);
    callMethod(el, 'handleSupportInput', 2, '');
    expect(getPrivate(el, 'showSupportList2')).toBe(false);
  });

  it('index 2: clears supportEntity2 when value is empty', () => {
    setPrivate(el, 'supportEntity2', 'sensor.pressure');
    callMethod(el, 'handleSupportInput', 2, '');
    expect(getPrivate(el, 'supportEntity2')).toBe('');
  });

  it('hides support list when value is whitespace-only (index 1)', () => {
    callMethod(el, 'handleSupportInput', 1, '   ');
    expect(getPrivate(el, 'showSupportList1')).toBe(false);
  });
});

// ─── handleSupportSelect() ───────────────────────────────────────────────────

describe('OigTileDialog — handleSupportSelect()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
  });

  const makeEntityItem = (id: string, name: string) => ({
    id,
    name,
    value: '50',
    unit: '%',
    icon: '',
    state: makeHassState({ entity_id: id }),
  });

  it('index 1: sets supportEntity1 to entity.id', () => {
    const item = makeEntityItem('sensor.humidity', 'Humidity');
    callMethod(el, 'handleSupportSelect', 1, item);
    expect(getPrivate(el, 'supportEntity1')).toBe('sensor.humidity');
  });

  it('index 1: sets supportSearch1 to entity name', () => {
    const item = makeEntityItem('sensor.humidity', 'Humidity');
    callMethod(el, 'handleSupportSelect', 1, item);
    expect(getPrivate(el, 'supportSearch1')).toBe('Humidity');
  });

  it('index 1: hides support list', () => {
    setPrivate(el, 'showSupportList1', true);
    const item = makeEntityItem('sensor.humidity', 'Humidity');
    callMethod(el, 'handleSupportSelect', 1, item);
    expect(getPrivate(el, 'showSupportList1')).toBe(false);
  });

  it('index 1: uses entity.id as name when entity.name is empty', () => {
    const item = makeEntityItem('sensor.humidity', '');
    callMethod(el, 'handleSupportSelect', 1, item);
    expect(getPrivate(el, 'supportSearch1')).toBe('sensor.humidity');
  });

  it('index 2: sets supportEntity2 to entity.id', () => {
    const item = makeEntityItem('sensor.pressure', 'Pressure');
    callMethod(el, 'handleSupportSelect', 2, item);
    expect(getPrivate(el, 'supportEntity2')).toBe('sensor.pressure');
  });

  it('index 2: sets supportSearch2 to entity name', () => {
    const item = makeEntityItem('sensor.pressure', 'Pressure');
    callMethod(el, 'handleSupportSelect', 2, item);
    expect(getPrivate(el, 'supportSearch2')).toBe('Pressure');
  });

  it('index 2: hides support list', () => {
    setPrivate(el, 'showSupportList2', true);
    const item = makeEntityItem('sensor.pressure', 'Pressure');
    callMethod(el, 'handleSupportSelect', 2, item);
    expect(getPrivate(el, 'showSupportList2')).toBe(false);
  });
});

// ─── getSupportInputValue() ──────────────────────────────────────────────────

describe('OigTileDialog — getSupportInputValue()', () => {
  let el: OigTileDialog;

  afterEach(() => {
    vi.mocked(getEntityStore).mockReturnValue(null);
  });

  beforeEach(() => {
    el = new OigTileDialog();
  });

  it('returns searchText when it is non-empty', () => {
    const result = callMethod(el, 'getSupportInputValue', 'humi', 'sensor.humidity');
    expect(result).toBe('humi');
  });

  it('returns empty string when both searchText and entityId are empty', () => {
    const result = callMethod(el, 'getSupportInputValue', '', '');
    expect(result).toBe('');
  });

  it('returns entityId when searchText is empty and entity not in store', () => {
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({}) as any);
    const result = callMethod(el, 'getSupportInputValue', '', 'sensor.unknown');
    expect(result).toBe('sensor.unknown');
  });

  it('returns friendly_name when searchText is empty and entity is in store', () => {
    const state = makeHassState({
      entity_id: 'sensor.humidity',
      state: '65',
      attributes: { friendly_name: 'Humidity Sensor' },
    });
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({ 'sensor.humidity': state }) as any);
    const result = callMethod(el, 'getSupportInputValue', '', 'sensor.humidity');
    expect(result).toBe('Humidity Sensor');
  });

  it('returns entityId when entity lacks friendly_name', () => {
    const state = makeHassState({ entity_id: 'sensor.humidity', state: '65', attributes: {} });
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({ 'sensor.humidity': state }) as any);
    const result = callMethod(el, 'getSupportInputValue', '', 'sensor.humidity');
    expect(result).toBe('sensor.humidity');
  });
});

// ─── handleSave() ─────────────────────────────────────────────────────────────

describe('OigTileDialog — handleSave() with no entity selected', () => {
  let el: OigTileDialog;
  let alertSpy: { mockRestore(): void; mock: { calls: unknown[][] } };

  beforeEach(() => {
    el = new OigTileDialog();
    alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
  });

  afterEach(() => {
    alertSpy.mockRestore();
  });

  it('calls window.alert when entity tab and no entity selected', () => {
    setPrivate(el, 'currentTab', 'entity');
    setPrivate(el, 'selectedEntityId', '');
    callMethod(el, 'handleSave');
    expect(alertSpy).toHaveBeenCalledOnce();
  });

  it('calls window.alert when button tab and no entity selected', () => {
    setPrivate(el, 'currentTab', 'button');
    setPrivate(el, 'selectedButtonEntityId', '');
    callMethod(el, 'handleSave');
    expect(alertSpy).toHaveBeenCalledOnce();
  });

  it('does not dispatch tile-saved when entity is missing', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    setPrivate(el, 'selectedEntityId', '');
    callMethod(el, 'handleSave');
    expect(handler).not.toHaveBeenCalled();
  });
});

describe('OigTileDialog — handleSave() with entity tab selected', () => {
  let el: OigTileDialog;
  let alertSpy: { mockRestore(): void; mock: { calls: unknown[][] } };

  beforeEach(() => {
    el = new OigTileDialog();
    alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    el.tileIndex = 2;
    el.tileSide = 'right';
    setPrivate(el, 'currentTab', 'entity');
    setPrivate(el, 'selectedEntityId', 'sensor.temp');
    setPrivate(el, 'label', 'My Temp');
    setPrivate(el, 'icon', 'mdi:thermometer');
    setPrivate(el, 'color', '#FF0000');
    setPrivate(el, 'supportEntity1', 'sensor.humidity');
    setPrivate(el, 'supportEntity2', '');
  });

  afterEach(() => {
    alertSpy.mockRestore();
  });

  it('dispatches "tile-saved" event', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    expect(handler).toHaveBeenCalledOnce();
  });

  it('tile-saved event detail includes correct index', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const detail = (handler.mock.calls[0][0] as CustomEvent).detail;
    expect(detail.index).toBe(2);
  });

  it('tile-saved event detail includes correct side', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const detail = (handler.mock.calls[0][0] as CustomEvent).detail;
    expect(detail.side).toBe('right');
  });

  it('tile-saved event detail config has type "entity"', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const config = (handler.mock.calls[0][0] as CustomEvent).detail.config;
    expect(config.type).toBe('entity');
  });

  it('tile-saved event detail config has entity_id', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const config = (handler.mock.calls[0][0] as CustomEvent).detail.config;
    expect(config.entity_id).toBe('sensor.temp');
  });

  it('tile-saved event detail config has label', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const config = (handler.mock.calls[0][0] as CustomEvent).detail.config;
    expect(config.label).toBe('My Temp');
  });

  it('tile-saved event detail config has icon', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const config = (handler.mock.calls[0][0] as CustomEvent).detail.config;
    expect(config.icon).toBe('mdi:thermometer');
  });

  it('tile-saved event detail config has color', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const config = (handler.mock.calls[0][0] as CustomEvent).detail.config;
    expect(config.color).toBe('#FF0000');
  });

  it('tile-saved event detail config has support_entities.top_right', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const config = (handler.mock.calls[0][0] as CustomEvent).detail.config;
    expect(config.support_entities.top_right).toBe('sensor.humidity');
  });

  it('tile-saved event detail config has support_entities.bottom_right as undefined when empty', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const config = (handler.mock.calls[0][0] as CustomEvent).detail.config;
    expect(config.support_entities.bottom_right).toBeUndefined();
  });

  it('tile-saved event detail config action is undefined for entity type', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const config = (handler.mock.calls[0][0] as CustomEvent).detail.config;
    expect(config.action).toBeUndefined();
  });

  it('tile-saved event bubbles', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const evt = handler.mock.calls[0][0] as CustomEvent;
    expect(evt.bubbles).toBe(true);
  });

  it('dispatches close event after saving', () => {
    const closeHandler = vi.fn();
    el.addEventListener('close', closeHandler);
    callMethod(el, 'handleSave');
    expect(closeHandler).toHaveBeenCalledOnce();
  });
});

describe('OigTileDialog — handleSave() with button tab selected', () => {
  let el: OigTileDialog;
  let alertSpy: { mockRestore(): void; mock: { calls: unknown[][] } };

  beforeEach(() => {
    el = new OigTileDialog();
    alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    setPrivate(el, 'currentTab', 'button');
    setPrivate(el, 'selectedButtonEntityId', 'switch.light');
    setPrivate(el, 'action', 'turn_on');
    setPrivate(el, 'label', 'Main Light');
  });

  afterEach(() => {
    alertSpy.mockRestore();
  });

  it('tile-saved event detail config has type "button"', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const config = (handler.mock.calls[0][0] as CustomEvent).detail.config;
    expect(config.type).toBe('button');
  });

  it('tile-saved event detail config has action for button type', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const config = (handler.mock.calls[0][0] as CustomEvent).detail.config;
    expect(config.action).toBe('turn_on');
  });

  it('tile-saved event detail config has entity_id from selectedButtonEntityId', () => {
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const config = (handler.mock.calls[0][0] as CustomEvent).detail.config;
    expect(config.entity_id).toBe('switch.light');
  });

  it('label set to undefined when empty string', () => {
    setPrivate(el, 'label', '');
    const handler = vi.fn();
    el.addEventListener('tile-saved', handler);
    callMethod(el, 'handleSave');
    const config = (handler.mock.calls[0][0] as CustomEvent).detail.config;
    expect(config.label).toBeUndefined();
  });
});

// ─── onIconSelected() ─────────────────────────────────────────────────────────

describe('OigTileDialog — onIconSelected()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
    setPrivate(el, 'iconPickerOpen', true);
  });

  it('sets icon from event detail', () => {
    const fakeEvent = new CustomEvent('icon-selected', { detail: { icon: 'mdi:lightbulb' } });
    callMethod(el, 'onIconSelected', fakeEvent);
    expect(getPrivate(el, 'icon')).toBe('mdi:lightbulb');
  });

  it('sets icon to empty string when event detail has no icon', () => {
    const fakeEvent = new CustomEvent('icon-selected', { detail: {} });
    callMethod(el, 'onIconSelected', fakeEvent);
    expect(getPrivate(el, 'icon')).toBe('');
  });

  it('closes icon picker after selection', () => {
    const fakeEvent = new CustomEvent('icon-selected', { detail: { icon: 'mdi:lightbulb' } });
    callMethod(el, 'onIconSelected', fakeEvent);
    expect(getPrivate(el, 'iconPickerOpen')).toBe(false);
  });
});

// ─── render() ────────────────────────────────────────────────────────────────

describe('OigTileDialog — render()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({}) as any);
  });

  afterEach(() => {
    vi.mocked(getEntityStore).mockReturnValue(null);
  });

  it('returns null when isOpen is false', () => {
    el.isOpen = false;
    expect(el.render()).toBeNull();
  });

  it('returns a TemplateResult when isOpen is true', () => {
    el.isOpen = true;
    const result = el.render();
    expect(result).not.toBeNull();
    expect(result).toBeDefined();
  });

  it('TemplateResult has values array when isOpen', () => {
    el.isOpen = true;
    const result = el.render() as unknown as TR;
    expect(Array.isArray(result.values)).toBe(true);
  });
});

// ─── renderEntityList() ───────────────────────────────────────────────────────

describe('OigTileDialog — renderEntityList()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({}) as any);
  });

  afterEach(() => {
    vi.mocked(getEntityStore).mockReturnValue(null);
  });

  it('returns empty message TemplateResult when no items match domain', () => {
    const result = callMethod(el, 'renderEntityList', ['fan.'], '', '', vi.fn()) as unknown;
    const _values = (result as TR).values;
    expect(result).toBeDefined();
    expect(result).not.toBeNull();
  });

  it('returns a TemplateResult with items when entities match domain', () => {
    const entities = {
      'sensor.temp': makeHassState({ entity_id: 'sensor.temp', state: '21', attributes: { friendly_name: 'Temp' } }),
    };
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore(entities) as any);
    const handler = vi.fn();
    const result = callMethod(el, 'renderEntityList', ['sensor.'], '', '', handler) as unknown;
    expect(result).toBeDefined();
    expect(result).not.toBeNull();
  });
});

// ─── renderSupportList() ──────────────────────────────────────────────────────

describe('OigTileDialog — renderSupportList()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({}) as any);
  });

  afterEach(() => {
    vi.mocked(getEntityStore).mockReturnValue(null);
  });

  it('returns empty message TemplateResult when no items (empty search)', () => {
    const result = callMethod(el, 'renderSupportList', '', 1) as unknown;
    expect(result).toBeDefined();
  });

  it('returns items TemplateResult when entities match search', () => {
    const entities = {
      'sensor.humidity': makeHassState({
        entity_id: 'sensor.humidity',
        state: '65',
        attributes: { friendly_name: 'Humidity' },
      }),
    };
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore(entities) as any);
    const result = callMethod(el, 'renderSupportList', 'humi', 1) as unknown;
    expect(result).toBeDefined();
    expect(result).not.toBeNull();
  });
});

// ─── renderEntityTab() ────────────────────────────────────────────────────────

describe('OigTileDialog — renderEntityTab()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({}) as any);
  });

  afterEach(() => {
    vi.mocked(getEntityStore).mockReturnValue(null);
  });

  it('returns a TemplateResult', () => {
    const result = callMethod(el, 'renderEntityTab');
    expect(result).toBeDefined();
    expect(result).not.toBeNull();
  });

  it('TemplateResult has values array', () => {
    const result = callMethod(el, 'renderEntityTab') as unknown as TR;
    expect(Array.isArray(result.values)).toBe(true);
  });
});

// ─── renderButtonTab() ────────────────────────────────────────────────────────

describe('OigTileDialog — renderButtonTab()', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
    vi.mocked(getEntityStore).mockReturnValue(makeMockStore({}) as any);
  });

  afterEach(() => {
    vi.mocked(getEntityStore).mockReturnValue(null);
  });

  it('returns a TemplateResult', () => {
    const result = callMethod(el, 'renderButtonTab');
    expect(result).toBeDefined();
    expect(result).not.toBeNull();
  });

  it('TemplateResult has values array', () => {
    const result = callMethod(el, 'renderButtonTab') as unknown as TR;
    expect(Array.isArray(result.values)).toBe(true);
  });
});

// ─── Tab switching integration ────────────────────────────────────────────────

describe('OigTileDialog — currentTab state management', () => {
  let el: OigTileDialog;

  beforeEach(() => {
    el = new OigTileDialog();
  });

  it('starts on entity tab', () => {
    expect(getPrivate(el, 'currentTab')).toBe('entity');
  });

  it('can be switched to button tab', () => {
    setPrivate(el, 'currentTab', 'button');
    expect(getPrivate(el, 'currentTab')).toBe('button');
  });

  it('can be switched back to entity tab', () => {
    setPrivate(el, 'currentTab', 'button');
    setPrivate(el, 'currentTab', 'entity');
    expect(getPrivate(el, 'currentTab')).toBe('entity');
  });
});
