# AnnaRakshak

**Hands-free, voice-guided food inventory and expiry-tracking for households.**

---

## Project Overview

AnnaRakshak uses a webcam and Gemini vision to scan food packages, read expiry dates, and maintain a spoken inventory — so you never have to touch a keyboard while cooking or unpacking groceries.> **Current phase:** Step 6A — SQLite Inventory Persistence (`annarakshak.db` + `inventory.py` CLI).  
> Using the **built-in MacBook Air FaceTime camera** (index 0) or external webcam.  
> Native Apple Vision OCR verifies visible text on packages before authorizing capture.  
> Google Gemini Flash analyzes captured frames for structured food identification and strict expiry date interpretation.  
> All scans and products are safely persisted locally in `annarakshak.db` without cloud dependencies or auto-confirming unverified dates.

---

## Architecture: Integrated Scanning & Gemini Analysis Pipeline

```
[ Camera Stream @ 30+ FPS ]
             │
             ├──► [ Async OCR Worker @ ~4 Hz ] (Apple Vision)
             │           │
             │           ▼
             │   [ Text Consistency Gate ] (3 checks, drift <= 15%)
             │           │
             │     Qualifying Text Verified?
             │           │
             │          YES
             │           ▼
             │   [ Capture 1 Clean Image ] ──► Saved to captures/<ts>_auto.jpg
             │           │
             ▼           ▼
      [ Live Preview ] [ Async Gemini Worker (Bounded Queue = 1) ]
      (Silky smooth)     │
                         ▼
                 [ Google GenAI SDK ]
                 • Model: gemini-3.8-flash (configurable)
                 • Zero-hallucination prompt
                 • Pydantic response schema: FoodAnalysisResult
                         │
                         ▼
                 [ Strict Date Interpretation & Post-Validation ]
                 • Never treat MFG / packed dates as expiry
                 • No inferred days for month/year-only dates
                 • Ambiguous / multiple dates -> needs_review=True
                         │
                         ├─────────────────────────┐
                         ▼                         ▼
                 [ Camera Preview HUD ]    [ Terminal Output ]
                 • Real-time status:       • Formatted JSON
                   - IMAGE CAPTURED        • Complete candidates list
                   - ANALYZING WITH GEMINI • Evidence & confidence
                   - PRODUCT IDENTIFIED
                   - EXPIRY DATE FOUND
                   - NEEDS MANUAL REVIEW
                   - GEMINI REQUEST FAILED
```

---

## 1. Secure Gemini API Configuration

AnnaRakshak uses Google's official `google-genai` Python SDK. The API key is loaded securely from the environment using `python-dotenv` and is never logged, printed, or committed to version control.

### Setup Steps:

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and add your Google Gemini API key:
   ```bash
   GEMINI_API_KEY=your_actual_gemini_api_key_here
   GEMINI_MODEL=gemini-3.8-flash
   ```
   *(Get your API key at [Google AI Studio](https://aistudio.google.com/)).*
3. Verify `.env` is ignored by git:
   ```bash
   git status --ignored
   # .env is listed under Ignored files (.gitignore)
   ```

> [!IMPORTANT]
> Never hardcode, commit, or print the `GEMINI_API_KEY`. If `.env` is missing, the scanner and analyzer run gracefully in offline/mock mode without crashing.

---

## 2. Gemini Analysis Module (`gemini_analyzer.py`)

A dedicated, mockable module providing:
- **Image Validation:** Checks path existence, regular file status, zero-byte detection, and supported extensions (`.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`).
- **Structured Schema:** Uses Pydantic (`FoodAnalysisResult` & `DateCandidate`) with strict typed fields:
  - `product_name`: Identifiable product name, or null.
  - `brand`: Brand name, or null.
  - `food_category`: Category (e.g. Dairy, Bakery, Beverage, Snacks), or null.
  - `date_candidates`: Printed dates with `raw_text`, `date_type` (`expiry`, `use_by`, `best_before`, `manufacturing`, `packed_on`, `unknown`), `normalized_date` (`YYYY-MM-DD` or null), `confidence`, and `evidence`.
  - `selected_expiry_date`: ISO `YYYY-MM-DD` only when supported by clear expiry evidence.
  - `analysis_status`: `success`, `needs_review`, `unreadable`, `not_a_food_product`, `error`.
  - `needs_review`: Boolean flag.
  - `review_reason`: Concise explanation.
- **Strict Date Rules:**
  - Zero hallucinations — evidence grounded strictly in visible image text.
  - Manufacturing/packed dates are NEVER accepted as expiry dates.
  - Month/year-only dates (e.g. `OCT 2026`) do NOT infer arbitrary days (`normalized_date=None`, `needs_review=True`).
  - Conflicting multiple expiry dates trigger `needs_review=True`.
- **Bounded Concurrency (`AsyncGeminiWorker`):** Uses a single-slot queue to prevent backlog buildup and guarantee 30+ FPS preview performance.
- **Dependency Injection:** Supports mock client injection for unit tests without network calls.

---

## 3. Manual Testing Mode (Offline / Single Image)

Analyze any saved image directly from the command line without opening the camera:

```bash
source .venv/bin/activate
python gemini_analyzer.py --image captures/<path_to_image>.jpg
```

Optional model override:
```bash
python gemini_analyzer.py --image captures/<path_to_image>.jpg --model gemini-3.8-flash
```

Outputs formatted JSON and a human-readable summary:
```
=================================================================
AnnaRakshak — Gemini Food Packaging Analysis
=================================================================
Target Image : captures/sample.jpg
Gemini Model : gemini-3.8-flash
API Key Set  : True
-----------------------------------------------------------------

Response received in 1.42s:

{
  "product_name": "Organic Whole Milk 1L",
  "brand": "Horizon Organic",
  "food_category": "Dairy",
  "date_candidates": [
    {
      "raw_text": "USE BY 15 NOV 2026",
      "date_type": "use_by",
      "normalized_date": "2026-11-15",
      "confidence": 0.98,
      "evidence": "Printed near carton spout"
    }
  ],
  "selected_expiry_date": "2026-11-15",
  "analysis_status": "success",
  "needs_review": false,
  "review_reason": null
}

=================================================================
HUMAN READABLE SUMMARY:
-----------------------------------------------------------------
Product Name : Organic Whole Milk 1L
Brand        : Horizon Organic
Category     : Dairy
Status       : SUCCESS
Needs Review : False
Expiry Date  : 2026-11-15
Date Count   : 1 candidate(s) found
  [1] 'USE BY 15 NOV 2026' -> Type: use_by, Norm: 2026-11-15, Conf: 0.98
      Evidence: Printed near carton spout
=================================================================
```

---

## 4. Running the Integrated Scanner

Launch the automatic scanner with Apple Vision text verification and background Gemini analysis:

```bash
source .venv/bin/activate
python auto_scan.py
```

### Launch Options:

```bash
# Start directly without pressing [c] to arm:
python auto_scan.py --skip-calib

# Configure capture stability duration (default: 2.5s continuous stability):
python auto_scan.py --capture-stability-seconds 2.5

# Target external USB webcam (index 1):
python auto_scan.py --index 1

# Disable Gemini analysis (runs offline OCR trigger only):
python auto_scan.py --no-gemini

# Override Gemini model:
python auto_scan.py --gemini-model gemini-3.5-flash-lite
```

### Preview Window Controls:
- `c` — Arm scanner (transitions to `SEARCHING FOR TEXT`).
- `r` — Reset scanner back to `UNCALIBRATED`.
- `s` — Save snapshot and submit to Gemini.
- `q` — Quit and cleanly release camera, OCR, and Gemini workers.

### Stability Gate & HUD Feedback:
- Requires **2.5 seconds** (configurable via `--capture-stability-seconds`) of continuous qualifying text stability.
- If the package moves beyond the drift tolerance (15%) or text disappears, the timer immediately resets.
- Live HUD renders a real-time countdown progress bar:
  `HOLD STEADY TO CAPTURE... 1.8s / 2.5s (72%)`
- Clean un-annotated camera frames are captured and passed to Gemini in the background without blocking the 30+ FPS preview stream.

---

---

## 5. SQLite Local Inventory Persistence (`inventory_db.py`)

All food records and scan attempts are safely stored in a local SQLite database:

`annarakshak.db` (auto-created at project root, excluded from git).

### Database Schema

1. **`products` Table:**
   - `id`: Unique integer primary key.
   - `product_name`: Identified product name (required).
   - `brand`: Brand name (nullable).
   - `food_category`: Category e.g. Dairy, Bakery (nullable).
   - `date_type`: Preserved date type (`expiry`, `use_by`, `best_before`, `manufacturing`, `packed_on`, `unknown`).
   - `date_text`: Raw printed date text from package.
   - `normalized_date`: Strict ISO `YYYY-MM-DD` date (nullable).
   - `date_status`: User verification state (`confirmed`, `unverified`, `needs_review`).
   - `date_source`: Source of the date (`printed`, `user_confirmed`).
   - `analysis_status`: Gemini analysis outcome.
   - `image_path`: Path to local captured image (stored locally in `captures/`, no image blobs).
   - `notes`: User notes.
   - `created_at` / `updated_at`: ISO 8601 UTC timestamps.

2. **`date_candidates` Table:**
   - Preserves all detected candidate dates from labels to prevent discarding evidence.
   - Foreign keys to `products` (cascade on delete) and `scan_history`.

3. **`scan_history` Table:**
   - Audit trail of every scan attempt including image path, timestamps, Gemini output, error messages, and review reasons.
   - Prevents duplicate scans from silently overwriting existing records.

---

## 6. Inventory CLI (`inventory.py`)

Manage and inspect your inventory directly from the command line:

```bash
# List all inventory products
python inventory.py list

# Filter inventory by status (unverified, expiring, expired, all)
python inventory.py list --filter expiring
python inventory.py list --filter unverified

# Search by product name, brand, or category
python inventory.py search "milk"

# Show detailed information for a product (including candidate dates & image path)
python inventory.py show 1

# Confirm or correct a product's date
python inventory.py confirm-date 1 2026-10-25 --date-type expiry

# Manually add a product
python inventory.py add "Organic Whole Milk" --brand "Amul" --date 2026-10-20 --date-type expiry

# Promote a captured scan into inventory (displays all candidate dates interactively):
python inventory.py add-scan 3

# Promote a scan and explicitly select candidate date #2:
python inventory.py add-scan 3 --candidate 2

# Promote a scan with a user-confirmed date override:
python inventory.py add-scan 3 --date 2028-03-31 --date-type expiry

# Edit an existing product
python inventory.py edit 1 --name "Full Cream Milk" --notes "Kept in top fridge shelf"

# Delete a product (prompts confirmation unless --force is supplied)
python inventory.py delete 1

# View recent scan history
python inventory.py scans --limit 10
```

---

## 7. Date Safeguards & Status Calculation

AnnaRakshak applies deterministic, safe food safety rules:

- **Missing or Unverified Dates:** Classified as `unknown`. Never assumed safe.
- **Expiry / Use-by Dates (`expiry`, `use_by`):**
  - `expired`: date < today
  - `expires_today`: date == today
  - `expiring_soon`: today < date <= today + 7 days (inclusive warning threshold)
  - `not_expiring_soon`: date > today + 7 days
- **Best-Before Dates (`best_before`):**
  - Kept distinct from safety expiry dates: `best_before_passed`, `best_before_today`, `best_before_soon`, `best_before_future`.
- **Manufacturing & Packing Dates (`manufacturing`, `packed_on`):**
  - Classified as `not_an_expiry_date`. Never treated as expiry.
- **Shelf-Life Wording:**
  - Preserved in notes/raw text without synthetic calculation.
- **Duplicate Protection:**
  - Prevents accidental duplicate entries when scanning the same item multiple times. Adding duplicates requires explicit confirmation (`--force`).

---

## 8. Backup & Recovery Guidance

Because AnnaRakshak uses standard SQLite with Write-Ahead Logging (WAL):

- **Database File:** `annarakshak.db`
- **Captured Images:** `captures/` folder

### Creating a Backup:
```bash
# Using sqlite3 backup API (safe even while scanner is running)
sqlite3 annarakshak.db ".backup 'backups/annarakshak_backup_$(date +%Y%m%d).db'"

# Backup captured image references alongside DB
cp -r captures/ backups/captures_backup_$(date +%Y%m%d)/
```

### Restoring from Backup:
```bash
cp backups/annarakshak_backup_20261011.db annarakshak.db
```

---

## 9. Running the Test Suite

The test suite runs **99 automated tests** across all project layers in ~1.4s with **zero external network access and no API key required**:

```bash
source .venv/bin/activate
python test_auto_scan.py
```

Or run test suites independently:
```bash
# Capture stability & date flow regression tests (13 tests):
python test_stability_and_dates.py

# SQLite inventory persistence tests (27 tests):
python test_inventory.py

# Gemini analyzer unit tests (19 tests):
python test_gemini_analyzer.py
```

### Test Coverage (99 Tests, 100% Passing):
- ✅ **Step 2 (11 tests):** Standalone frame-to-frame stability and motion thresholds.
- ✅ **Step 3 (9 tests):** Two-stage foreground gate and background calibration.
- ✅ **Step 4 (20 tests):** Text-verified trigger, shadow rejection, Apple Vision OCR, drift stability, rearming.
- ✅ **Step 5 (19 tests):** Gemini analyzer, structured output, schema validation, zero-hallucination date rules, error handling, worker queues.
- ✅ **Step 6A (27 tests):**
  - SQLite schema creation, idempotency, foreign keys, and indexes.
  - Adding, retrieving, listing, searching, editing, and deleting products.
  - Deterministic date status calculations across boundary conditions.
  - Distinct `best_before` quality classification.
  - Strict rejection of manufacturing/packing dates as expiry.
  - Strict validation of ISO dates and rejection of malformed/impossible dates.
  - Scan history and date candidate persistence.
  - Verification safety: unreviewed scans remain unconfirmed until explicit confirmation.
  - Duplicate product detection and `--force` confirmation guard.
  - Persistence across separate SQLite connections.
  - Full CLI test coverage (`list`, `search`, `show`, `add`, `confirm-date`, `delete`).
- ✅ **Part A & B Regression (13 tests):**
  - 2.5s continuous stability gate enforcement.
  - Stability timer reset on motion drift or text disappearance.
  - Zero premature captures before 2.5s threshold.
  - Single capture guard (no duplicate triggers for same presentation).
  - Scanner rearming upon package removal.
  - Complete end-to-end survival of all date candidates in DB and CLI.
  - Interactive candidate selection and user-confirmed overrides during `add-scan`.
  - Re-analysis of saved images without duplicate scan records.

---

## Roadmap

- [x] Camera foundation (`camera_test.py`)
- [x] Steady-frame motion detection (`auto_scan.py` — Step 2)
- [x] Two-stage foreground trigger & background calibration (`auto_scan.py` — Step 3)
- [x] Apple Vision text-verified trigger (`auto_scan.py` & `ocr_engine.py` — Step 4)
- [x] Gemini vision integration — product identification + expiry date extraction (`gemini_analyzer.py` — Step 5)
- [x] Local SQLite inventory persistence & CLI (`inventory_db.py`, `inventory.py` — Step 6A)
- [ ] Voice guidance (spoken feedback via macOS `say` or TTS — Step 6B)
- [ ] Expiry dashboard with urgency indicators
- [ ] Unpackaged food tracking (produce, dairy, bakery)

---

*AnnaRakshak (अन्नरक्षक) — Guardian of Food.*
