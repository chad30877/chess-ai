import { DatePipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnDestroy, effect, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { Job, JobsStore, STATUS_LABELS, progressText } from '../jobs/jobs';
import { CopyId } from '../ui/copy-id';
import { StatusKind, StatusPill } from '../ui/status-pill';

interface Resumable {
  kind: string;
  kind_label: string;
  status: string;
  status_label: string;
  name: string;
  id: string;
  path: string;
}

interface Research {
  name: string;
  id: string;
  updated_at: string;
}

interface RecordItem {
  key: string;
  batch_id: string;
  name: string;
  kind_label: string;
  created_at: string | null;
  games: number;
  unfinished: number;
  error: string;
}

interface HomeState {
  status: 'scanning' | 'ready' | 'failed';
  scanned_at: string | null;
  error: string;
  resumable: Resumable[];
  recent_research: Research[];
  recent_records: RecordItem[];
}

const RESUMABLE_KIND: Record<string, StatusKind> = {
  failed: 'negative',
  unavailable: 'negative',
  stopped: 'warning',
  interrupted: 'warning',
  partial: 'warning',
};

@Component({
  selector: 'app-home-page',
  imports: [RouterLink, DatePipe, StatusPill, CopyId],
  template: `
    <header class="title-row">
      <h1>Chess AI</h1>
      <nav class="entries" aria-label="快速入口">
        <a routerLink="/play">新對局</a>
        <a routerLink="/batch">新批次</a>
        <a class="primary" routerLink="/learning">新研究</a>
      </nav>
    </header>

    <section>
      <h2>進行中的工作</h2>
      @if (store.running().length === 0) {
        <p class="empty">沒有執行中的工作。</p>
      } @else {
        <table>
          <thead><tr><th>工作</th><th>進度</th><th>狀態</th><th><span class="visually-hidden">動作</span></th></tr></thead>
          <tbody>
            @for (job of store.running(); track job.id) {
              <tr>
                <td class="identity"><a [routerLink]="job.link">{{ job.label }}</a></td>
                <td>{{ progress(job) }}</td>
                <td><app-status-pill>{{ labels[job.status] }}</app-status-pill></td>
                <td class="actions">
                  <button type="button" [disabled]="job.status === 'stopping'" (click)="store.control(job, 'stop')">停止</button>
                </td>
              </tr>
            }
          </tbody>
        </table>
      }
    </section>

    @let home = state();
    <section>
      <h2>
        可續跑的工作
        @if (home?.status === 'scanning' && home?.scanned_at) {
          <span class="updating">更新中</span>
        }
      </h2>
      @if (home === null || (home.status === 'scanning' && !home.scanned_at)) {
        <p class="empty">正在掃描未完成的工作…</p>
      } @else if (home.status === 'failed') {
        <app-status-pill kind="negative">掃描失敗：{{ home.error }}</app-status-pill>
      } @else if (home.resumable.length === 0) {
        <p class="empty">沒有未完成的工作。</p>
      } @else {
        <table>
          <thead><tr><th>名稱</th><th>類型</th><th>狀態</th><th><span class="visually-hidden">動作</span></th></tr></thead>
          <tbody>
            @for (item of home.resumable; track item.path + item.kind) {
              <tr>
                <td class="identity">
                  <span class="name">{{ item.name }}</span>
                  <app-copy-id [value]="item.id" />
                </td>
                <td>{{ item.kind_label }}</td>
                <td><app-status-pill [kind]="resumableKind(item.status)">{{ item.status_label }}</app-status-pill></td>
                <td class="actions"><a routerLink="/learning">前往</a></td>
              </tr>
            }
          </tbody>
        </table>
      }
    </section>

    <div class="recent">
      <section>
        <h2>最近的研究</h2>
        @if (home && home.recent_research.length) {
          <table>
            <tbody>
              @for (item of home.recent_research; track item.id) {
                <tr>
                  <td class="identity">
                    <a routerLink="/learning">{{ item.name }}</a>
                    <app-copy-id [value]="item.id" />
                  </td>
                  <td class="num">{{ item.updated_at | date: 'yyyy/MM/dd HH:mm' }}</td>
                </tr>
              }
            </tbody>
          </table>
        } @else if (home && home.status === 'ready') {
          <p class="empty">還沒有研究資料。</p>
        }
      </section>
      <section>
        <h2>最近的對局紀錄</h2>
        @if (home && home.recent_records.length) {
          <table>
            <tbody>
              @for (item of home.recent_records; track item.key) {
                <tr>
                  <td class="identity">
                    <a routerLink="/records">{{ item.name || item.batch_id }}</a>
                    <span class="meta">{{ item.kind_label }}</span>
                  </td>
                  <td class="num">{{ item.games }} 局</td>
                </tr>
              }
            </tbody>
          </table>
        } @else if (home && home.status === 'ready') {
          <p class="empty">還沒有對局紀錄。</p>
        }
      </section>
    </div>
  `,
  styles: `
    :host {
      display: block;
      max-width: 1200px;
    }

    .title-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: var(--gap);
      margin-bottom: var(--gap);
    }

    .entries {
      display: flex;
      gap: 8px;
    }

    .entries a {
      display: inline-flex;
      align-items: center;
      height: 32px;
      padding: 0 14px;
      border: 1px solid var(--control);
      border-radius: var(--radius-control);
      color: var(--text);
      text-decoration: none;
    }

    .entries a.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: var(--on-accent);
    }

    section + section,
    .recent {
      margin-top: 40px;
    }

    .recent {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: var(--gap);
    }

    .recent section + section {
      margin-top: 0;
    }

    h2 {
      margin-bottom: 8px;
    }

    .updating {
      margin-left: 8px;
      color: var(--muted);
      font-size: var(--fs-small);
      font-weight: 400;
    }

    .empty {
      margin: 0;
      color: var(--muted);
    }

    table {
      width: 100%;
      border-collapse: collapse;
    }

    th {
      height: 32px;
      padding: 0 12px;
      color: var(--muted);
      font-size: var(--fs-small);
      font-weight: 500;
      text-align: left;
      white-space: nowrap;
    }

    td {
      height: 44px;
      padding: 4px 12px;
      border-top: 1px solid var(--rule);
      white-space: nowrap;
    }

    td.identity {
      width: 100%;
      white-space: normal;
      overflow-wrap: anywhere;
    }

    .name {
      margin-right: 8px;
    }

    td.identity a {
      margin-right: 8px;
      color: var(--text);
      font-weight: 500;
    }

    .meta {
      color: var(--muted);
      font-size: var(--fs-small);
    }

    .num,
    .actions {
      text-align: right;
    }

    a {
      color: var(--accent);
    }

    button {
      height: 28px;
      padding: 0 10px;
      border: 1px solid var(--control);
      border-radius: var(--radius-control);
      background: var(--surface);
      color: var(--text);
      font: inherit;
      cursor: pointer;
    }

    .visually-hidden {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
    }

    @media (max-width: 900px) {
      .recent {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 720px) {
      .title-row {
        flex-direction: column;
        align-items: flex-start;
      }
    }
  `,
})
export class HomePage implements OnDestroy {
  protected readonly store = inject(JobsStore);
  private readonly http = inject(HttpClient);
  protected readonly labels = STATUS_LABELS;
  protected readonly state = signal<HomeState | null>(null);
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    // 有工作結束時，伺服器會重新掃描；稍後重新讀取首頁資料。
    effect(() => {
      this.store.finishedCount();
      setTimeout(() => this.load(), 500);
    });
  }

  async load() {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    try {
      const state = await firstValueFrom(this.http.get<HomeState>('/api/home'));
      this.state.set(state);
      if (state.status === 'scanning') {
        this.timer = setTimeout(() => this.load(), 1000);
      }
    } catch {
      this.timer = setTimeout(() => this.load(), 3000);
    }
  }

  protected progress(job: Job) {
    return progressText(job);
  }

  protected resumableKind(status: string): StatusKind {
    return RESUMABLE_KIND[status] ?? 'neutral';
  }

  ngOnDestroy() {
    if (this.timer) {
      clearTimeout(this.timer);
    }
  }
}
