/**
 * OIG Cloud V2 — Control Panel
 *
 * Container component that wires together:
 * - ShieldController (data layer)
 * - Box mode / Grid delivery / Boiler mode selectors
 * - Shield queue display
 * - Confirm dialog (acknowledgement / grid delivery / simple)
 *
 * Subscribes to shieldController for reactive state updates.
 * Handles all user interactions → confirm dialog → service calls.
 *
 * Port of V1 shield.js UI orchestration.
 */

import { LitElement, html, css, unsafeCSS, nothing } from 'lit';
import { customElement, state, query } from 'lit/decorators.js';
import { CSS_VARS } from '@/ui/theme';
import { shieldController, ShieldListener } from '@/data/shield-controller';
import {
  ShieldState,
  EMPTY_SHIELD_STATE,
  BoxMode,
  GridDelivery,
  BoilerMode,
  BOX_MODE_LABELS,
  GRID_DELIVERY_LABELS,
  GRID_DELIVERY_ICONS,
  BOILER_MODE_LABELS,
  BOILER_MODE_ICONS,
  ButtonState,
  ConfirmDialogConfig,
  SupplementaryState,
} from './types';
import { oigLog } from '@/core/logger';

// Import sub-components so they register
import './selectors';
import './shield';
import './queue';
import './confirm-dialog';
import type { OigConfirmDialog } from './confirm-dialog';

const u = unsafeCSS;

@customElement('oig-control-panel')
export class OigControlPanel extends LitElement {
  @state() private shieldState: ShieldState = {
    ...EMPTY_SHIELD_STATE,
    pendingServices: new Map(),
    changingServices: new Set(),
  };

  private _confirmDialogOverride: OigConfirmDialog | null = null;
  @query('oig-confirm-dialog') private _confirmDialogQuery!: OigConfirmDialog;
  private get confirmDialog(): OigConfirmDialog {
    return (this._confirmDialogOverride ?? this._confirmDialogQuery) as OigConfirmDialog;
  }
  private set confirmDialog(value: OigConfirmDialog) {
    this._confirmDialogOverride = value;
  }

  private unsubscribe: (() => void) | null = null;

  static styles = css`
    :host {
      display: block;
      margin-top: 16px;
    }

    .control-panel {
      background: ${u(CSS_VARS.cardBg)};
      border-radius: 16px;
      box-shadow: ${u(CSS_VARS.cardShadow)};
      overflow: hidden;
    }

    .panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 20px;
      border-bottom: 1px solid ${u(CSS_VARS.divider)};
    }

    .panel-title {
      font-size: 15px;
      font-weight: 600;
      color: ${u(CSS_VARS.textPrimary)};
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .panel-status {
      font-size: 11px;
      padding: 3px 10px;
      border-radius: 10px;
      font-weight: 500;
    }

    .panel-status.idle {
      color: #4caf50;
      background: rgba(76, 175, 80, 0.1);
    }

    .panel-status.running {
      color: #2196f3;
      background: rgba(33, 150, 243, 0.1);
    }

    .panel-body {
      padding: 16px 20px;
    }

    .selector-section {
      margin-bottom: 20px;
    }

    .selector-section:last-child {
      margin-bottom: 0;
    }

    .section-divider {
      height: 1px;
      background: ${u(CSS_VARS.divider)};
      margin: 16px 0;
    }

    .queue-section {
      border-top: 1px solid ${u(CSS_VARS.divider)};
    }

    @media (max-width: 480px) {
      .panel-body {
        padding: 12px 14px;
      }
    }
  `;

  // --------------------------------------------------------------------------
  // Lifecycle
  // --------------------------------------------------------------------------

  connectedCallback(): void {
    super.connectedCallback();
    // Subscribe to shield state changes
    this.unsubscribe = shieldController.subscribe(this.onShieldUpdate);
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    this.unsubscribe?.();
    this.unsubscribe = null;
  }

  // --------------------------------------------------------------------------
  // Shield state subscription
  // --------------------------------------------------------------------------

  private onShieldUpdate: ShieldListener = (state: ShieldState) => {
    this.shieldState = state;
  };

  // --------------------------------------------------------------------------
  // Button state computation
  // --------------------------------------------------------------------------

  private get boxModeButtonStates(): Record<BoxMode, ButtonState> {
    return {
      home_1: shieldController.getBoxModeButtonState('home_1'),
      home_2: shieldController.getBoxModeButtonState('home_2'),
      home_3: shieldController.getBoxModeButtonState('home_3'),
      home_ups: shieldController.getBoxModeButtonState('home_ups'),
    };
  }

  private get gridDeliveryButtonStates(): Record<GridDelivery, ButtonState> {
    return {
      off: shieldController.getGridDeliveryButtonState('off'),
      on: shieldController.getGridDeliveryButtonState('on'),
      limited: shieldController.getGridDeliveryButtonState('limited'),
    };
  }

  private get boilerModeButtonStates(): Record<BoilerMode, ButtonState> {
    return {
      cbb: shieldController.getBoilerModeButtonState('cbb'),
      manual: shieldController.getBoilerModeButtonState('manual'),
    };
  }

  // --------------------------------------------------------------------------
  // Event handlers — Box Mode
  // --------------------------------------------------------------------------

  private async onBoxModeChange(e: CustomEvent<{ mode: BoxMode }>): Promise<void> {
    const { mode } = e.detail;
    const label = BOX_MODE_LABELS[mode];

    oigLog.debug('Control panel: box mode change requested', { mode });

    // Show acknowledgement dialog
    const result = await this.confirmDialog.showDialog({
      title: 'Zm\u011Bna re\u017Eimu st\u0159\u00EDda\u010De',
      message: `Chyst\u00E1te se zm\u011Bnit re\u017Eim boxu na <strong>"${label}"</strong>.<br><br>` +
        `Tato zm\u011Bna ovlivn\u00ED chov\u00E1n\u00ED cel\u00E9ho syst\u00E9mu a m\u016F\u017Ee trvat a\u017E 10 minut.`,
      warning: 'Zm\u011Bna re\u017Eimu m\u016F\u017Ee trvat a\u017E 10 minut. B\u011Bhem t\u00E9to doby je syst\u00E9m v p\u0159echodn\u00E9m stavu.',
      requireAcknowledgement: true,
      confirmText: 'Potvrdit zm\u011Bnu',
      cancelText: 'Zru\u0161it',
    });

    if (!result.confirmed) return;

    // Queue warning check
    if (!shieldController.shouldProceedWithQueue()) return;

    // Call service
    const success = await shieldController.setBoxMode(mode);
    if (!success) {
      oigLog.warn('Box mode change failed or already active', { mode });
    }
  }

  // --------------------------------------------------------------------------
  // Event handlers — Grid Delivery
  // --------------------------------------------------------------------------

  private async onGridDeliveryChange(
    e: CustomEvent<{ value: GridDelivery; limit: number | null }>,
  ): Promise<void> {
    const { value: delivery, limit } = e.detail;
    const label = GRID_DELIVERY_LABELS[delivery];
    const icon = GRID_DELIVERY_ICONS[delivery];
    const needsLimit = delivery === 'limited';
    const currentLimit = this.shieldState.gridDeliveryState.currentLiveLimit ?? 5000;

    oigLog.debug('Control panel: grid delivery change requested', { delivery, limit });

    // ── FAST PATH: re-click on active limited button → limit-only dialog ─────
    const liveDelivery = this.shieldState.gridDeliveryState.currentLiveDelivery;
    const isTransitioning = this.shieldState.gridDeliveryState.isTransitioning;

    if (!isTransitioning && liveDelivery === 'limited' && delivery === 'limited') {
      const fastConfig: ConfirmDialogConfig = {
        title: '🚰 Změnit limit přetoků',
        message: '',
        limitOnly: true,
        showLimitInput: true,
        limitValue: currentLimit,
        limitMin: 1,
        limitMax: 20000,
        limitStep: 100,
        confirmText: 'Uložit limit',
        cancelText: 'Zrušit',
      };
      const result = await this.confirmDialog.showDialog(fastConfig);
      if (!result.confirmed) return;
      if (!shieldController.shouldProceedWithQueue()) return;
      await shieldController.setGridDelivery('limited', result.limit);
      return;
    }
    // ── END FAST PATH ─────────────────────────────────────────────────────────

    // Build dialog config (matches V1 showGridDeliveryDialog)
    const config: ConfirmDialogConfig = {
      title: `${icon} Zm\u011Bna dod\u00E1vky do s\u00EDt\u011B`,
      message: `Chyst\u00E1te se zm\u011Bnit dod\u00E1vku do s\u00EDt\u011B na: <strong>"${label}"</strong>`,
      warning: needsLimit
        ? 'Re\u017Eim a limit budou zm\u011Bn\u011Bny postupn\u011B (serializov\u00E1no). Ka\u017Ed\u00E1 zm\u011Bna m\u016F\u017Ee trvat a\u017E 10 minut.'
        : 'Zm\u011Bna re\u017Eimu m\u016F\u017Ee trvat a\u017E 10 minut. B\u011Bhem t\u00E9to doby je syst\u00E9m v p\u0159echodn\u00E9m stavu.',
      requireAcknowledgement: true,
      acknowledgementText: '<strong>Souhlasím</strong> s tím, že měním dodávku do sítě na vlastní odpovědnost. Aplikace nenese odpovědnost za případné negativní důsledky této změny.',
      confirmText: 'Potvrdit zm\u011Bnu',
      cancelText: 'Zru\u0161it',
      showLimitInput: needsLimit,
      limitValue: currentLimit,
      limitMin: 1,
      limitMax: 20000,
      limitStep: 100,
    };

    const result = await this.confirmDialog.showDialog(config);

    if (!result.confirmed) return;

    // Queue warning check
    if (!shieldController.shouldProceedWithQueue()) return;

    // Determine what to send based on current state (matches V1 logic)
    const isLimitedActive = this.shieldState.gridDeliveryState.currentLiveDelivery === 'limited';
    const isChangingToLimited = delivery === 'limited';

    if (isLimitedActive && isChangingToLimited && result.limit != null) {
      // Case 1: Already limited, just change limit
      await shieldController.setGridDelivery(delivery, result.limit);
    } else if (isChangingToLimited && result.limit != null) {
      // Case 2: Mode + limit together
      await shieldController.setGridDelivery(delivery, result.limit);
    } else {
      // Case 3: Just mode change
      await shieldController.setGridDelivery(delivery);
    }
  }

  // --------------------------------------------------------------------------
  // Event handlers — Boiler Mode
  // --------------------------------------------------------------------------

  private async onBoilerModeChange(e: CustomEvent<{ mode: BoilerMode }>): Promise<void> {
    const { mode } = e.detail;
    const label = BOILER_MODE_LABELS[mode];
    const icon = BOILER_MODE_ICONS[mode];

    oigLog.debug('Control panel: boiler mode change requested', { mode });

    // Show acknowledgement dialog
    const result = await this.confirmDialog.showDialog({
      title: 'Zm\u011Bna re\u017Eimu bojleru',
      message: `Chyst\u00E1te se zm\u011Bnit re\u017Eim bojleru na <strong>"${icon} ${label}"</strong>.<br><br>` +
        `Tato zm\u011Bna ovlivn\u00ED chov\u00E1n\u00ED oh\u0159evu vody a m\u016F\u017Ee trvat a\u017E 10 minut.`,
      warning: 'Zm\u011Bna re\u017Eimu m\u016F\u017Ee trvat a\u017E 10 minut. B\u011Bhem t\u00E9to doby je syst\u00E9m v p\u0159echodn\u00E9m stavu.',
      requireAcknowledgement: true,
      confirmText: 'Potvrdit zm\u011Bnu',
      cancelText: 'Zru\u0161it',
    });

    if (!result.confirmed) return;

    // Queue warning check
    if (!shieldController.shouldProceedWithQueue()) return;

    // Call service
    const success = await shieldController.setBoilerMode(mode);
    if (!success) {
      oigLog.warn('Boiler mode change failed or already active', { mode });
    }
  }

  // --------------------------------------------------------------------------
  // Event handlers — Supplementary Toggles
  // --------------------------------------------------------------------------

  private async onSupplementaryToggle(
    e: CustomEvent<{ field: 'home_grid_v' | 'home_grid_vi'; value: boolean }>,
  ): Promise<void> {
    const { field, value } = e.detail;
    const sup: SupplementaryState = this.shieldState.supplementary;

    if (!sup.available || sup.flexibilita) return;

    const fieldLabel = field === 'home_grid_v' ? 'Home Grid V' : 'Home Grid VI';
    const actionLabel = value ? 'zapnout' : 'vypnout';

    // Show acknowledgement dialog
    const result = await this.confirmDialog.showDialog({
      title: 'Změna doplňkového režimu',
      message: `Chystáte se ${actionLabel} <strong>"${fieldLabel}"</strong>.<br><br>` +
        `Tato změna ovlivní chování systému a může trvat až 10 minut.`,
      warning: 'Změna režimu může trvat až 10 minut. Během této doby je systém v přechodném stavu.',
      requireAcknowledgement: true,
      confirmText: 'Potvrdit změnu',
      cancelText: 'Zrušit',
    });

    if (!result.confirmed) return;

    // Queue warning check
    if (!shieldController.shouldProceedWithQueue()) return;

    // Call service
    const success = await shieldController.toggleSupplementary(field, value);
    if (!success) {
      oigLog.warn('Supplementary toggle failed', { field, value });
    }
  }

  // --------------------------------------------------------------------------
  // Event handlers — Queue removal
  // --------------------------------------------------------------------------

  private async onQueueRemoveItem(e: CustomEvent<{ position: number }>): Promise<void> {
    const { position } = e.detail;

    oigLog.debug('Control panel: queue remove requested', { position });

    // Find the request for descriptive title
    const request = this.shieldState.allRequests.find((r) => r.position === position);
    let actionName = 'Operace';
    if (request) {
      if (request.service.includes('set_box_mode')) {
        actionName = `Zm\u011Bna re\u017Eimu na ${request.targetValue || 'nezn\u00E1m\u00FD'}`;
      } else if (request.service.includes('set_grid_delivery')) {
        actionName = `Zm\u011Bna dod\u00E1vky do s\u00EDt\u011B na ${request.targetValue || 'nezn\u00E1m\u00FD'}`;
      } else if (request.service.includes('set_boiler_mode')) {
        actionName = `Zm\u011Bna re\u017Eimu bojleru na ${request.targetValue || 'nezn\u00E1m\u00FD'}`;
      }
    }

    // Simple confirm dialog (no acknowledgement checkbox)
    const result = await this.confirmDialog.showDialog({
      title: actionName,
      message: 'Operace bude odstran\u011Bna z fronty bez proveden\u00ED.',
      requireAcknowledgement: false,
      confirmText: 'OK',
      cancelText: 'Zru\u0161it',
    });

    if (!result.confirmed) return;

    const success = await shieldController.removeFromQueue(position);
    if (!success) {
      oigLog.warn('Failed to remove from queue', { position });
    }
  }

  // --------------------------------------------------------------------------
  // Render
  // --------------------------------------------------------------------------

  render() {
    const s = this.shieldState;
    const statusClass = s.status === 'running' ? 'running' : 'idle';
    const statusText = s.status === 'running' ? 'Zpracov\u00E1v\u00E1' : 'P\u0159ipraveno';
    const hasQueue = s.allRequests.length > 0;

    return html`
      <div class="control-panel">
        <div class="panel-header">
          <span class="panel-title">
            \u{1F6E1}\uFE0F Ovl\u00E1dac\u00ED panel
          </span>
          <span class="panel-status ${statusClass}">
            ${s.status === 'running' ? '\uD83D\uDD04 ' : '\u2713 '}${statusText}
          </span>
        </div>

        <div class="panel-body">
          <!-- Box Mode Selector -->
          <div class="selector-section">
            <oig-box-mode-selector
              .value=${s.currentBoxMode}
              .buttonStates=${this.boxModeButtonStates}
              @mode-change=${this.onBoxModeChange}
            ></oig-box-mode-selector>
          </div>

          <div class="section-divider"></div>

          <!-- Supplementary Toggles -->
          <div class="selector-section">
            <oig-supplementary-toggles
              .supplementary=${s.supplementary}
              @supplementary-toggle=${this.onSupplementaryToggle}
            ></oig-supplementary-toggles>
          </div>

          <div class="section-divider"></div>

          <!-- Grid Delivery Selector -->
          <div class="selector-section">
            <oig-grid-delivery-selector
              .value=${s.gridDeliveryState.currentLiveDelivery}
              .limit=${s.gridDeliveryState.currentLiveLimit ?? 0}
              .pendingTarget=${s.gridDeliveryState.pendingDeliveryTarget}
              .buttonStates=${this.gridDeliveryButtonStates}
              @delivery-change=${this.onGridDeliveryChange}
            ></oig-grid-delivery-selector>
          </div>

          <div class="section-divider"></div>

          <!-- Boiler Mode Selector -->
          <div class="selector-section">
            <oig-boiler-mode-selector
              .value=${s.currentBoilerMode}
              .buttonStates=${this.boilerModeButtonStates}
              @boiler-mode-change=${this.onBoilerModeChange}
            ></oig-boiler-mode-selector>
          </div>
        </div>

        <!-- Shield Status (always shown) -->
        <oig-shield-status .shieldState=${s}></oig-shield-status>

        <!-- Shield Queue (always rendered, collapsible) -->
        ${hasQueue ? html`
          <div class="queue-section">
            <oig-shield-queue
              .items=${s.allRequests}
              .shieldStatus=${s.status}
              .queueCount=${s.queueCount}
              .expanded=${false}
              @remove-item=${this.onQueueRemoveItem}
            ></oig-shield-queue>
          </div>
        ` : nothing}
      </div>

      <!-- Shared confirm dialog instance -->
      <oig-confirm-dialog></oig-confirm-dialog>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'oig-control-panel': OigControlPanel;
  }
}
