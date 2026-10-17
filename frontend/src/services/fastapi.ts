import {
  categories,
  dateTypes,
  type Category,
  type DateType,
  type Product,
  type ProductInput,
  type ScanRecord,
  type DateCandidate,
  type DashboardSummary,
  type FoodSafetyService,
  type WasteEntry,
  type WasteInput,
  type Settings,
} from './types';
import { isExactDate, relativeDate, daysFromToday, productStatus } from './dates';

// Backend Response Schemas
interface BackendProduct {
  id: number;
  product_name: string;
  brand: string | null;
  food_category: string | null;
  date_type: string;
  date_text: string | null;
  normalized_date: string | null;
  date_status: string;
  current_status: string;
  date_source: string;
  analysis_status: string | null;
  image_path: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  date_candidates: BackendDateCandidate[];
}

interface BackendDateCandidate {
  id: number | null;
  product_id: number | null;
  scan_id: number | null;
  raw_text: string;
  date_type: string;
  normalized_date: string | null;
  confidence: number;
  evidence: string;
  created_at: string;
}

interface BackendDashboard {
  total_products: number;
  expired_count: number;
  expiring_soon_count: number;
  best_before_soon_count: number;
  best_before_passed_count: number;
  safe_count: number;
  needs_review_count: number;
  total_scans: number;
  recent_scans_count: number;
  categories: Record<string, number>;
}

interface BackendAlert {
  product_id: number;
  product_name: string;
  brand: string | null;
  food_category: string | null;
  date_type: string;
  normalized_date: string | null;
  date_status: string;
  urgency: 'critical' | 'warning' | 'info';
  message: string;
  days_remaining: number | null;
}

interface BackendScan {
  id: number;
  timestamp: string;
  image_path: string;
  product_name: string | null;
  brand: string | null;
  food_category: string | null;
  analysis_status: string;
  needs_review: boolean;
  review_reason: string | null;
  selected_expiry_date: string | null;
  error_message: string | null;
  raw_json: string | null;
  date_candidates: BackendDateCandidate[];
}

// ---------------------------------------------------------------------------
// Helpers & Mapping Functions
// ---------------------------------------------------------------------------

const categoryMap: Record<string, Category> = {
  dairy: 'Dairy & Eggs',
  'dairy & eggs': 'Dairy & Eggs',
  grains: 'Grains & Cereals',
  bakery: 'Grains & Cereals',
  'grains & cereals': 'Grains & Cereals',
  snacks: 'Snacks',
  snack: 'Snacks',
  beverage: 'Beverages',
  beverages: 'Beverages',
  pantry: 'Pantry Staples',
  'pantry staples': 'Pantry Staples',
  condiments: 'Pantry Staples',
  'canned goods': 'Pantry Staples',
  produce: 'Fresh Produce',
  'fresh produce': 'Fresh Produce',
  medicine: 'Pantry Staples',
  medicines: 'Pantry Staples',
  pharmaceutical: 'Pantry Staples',
  pharmaceuticals: 'Pantry Staples',
};

export function toFrontendCategory(raw: string | null | undefined): Category {
  if (!raw) return 'Pantry Staples';
  const clean = raw.trim().toLowerCase();
  return categoryMap[clean] || 'Pantry Staples';
}

export function toBackendCategory(cat: Category): string {
  switch (cat) {
    case 'Dairy & Eggs':
      return 'Dairy';
    case 'Grains & Cereals':
      return 'Grains';
    case 'Snacks':
      return 'Snacks';
    case 'Beverages':
      return 'Beverage';
    case 'Fresh Produce':
      return 'Produce';
    case 'Pantry Staples':
    default:
      return 'Pantry';
  }
}

export function toFrontendDateType(raw: string | null | undefined): DateType {
  const clean = (raw || '').trim().toLowerCase();
  if (clean === 'use_by' || clean === 'use by') return 'Use By';
  if (clean === 'best_before' || clean === 'best before' || clean === 'after_opening') return 'Best Before';
  if (clean === 'manufacturing') return 'Manufacturing';
  if (clean === 'packed_on' || clean === 'packed on') return 'Packed On';
  return 'Expiry';
}

export function toBackendDateType(dt: DateType): string {
  switch (dt) {
    case 'Use By':
      return 'use_by';
    case 'Best Before':
      return 'best_before';
    case 'Manufacturing':
      return 'manufacturing';
    case 'Packed On':
      return 'packed_on';
    case 'Expiry':
    default:
      return 'expiry';
  }
}

export function categorySvg(category: Category): string {
  const idx = categories.indexOf(category);
  return `/products/${idx >= 0 ? idx : 0}.svg`;
}

export function parseId(id: string): number {
  const num = parseInt(id.replace(/^PR-|^SC-/, ''), 10);
  if (isNaN(num)) {
    throw new Error(`Invalid numeric ID: "${id}"`);
  }
  return num;
}

// ---------------------------------------------------------------------------
// FastAPI Adapter Implementation
// ---------------------------------------------------------------------------

/**
 * Resolves the backend API base URL:
 * 1. Server-side runtime: checks process.env.FASTAPI_URL (injected via Vercel service binding)
 * 2. Client/build-time: checks import.meta.env.VITE_API_BASE_URL
 * 3. Browser environment:
 *    - In local dev (localhost / 127.0.0.1): defaults to 'http://127.0.0.1:8000'
 *    - In production (Vercel): uses '' (relative path) to route via top-level /api/(.*) rewrites
 * 4. Fallback default: 'http://127.0.0.1:8000'
 */
export function getApiBaseUrl(): string {
  if (typeof process !== 'undefined' && process.env?.FASTAPI_URL) {
    return process.env.FASTAPI_URL.replace(/\/+$/, '');
  }

  if (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL.replace(/\/+$/, '');
  }

  if (typeof window !== 'undefined') {
    if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
      return 'http://127.0.0.1:8000';
    }
    return '';
  }

  return 'http://127.0.0.1:8000';
}

export class FastApiFoodSafetyService implements FoodSafetyService {
  private explicitBaseUrl?: string;

  constructor(baseUrl?: string) {
    if (baseUrl !== undefined) {
      this.explicitBaseUrl = baseUrl.replace(/\/+$/, '');
    }
  }

  public get baseUrl(): string {
    if (this.explicitBaseUrl !== undefined) {
      return this.explicitBaseUrl;
    }
    return getApiBaseUrl();
  }

  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    const base = this.baseUrl;
    const url = base ? `${base}${cleanPath}` : cleanPath;
    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...(options?.headers || {}),
        },
      });

      if (!response.ok) {
        let errorDetail = `Request failed with status ${response.status}`;
        try {
          const errData = await response.json();
          if (errData && errData.detail) {
            errorDetail = typeof errData.detail === 'string' ? errData.detail : JSON.stringify(errData.detail);
          }
        } catch {
          // Response body was not JSON
        }
        throw new Error(errorDetail);
      }

      return (await response.json()) as T;
    } catch (err: unknown) {
      if (err instanceof TypeError && err.message.includes('Failed to fetch')) {
        throw new Error(
          `Unable to connect to AnnaRakshak API at ${this.baseUrl || 'current origin'}. Make sure the FastAPI server is running (.venv/bin/python api.py).`
        );
      }
      throw err;
    }
  }

  // -------------------------------------------------------------------------
  // Health
  // -------------------------------------------------------------------------

  async getHealth(): Promise<{ status: string; database: string; total_products: number; version: string }> {
    return this.request('/api/health');
  }

  // -------------------------------------------------------------------------
  // Dashboard & Metrics
  // -------------------------------------------------------------------------

  async getDashboardSummary(): Promise<DashboardSummary> {
    const settings = await this.getSettings();
    const alertWindow = settings.alertWindow || 7;

    // Fetch dashboard stats, alerts, products, and recent scans in parallel
    const [dash, alerts, allProducts, recentScans] = await Promise.all([
      this.request<BackendDashboard>(`/api/dashboard?warning_days=${alertWindow}`),
      this.request<BackendAlert[]>(`/api/alerts?warning_days=${alertWindow}`).catch(() => []),
      this.getProducts(),
      this.getScanHistory(),
    ]);

    // Format category distribution
    const categoryCounts: { name: Category; count: number }[] = categories.map((catName) => {
      const matchCount = allProducts.filter((p) => p.category === catName).length;
      return { name: catName, count: matchCount };
    });

    // Determine expiring items (alert window)
    const expiringItems = allProducts
      .filter((p) => {
        const stat = productStatus(p, alertWindow);
        return ['Expires Today', 'Expiring Soon', 'Best Before Today', 'Best Before Soon', 'Expired', 'Best Before Passed'].includes(
          stat
        );
      })
      .sort((a, b) => daysFromToday(a.date) - daysFromToday(b.date));

    // Scans needing review
    const reviewScans = recentScans.filter((s) => s.reviewStatus === 'Needs Review');

    // Local waste calculations
    const wasteJournal = await this.getWasteJournal();
    const currentMonth = relativeDate(0).slice(0, 7);
    const monthWaste = wasteJournal.filter((w) => w.date.startsWith(currentMonth));
    const wasteThisMonth = monthWaste.reduce((total, w) => total + w.value, 0);

    const verifiedCount = allProducts.filter(
      (p) => p.verified && isExactDate(p.date) && ['Expiry', 'Use By'].includes(p.dateType)
    ).length;

    const inventoryValue = allProducts.reduce((sum, p) => sum + (p.price || 0), 0);
    const pricedCount = allProducts.filter((p) => p.price && p.price > 0).length;

    return {
      total: dash.total_products,
      verified: verifiedCount,
      expired: dash.expired_count,
      today: alerts.filter((a) => a.days_remaining === 0).length,
      soon: dash.expiring_soon_count + dash.best_before_soon_count,
      review: dash.needs_review_count,
      expiring: expiringItems,
      reviewScans,
      recent: recentScans.slice(0, 5),
      categories: categoryCounts,
      inventoryValue,
      pricedCount,
      wasteThisMonth,
      wasteEntries: monthWaste.length,
    };
  }

  // -------------------------------------------------------------------------
  // Products
  // -------------------------------------------------------------------------

  async getProducts(): Promise<Product[]> {
    const rawList = await this.request<BackendProduct[]>('/api/products');
    return rawList.map((bp) => this.mapBackendProduct(bp));
  }

  async getProductById(id: string): Promise<Product> {
    const numericId = parseId(id);
    const bp = await this.request<BackendProduct>(`/api/products/${numericId}`);
    return this.mapBackendProduct(bp);
  }

  async createProduct(data: ProductInput): Promise<Product> {
    const payload = {
      product_name: data.name.trim(),
      brand: data.brand?.trim() || null,
      food_category: toBackendCategory(data.category),
      date_type: toBackendDateType(data.dateType),
      normalized_date: data.date && isExactDate(data.date) ? data.date : null,
      date_status: data.verified ? 'confirmed' : 'unverified',
      date_source: data.verified ? 'user_confirmed' : 'manual',
      notes: data.notes?.trim() || null,
      force: true, // Allow user-driven additions from UI
    };

    const bp = await this.request<BackendProduct>('/api/products', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    return this.mapBackendProduct(bp);
  }

  async updateProduct(id: string, data: ProductInput): Promise<Product> {
    const numericId = parseId(id);
    const payload = {
      product_name: data.name.trim(),
      brand: data.brand?.trim() || null,
      food_category: toBackendCategory(data.category),
      date_type: toBackendDateType(data.dateType),
      normalized_date: data.date && isExactDate(data.date) ? data.date : null,
      notes: data.notes?.trim() || null,
    };

    const bp = await this.request<BackendProduct>(`/api/products/${numericId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
    return this.mapBackendProduct(bp);
  }

  async deleteProduct(id: string): Promise<void> {
    const numericId = parseId(id);
    await this.request<{ success: boolean; deleted_id: number }>(`/api/products/${numericId}`, {
      method: 'DELETE',
    });
  }

  // -------------------------------------------------------------------------
  // Scans & Review
  // -------------------------------------------------------------------------

  async getScanHistory(): Promise<ScanRecord[]> {
    const rawList = await this.request<BackendScan[]>('/api/scans?limit=50');
    return rawList.map((bs) => this.mapBackendScan(bs));
  }

  async getScanById(id: string): Promise<ScanRecord> {
    const numericId = parseId(id);
    const bs = await this.request<BackendScan>(`/api/scans/${numericId}`);
    return this.mapBackendScan(bs);
  }

  async getDateCandidates(scanId: string): Promise<DateCandidate[]> {
    const numericId = parseId(scanId);
    const rawCandidates = await this.request<BackendDateCandidate[]>(`/api/scans/${numericId}/date-candidates`);
    return rawCandidates.map((c) => this.mapBackendCandidate(c));
  }

  async reanalyzeScan(id: string): Promise<ScanRecord> {
    const numericId = parseId(id);
    const updated = await this.request<BackendScan>(`/api/scans/${numericId}/reanalyze`, {
      method: 'POST',
    });
    return this.mapBackendScan(updated);
  }

  async startScan(image?: string): Promise<ScanRecord> {
    if (!image) {
      throw new Error('Please capture or select an image to scan.');
    }

    const formData = new FormData();
    if (image.startsWith('data:')) {
      const [header, base64] = image.split(',');
      const mime = header.match(/:(.*?);/)?.[1] || 'image/jpeg';
      const binary = atob(base64);
      const array = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        array[i] = binary.charCodeAt(i);
      }
      const blob = new Blob([array], { type: mime });
      formData.append('image', blob, 'scan_capture.jpg');
    } else {
      formData.append('image', image);
    }

    const url = this.baseUrl ? `${this.baseUrl}/api/scans` : '/api/scans';
    const response = await fetch(url, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      let errorDetail = `Scanning failed with status ${response.status}`;
      try {
        const errData = await response.json();
        if (errData && errData.detail) {
          errorDetail = typeof errData.detail === 'string' ? errData.detail : JSON.stringify(errData.detail);
        }
      } catch {
        // Not JSON
      }
      throw new Error(errorDetail);
    }

    const createdScan = (await response.json()) as BackendScan;
    return this.mapBackendScan(createdScan);
  }

  async simulateAnalysisFailure(id: string): Promise<ScanRecord> {
    const scan = await this.getScanById(id);
    return {
      ...scan,
      analysisStatus: 'Failed',
      reason: 'Analysis could not extract readable date evidence.',
      candidates: [],
    };
  }

  async confirmDate(scanId: string, candidateId: string): Promise<Product> {
    const scan = await this.getScanById(scanId);
    const cand = scan.candidates.find((c) => c.id === candidateId);
    if (!cand || cand.precision !== 'day' || !isExactDate(cand.date)) {
      throw new Error('This evidence has no exact date. Enter a full date from the package, or leave it in review.');
    }

    return this.createProduct({
      name: scan.name,
      brand: scan.brand,
      category: scan.category,
      quantity: '',
      date: cand.date,
      dateType: cand.dateType,
      notes: `Original evidence: ${cand.printedText}`,
      verified: true,
    });
  }

  async correctScan(scanId: string, data: ProductInput): Promise<Product> {
    if (!data.verified) {
      throw new Error('Explicit date confirmation is required.');
    }
    return this.createProduct(data);
  }

  // -------------------------------------------------------------------------
  // Waste Journal & Settings (Client Persistence)
  // -------------------------------------------------------------------------

  async getWasteJournal(): Promise<WasteEntry[]> {
    try {
      const raw = localStorage.getItem('annarakshak_waste');
      if (raw) return JSON.parse(raw);
    } catch {
      // LocalStorage not available or parse failed
    }
    return [];
  }

  async addWasteEntry(data: WasteInput): Promise<WasteEntry> {
    if (!data.name.trim()) throw new Error('Enter what was wasted.');
    if (!isExactDate(data.date)) throw new Error('Enter a valid date.');
    if (!(data.value >= 0)) throw new Error('Enter a value of 0 or more.');

    const entry: WasteEntry = {
      ...data,
      name: data.name.trim(),
      id: `WJ-${Date.now()}`,
    };
    const current = await this.getWasteJournal();
    current.unshift(entry);
    try {
      localStorage.setItem('annarakshak_waste', JSON.stringify(current));
    } catch {
      // Ignore
    }
    return entry;
  }

  async deleteWasteEntry(id: string): Promise<void> {
    const current = await this.getWasteJournal();
    const filtered = current.filter((w) => w.id !== id);
    try {
      localStorage.setItem('annarakshak_waste', JSON.stringify(filtered));
    } catch {
      // Ignore
    }
  }

  async getSettings(): Promise<Settings> {
    try {
      const raw = localStorage.getItem('annarakshak_settings');
      if (raw) return JSON.parse(raw);
    } catch {
      // Ignore
    }
    return { alertWindow: 7, compact: false, dateFormat: 'short' };
  }

  async updateSettings(data: Settings): Promise<Settings> {
    if (data.alertWindow < 1 || data.alertWindow > 30) {
      throw new Error('Choose between 1 and 30 days.');
    }
    try {
      localStorage.setItem('annarakshak_settings', JSON.stringify(data));
    } catch {
      // Ignore
    }
    return data;
  }

  // -------------------------------------------------------------------------
  // Private Object Mappers
  // -------------------------------------------------------------------------

  private mapBackendProduct(bp: BackendProduct): Product {
    const cat = toFrontendCategory(bp.food_category);
    return {
      id: `PR-${bp.id}`,
      name: bp.product_name,
      brand: bp.brand || '',
      category: cat,
      quantity: '',
      date: bp.normalized_date || '',
      dateType: toFrontendDateType(bp.date_type),
      notes: bp.notes || '',
      verified: bp.date_status === 'confirmed',
      image: categorySvg(cat),
      scanId: bp.date_candidates?.[0]?.scan_id ? `SC-${bp.date_candidates[0].scan_id}` : undefined,
    };
  }

  private mapBackendScan(bs: BackendScan): ScanRecord {
    const cat = toFrontendCategory(bs.food_category);
    const candidates = (bs.date_candidates || []).map((c) => this.mapBackendCandidate(c));

    let reviewStatus: 'Needs Review' | 'Confirmed' = bs.needs_review ? 'Needs Review' : 'Confirmed';
    let analysisStatus: 'Successful' | 'Failed' | 'Analyzing' = bs.analysis_status === 'error' ? 'Failed' : 'Successful';

    return {
      id: `SC-${bs.id}`,
      timestamp: bs.timestamp,
      image: bs.image_path
        ? (typeof process !== 'undefined' && process.env?.FASTAPI_URL && this.baseUrl === process.env.FASTAPI_URL
            ? `/api/scans/${bs.id}/image`
            : this.baseUrl
            ? `${this.baseUrl}/api/scans/${bs.id}/image`
            : `/api/scans/${bs.id}/image`)
        : categorySvg(cat),
      name: bs.product_name || 'Unidentified Item',
      brand: bs.brand || '',
      category: cat,
      analysisStatus,
      reviewStatus,
      reason: bs.review_reason || bs.error_message || undefined,
      candidates,
    };
  }

  private mapBackendCandidate(c: BackendDateCandidate): DateCandidate {
    const isIsoDay = c.normalized_date && isExactDate(c.normalized_date);
    return {
      id: String(c.id || Math.random()),
      printedText: c.raw_text,
      date: c.normalized_date || c.raw_text,
      dateType: toFrontendDateType(c.date_type),
      precision: isIsoDay ? 'day' : 'month',
      confidence: c.confidence,
      reason: c.evidence,
    };
  }
}
