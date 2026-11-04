import { Routes } from '@angular/router';

import { PlaceholderPage } from './pages/placeholder-page';
import { NAV_ITEMS } from './shell/nav-items';

export const routes: Routes = [
  { path: '', component: PlaceholderPage, data: { title: '首頁' }, title: 'Chess AI' },
  ...NAV_ITEMS.map((item) => ({
    path: item.path,
    component: PlaceholderPage,
    data: { title: item.label },
    title: `${item.label} · Chess AI`,
  })),
  { path: '**', redirectTo: '' },
];
