import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { NAV_ITEMS } from './shell/nav-items';
import { ProductMark } from './ui/product-mark';

/** 框架紙面：側欄在淡色框架上，工作內容在內縮的白色紙面上。 */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, ProductMark],
  template: `
    <nav class="sidebar" aria-label="主要區域">
      <a class="brand" routerLink="/">
        <app-product-mark />
        <span>Chess AI</span>
      </a>
      <ul>
        @for (item of navItems; track item.path) {
          <li>
            <a [routerLink]="item.path" routerLinkActive="active" ariaCurrentWhenActive="page">
              <span class="material-symbols-outlined" aria-hidden="true">{{ item.icon }}</span>
              {{ item.label }}
            </a>
          </li>
        }
      </ul>
    </nav>
    <main class="sheet">
      <router-outlet />
    </main>
  `,
  styles: `
    :host {
      display: grid;
      grid-template-columns: var(--sidebar-width) 1fr;
      height: 100vh;
      background: var(--ground);
    }

    .sidebar {
      padding: 12px 8px;
      overflow-y: auto;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 8px;
      height: 36px;
      padding: 0 8px;
      margin-bottom: 16px;
      color: var(--text);
      font-weight: 600;
      text-decoration: none;
    }

    ul {
      margin: 0;
      padding: 0;
      list-style: none;
    }

    li a {
      display: flex;
      align-items: center;
      gap: 10px;
      height: 32px;
      margin-bottom: 2px;
      padding: 0 8px;
      border-radius: var(--radius-control);
      color: var(--muted);
      text-decoration: none;
    }

    li a:hover {
      color: var(--text);
    }

    li a.active {
      background: var(--active);
      color: var(--text);
    }

    .material-symbols-outlined {
      font-size: 18px;
    }

    .sheet {
      margin: var(--sheet-inset) var(--sheet-inset) var(--sheet-inset) 0;
      padding: var(--pad);
      overflow: auto;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-sheet);
    }

    @media (max-width: 720px) {
      :host {
        grid-template-columns: 1fr;
        grid-template-rows: auto 1fr;
      }

      .sidebar {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 4px 8px;
        padding: 6px 16px;
      }

      .brand {
        margin: 0;
      }

      ul {
        display: flex;
        flex-wrap: wrap;
        gap: 2px;
      }

      li a {
        margin: 0;
        white-space: nowrap;
      }

      .sheet {
        margin: 0;
        border-radius: 0;
        border-width: 1px 0 0;
      }
    }
  `,
})
export class App {
  protected readonly navItems = NAV_ITEMS;
}
