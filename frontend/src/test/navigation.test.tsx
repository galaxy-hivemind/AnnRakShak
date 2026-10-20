import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  createRouter,
  createRoute,
  createRootRoute,
  createMemoryHistory,
  RouterProvider,
  Outlet,
} from '@tanstack/react-router';
import { AppShell, PageHero } from '@/features/annarakshak/common';
import { Dashboard } from '@/features/annarakshak/dashboard';
import { Inventory } from '@/features/annarakshak/inventory';
import { service } from '@/services/api';
import type { Product, ScanRecord, Settings as AppSettings, DashboardSummary } from '@/services/types';

vi.mock('@/services/api', () => ({
  service: {
    getProducts: vi.fn(),
    getScans: vi.fn(),
    getScanHistory: vi.fn(),
    getSettings: vi.fn(),
    getDashboardSummary: vi.fn(),
    getWasteJournal: vi.fn(),
    addWasteEntry: vi.fn(),
    deleteWasteEntry: vi.fn(),
    addProduct: vi.fn(),
    updateProduct: vi.fn(),
    deleteProduct: vi.fn(),
  },
  settingsQuery: {
    queryKey: ['settings'],
    queryFn: () => service.getSettings(),
  },
  scansQuery: {
    queryKey: ['scans'],
    queryFn: () => service.getScanHistory(),
  },
  dashboardQuery: {
    queryKey: ['dashboard'],
    queryFn: () => service.getDashboardSummary(),
  },
  productsQuery: {
    queryKey: ['products'],
    queryFn: () => service.getProducts(),
  },
  wasteQuery: {
    queryKey: ['waste'],
    queryFn: () => service.getWasteJournal(),
  },
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const mockProducts: Product[] = [
  {
    id: 'P-1',
    name: 'Fresh Milk',
    brand: 'Amul',
    category: 'Dairy & Eggs',
    quantity: '1 L',
    date: '2026-10-25',
    dateType: 'Expiry',
    verified: true,
  },
];

const mockScans: ScanRecord[] = [
  {
    id: 'SC-1',
    timestamp: '2026-10-20T00:00:00Z',
    name: 'Cheddar Cheese',
    brand: 'Britannia',
    category: 'Dairy & Eggs',
    quantity: '200 g',
    analysisStatus: 'Successful',
    reviewStatus: 'Needs Review',
    candidates: [],
  },
];

const mockSettings: AppSettings = {
  alertWindow: 3,
  compact: false,
};

const mockDashboard: DashboardSummary = {
  totalItems: 1,
  expiringCount: 1,
  reviewCount: 1,
  recentWaste: 0,
  expiring: mockProducts,
  categories: [{ name: 'Dairy & Eggs', count: 1 }],
  recentActivity: [],
};

describe('UI Discoverability & Navigation Enhancement', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    vi.clearAllMocks();
    vi.mocked(service.getProducts).mockResolvedValue(mockProducts);
    vi.mocked(service.getScans).mockResolvedValue(mockScans);
    vi.mocked(service.getScanHistory).mockResolvedValue(mockScans);
    vi.mocked(service.getSettings).mockResolvedValue(mockSettings);
    vi.mocked(service.getDashboardSummary).mockResolvedValue(mockDashboard);
    vi.mocked(service.getWasteJournal).mockResolvedValue([]);
  });

  function setupRouter(initialPath: string = '/') {
    const memoryHistory = createMemoryHistory({ initialEntries: [initialPath] });

    const rootRoute = createRootRoute({
      component: () => (
        <AppShell>
          <Outlet />
        </AppShell>
      ),
    });

    const indexRoute = createRoute({
      getParentRoute: () => rootRoute,
      path: '/',
      component: () => <Dashboard />,
    });

    const inventoryRoute = createRoute({
      getParentRoute: () => rootRoute,
      path: '/inventory',
      component: () => <Inventory />,
    });

    const scanRoute = createRoute({
      getParentRoute: () => rootRoute,
      path: '/scan',
      component: () => <div data-testid="scan-page">Scanner Page</div>,
    });

    const historyRoute = createRoute({
      getParentRoute: () => rootRoute,
      path: '/history',
      component: () => <div data-testid="history-page">Scanned History Page</div>,
    });

    const reviewRoute = createRoute({
      getParentRoute: () => rootRoute,
      path: '/review',
      component: () => <div data-testid="review-page">Needs Review Page</div>,
    });

    const settingsRoute = createRoute({
      getParentRoute: () => rootRoute,
      path: '/settings',
      component: () => <div data-testid="settings-page">Settings Page</div>,
    });

    const timelineRoute = createRoute({
      getParentRoute: () => rootRoute,
      path: '/timeline',
      component: () => <div>Timeline</div>,
    });

    const wasteRoute = createRoute({
      getParentRoute: () => rootRoute,
      path: '/waste',
      component: () => <div>Waste</div>,
    });

    const routeTree = rootRoute.addChildren([
      indexRoute,
      inventoryRoute,
      scanRoute,
      historyRoute,
      reviewRoute,
      settingsRoute,
      timelineRoute,
      wasteRoute,
    ]);

    const router = createRouter({
      routeTree,
      history: memoryHistory,
      context: { queryClient },
    });

    return { router, memoryHistory };
  }

  describe('Top Navigation: Scan Icon and Settings Dropdown', () => {
    it('renders the scan icon in top navigation linking directly to /scan without opening a dropdown', async () => {
      const { router, memoryHistory } = setupRouter('/');
      render(
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      );

      const scanBtn = await screen.findByRole('link', { name: /scan ingredients/i });
      expect(scanBtn).toBeInTheDocument();
      expect(scanBtn).toHaveAttribute('href', '/scan');

      // It must contain an svg (ScanLine)
      const svg = scanBtn.querySelector('svg');
      expect(svg).toBeInTheDocument();

      // Clicking it navigates directly to /scan and does NOT open any dropdown
      fireEvent.click(scanBtn);
      await waitFor(() => {
        expect(memoryHistory.location.pathname).toBe('/scan');
      });

      // No dropdown menu should be opened
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });

    it('renders the settings icon with no text label beside it', async () => {
      const { router } = setupRouter('/');
      render(
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      );

      const settingsTrigger = await screen.findByRole('button', { name: /open settings menu/i });
      expect(settingsTrigger).toBeInTheDocument();

      // Must display only the gear icon; no text label inside or beside it
      expect(settingsTrigger.textContent?.trim()).toBe('');
      expect(settingsTrigger.querySelector('svg')).toBeInTheDocument();
    });

    it('opens the settings dropdown with exactly three entries in order: Scanned History, Needs Review, Settings', async () => {
      const { router, memoryHistory } = setupRouter('/');
      render(
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      );

      const settingsTrigger = await screen.findByRole('button', { name: /open settings menu/i });
      fireEvent.keyDown(settingsTrigger, { key: 'ArrowDown', code: 'ArrowDown' });

      // Verify dropdown menu opens
      const menuItems = await screen.findAllByRole('menuitem');
      expect(menuItems).toHaveLength(3);

      // Verify exact names and order
      expect(menuItems[0]).toHaveTextContent(/scanned history/i);
      expect(menuItems[1]).toHaveTextContent(/needs review/i);
      expect(menuItems[2]).toHaveTextContent(/settings/i);

      // Verify each entry has the correct link destination
      expect(menuItems[0].getAttribute('href')).toBe('/history');
      expect(menuItems[1].getAttribute('href')).toBe('/review');
      expect(menuItems[2].getAttribute('href')).toBe('/settings');

      // Click the first entry (Scanned History) and verify navigation
      fireEvent.click(menuItems[0]);
      await waitFor(() => {
        expect(memoryHistory.location.pathname).toBe('/history');
      });
    });

    it('navigates to /review when Needs Review dropdown entry is clicked', async () => {
      const { router, memoryHistory } = setupRouter('/');
      render(
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      );

      const settingsTrigger = await screen.findByRole('button', { name: /open settings menu/i });
      fireEvent.keyDown(settingsTrigger, { key: 'ArrowDown', code: 'ArrowDown' });

      const reviewItem = await screen.findByRole('menuitem', { name: /needs review/i });
      fireEvent.click(reviewItem);

      await waitFor(() => {
        expect(memoryHistory.location.pathname).toBe('/review');
      });
    });

    it('navigates to /settings when Settings dropdown entry is clicked', async () => {
      const { router, memoryHistory } = setupRouter('/');
      render(
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      );

      const settingsTrigger = await screen.findByRole('button', { name: /open settings menu/i });
      fireEvent.keyDown(settingsTrigger, { key: 'ArrowDown', code: 'ArrowDown' });

      const settingsItem = await screen.findByRole('menuitem', { name: /^settings$/i });
      fireEvent.click(settingsItem);

      await waitFor(() => {
        expect(memoryHistory.location.pathname).toBe('/settings');
      });
    });
  });

  describe('Homepage: Add Ingredients Button', () => {
    it('displays the scan icon to the left of "Add Ingredients" and navigates directly to /scan', async () => {
      const { router, memoryHistory } = setupRouter('/');
      render(
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      );

      const addBtn = await screen.findByRole('link', { name: /add ingredients/i });
      expect(addBtn).toBeInTheDocument();
      expect(addBtn).toHaveAttribute('href', '/scan');
      expect(addBtn).toHaveClass('add-btn');

      // Verify scan icon is present inside the button
      const svg = addBtn.querySelector('svg');
      expect(svg).toBeInTheDocument();

      // Verify the icon appears before the text
      const buttonHtml = addBtn.innerHTML;
      const svgIndex = buttonHtml.indexOf('<svg');
      const textIndex = buttonHtml.indexOf('Add Ingredients');
      expect(svgIndex).toBeGreaterThanOrEqual(0);
      expect(textIndex).toBeGreaterThan(svgIndex);

      // Clicking navigates directly to /scan without intermediate dialog
      fireEvent.click(addBtn);
      await waitFor(() => {
        expect(memoryHistory.location.pathname).toBe('/scan');
      });

      // No modal dialog opened
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  describe('Inventory Page: Add Ingredients Button', () => {
    it('displays the same scan icon to the left of "Add Ingredients" and navigates to /scan', async () => {
      const { router, memoryHistory } = setupRouter('/inventory');
      render(
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      );

      const addBtn = await screen.findByRole('link', { name: /add ingredients/i });
      expect(addBtn).toBeInTheDocument();
      expect(addBtn).toHaveAttribute('href', '/scan');
      expect(addBtn).toHaveClass('add-btn');

      // Verify scan icon is present inside the button and precedes the text
      const svg = addBtn.querySelector('svg');
      expect(svg).toBeInTheDocument();
      const buttonHtml = addBtn.innerHTML;
      const svgIndex = buttonHtml.indexOf('<svg');
      const textIndex = buttonHtml.indexOf('Add Ingredients');
      expect(svgIndex).toBeGreaterThanOrEqual(0);
      expect(textIndex).toBeGreaterThan(svgIndex);

      // Clicking navigates directly to /scan without dialog
      fireEvent.click(addBtn);
      await waitFor(() => {
        expect(memoryHistory.location.pathname).toBe('/scan');
      });

      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('preserves existing manual addition behavior on the inventory page', async () => {
      const { router } = setupRouter('/inventory');
      render(
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      );

      const manualBtn = await screen.findByRole('button', { name: /add manually/i });
      expect(manualBtn).toBeInTheDocument();

      // Clicking opens the manual addition dialog
      fireEvent.click(manualBtn);
      expect(await screen.findByRole('dialog')).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: /add product/i })).toBeInTheDocument();
    });
  });
});
