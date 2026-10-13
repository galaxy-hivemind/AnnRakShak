# FreshTrack Hub

Build AnnaRakshak — Smart Food Safety & Expiry Management

Build a polished, responsive web application called AnnaRakshak, a smart food-safety and expiry-management system. It helps households, students living in hostels, and small kitchens track packaged products, identify expiry dates, monitor upcoming expirations, and review uncertain packaging information.

This is the frontend for an existing Python project. The existing backend already uses OpenCV, Apple Vision OCR on macOS, Google's Gemini API, and SQLite for product inventory and scan history.

Your task is to build the user interface first, without replacing or pretending to implement the existing backend.

1. Technology and constraints

React, TypeScript, Tailwind CSS, and reusable UI components.

Use a clean component-based architecture.

Build a working frontend prototype using realistic mock data.

Keep all mock data and mock operations inside a clearly separated service/adapter layer so they can later be replaced with real API calls.

Do not use Supabase, Firebase, a new database, or paid external services.

Do not expose API keys in frontend code.

Do not claim that scanning, OCR, Gemini analysis, or database persistence works until a real backend is connected.

Do not build an authentication system in this phase.

All major navigation links, buttons, search, filters, forms, and dialogs should work in the prototype.

2. Design direction

Create a premium, modern food-safety product, not a generic admin dashboard.

Visual identity:

Product name: AnnaRakshak.

Meaning: protection of food.

Primary palette: deep forest green, fresh sage, warm ivory, and restrained amber/red for meaningful warnings.

Use generous whitespace, rounded cards, subtle borders, refined typography, and simple line icons.

Use green for healthy or safe-to-track states, amber for upcoming dates or review-required items, and red for past-expiry warnings.

Use colors alongside text labels and icons so status is never communicated by color alone.

Use tasteful transitions and clear hover/focus states.

Avoid excessive gradients, glassmorphism, giant hero sections, unnecessary charts, and overly decorative animations.

The interface should feel trustworthy, practical, accessible, and production-ready.

Make the desktop experience excellent while ensuring it adapts well to tablet and mobile screens.

3. Application layout

Create a persistent sidebar on desktop with:

AnnaRakshak logo and wordmark.

Dashboard.

My Inventory.

Scan Product.

Scan History.

Needs Review.

Settings.

Show a compact navigation layout on smaller screens.

The top bar should contain the current page title, a useful search action where appropriate, and a notification/attention indicator.

4. Dashboard

Create a useful operational dashboard with:

Total tracked products.

Products with verified expiry dates.

Expired products.

Products expiring today.

Products expiring within seven days.

Products needing date verification.

Include:

A prominent "Scan Product" action.

An "Expiring Soon" list with product name, brand, expiry date, and remaining days.

A "Needs Review" section for uncertain or incomplete date information.

Recent scan activity.

A compact inventory category summary.

Use realistic sample data. Make it visually clear which metrics are derived from confirmed dates and which refer to unverified scans.

Do not display a fabricated claim that any food is safe to consume.

5. My Inventory

Create a searchable inventory page with:

Table view on desktop and well-designed cards on mobile.

Product thumbnail, name, brand, category, quantity if available, date type, date, and status.

Search by product name or brand.

Filters for category and date status.

Sorting by product name, expiry date, and status.

A product detail panel or page.

Actions to view, edit, and delete a product, with confirmation before deletion.

A manual "Add Product" form.

The manual form should support product name, brand, category, quantity, date, date type, and notes. Validate required fields and dates.

Support date types such as Expiry, Use By, Best Before, Manufacturing, and Packed On. Keep these types distinct.

6. Scan Product

Design a dedicated scanning workspace.

Include:

A large camera preview area.

A clear "Start Scan" action.

A capture-state indicator: Ready, Capturing, Analyzing, Analysis Failed, or Complete.

A captured-image preview.

A product analysis panel showing detected name, brand, category, and date candidates.

Date evidence showing the original printed text and the interpreted date type.

Confidence or review indicators only when provided by the analysis result.

"Confirm Details", "Edit Details", "Retry Analysis", and "Cancel" actions as appropriate.

For the initial prototype, simulate the scanning workflow using mock data and a sample image or image-upload control. Clearly label simulated analysis as demo behavior.

Do not pretend that the browser camera is already connected to the Python scanner. Do not call a nonexistent API. Structure this page so a real backend can be connected later.

If multiple date candidates exist, let the user select a candidate and review its evidence. Require explicit confirmation before adding an uncertain date to confirmed inventory.

7. Scan History

Build a scan-history page with:

Scan ID.

Timestamp.

Captured image thumbnail.

Detected product name where available.

Analysis status.

Review status.

Date candidates count.

Actions to view details and retry analysis.

Include filters for successful, failed, and review-required scans.

A scan-history record must be allowed to exist without a confirmed inventory product.

8. Needs Review

Build a dedicated review queue for records with:

Missing dates.

Ambiguous date formats.

Multiple possible dates.

Month/year-only dates.

Failed analysis.

Conflicting date evidence.

Show the original evidence alongside the proposed interpretation.

Allow a user to correct or confirm details explicitly. Do not silently infer an exact day from a month/year-only date. Keep the original OCR or model evidence visible where available.

9. Date-status rules

Implement these rules in the mock-data layer where needed:

A verified explicit expiry/use-by date before today is "Expired".

A verified expiry/use-by date today is "Expires Today".

A verified expiry/use-by date within the next seven days is "Expiring Soon".

Later expiry dates are "Upcoming".

Best Before dates use separate labels: "Best Before Passed", "Best Before Today", "Best Before Soon", and "Best Before Future".

Missing, ambiguous, or unverified dates are "Needs Review" or "Unknown".

Manufacturing and Packed On dates must never be classified as expiry dates.

A successful AI analysis does not automatically mean the date is user-confirmed.

Never display an unverified date as a confirmed expiry date.

Make date calculations use local calendar dates consistently.

10. Settings

Build a simple settings page for:

Upcoming-alert window, default seven days.

Display preferences.

A description of the scanning workflow.

A privacy notice explaining that actual data persistence and API behavior will be provided by the connected backend.

Do not implement fake notification permissions or claim that real reminders are running.

11. Architecture for future backend integration

Create a clean service layer with typed interfaces for:

getDashboardSummary()

getProducts()

getProductById(id)

createProduct(data)

updateProduct(id, data)

deleteProduct(id)

getScanHistory()

getScanById(id)

startScan()

reanalyzeScan(id)

getDateCandidates(scanId)

confirmDate(scanId, candidateId)

For now, these methods may use local mock data. Keep the UI independent of the mock implementation.

Use a central API configuration so the service layer can later communicate with a Python FastAPI backend through an environment variable such as VITE_API_BASE_URL.

Define appropriate TypeScript types for products, date candidates, scan records, dashboard metrics, and API errors.

Do not hardcode sample data inside individual UI components.

12. Deliverable

Deliver a cohesive, navigable frontend prototype with:

All main pages implemented.

Consistent visual design.

Responsive layouts.

Functional search, filtering, sorting, forms, and dialogs.

Realistic sample data.

Clearly separated mock services.

Loading, empty, and error states.

No broken navigation or nonfunctional primary buttons.

Prioritize a high-quality, polished user experience. Do not add unrelated features. Keep the project ready for later integration with the existing AnnaRakshak Python backend.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/b873e305-ada3-53a4-9dda-3c1e3ea89dda).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
