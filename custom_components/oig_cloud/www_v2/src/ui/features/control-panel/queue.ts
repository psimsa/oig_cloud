/**
 * OIG Cloud V2 — Shield Queue Display
 *
 * Displays running + queued requests from the shield activity sensor.
 * Shows service name, changes, timestamps, live duration, and remove button.
 *
 * Data is provided by the parent oig-control-panel via `items` property,
 * sourced from ShieldController.
 *
 * Port of V1 shield.js updateShieldQueue() + buildQueueRow().
 */

import { LitElement, html, css, unsafeCSS, nothing } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { CSS_VARS } from '@/ui/theme';
import {
  ShieldQueueItem,
  QUEUE_SERVICE_MAP,
  QUEUE_VALUE_MAP,
} from './types';

const u = unsafeCSS;

@customElement('oig-shield-queue')
export class OigShieldQueue extends LitElement {
  @property({ type: Array }) items: ShieldQueueItem[] = [];
  @property({ type: Boolean }) expanded = false;
  /** Shield global status: idle | running */
  @property({ type: String }) shieldStatus: 'idle' | 'running' = 'idle';
  @property({ type: Number }) queueCount = 0;
  @state() private _now = Date.now();

  private updateInterval: number | null = null;

  static styles = css`
    :host {
      display: block;
      background: ${u(CSS_VARS.cardBg)};
      border-radius: 12px;
      box-shadow: ${u(CSS_VARS.cardShadow)};
      overflow: hidden;
    }

    .queue-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      cursor: pointer;
      background: ${u(CSS_VARS.bgSecondary)};
      user-select: none;
    }

    .queue-header:hover {
      opacity: 0.9;
    }

    .queue-title-area {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .queue-title {
      font-size: 14px;
      font-weight: 500;
      color: ${u(CSS_VARS.textPrimary)};
    }

    .queue-count {
      font-size: 12px;
      color: ${u(CSS_VARS.textSecondary)};
    }

    .shield-status {
      font-size: 12px;
      padding: 2px 8px;
      border-radius: 10px;
      font-weight: 500;
    }

    .shield-status.idle {
      color: #4caf50;
      background: rgba(76, 175, 80, 0.1);
    }

    .shield-status.running {
      color: #2196f3;
      background: rgba(33, 150, 243, 0.1);
    }

    .queue-toggle {
      font-size: 12px;
      color: ${u(CSS_VARS.accent)};
      transition: transform 0.2s;
    }

    .queue-toggle.expanded {
      transform: rotate(180deg);
    }

    .queue-content {
      padding: 0;
      border-top: 1px solid ${u(CSS_VARS.divider)};
    }

    /* Table layout (matches V1) */
    .queue-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }

    .queue-table th {
      text-align: left;
      padding: 8px 12px;
      font-weight: 600;
      color: ${u(CSS_VARS.textSecondary)};
      border-bottom: 1px solid ${u(CSS_VARS.divider)};
      background: ${u(CSS_VARS.bgSecondary)};
    }

    .queue-table td {
      padding: 8px 12px;
      color: ${u(CSS_VARS.textPrimary)};
      border-bottom: 1px solid ${u(CSS_VARS.divider)};
      vertical-align: middle;
    }

    .queue-table tr:last-child td {
      border-bottom: none;
    }

    .status-running {
      color: #2196f3;
      font-weight: 500;
    }

    .status-queued {
      color: #ff9800;
      font-weight: 500;
    }

    .queue-time {
      font-variant-numeric: tabular-nums;
    }

    .duration {
      font-weight: 600;
    }

    .remove-btn {
      background: none;
      border: none;
      cursor: pointer;
      font-size: 16px;
      opacity: 0.6;
      padding: 4px 8px;
      transition: all 0.2s;
    }

    .remove-btn:hover {
      opacity: 1;
      transform: scale(1.2);
    }

    .empty-state {
      text-align: center;
      padding: 16px;
      color: ${u(CSS_VARS.textSecondary)};
      font-size: 12px;
    }

    /* Responsive: hide some columns on mobile */
    @media (max-width: 600px) {
      .hide-mobile {
        display: none;
      }

      .queue-table td,
      .queue-table th {
        padding: 6px 8px;
        font-size: 11px;
      }
    }
  `;

  connectedCallback(): void {
    super.connectedCallback();
    this.updateInterval = window.setInterval(() => {
      this._now = Date.now();
    }, 1000);
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    if (this.updateInterval !== null) {
      clearInterval(this.updateInterval);
    }
  }

  private toggleExpanded(): void {
    this.expanded = !this.expanded;
  }

  private removeItem(position: number, e: Event): void {
    e.stopPropagation();
    this.dispatchEvent(new CustomEvent('remove-item', {
      detail: { position },
      bubbles: true,
    }));
  }

  // --------------------------------------------------------------------------
  // Formatting helpers (from V1 shield.js)
  // --------------------------------------------------------------------------

  private formatServiceName(service: string): string {
    return QUEUE_SERVICE_MAP[service] || service || 'N/A';
  }

  private formatChanges(changes: string[]): string {
    if (!changes || changes.length === 0) return 'N/A';

    return changes.map((change) => {
      const arrowIndex = change.indexOf('\u2192');
      if (arrowIndex === -1) return change;

      const left = change.slice(0, arrowIndex).trim();
      const right = change.slice(arrowIndex + 1).trim();
      const colonIndex = left.indexOf(':');
      const fromRaw = colonIndex === -1 ? left : left.slice(colonIndex + 1);

      const from = (QUEUE_VALUE_MAP[fromRaw.replace(/'/g, '').trim()] || fromRaw).replace(/'/g, '').trim();
      const to = (QUEUE_VALUE_MAP[right.replace(/'/g, '').trim()] || right).replace(/'/g, '').trim();

      return `${from} \u2192 ${to}`;
    }).join(', ');
  }

  private formatTimestamp(timestamp: string): { time: string; duration: string } {
    if (!timestamp) return { time: '--', duration: '--' };

    try {
      const date = new Date(timestamp);
      if (isNaN(date.getTime())) {
        return { time: '--', duration: '--' };
      }
      const now = new Date(this._now);
      const diffSec = Math.floor((now.getTime() - date.getTime()) / 1000);

      const hours = String(date.getHours()).padStart(2, '0');
      const minutes = String(date.getMinutes()).padStart(2, '0');
      let timeStr = `${hours}:${minutes}`;

      if (date.toDateString() !== now.toDateString()) {
        const day = date.getDate();
        const month = date.getMonth() + 1;
        timeStr = `${day}.${month}. ${timeStr}`;
      }

      let durationStr: string;
      if (diffSec < 60) {
        durationStr = `${diffSec}s`;
      } else if (diffSec < 3600) {
        const m = Math.floor(diffSec / 60);
        const s = diffSec % 60;
        durationStr = `${m}m ${s}s`;
      } else {
        const h = Math.floor(diffSec / 3600);
        const m = Math.floor((diffSec % 3600) / 60);
        durationStr = `${h}h ${m}m`;
      }

      return { time: timeStr, duration: durationStr };
    } catch {
      return { time: '--', duration: '--' };
    }
  }

  private get activeCount(): number {
    return this.items.length;
  }

  // --------------------------------------------------------------------------
  // Render
  // --------------------------------------------------------------------------

  render() {
    // _now triggers re-render every second for live duration updates
    void this._now;
    const statusClass = this.shieldStatus === 'running' ? 'running' : 'idle';
    const statusText = this.shieldStatus === 'running' ? '\uD83D\uDD04 Zpracov\u00E1v\u00E1' : '\u2713 P\u0159ipraveno';

    return html`
      <div class="queue-header" @click=${this.toggleExpanded}>
        <div class="queue-title-area">
          <span class="queue-title">Shield fronta</span>
          ${this.activeCount > 0 ? html`
            <span class="queue-count">(${this.activeCount} aktivn\u00EDch)</span>
          ` : nothing}
          <span class="shield-status ${statusClass}">${statusText}</span>
        </div>
        <span class="queue-toggle ${this.expanded ? 'expanded' : ''}">\u25BC</span>
      </div>

      ${this.expanded ? html`
        <div class="queue-content">
          ${this.items.length === 0 ? html`
            <div class="empty-state">\u2705 Fronta je pr\u00E1zdn\u00E1</div>
          ` : html`
            <table class="queue-table">
              <thead>
                <tr>
                  <th>Stav</th>
                  <th>Slu\u017Eba</th>
                  <th class="hide-mobile">Zm\u011Bny</th>
                  <th>Vytvo\u0159eno</th>
                  <th>Trv\u00E1n\u00ED</th>
                  <th>Akce</th>
                </tr>
              </thead>
              <tbody>
                ${this.items.map((item, index) => this.renderRow(item, index))}
              </tbody>
            </table>
          `}
        </div>
      ` : nothing}
    `;
  }

  private renderRow(item: ShieldQueueItem, _index: number) {
    const isRunning = item.status === 'running';
    const { time, duration } = this.formatTimestamp(item.createdAt);

    return html`
      <tr>
        <td class="${isRunning ? 'status-running' : 'status-queued'}">
          ${isRunning ? '\uD83D\uDD04 Zpracov\u00E1v\u00E1 se' : '\u23F3 \u010Cek\u00E1'}
        </td>
        <td>${this.formatServiceName(item.service)}</td>
        <td class="hide-mobile" style="font-size: 11px;">${this.formatChanges(item.changes)}</td>
        <td class="queue-time">${time}</td>
        <td class="queue-time duration">${duration}</td>
        <td style="text-align: center;">
          ${!isRunning ? html`
            <button
              class="remove-btn"
              title="Odstranit z fronty"
              @click=${(e: Event) => this.removeItem(item.position, e)}
            >\uD83D\uDDD1\uFE0F</button>
          ` : html`<span style="opacity: 0.4;">\u2014</span>`}
        </td>
      </tr>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'oig-shield-queue': OigShieldQueue;
  }
}
