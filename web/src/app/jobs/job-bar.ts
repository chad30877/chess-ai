import { Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';

import { StatusPill } from '../ui/status-pill';
import { Job, JobsStore, STATUS_LABELS, progressText } from './jobs';

/** 頂端工作列：任何一頁都看得到執行中的工作並可停止。 */
@Component({
  selector: 'app-job-bar',
  imports: [RouterLink, StatusPill],
  template: `
    @let running = store.running();
    @if (running.length === 0) {
      <span class="idle">沒有執行中的工作</span>
    } @else {
      @for (job of running; track job.id) {
        <div class="job">
          <app-status-pill [kind]="job.status === 'paused' ? 'warning' : 'neutral'">{{ labels[job.status] }}</app-status-pill>
          <a class="label" [routerLink]="job.link">{{ job.label }}</a>
          <span class="progress">{{ progress(job) }}</span>
          @if (job.can_pause && job.status === 'running') {
            <button type="button" (click)="store.control(job, 'pause')">暫停</button>
          }
          @if (job.status === 'paused') {
            <button type="button" (click)="store.control(job, 'resume')">繼續</button>
          }
          <button type="button" [disabled]="job.status === 'stopping'" (click)="store.control(job, 'stop')">停止</button>
        </div>
      }
    }
    @if (!store.connected()) {
      <span class="offline">與伺服器的連線中斷，重新連線中</span>
    }
  `,
  styles: `
    :host {
      display: flex;
      align-items: center;
      gap: 16px;
      height: 48px;
      padding: 0 var(--sheet-inset) 0 0;
      overflow-x: auto;
    }

    .idle,
    .progress {
      color: var(--muted);
      white-space: nowrap;
    }

    .job {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .label {
      color: var(--text);
      font-weight: 500;
      white-space: nowrap;
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

    button:hover:not(:disabled) {
      background: var(--raised);
    }

    button:disabled {
      color: var(--muted);
      cursor: default;
    }

    .offline {
      margin-left: auto;
      color: var(--warning);
      white-space: nowrap;
    }
  `,
})
export class JobBar {
  protected readonly store = inject(JobsStore);
  protected readonly labels = STATUS_LABELS;
  protected progress(job: Job) {
    return progressText(job);
  }
}
