import { Routes } from '@angular/router';

import { PlaceholderPage } from './pages/placeholder-page';
import { NAV_ITEMS } from './shell/nav-items';

export const routes: Routes = [
  { path: '', loadComponent: () => import('./home/home-page').then((m) => m.HomePage), title: 'Chess AI' },
  ...NAV_ITEMS.map((item) => ({
    path: item.path,
    component: PlaceholderPage,
    data: { title: item.label },
    title: `${item.label} · Chess AI`,
  })),
  {
    path: 'design',
    loadComponent: () => import('./pages/design-page').then((m) => m.DesignPage),
    title: '元件示範 · Chess AI',
  },
  { path: '**', redirectTo: '' },
];
