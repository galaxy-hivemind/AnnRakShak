import { queryOptions } from '@tanstack/react-query';
import { mockService } from './mock';
import { FastApiFoodSafetyService, getApiBaseUrl } from './fastapi';
import type { FoodSafetyService } from './types';

const apiMode = import.meta.env.VITE_API_MODE === 'demo' ? 'demo' : 'live';

export const apiConfig = {
  get baseUrl() {
    return getApiBaseUrl();
  },
  mode: apiMode,
};

// Use live FastAPI adapter by default (with dynamic Vercel service binding / relative URL resolution),
// or mockService if explicitly in demo mode
export const service: FoodSafetyService =
  apiMode === 'demo' ? mockService : new FastApiFoodSafetyService();

export const dashboardQuery = queryOptions({
  queryKey: ['dashboard'],
  queryFn: () => service.getDashboardSummary(),
});

export const productsQuery = queryOptions({
  queryKey: ['products'],
  queryFn: () => service.getProducts(),
});

export const scansQuery = queryOptions({
  queryKey: ['scans'],
  queryFn: () => service.getScanHistory(),
});

export const settingsQuery = queryOptions({
  queryKey: ['settings'],
  queryFn: () => service.getSettings(),
});

export const wasteQuery = queryOptions({
  queryKey: ['waste'],
  queryFn: () => service.getWasteJournal(),
});
