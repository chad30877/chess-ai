import { Component, input, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';

/**
 * 動作按鈕：每個區塊最多一個 primary。
 * 給了 blockedReason 就停用，滑過或聚焦時說明原因。
 */
@Component({
  selector: 'app-action-button',
  imports: [MatButtonModule, MatTooltipModule],
  template: `
    <span
      class="wrap"
      [matTooltip]="blockedReason() ?? ''"
      [matTooltipDisabled]="!blockedReason()"
      [attr.tabindex]="blockedReason() ? 0 : null"
      [attr.aria-label]="blockedReason() ? label() + '：' + blockedReason() : null"
    >
      @if (kind() === 'primary') {
        <button mat-flat-button type="button" [disabled]="!!blockedReason()" (click)="pressed.emit()">
          {{ label() }}
        </button>
      } @else {
        <button mat-stroked-button type="button" [disabled]="!!blockedReason()" (click)="pressed.emit()">
          {{ label() }}
        </button>
      }
    </span>
  `,
  styles: `
    .wrap {
      display: inline-flex;
      border-radius: var(--radius-control);
    }
  `,
})
export class ActionButton {
  readonly label = input.required<string>();
  readonly kind = input<'primary' | 'secondary'>('secondary');
  readonly blockedReason = input<string | null>(null);
  readonly pressed = output<void>();
}
