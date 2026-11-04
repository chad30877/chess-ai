export interface NavItem {
  path: string;
  label: string;
  icon: string;
}

/** 側欄四區；網址與標題由此單一來源產生。 */
export const NAV_ITEMS: readonly NavItem[] = [
  { path: 'play', label: '對戰', icon: 'chess' },
  { path: 'records', label: '對局紀錄', icon: 'history' },
  { path: 'batch', label: '批次對戰', icon: 'stacks' },
  { path: 'learning', label: '學習實驗', icon: 'science' },
];
