import { Component, signal } from '@angular/core';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';

import { ActionButton } from '../ui/action-button';
import { CopyId } from '../ui/copy-id';
import { StatusKind, StatusPill } from '../ui/status-pill';

interface CandidateRow {
  name: string;
  id: string;
  composition: string;
  method: string;
  mae: number;
  rating: number | null;
  status: { kind: StatusKind; label: string };
}

/** 示範資料：教師 8fbfe04e 的實際驗證 MAE；棋力尚未評估，以破折號呈現。 */
const ROWS: CandidateRow[] = [
  {
    name: '教師 8fbfe04e -SMKC (2)',
    id: '53099fc398e44a16bdf087f58fbfe04e',
    composition: 'J:-SMKC',
    method: '聯合學習',
    mae: 1.2068,
    rating: null,
    status: { kind: 'neutral', label: '未評估' },
  },
  {
    name: '教師 8fbfe04e -SM-C (2)',
    id: '0b7e2d4c9a1f4e3b8c6d5a4b3c2d1e0f',
    composition: 'J:-SM-C',
    method: '聯合學習',
    mae: 1.2115,
    rating: null,
    status: { kind: 'neutral', label: '未評估' },
  },
  {
    name: '教師 8fbfe04e -SMKC',
    id: '9f8e7d6c5b4a49388271605f4e3d2c1b',
    composition: 'D:-SMKC',
    method: '直接組合',
    mae: 1.2123,
    rating: null,
    status: { kind: 'warning', label: '設定檔遺失' },
  },
];

/** 元件示範頁：設計規範中各元件規則的實際樣子，不列在側欄。 */
@Component({
  selector: 'app-design-page',
  imports: [ActionButton, CopyId, StatusPill, MatFormFieldModule, MatInputModule, MatSelectModule, MatButtonToggleModule],
  template: `
    <header class="title-row">
      <div>
        <h1>元件示範</h1>
        <p class="subline">設計規範的元件規則；表格為示範資料。</p>
      </div>
      <app-action-button label="比較所選候選" kind="primary" [blockedReason]="selected() ? null : '先勾選至少一份候選'" />
    </header>

    <section>
      <h2>候選</h2>
      <table>
        <thead>
          <tr>
            <th class="check"><span class="visually-hidden">選取</span></th>
            <th>名稱</th>
            <th>組成</th>
            <th>方式</th>
            <th class="num">驗證 MAE</th>
            <th class="num">棋力</th>
            <th>狀態</th>
          </tr>
        </thead>
        <tbody>
          @for (row of rows; track row.id) {
            <tr>
              <td class="check">
                <input type="checkbox" class="checkbox" [attr.aria-label]="'選取 ' + row.name" (change)="toggle($event)" />
              </td>
              <td class="identity">
                <div class="name">{{ row.name }}</div>
                <app-copy-id [value]="row.id" />
              </td>
              <td><code class="composition">{{ row.composition }}</code></td>
              <td>{{ row.method }}</td>
              <td class="num">{{ row.mae.toFixed(4) }}</td>
              <td class="num">
                @if (row.rating === null) {
                  <span class="dash">—</span>
                } @else {
                  {{ row.rating }}
                }
              </td>
              <td><app-status-pill [kind]="row.status.kind">{{ row.status.label }}</app-status-pill></td>
            </tr>
          }
        </tbody>
      </table>
    </section>

    <section>
      <h2>教師先導</h2>
      <div class="form">
        <mat-form-field appearance="outline" class="path">
          <mat-label>教師引擎</mat-label>
          <input matInput value="D:\\Projects\\chess-ai\\tools\\stockfish\\stockfish-windows-x86-64-universal.exe" />
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>同時分析</mat-label>
          <mat-select value="2">
            @for (n of ['1', '2', '3', '4']; track n) {
              <mat-option [value]="n">{{ n }} 個局面</mat-option>
            }
          </mat-select>
        </mat-form-field>
        <mat-button-toggle-group value="200000" aria-label="節點預算">
          <mat-button-toggle value="50000">50,000 節點</mat-button-toggle>
          <mat-button-toggle value="200000">200,000 節點</mat-button-toggle>
        </mat-button-toggle-group>
      </div>
      <div class="actions">
        <app-action-button label="量測預計時間" kind="primary" />
        <app-action-button label="停止量測" blockedReason="目前沒有進行中的量測" />
      </div>
    </section>

    <section>
      <h2>狀態</h2>
      <div class="pills">
        <app-status-pill kind="positive">完成 5,809 / 5,809 局面</app-status-pill>
        <app-status-pill kind="warning">缺少前置：教師標記未完成</app-status-pill>
        <app-status-pill kind="negative">讀取失敗：快照身分不符</app-status-pill>
        <app-status-pill kind="neutral">未開始</app-status-pill>
      </div>
    </section>
  `,
  styles: `
    :host {
      display: block;
      max-width: 1200px;
    }

    .title-row {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: var(--gap);
      margin-bottom: var(--gap);
    }

    .subline {
      margin: 4px 0 0;
      color: var(--muted);
    }

    section + section {
      margin-top: 40px;
    }

    h2 {
      margin-bottom: 12px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
    }

    th,
    td {
      white-space: nowrap;
    }

    td.identity {
      width: 100%;
      white-space: normal;
    }

    th {
      height: 36px;
      padding: 0 12px;
      color: var(--muted);
      font-size: var(--fs-small);
      font-weight: 500;
      text-align: left;
    }

    td {
      height: var(--row-height);
      padding: 6px 12px;
      border-top: 1px solid var(--rule);
      vertical-align: middle;
    }

    tbody tr:hover td {
      background: var(--raised);
    }

    .num {
      text-align: right;
    }

    .check {
      width: 32px;
      padding-right: 0;
    }

    .name {
      font-weight: 500;
    }

    .checkbox {
      width: 16px;
      height: 16px;
      accent-color: var(--accent);
    }

    .composition {
      font: 400 var(--fs-body) var(--font-mono);
    }

    .dash {
      color: var(--muted);
    }

    .form {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0 16px;
    }

    .path {
      flex: 1 1 420px;
    }

    .actions,
    .pills {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }

    .visually-hidden {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
    }

    @media (max-width: 720px) {
      .title-row {
        flex-direction: column;
      }

      table,
      tbody,
      tr,
      td {
        display: block;
      }

      thead {
        display: none;
      }

      tr {
        position: relative;
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 4px 12px;
        padding: 10px 0 10px 32px;
        border-top: 1px solid var(--rule);
      }

      td {
        height: auto;
        padding: 0;
        border: 0;
      }

      td.check {
        position: absolute;
        top: 10px;
        left: 0;
      }

      td.identity {
        width: 100%;
      }

      tbody tr:hover td {
        background: none;
      }
    }
  `,
})
export class DesignPage {
  protected readonly rows = ROWS;
  protected readonly selected = signal(0);

  toggle(event: Event) {
    const checked = (event.target as HTMLInputElement).checked;
    this.selected.update((n) => n + (checked ? 1 : -1));
  }
}
