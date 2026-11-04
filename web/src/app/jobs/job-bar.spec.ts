import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { JobBar } from './job-bar';
import { Job, JobsStore } from './jobs';

const JOB: Job = {
  id: '1',
  kind: 'general_batch',
  label: '一般批次 Random 對 Random・3 局',
  link: '/batch',
  started_at: '2026-11-04T13:00:00+00:00',
  status: 'running',
  can_pause: true,
  progress: { saved_games: 1, requested_games: 3 },
};

describe('JobBar', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [JobBar],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
  });

  it('沒有工作時說明目前沒有執行中的工作', async () => {
    const fixture = TestBed.createComponent(JobBar);
    TestBed.inject(JobsStore).connected.set(true);
    await fixture.whenStable();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('沒有執行中的工作');
  });

  it('顯示進度並可停止，已結束的工作不列出', async () => {
    const store = TestBed.inject(JobsStore);
    store.connected.set(true);
    store.jobs.set([JOB, { ...JOB, id: '2', label: '已結束', status: 'completed' }]);
    const fixture = TestBed.createComponent(JobBar);
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;
    expect(host.textContent).toContain('已保存 1 / 3 局');
    expect(host.textContent).not.toContain('已結束');
    const stop = Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === '停止')!;
    stop.click();
    const request = TestBed.inject(HttpTestingController).expectOne('/api/jobs/1/stop');
    expect(request.request.method).toBe('POST');
  });

  it('斷線時提示重新連線中', async () => {
    const fixture = TestBed.createComponent(JobBar);
    await fixture.whenStable();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('重新連線中');
  });
});
