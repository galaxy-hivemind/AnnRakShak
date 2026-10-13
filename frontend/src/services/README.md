# AnnaRakshak service boundary

The prototype deliberately uses an in-memory mock adapter. No browser camera, OCR, Gemini, Python API, database, authentication, or notifications are connected. Data and image previews reset on refresh.

- `types.ts`: domain types and the `FoodSafetyService` contract.
- `dates.ts`: local calendar parsing, validation, and date-type-specific status rules.
- `mock.ts`: all sample inventory, scan history, preferences, and mock operations.
- `api.ts`: the central adapter selection, `VITE_API_BASE_URL`, and TanStack Query read definitions.

To connect the existing Python project, implement `FoodSafetyService` in a separate HTTP adapter, explicitly select it in `api.ts`, and map actual responses to the domain types. Setting `VITE_API_BASE_URL` alone does not enable live mode. Keep secrets, OCR, analysis, and SQLite inside Python. Preserve independent scan records, original evidence, date precision, and explicit user confirmation. The `simulateAnalysisFailure` operation is demo-only and should not call a live endpoint.

Production capture integration should replace demo capture timing with the actual scanner state. Uploaded images currently show previews while the adapter returns clearly labeled sample analysis unrelated to image content.
