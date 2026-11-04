import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { App } from './app';
import { routes } from './app.routes';
import { NAV_ITEMS } from './shell/nav-items';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter(routes), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
  });

  it('側欄列出四區並連到各自網址', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const links = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLAnchorElement>('.sidebar li a'),
    );
    expect(links.map((link) => link.textContent?.replace(/^\s*\S+\s+/, '').trim())).toEqual(
      NAV_ITEMS.map((item) => item.label),
    );
    expect(links.map((link) => new URL(link.href).pathname)).toEqual(
      NAV_ITEMS.map((item) => '/' + item.path),
    );
  });
});
