<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

- Keep AnnaRakshak UI under src/features/annarakshak and data types, local-calendar rules, and mock operations under src/services; this keeps the frontend independent of the future Python adapter.
- Use the FoodSafetyService interface behind a central apiConfig and explicitly demo-only adapter; a configured URL alone must never imply live analysis or persistence.
- Use TanStack Query for shared service reads and invalidate queries after changes so inventory, review counts, history, and dashboard remain synchronized.
- Use dedicated file routes for all main navigation destinations and shared app chrome in the root route so deep links remain usable.
- App chrome is a top navigation bar in AppShell (primary links plus a 'Scans & more' menu); keeps every route reachable without a sidebar.
