export const dateTypes = ['Expiry', 'Use By', 'Best Before', 'Manufacturing', 'Packed On'] as const;
export type DateType = typeof dateTypes[number];
export const categories = ['Dairy & Eggs', 'Grains & Cereals', 'Snacks', 'Beverages', 'Pantry Staples', 'Fresh Produce'] as const;
export type Category = typeof categories[number];
export type ProductStatus = 'Expired' | 'Expires Today' | 'Expiring Soon' | 'Upcoming' | 'Best Before Passed' | 'Best Before Today' | 'Best Before Soon' | 'Best Before Future' | 'Needs Review' | 'Unknown' | 'Manufactured' | 'Packed';
export interface ProductInput { name: string; brand: string; category: Category; quantity: string; date: string; dateType: DateType; notes: string; verified: boolean; }
export interface Product extends ProductInput { id: string; image: string; scanId?: string; storage?: 'Fridge' | 'Freezer' | 'Pantry' | 'Counter'; price?: number; produce?: 'Vegetable' | 'Fruit'; }
export interface WasteEntry { id: string; name: string; quantity: string; value: number; reason: string; date: string; }
export interface WasteInput { name: string; quantity: string; value: number; reason: string; date: string; }
export interface DateCandidate { id: string; printedText: string; date: string; dateType: DateType; precision: 'day' | 'month' | 'unknown'; reason?: string; confidence?: number; isCalculated?: boolean; source?: 'printed' | 'calculated' | 'manual'; calculatedFrom?: string; }
export interface ScanRecord { id: string; timestamp: string; image: string; name: string; brand: string; category: Category | ''; quantity?: string; analysisStatus: 'Successful' | 'Failed' | 'Analyzing'; reviewStatus: 'Needs Review' | 'Confirmed'; reason?: string; candidates: DateCandidate[]; productId?: string; autoSaved?: boolean; confidenceScore?: number; decisionReason?: string; supplementaryImages?: string[]; }
export interface DashboardSummary { total: number; verified: number; expired: number; today: number; soon: number; review: number; expiring: Product[]; reviewScans: ScanRecord[]; recent: ScanRecord[]; categories: { name: Category; count: number }[]; inventoryValue: number; pricedCount: number; wasteThisMonth: number; wasteEntries: number; }
export interface ApiError { code: string; message: string; }
export interface Settings { alertWindow: number; compact: boolean; dateFormat: 'short' | 'long'; }
export interface FoodSafetyService {
 getDashboardSummary(): Promise<DashboardSummary>;
 getProducts(): Promise<Product[]>;
 getProductById(id: string): Promise<Product>;
 createProduct(data: ProductInput): Promise<Product>;
 updateProduct(id: string, data: ProductInput): Promise<Product>;
 deleteProduct(id: string): Promise<void>;
 getScanHistory(): Promise<ScanRecord[]>;
 getScanById(id: string): Promise<ScanRecord>;
 deleteScan(id: string): Promise<void>;
 startScan(image?: string): Promise<ScanRecord>;
 addSupplementaryImage?(
   scanId: string,
   image: string,
   overrides?: {
     name?: string;
     brand?: string;
     category?: Category | '';
     quantity?: string;
   }
 ): Promise<ScanRecord>;
 reanalyzeScan(id: string): Promise<ScanRecord>;
 simulateAnalysisFailure(id: string): Promise<ScanRecord>;
 getDateCandidates(scanId: string): Promise<DateCandidate[]>;
 confirmDate(
   scanId: string,
   candidateIdOrIds: string | string[],
   overrides?: {
     name?: string;
     brand?: string;
     category?: Category | '';
     quantity?: string;
     candidates?: DateCandidate[];
     notes?: string;
   }
 ): Promise<Product>;
 correctScan(scanId: string, data: ProductInput): Promise<Product>;
 getWasteJournal(): Promise<WasteEntry[]>;
 addWasteEntry(data: WasteInput): Promise<WasteEntry>;
 deleteWasteEntry(id: string): Promise<void>;
 getSettings(): Promise<Settings>;
 updateSettings(data: Settings): Promise<Settings>;
}
