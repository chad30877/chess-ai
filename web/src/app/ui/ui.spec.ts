import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { ActionButton } from './action-button';
import { CopyId } from './copy-id';

@Component({
  imports: [ActionButton],
  template: `<app-action-button label="開始" [blockedReason]="reason()" (pressed)="count = count + 1" />`,
})
class ActionHost {
  readonly reason = signal<string | null>(null);
  count = 0;
}

describe('ActionButton', () => {
  it('沒有阻擋原因時可按', async () => {
    const fixture = TestBed.createComponent(ActionHost);
    await fixture.whenStable();
    const button = fixture.nativeElement.querySelector('button') as HTMLButtonElement;
    button.click();
    expect(button.disabled).toBe(false);
    expect(fixture.componentInstance.count).toBe(1);
  });

  it('有阻擋原因時停用並以可聚焦的外框說明原因', async () => {
    const fixture = TestBed.createComponent(ActionHost);
    fixture.componentInstance.reason.set('先選擇教師引擎');
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;
    const button = host.querySelector('button') as HTMLButtonElement;
    const wrap = host.querySelector('.wrap') as HTMLElement;
    button.click();
    expect(button.disabled).toBe(true);
    expect(fixture.componentInstance.count).toBe(0);
    expect(wrap.getAttribute('tabindex')).toBe('0');
    expect(wrap.getAttribute('aria-label')).toBe('開始：先選擇教師引擎');
  });
});

@Component({
  imports: [CopyId],
  template: `<app-copy-id value="53099fc398e44a16bdf087f58fbfe04e" />`,
})
class CopyHost {}

describe('CopyId', () => {
  it('顯示前 8 碼並複製完整識別碼', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    const fixture = TestBed.createComponent(CopyHost);
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelector('code')?.textContent).toBe('53099fc3…');
    (host.querySelector('button') as HTMLButtonElement).click();
    await fixture.whenStable();
    expect(writeText).toHaveBeenCalledWith('53099fc398e44a16bdf087f58fbfe04e');
  });
});
