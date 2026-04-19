import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  renderSplitFlap,
  updateWithFlip,
  clearFlipCache,
  SPLIT_FLAP_STYLES,
} from '@/utils/split-flap';

describe('split-flap', () => {
  let container: HTMLElement;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    document.body.innerHTML = '';
    clearFlipCache('test-key');
    vi.restoreAllMocks();
  });

  describe('renderSplitFlap', () => {
    it('should set textContent directly when prefersReducedMotion is true', () => {
      Object.defineProperty(globalThis, 'matchMedia', {
        value: vi.fn().mockImplementation((query: string) => ({
          matches: query === '(prefers-reduced-motion: reduce)',
          media: query,
          onchange: null,
          addListener: vi.fn(),
          removeListener: vi.fn(),
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          dispatchEvent: vi.fn(),
        })),
        writable: true,
        configurable: true,
      });

      renderSplitFlap(container, 'test-key', 'old', 'new');
      expect(container.textContent).toBe('new');
    });

    it('should create flipboard structure', () => {
      renderSplitFlap(container, 'test-key', 'AB', 'CD');

      const board = container.querySelector('.oig-flipboard');
      expect(board).toBeTruthy();

      const cells = board?.querySelectorAll('.oig-flip-cell');
      expect(cells?.length).toBeGreaterThan(0);
    });

    it('should pad values to match length', () => {
      renderSplitFlap(container, 'test-key', 'A', 'BC');

      const board = container.querySelector('.oig-flipboard');
      const cells = board?.querySelectorAll('.oig-flip-cell');
      expect(cells?.length).toBe(2);
    });

    it('should respect flipPad=none to disable padding', () => {
      container.dataset.flipPad = 'none';
      renderSplitFlap(container, 'test-key', 'A', 'BC');

      const board = container.querySelector('.oig-flipboard');
      const cells = board?.querySelectorAll('.oig-flip-cell');
      expect(cells?.length).toBe(2);
    });

    it('should handle empty old value', () => {
      renderSplitFlap(container, 'test-key', '', 'ABC');

      const board = container.querySelector('.oig-flipboard');
      expect(board).toBeTruthy();
    });

    it('should handle null/undefined values', () => {
      renderSplitFlap(container, 'test-key', null as any, 'test');

      const board = container.querySelector('.oig-flipboard');
      expect(board).toBeTruthy();
    });

    it('should create flip cells with correct structure', () => {
      renderSplitFlap(container, 'test-key', 'A', 'B');

      const cell = container.querySelector('.oig-flip-cell');
      expect(cell?.querySelector('.oig-flip-size')).toBeTruthy();
      expect(cell?.querySelector('.oig-flip-static-top')).toBeTruthy();
      expect(cell?.querySelector('.oig-flip-static-bottom')).toBeTruthy();
    });

    it('should handle forceFlip parameter', () => {
      renderSplitFlap(container, 'test-key', 'A', 'A', true);

      const board = container.querySelector('.oig-flipboard');
      expect(board).toBeTruthy();
    });

    it('should handle same character without animation', () => {
      renderSplitFlap(container, 'test-key', 'A', 'A');

      const cell = container.querySelector('.oig-flip-cell');
      const staticTop = cell?.querySelector('.oig-flip-static-top');
      expect(staticTop?.textContent).toBe('A');
    });

    it('should handle spaces as non-breaking spaces', () => {
      renderSplitFlap(container, 'test-key', 'A B', 'C D');

      const sizeSpans = container.querySelectorAll('.oig-flip-size');
      const hasNonBreakingSpace = Array.from(sizeSpans).some(
        (span) => span.textContent === '\u00A0'
      );
      expect(hasNonBreakingSpace).toBe(true);
    });

    it('should handle empty element gracefully', () => {
      expect(() => {
        renderSplitFlap(null as any, 'test-key', 'old', 'new');
      }).not.toThrow();
    });

    it('should handle multi-character strings', () => {
      renderSplitFlap(container, 'test-key', 'Hello', 'World');

      const board = container.querySelector('.oig-flipboard');
      const cells = board?.querySelectorAll('.oig-flip-cell');
      expect(cells?.length).toBe(5);
    });
  });

  describe('updateWithFlip', () => {
    beforeEach(() => {
      clearFlipCache('update-key');
    });

    it('should return false when value has not changed', () => {
      updateWithFlip(container, 'update-key', 'same');
      const result = updateWithFlip(container, 'update-key', 'same');
      expect(result).toBe(false);
    });

    it('should return true when value changes', () => {
      updateWithFlip(container, 'update-key', 'old');
      const result = updateWithFlip(container, 'update-key', 'new');
      expect(result).toBe(true);
    });

    it('should update textContent when not animating', () => {
      updateWithFlip(container, 'update-key', 'test', false);
      expect(container.textContent).toBe('test');
    });

    it('should respect flip class for animation', () => {
      container.classList.add('flip-value');

      Object.defineProperty(globalThis, 'matchMedia', {
        value: vi.fn().mockImplementation((query: string) => ({
          matches: false,
          media: query,
          onchange: null,
          addListener: vi.fn(),
          removeListener: vi.fn(),
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          dispatchEvent: vi.fn(),
        })),
        writable: true,
        configurable: true,
      });

      updateWithFlip(container, 'update-key', 'test');
      const board = container.querySelector('.oig-flipboard');
      expect(board).toBeTruthy();
    });

    it('should respect data-flip attribute', () => {
      container.dataset.flip = 'true';

      Object.defineProperty(globalThis, 'matchMedia', {
        value: vi.fn().mockImplementation((query: string) => ({
          matches: false,
          media: query,
          onchange: null,
          addListener: vi.fn(),
          removeListener: vi.fn(),
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          dispatchEvent: vi.fn(),
        })),
        writable: true,
        configurable: true,
      });

      updateWithFlip(container, 'update-key', 'test');
      const board = container.querySelector('.oig-flipboard');
      expect(board).toBeTruthy();
    });

    it('should throttle rapid updates', () => {
      container.classList.add('flip-value');

      Object.defineProperty(globalThis, 'matchMedia', {
        value: vi.fn().mockImplementation((query: string) => ({
          matches: false,
          media: query,
          onchange: null,
          addListener: vi.fn(),
          removeListener: vi.fn(),
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          dispatchEvent: vi.fn(),
        })),
        writable: true,
        configurable: true,
      });

      updateWithFlip(container, 'throttle-key', '1');
      const result = updateWithFlip(container, 'throttle-key', '2');

      expect(result).toBe(true);
    });

    it('should handle null/undefined new values', () => {
      const result = updateWithFlip(container, 'update-key', null as any);
      expect(result).toBe(true);
      expect(container.textContent).toBe('');
    });

    it('should use existing textContent as fromValue on first update', () => {
      container.textContent = 'existing';
      container.classList.add('flip-value');

      Object.defineProperty(globalThis, 'matchMedia', {
        value: vi.fn().mockImplementation((query: string) => ({
          matches: false,
          media: query,
          onchange: null,
          addListener: vi.fn(),
          removeListener: vi.fn(),
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          dispatchEvent: vi.fn(),
        })),
        writable: true,
        configurable: true,
      });

      updateWithFlip(container, 'update-key', 'new');
      const board = container.querySelector('.oig-flipboard');
      expect(board).toBeTruthy();
    });
  });

  describe('clearFlipCache', () => {
    it('should clear cached value', () => {
      updateWithFlip(container, 'clear-key', 'value');
      clearFlipCache('clear-key');

      const result = updateWithFlip(container, 'clear-key', 'value');
      expect(result).toBe(true);
    });

    it('should handle non-existent key gracefully', () => {
      expect(() => {
        clearFlipCache('non-existent');
      }).not.toThrow();
    });
  });

  describe('SPLIT_FLAP_STYLES', () => {
    it('should be a CSSResult', () => {
      expect(SPLIT_FLAP_STYLES).toBeDefined();
      expect(SPLIT_FLAP_STYLES.cssText).toBeDefined();
    });

    it('should contain flipboard styles', () => {
      expect(SPLIT_FLAP_STYLES.cssText).toContain('.oig-flipboard');
    });

    it('should contain flip cell styles', () => {
      expect(SPLIT_FLAP_STYLES.cssText).toContain('.oig-flip-cell');
    });

    it('should contain animation keyframes', () => {
      expect(SPLIT_FLAP_STYLES.cssText).toContain('@keyframes');
      expect(SPLIT_FLAP_STYLES.cssText).toContain('oig-flip-down');
      expect(SPLIT_FLAP_STYLES.cssText).toContain('oig-flip-up');
    });

    it('should contain reduced motion media query', () => {
      expect(SPLIT_FLAP_STYLES.cssText).toContain('prefers-reduced-motion');
    });

    it('should contain flip face styles', () => {
      expect(SPLIT_FLAP_STYLES.cssText).toContain('.oig-flip-face');
      expect(SPLIT_FLAP_STYLES.cssText).toContain('.oig-flip-static-top');
      expect(SPLIT_FLAP_STYLES.cssText).toContain('.oig-flip-static-bottom');
    });

    it('should contain animation styles', () => {
      expect(SPLIT_FLAP_STYLES.cssText).toContain('.oig-flip-anim-top');
      expect(SPLIT_FLAP_STYLES.cssText).toContain('.oig-flip-anim-bottom');
    });
  });

  describe('grapheme handling', () => {
    it('should handle emoji characters', () => {
      renderSplitFlap(container, 'emoji-key', '👍', '👎');

      const board = container.querySelector('.oig-flipboard');
      expect(board).toBeTruthy();
    });

    it('should handle multi-byte characters', () => {
      renderSplitFlap(container, 'unicode-key', 'café', 'coffee');

      const board = container.querySelector('.oig-flipboard');
      expect(board).toBeTruthy();
    });

    it('should handle numbers', () => {
      renderSplitFlap(container, 'number-key', '123', '456');

      const board = container.querySelector('.oig-flipboard');
      const cells = board?.querySelectorAll('.oig-flip-cell');
      expect(cells?.length).toBe(3);
    });

    it('should handle special characters', () => {
      renderSplitFlap(container, 'special-key', '!@#', '$%^');

      const board = container.querySelector('.oig-flipboard');
      expect(board).toBeTruthy();
    });
  });

  describe('edge cases', () => {
    it('should handle very long strings', () => {
      const longString = 'A'.repeat(100);
      renderSplitFlap(container, 'long-key', '', longString);

      const board = container.querySelector('.oig-flipboard');
      expect(board).toBeTruthy();
    });

    it('should handle single character', () => {
      renderSplitFlap(container, 'single-key', 'A', 'B');

      const board = container.querySelector('.oig-flipboard');
      const cells = board?.querySelectorAll('.oig-flip-cell');
      expect(cells?.length).toBe(1);
    });

    it('should handle empty string values', () => {
      renderSplitFlap(container, 'empty-key', '', '');

      const board = container.querySelector('.oig-flipboard');
      expect(board).toBeTruthy();
    });

    it('should maintain padding length across updates', () => {
      renderSplitFlap(container, 'pad-key', 'A', 'BC');
      renderSplitFlap(container, 'pad-key', 'BC', 'D');

      const board = container.querySelector('.oig-flipboard');
      const cells = board?.querySelectorAll('.oig-flip-cell');
      expect(cells?.length).toBe(2);
    });
  });
});
