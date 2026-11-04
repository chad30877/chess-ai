import { Component, computed, input } from '@angular/core';

export type StatusKind = 'positive' | 'negative' | 'warning' | 'neutral';

const ICONS: Record<StatusKind, string> = {
  positive: 'check_circle',
  negative: 'error',
  warning: 'warning',
  neutral: 'radio_button_unchecked',
};

/** 狀態一律同時有顏色、圖示與文字，不只靠顏色辨識。 */
@Component({
  selector: 'app-status-pill',
  template: `
    <span class="material-symbols-outlined" aria-hidden="true">{{ icon() }}</span>
    <ng-content />
  `,
  host: {
    '[class]': '"pill " + kind()',
  },
  styles: `
    :host {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      height: 22px;
      padding: 0 8px 0 6px;
      border-radius: 11px;
      font-size: var(--fs-small);
      font-weight: 500;
      white-space: nowrap;
    }

    .material-symbols-outlined {
      font-size: 14px;
    }

    :host(.positive) {
      background: var(--pill-positive-bg);
      color: var(--pill-positive-ink);
    }

    :host(.negative) {
      background: var(--pill-negative-bg);
      color: var(--pill-negative-ink);
    }

    :host(.warning) {
      background: var(--pill-warning-bg);
      color: var(--pill-warning-ink);
    }

    :host(.neutral) {
      background: var(--pill-neutral-bg);
      color: var(--pill-neutral-ink);
    }
  `,
})
export class StatusPill {
  readonly kind = input<StatusKind>('neutral');
  protected readonly icon = computed(() => ICONS[this.kind()]);
}
