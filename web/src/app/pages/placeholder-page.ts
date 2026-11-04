import { Component, input } from '@angular/core';

/** 尚未搬移的區域先以占位頁呈現，標題來自路由資料。 */
@Component({
  selector: 'app-placeholder-page',
  template: `
    <h1>{{ title() }}</h1>
    <p>此區尚未搬移到網頁介面。</p>
  `,
  styles: `
    h1 {
      font: var(--mat-sys-headline-small);
      margin: 0 0 8px;
    }

    p {
      color: var(--mat-sys-on-surface-variant);
      margin: 0;
    }
  `,
})
export class PlaceholderPage {
  readonly title = input.required<string>();
}
