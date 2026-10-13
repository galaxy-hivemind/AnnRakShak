import { queryOptions } from '@tanstack/react-query';
import { mockService } from './mock';
import { FastApiFoodSafetyService } from './fastapi';
import type { FoodSafetyService } from './types';

// The backend API base URL from VITE_API_BASE_URL or local default
const rawBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
const apiMode = import.meta.env.VITE_API_MODE === 'demo' ? 'demo' : 'live';

export const apiConfig = {
  baseUrl: rawBaseUrl,
  mode: apiMode,
};

// Use live FastAPI adapter by default, or mockService if explicitly in demo mode
export const service: FoodSafetyService =
  apiMode === 'demo' ? mockService : new FastApiFoodSafetyService(rawBaseUrl);

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
