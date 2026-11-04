import { HttpClient } from '@angular/common/http';
import { Injectable, NgZone, OnDestroy, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

export type JobStatus = 'running' | 'paused' | 'stopping' | 'completed' | 'stopped' | 'failed';

export interface JobProgress {
  saved_games?: number;
  requested_games?: number;
  completed_games?: number;
  unfinished?: number;
  batch_id?: string;
  path?: string;
  error?: string;
}

export interface Job {
  id: string;
  kind: string;
  label: string;
  link: string;
  started_at: string;
  status: JobStatus;
  can_pause: boolean;
  progress: JobProgress;
}

const FINISHED: JobStatus[] = ['completed', 'stopped', 'failed'];

export function isFinished(job: Job) {
  return FINISHED.includes(job.status);
}

export function progressText(job: Job) {
  const { saved_games, requested_games } = job.progress;
  return requested_games ? `已保存 ${saved_games ?? 0} / ${requested_games} 局` : '';
}

export const STATUS_LABELS: Record<JobStatus, string> = {
  running: '執行中',
  paused: '已暫停',
  stopping: '停止中',
  completed: '已完成',
  stopped: '已停止',
  failed: '失敗',
};

/** 伺服器工作的即時狀態：SSE 連線後先收到完整快照，斷線由瀏覽器自動重連。 */
@Injectable({ providedIn: 'root' })
export class JobsStore implements OnDestroy {
  private readonly http = inject(HttpClient);
  private readonly zone = inject(NgZone);
  private source: EventSource | null = null;

  readonly jobs = signal<Job[]>([]);
  readonly connected = signal(false);
  readonly running = computed(() => this.jobs().filter((job) => !isFinished(job)));
  /** 每當有工作結束就加一，供首頁重新讀取。 */
  readonly finishedCount = computed(() => this.jobs().filter(isFinished).length);

  connect() {
    if (this.source || typeof EventSource === 'undefined') {
      return;
    }
    this.source = new EventSource('/api/jobs/events');
    this.source.addEventListener('jobs', (event) => {
      const jobs = JSON.parse((event as MessageEvent).data) as Job[];
      this.zone.run(() => {
        this.jobs.set(jobs);
        this.connected.set(true);
      });
    });
    this.source.onerror = () => this.zone.run(() => this.connected.set(false));
  }

  control(job: Job, action: 'stop' | 'pause' | 'resume') {
    return firstValueFrom(this.http.post<Job>(`/api/jobs/${job.id}/${action}`, {}));
  }

  ngOnDestroy() {
    this.source?.close();
  }
}
