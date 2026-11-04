import { Component } from '@angular/core';

/** 產品標記：兩格對角棋盤，取自本產品的棋盤本身。 */
@Component({
  selector: 'app-product-mark',
  template: `
    <svg viewBox="0 0 16 16" width="20" height="20" aria-hidden="true">
      <rect width="16" height="16" rx="3" fill="var(--board-light)" />
      <path d="M0 3a3 3 0 0 1 3-3h5v8H0zM8 8h8v5a3 3 0 0 1-3 3H8z" fill="var(--accent)" />
    </svg>
  `,
  styles: `
    :host {
      display: inline-flex;
    }
  `,
})
export class ProductMark {}
