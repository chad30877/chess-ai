import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { App } from './app';
import { routes } from './app.routes';
import { NAV_ITEMS } from './shell/nav-items';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter(routes)],
    }).compileComponents();
  });

  it('側欄列出四區並連到各自網址', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const links = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLAnchorElement>('mat-nav-list a'),
    );
    expect(links.map((link) => link.querySelector('[matListItemTitle]')?.textContent?.trim())).toEqual(
      NAV_ITEMS.map((item) => item.label),
    );
    expect(links.map((link) => new URL(link.href).pathname)).toEqual(
      NAV_ITEMS.map((item) => '/' + item.path),
    );
  });
});
