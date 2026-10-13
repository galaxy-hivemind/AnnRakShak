# AnnaRakshak — REST HTTP API Documentation

AnnaRakshak Phase 8 provides a local FastAPI backend connecting the existing SQLite persistence layer (`annarakshak.db`), date classification engine, and Gemini packaging reanalysis to the Lovable frontend.

---

## 1. Starting the Server

The server runs on `http://127.0.0.1:8000` by default.

### Development Start Command

```bash
# Using Python directly
.venv/bin/python api.py

# Or via Uvicorn CLI
.venv/bin/uvicorn api:app --host 127.0.0.1 --port 8000
```

### Environment Configuration

Configure optional parameters in `.env`:

```ini
# Frontend origins allowed by CORS (comma-separated, default: localhost:5173, localhost:3000, 127.0.0.1:5173, 127.0.0.1:3000)
FRONTEND_ORIGINS=http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173

# API host and port (default: 127.0.0.1:8000)
API_HOST=127.0.0.1
API_PORT=8000

# SQLite database path (default: annarakshak.db in project root)
ANNARAKSHAK_DB_PATH=annarakshak.db
```

### Interactive Documentation

- **Swagger UI:** `http://127.0.0.1:8000/docs`
- **ReDoc:** `http://127.0.0.1:8000/redoc`

---

## 2. Core Architecture & Guardrails

1. **100% Local**: Uses the local SQLite database (`annarakshak.db`) in WAL mode.
2. **Zero Silent Conversions**:
   - Manufacturing (`manufacturing`, `packed_on`) dates are **never** treated as expiry dates.
   - Best-before (`best_before`) quality dates are classified under distinct statuses (`best_before_passed`, `best_before_soon`, `best_before_future`) separate from explicit expiry (`expired`, `expiring_soon`, `not_expiring_soon`).
3. **No Camera on HTTP**: Camera preview and scanning remain local; the HTTP API exposes scan history and safe reanalysis.
4. **Secret Isolation**: Gemini API keys and system paths are never exposed in responses or stack traces.
5. **CORS**: Configured narrowly for authorized frontend development ports (`localhost:5173`, etc.).

---

## 3. Endpoints Reference

### System & Health

#### `GET /api/health`
Check service health and database connectivity.

**Response (200 OK):**
```json
{
  "status": "ok",
  "database": "connected",
  "total_products": 12,
  "version": "1.0.0"
}
```

---

### Dashboard & Analytics

#### `GET /api/dashboard`
Aggregated inventory metrics for the dashboard view.

**Query Parameters:**
- `warning_days` *(int, optional, default: 7)*: Threshold for "soon" flags.

**Response (200 OK):**
```json
{
  "total_products": 12,
  "expired_count": 2,
  "expiring_soon_count": 3,
  "best_before_soon_count": 1,
  "best_before_passed_count": 0,
  "safe_count": 5,
  "needs_review_count": 1,
  "total_scans": 24,
  "recent_scans_count": 5,
  "categories": {
    "Dairy": 4,
    "Bakery": 3,
    "Snacks": 5
  }
}
```

---

### Alerts

#### `GET /api/alerts`
Prioritized list of inventory items requiring attention (critical, warning, and info).

**Query Parameters:**
- `warning_days` *(int, optional, default: 7)*: Threshold in days.

**Response (200 OK):**
```json
[
  {
    "product_id": 4,
    "product_name": "Fresh Milk",
    "brand": "Amul",
    "food_category": "Dairy",
    "date_type": "expiry",
    "normalized_date": "2026-10-10",
    "date_status": "expired",
    "urgency": "critical",
    "message": "Expired 2 day(s) ago (2026-10-10)",
    "days_remaining": -2
  },
  {
    "product_id": 8,
    "product_name": "Whole Wheat Bread",
    "brand": "Modern",
    "food_category": "Bakery",
    "date_type": "use_by",
    "normalized_date": "2026-10-14",
    "date_status": "expiring_soon",
    "urgency": "warning",
    "message": "Expires in 2 day(s) (2026-10-14)",
    "days_remaining": 2
  },
  {
    "product_id": 11,
    "product_name": "Organic Honey",
    "brand": "Dabur",
    "food_category": "Condiments",
    "date_type": "unknown",
    "normalized_date": null,
    "date_status": "needs_review",
    "urgency": "info",
    "message": "Date unconfirmed or missing; manual review required",
    "days_remaining": null
  }
]
```

---

### Products

#### `GET /api/products`
List inventory products with filtering and sorting.

**Query Parameters:**
- `status` *(string, optional)*: Filter by stored status (`confirmed`, `unverified`) or live status (`expired`, `expiring_soon`, `safe`, `needs_review`).
- `search` *(string, optional)*: Search substring across name, brand, category, notes.
- `category` *(string, optional)*: Filter by food category.
- `sort_by` *(string, optional, default: `date`)*: `date`, `name`, or `id`.

**Response (200 OK):**
```json
[
  {
    "id": 1,
    "product_name": "Amul Taaza Milk",
    "brand": "Amul",
    "food_category": "Dairy",
    "date_type": "expiry",
    "date_text": "EXP 20/10/2026",
    "normalized_date": "2026-10-20",
    "date_status": "confirmed",
    "current_status": "expiring_soon",
    "date_source": "printed",
    "analysis_status": "success",
    "image_path": null,
    "notes": "Kept in door shelf",
    "created_at": "2026-10-12T12:00:00+00:00",
    "updated_at": "2026-10-12T12:00:00+00:00",
    "date_candidates": []
  }
]
```

#### `GET /api/products/{product_id}`
Retrieve a single product with any associated candidate date evidence.

**Response (200 OK):**
```json
{
  "id": 1,
  "product_name": "Amul Taaza Milk",
  "brand": "Amul",
  "food_category": "Dairy",
  "date_type": "expiry",
  "date_text": "EXP 20/10/2026",
  "normalized_date": "2026-10-20",
  "date_status": "confirmed",
  "current_status": "expiring_soon",
  "date_source": "printed",
  "analysis_status": "success",
  "image_path": null,
  "notes": null,
  "created_at": "2026-10-12T12:00:00+00:00",
  "updated_at": "2026-10-12T12:00:00+00:00",
  "date_candidates": [
    {
      "id": 10,
      "product_id": 1,
      "scan_id": 3,
      "raw_text": "EXP 20/10/2026",
      "date_type": "expiry",
      "normalized_date": "2026-10-20",
      "confidence": 0.98,
      "evidence": "Top spout printed ink",
      "created_at": "2026-10-12T12:00:00+00:00"
    }
  ]
}
```

**Errors:**
- `404 Not Found` if `product_id` does not exist.

#### `POST /api/products`
Add a new product to inventory.

**Request Body:**
```json
{
  "product_name": "Amul Butter 500g",
  "brand": "Amul",
  "food_category": "Dairy",
  "date_type": "best_before",
  "date_text": "BB 15/12/2026",
  "normalized_date": "2026-12-15",
  "date_status": "confirmed",
  "date_source": "manual",
  "notes": "Main refrigerator",
  "force": false
}
```

**Validation & Duplicate Protection:**
- `product_name`: Required, non-empty.
- `normalized_date`: Must be valid ISO `YYYY-MM-DD` or null.
- `date_type`: One of `expiry`, `use_by`, `best_before`, `manufacturing`, `packed_on`, `unknown`.
- If an item with the same name, brand, and date exists and `force=false`: returns **`409 Conflict`** with `"existing_id"` in the response. Set `"force": true` to add anyway.

**Response (201 Created):** Returns the created `ProductResponse`.

#### `PATCH /api/products/{product_id}`
Update fields or confirm/correct dates for an existing product.

**Request Body:**
```json
{
  "product_name": "Amul Butter Salted 500g",
  "brand": "Amul",
  "food_category": "Dairy",
  "normalized_date": "2026-12-20",
  "date_type": "best_before",
  "notes": "Confirmed by user after checking wrapper"
}
```

**Behavior:**
- Updates name, brand, category, notes, or image path.
- If `normalized_date` or `date_type` is provided, automatically marks `date_status="confirmed"` and `date_source="user_confirmed"`.

**Response (200 OK):** Returns the updated `ProductResponse`.

**Errors:**
- `404 Not Found` if product does not exist.
- `422 Unprocessable Entity` for invalid date strings or empty names.

#### `DELETE /api/products/{product_id}`
Delete a product from inventory.

**Response (200 OK):**
```json
{
  "success": true,
  "message": "Product 1 successfully deleted.",
  "deleted_id": 1
}
```

**Preservation Guarantee:** Deleting a product removes its inventory record and cascades only product-tied candidates; scan history records in `scan_history` and scan-level date candidates are **never** deleted.

---

### Scans & Reanalysis

#### `POST /api/scans`
Process a newly captured or uploaded packaging image with OCR and Gemini AI.

**Request:**
- `multipart/form-data` with file field `image` (JPEG, PNG, WebP; max 15 MB)
- OR `application/json` with `{"image": "data:image/jpeg;base64,..."}`

**Behavior:**
1. Validates image decodability and payload size.
2. Saves original frame to `captures/`.
3. Runs local Apple Vision OCR and asynchronous Gemini multi-modal packaging analysis.
4. Records scan history and extracted candidate dates into SQLite.

**Response (201 Created):** Returns `ScanResponse` containing detected product name, brand, category, review requirements, and date candidates.

**Errors:**
- `400 Bad Request` if image is missing, empty, or unreadable.
- `413 Request Entity Too Large` if image exceeds 15 MB.

#### `GET /api/scans/{scan_id}/image`
Retrieve the original packaging capture file for a scan.

**Response (200 OK):** Binary image file (`image/jpeg`, `image/png`, or `image/webp`).

**Errors:**
- `404 Not Found` if scan ID or image file does not exist.

#### `GET /api/scans`
List captured scan history.

**Query Parameters:**
- `limit` *(int, optional, default: 20, max: 100)*: Maximum scan records to fetch.

**Response (200 OK):**
```json
[
  {
    "id": 5,
    "timestamp": "2026-10-12T12:30:00+00:00",
    "image_path": "captures/scan_20261012_123000.jpg",
    "product_name": "Greek Yogurt",
    "brand": "Epigamia",
    "food_category": "Dairy",
    "analysis_status": "success",
    "needs_review": false,
    "review_reason": null,
    "selected_expiry_date": "2026-10-25",
    "error_message": null,
    "raw_json": null,
    "date_candidates": []
  }
]
```

#### `GET /api/scans/{scan_id}`
Retrieve a specific scan record and its date candidates.

**Response (200 OK):**
```json
{
  "id": 5,
  "timestamp": "2026-10-12T12:30:00+00:00",
  "image_path": "captures/scan_20261012_123000.jpg",
  "product_name": "Greek Yogurt",
  "brand": "Epigamia",
  "food_category": "Dairy",
  "analysis_status": "success",
  "needs_review": false,
  "review_reason": null,
  "selected_expiry_date": "2026-10-25",
  "error_message": null,
  "raw_json": null,
  "date_candidates": [
    {
      "id": 12,
      "product_id": null,
      "scan_id": 5,
      "raw_text": "USE BY 25/10/26",
      "date_type": "use_by",
      "normalized_date": "2026-10-25",
      "confidence": 0.99,
      "evidence": "Foil lid print",
      "created_at": "2026-10-12T12:30:00+00:00"
    }
  ]
}
```

#### `GET /api/scans/{scan_id}/date-candidates`
Retrieve only the candidate date evidence for a specific scan.

**Response (200 OK):**
```json
[
  {
    "id": 12,
    "product_id": null,
    "scan_id": 5,
    "raw_text": "USE BY 25/10/26",
    "date_type": "use_by",
    "normalized_date": "2026-10-25",
    "confidence": 0.99,
    "evidence": "Foil lid print",
    "created_at": "2026-10-12T12:30:00+00:00"
  }
]
```

#### `POST /api/scans/{scan_id}/reanalyze`
Re-runs Gemini packaging analysis on the saved image capture asynchronously.

- Offloads analysis to a background worker thread (`asyncio.to_thread`), preventing event-loop blocks.
- Updates the existing scan record and refreshes date candidates in place.
- Does not create duplicate scans.

**Response (200 OK):** Returns the updated `ScanResponse`.

**Errors:**
- `404 Not Found` if `scan_id` does not exist.
- `400 Bad Request` if the image file was moved or deleted from disk.

---

## 4. Frontend Integration Adapter (Lovable / TypeScript)

Lovable React/TypeScript applications can integrate using this typed client:

```typescript
// src/services/api.ts

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api';

export interface Product {
  id: number;
  product_name: string;
  brand: string | null;
  food_category: string | null;
  date_type: 'expiry' | 'use_by' | 'best_before' | 'manufacturing' | 'packed_on' | 'unknown';
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
}

export interface DashboardStats {
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

export interface AlertItem {
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

export const api = {
  getHealth: () => fetch(`${API_BASE_URL}/health`).then(r => r.json()),
  getDashboard: () => fetch(`${API_BASE_URL}/dashboard`).then(r => r.json()),
  getAlerts: () => fetch(`${API_BASE_URL}/alerts`).then(r => r.json()),
  getProducts: (params?: { search?: string; status?: string; category?: string }) => {
    const q = new URLSearchParams(params as Record<string, string>).toString();
    return fetch(`${API_BASE_URL}/products?${q}`).then(r => r.json());
  },
  getProduct: (id: number) => fetch(`${API_BASE_URL}/products/${id}`).then(r => r.json()),
  createProduct: (data: Partial<Product> & { force?: boolean }) =>
    fetch(`${API_BASE_URL}/products`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(async r => {
      if (!r.ok) {
        const err = await r.json();
        throw err;
      }
      return r.json();
    }),
  updateProduct: (id: number, data: Partial<Product>) =>
    fetch(`${API_BASE_URL}/products/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(r => r.json()),
  deleteProduct: (id: number) =>
    fetch(`${API_BASE_URL}/products/${id}`, { method: 'DELETE' }).then(r => r.json()),
  getScans: (limit = 20) => fetch(`${API_BASE_URL}/scans?limit=${limit}`).then(r => r.json()),
  reanalyzeScan: (scanId: number) =>
    fetch(`${API_BASE_URL}/scans/${scanId}/reanalyze`, { method: 'POST' }).then(r => r.json()),
};
```
