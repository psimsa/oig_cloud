/**
 * OIG Cloud V2 — Mode Selectors
 *
 * Three selector components:
 * 1. oig-box-mode-selector — Home 1/2/3/UPS
 * 2. oig-grid-delivery-selector — Vypnuto/Zapnuto/S omezením
 * 3. oig-boiler-mode-selector — CBB/Manual
 *
 * Each button supports 5 visual states: idle, active, pending, processing, disabled-by-service.
 * State is driven by the `buttonStates` property (set by parent oig-control-panel from ShieldController).
 *
 * Port of V1 shield.js button state machine.
 */

import { LitElement, html, css, unsafeCSS } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { CSS_VARS } from '@/ui/theme';
import {
  BoxMode,
  BOX_MODE_LABELS,
  GridDelivery,
  GRID_DELIVERY_LABELS,
  BoilerMode,
  BOILER_MODE_LABELS,
  BOILER_MODE_ICONS,
  ButtonState,
  SupplementaryState,
} from './types';

const u = unsafeCSS;

// ============================================================================
// SHARED BUTTON STYLES (all 3 selectors use same visual state system)
// ============================================================================

const sharedButtonStyles = css`
  .selector-label {
    font-size: 12px;
    color: ${u(CSS_VARS.textSecondary)};
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .status-text {
    font-size: 11px;
    font-weight: 500;
  }

  .status-text.transitioning {
    color: #ff9800;
  }

  .mode-buttons {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }

  .mode-btn {
    flex: 1;
    min-width: 80px;
    padding: 10px 12px;
    border: 2px solid ${u(CSS_VARS.divider)};
    background: ${u(CSS_VARS.bgSecondary)};
    color: ${u(CSS_VARS.textPrimary)};
    border-radius: 8px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
    position: relative;
    overflow: hidden;
  }

  .mode-btn:hover:not(:disabled):not(.active) {
    border-color: ${u(CSS_VARS.accent)};
  }

  .mode-btn.active {
    background: ${u(CSS_VARS.accent)};
    border-color: ${u(CSS_VARS.accent)};
    color: #fff;
  }

  .mode-btn.pending {
    border-color: #ffc107;
    animation: pulse-pending 1.5s ease-in-out infinite;
    opacity: 0.8;
  }

  .mode-btn.processing {
    border-color: #42a5f5;
    animation: pulse-processing 1s ease-in-out infinite;
    opacity: 0.9;
  }

  .mode-btn.disabled-by-service {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .mode-btn:disabled {
    cursor: not-allowed;
  }

  @keyframes pulse-pending {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }

  @keyframes pulse-processing {
    0%, 100% { opacity: 0.7; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.02); }
  }

  @media (max-width: 480px) {
    .mode-buttons {
      flex-direction: column;
    }

    .mode-btn {
      min-width: auto;
    }
  }
`;

// ============================================================================
// BOX MODE SELECTOR
// ============================================================================

@customElement('oig-box-mode-selector')
export class OigBoxModeSelector extends LitElement {
  @property({ type: String }) value: BoxMode = 'home_1';
  @property({ type: Boolean }) disabled = false;
  /** Map of mode → ButtonState, set by parent from ShieldController */
  @property({ type: Object }) buttonStates: Record<BoxMode, ButtonState> = {
    home_1: 'idle',
    home_2: 'idle',
    home_3: 'idle',
    home_ups: 'idle',
  };

  static styles = [sharedButtonStyles];

  private onModeClick(mode: BoxMode): void {
    const state = this.buttonStates[mode];
    if (this.disabled || state === 'active' || state === 'pending' || state === 'processing' || state === 'disabled-by-service') return;

    this.dispatchEvent(new CustomEvent('mode-change', {
      detail: { mode },
      bubbles: true,
    }));
  }

  render() {
    const modes: BoxMode[] = ['home_1', 'home_2', 'home_3', 'home_ups'];

    return html`
      <div class="selector-label">
        Re\u017Eim st\u0159\u00EDda\u010De
      </div>
      <div class="mode-buttons">
        ${modes.map(mode => {
          const state = this.buttonStates[mode];
          const isDisabled = this.disabled || state === 'pending' || state === 'processing' || state === 'disabled-by-service';
          return html`
            <button
              class="mode-btn ${state}"
              ?disabled=${isDisabled}
              @click=${() => this.onModeClick(mode)}
            >
              ${BOX_MODE_LABELS[mode]}
              ${state === 'pending' ? html`<span style="font-size:10px"> \u23F3</span>` : ''}
              ${state === 'processing' ? html`<span style="font-size:10px"> \uD83D\uDD04</span>` : ''}
            </button>
          `;
        })}
      </div>
    `;
  }
}

// ============================================================================
// GRID DELIVERY SELECTOR
// ============================================================================

@customElement('oig-grid-delivery-selector')
export class OigGridDeliverySelector extends LitElement {
  @property({ type: String }) value: GridDelivery | 'unknown' = 'off';
  @property({ type: Number }) limit = 0;
  @property({ type: Boolean }) disabled = false;
  @property({ type: String }) pendingTarget: GridDelivery | null = null;
  @property({ type: Object }) buttonStates: Record<GridDelivery, ButtonState> = {
    off: 'idle',
    on: 'idle',
    limited: 'idle',
  };

  static styles = [
    sharedButtonStyles,
    css`
      .mode-btn.pending-target {
        border-color: #ffc107;
        color: #ffc107;
        background: rgba(255, 193, 7, 0.08);
      }
    `,
  ];

  private onDeliveryClick(delivery: GridDelivery): void {
    const state = this.buttonStates[delivery];
    if (this.disabled || state === 'pending' || state === 'processing' || state === 'disabled-by-service') return;
    if (state === 'active' && delivery !== 'limited') return;

    this.dispatchEvent(new CustomEvent('delivery-change', {
      detail: { value: delivery, limit: delivery === 'limited' ? this.limit : null },
      bubbles: true,
    }));
  }

  render() {
    const options: Array<{ value: GridDelivery; label: string }> = [
      { value: 'off', label: GRID_DELIVERY_LABELS.off },
      { value: 'on', label: GRID_DELIVERY_LABELS.on },
      { value: 'limited', label: GRID_DELIVERY_LABELS.limited },
    ];

    const hasPendingChange = this.pendingTarget !== null && this.pendingTarget !== this.value;
    const pendingLabel = hasPendingChange
      ? html`<span class="status-text transitioning">\u23F3\u00A0${GRID_DELIVERY_LABELS[this.pendingTarget!]}</span>`
      : null;

    return html`
      <div class="selector-label">
        Dod\u00E1vka do s\u00EDt\u011B ${pendingLabel}
      </div>
      <div class="mode-buttons">
        ${options.map(opt => {
          const state = this.buttonStates[opt.value];
          const isCurrentValue = opt.value === this.value;
          const isPendingTarget = opt.value === this.pendingTarget && !isCurrentValue;
          const isDisabled = this.disabled || state === 'pending' || state === 'processing' || state === 'disabled-by-service';
          const effectiveClass = (isCurrentValue && state === 'disabled-by-service')
            ? 'active disabled-by-service'
            : isPendingTarget
              ? `${state} pending-target`
              : state;
          return html`
            <button
              class="mode-btn ${effectiveClass}"
              ?disabled=${isDisabled}
              @click=${() => this.onDeliveryClick(opt.value)}
            >
              ${opt.label}
              ${state === 'pending' ? html`<span style="font-size:10px"> \u23F3</span>` : ''}
              ${state === 'processing' ? html`<span style="font-size:10px"> \uD83D\uDD04</span>` : ''}
            </button>
          `;
        })}
      </div>
    `;
  }
}

// ============================================================================
// BOILER MODE SELECTOR
// ============================================================================

@customElement('oig-boiler-mode-selector')
export class OigBoilerModeSelector extends LitElement {
  @property({ type: String }) value: BoilerMode = 'cbb';
  @property({ type: Boolean }) disabled = false;
  @property({ type: Object }) buttonStates: Record<BoilerMode, ButtonState> = {
    cbb: 'idle',
    manual: 'idle',
  };

  static styles = [sharedButtonStyles];

  private onModeClick(mode: BoilerMode): void {
    const state = this.buttonStates[mode];
    if (this.disabled || state === 'active' || state === 'pending' || state === 'processing' || state === 'disabled-by-service') return;

    this.dispatchEvent(new CustomEvent('boiler-mode-change', {
      detail: { mode },
      bubbles: true,
    }));
  }

  render() {
    const modes: BoilerMode[] = ['cbb', 'manual'];

    return html`
      <div class="selector-label">
        Re\u017Eim bojleru
      </div>
      <div class="mode-buttons">
        ${modes.map(mode => {
          const state = this.buttonStates[mode];
          const isDisabled = this.disabled || state === 'pending' || state === 'processing' || state === 'disabled-by-service';
          return html`
            <button
              class="mode-btn ${state}"
              ?disabled=${isDisabled}
              @click=${() => this.onModeClick(mode)}
            >
              ${BOILER_MODE_ICONS[mode]} ${BOILER_MODE_LABELS[mode]}
              ${state === 'pending' ? html`<span style="font-size:10px"> \u23F3</span>` : ''}
              ${state === 'processing' ? html`<span style="font-size:10px"> \uD83D\uDD04</span>` : ''}
            </button>
          `;
        })}
      </div>
    `;
  }
}

// ============================================================================
// PURE SELECTORS
// ============================================================================

export function selectBoxModeButtons(): BoxMode[] {
  return ['home_1', 'home_2', 'home_3', 'home_ups'];
}

export function selectSupplementaryToggles(state: SupplementaryState): {
  home_grid_v: boolean;
  home_grid_vi: boolean;
  flexibilita: boolean;
  available: boolean;
  disabled: boolean;
} {
  return {
    home_grid_v: state.available ? state.home_grid_v : false,
    home_grid_vi: state.available ? state.home_grid_vi : false,
    flexibilita: state.available ? state.flexibilita : false,
    available: state.available,
    disabled: !state.available || state.flexibilita,
  };
}

// ============================================================================
// SUPPLEMENTARY TOGGLES COMPONENT
// ============================================================================

@customElement('oig-supplementary-toggles')
export class OigSupplementaryToggles extends LitElement {
  @property({ type: Object }) supplementary: SupplementaryState = {
    home_grid_v: false,
    home_grid_vi: false,
    flexibilita: false,
    available: false,
  };

  static styles = [
    sharedButtonStyles,
    css`
      .toggle-section {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }

      .toggle-row {
        display: flex;
        align-items: center;
        gap: 10px;
      }

      .toggle-checkbox {
        width: 18px;
        height: 18px;
        cursor: pointer;
        accent-color: var(--oig-accent, #2196f3);
      }

      .toggle-checkbox:disabled {
        cursor: not-allowed;
        opacity: 0.4;
      }

      .toggle-label {
        font-size: 13px;
        font-weight: 500;
        color: var(--oig-text-primary, #e0e0e0);
      }

      .toggle-label.disabled {
        opacity: 0.4;
      }

      .flexibilita-badge {
        font-size: 11px;
        padding: 2px 8px;
        border-radius: 8px;
        background: rgba(255, 152, 0, 0.15);
        color: #ff9800;
        font-weight: 500;
        margin-left: auto;
      }

      .unavailable-note {
        font-size: 11px;
        color: var(--oig-text-secondary, #9e9e9e);
        font-style: italic;
      }
    `,
  ];

  private onToggle(field: 'home_grid_v' | 'home_grid_vi', value: boolean): void {
    if (!this.supplementary.available || this.supplementary.flexibilita) return;

    this.dispatchEvent(new CustomEvent('supplementary-toggle', {
      detail: { field, value },
      bubbles: true,
    }));
  }

  render() {
    const derived = selectSupplementaryToggles(this.supplementary);
    const { flexibilita, available, disabled } = derived;

    return html`
      <div class="selector-label">
        Dopl\u0148kov\u00E9 re\u017Eimy
        ${flexibilita ? html`<span class="flexibilita-badge">\u{26A1} Flexibilita</span>` : ''}
      </div>
      <div class="toggle-section">
        <div class="toggle-row">
          <input
            type="checkbox"
            class="toggle-checkbox"
            .checked=${derived.home_grid_v}
            ?disabled=${disabled}
            @change=${(e: Event) => this.onToggle('home_grid_v', (e.target as HTMLInputElement).checked)}
          />
          <span class="toggle-label ${disabled ? 'disabled' : ''}">Home Grid V</span>
        </div>
        <div class="toggle-row">
          <input
            type="checkbox"
            class="toggle-checkbox"
            .checked=${derived.home_grid_vi}
            ?disabled=${disabled}
            @change=${(e: Event) => this.onToggle('home_grid_vi', (e.target as HTMLInputElement).checked)}
          />
          <span class="toggle-label ${disabled ? 'disabled' : ''}">Home Grid VI</span>
        </div>
        ${!available ? html`<span class="unavailable-note">Roz\u0161\u00ED\u0159en\u00E9 atributy nejsou dostupn\u00E9</span>` : ''}
        ${flexibilita ? html`<span class="unavailable-note">Flexibilita je aktivn\u00ED &mdash; p\u0159ep\u00EDna\u010D\u00E8 jsou zam\u010Deny</span>` : ''}
      </div>
    `;
  }
}

// ============================================================================
// TAG NAME DECLARATIONS
// ============================================================================

declare global {
  interface HTMLElementTagNameMap {
    'oig-box-mode-selector': OigBoxModeSelector;
    'oig-grid-delivery-selector': OigGridDeliverySelector;
    'oig-boiler-mode-selector': OigBoilerModeSelector;
    'oig-supplementary-toggles': OigSupplementaryToggles;
  }
}
