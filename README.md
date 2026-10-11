# AnnaRakshak

**Hands-free, voice-guided food inventory and expiry-tracking for households.**

---

## Project Overview

AnnaRakshak uses a webcam and Gemini vision to scan food packages, read expiry dates, and maintain a spoken inventory — so you never have to touch a keyboard while cooking or unpacking groceries.> **Current phase:** Step 5 — Gemini Vision Integration (`google-genai` SDK + Structured Output).  
> Using the **built-in MacBook Air FaceTime camera** (index 0) or external webcam (e.g. Logitech C505e).  
> Native Apple Vision OCR verifies visible text on packages before authorizing capture.  
> Google Gemini 2.5 Flash (`google-genai` SDK) analyzes captured frames for structured food identification and strict expiry date interpretation.

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

# Target external USB webcam (index 1):
python auto_scan.py --index 1

# Disable Gemini analysis (runs offline OCR trigger only):
python auto_scan.py --no-gemini

# Override Gemini model:
python auto_scan.py --gemini-model gemini-3.8-flash
```

### Preview Window Controls:
- `c` — Arm scanner (transitions to `SEARCHING FOR TEXT`).
- `r` — Reset scanner back to `UNCALIBRATED`.
- `s` — Save snapshot and submit to Gemini.
- `q` — Quit and cleanly release camera, OCR, and Gemini workers.

---

## 5. Running the Test Suite

The test suite runs **59 automated tests** across all project layers in ~0.8s with **zero external network access and no API key required**:

```bash
source .venv/bin/activate
python test_auto_scan.py
```

Or run the Gemini analyzer unit tests independently:
```bash
python test_gemini_analyzer.py
```

### Test Coverage (59 Tests, 100% Passing):
- ✅ **Step 2 (11 tests):** Standalone frame-to-frame stability and motion thresholds.
- ✅ **Step 3 (9 tests):** Two-stage foreground gate and background calibration.
- ✅ **Step 4 (20 tests):** Text-verified trigger, shadow rejection, Apple Vision OCR, drift stability, rearming.
- ✅ **Step 5 (19 tests):**
  - Image file validation (missing, directories, unsupported extensions, 0 bytes).
  - Missing API key graceful handling.
  - Structured output parsing and JSON fallback.
  - Distinguishing manufacturing/packing dates from expiry dates (zero false expiry dates).
  - Rejection of inferred days for month/year-only dates.
  - Ambiguous / conflicting multiple dates handling (`needs_review=True`).
  - Unreadable labels & non-food items classification.
  - Malformed API responses & invalid JSON handling.
  - Rate limit (429) & timeout error handling.
  - `AsyncGeminiWorker` non-blocking lifecycle and single-slot bounded queue.
  - Scanner engine state machine resilience upon Gemini failure.

---

## Roadmap

- [x] Camera foundation (`camera_test.py`)
- [x] Steady-frame motion detection (`auto_scan.py` — Step 2)
- [x] Two-stage foreground trigger & background calibration (`auto_scan.py` — Step 3)
- [x] Apple Vision text-verified trigger (`auto_scan.py` & `ocr_engine.py` — Step 4)
- [x] Gemini vision integration — product identification + expiry date extraction (`gemini_analyzer.py` — Step 5)
- [ ] Voice guidance (spoken feedback via macOS `say` or TTS)
- [ ] Inventory storage (SQLite or JSON)
- [ ] Expiry dashboard with urgency indicators
- [ ] Unpackaged food tracking (produce, dairy, bakery)

---

*AnnaRakshak (अन्नरक्षक) — Guardian of Food.*
