import { Component, computed, input, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

/** 識別碼只顯示前 8 碼，按鈕複製完整值。 */
@Component({
  selector: 'app-copy-id',
  imports: [MatTooltipModule],
  template: `
    <code [title]="value()">{{ short() }}</code>
    <button
      type="button"
      class="copy"
      [attr.aria-label]="'複製 ' + value()"
      [matTooltip]="copied() ? '已複製' : '複製識別碼'"
      (click)="copy()"
    >
      <span class="material-symbols-outlined" aria-hidden="true">{{ copied() ? 'check' : 'content_copy' }}</span>
    </button>
  `,
  styles: `
    :host {
      display: inline-flex;
      align-items: center;
      gap: 2px;
    }

    code {
      font: 400 var(--fs-small) var(--font-mono);
      color: var(--muted);
    }

    .copy {
      display: inline-flex;
      padding: 2px;
      border: 0;
      border-radius: 4px;
      background: none;
      color: var(--muted);
      cursor: pointer;
    }

    .copy:hover {
      background: var(--active);
      color: var(--text);
    }

    .material-symbols-outlined {
      font-size: 14px;
    }
  `,
})
export class CopyId {
  readonly value = input.required<string>();
  protected readonly short = computed(() => {
    const value = this.value();
    return value.length > 8 ? value.slice(0, 8) + '…' : value;
  });
  protected readonly copied = signal(false);

  async copy() {
    await navigator.clipboard.writeText(this.value());
    this.copied.set(true);
  }
}
