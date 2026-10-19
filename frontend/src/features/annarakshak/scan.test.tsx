import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Scan } from './scan';
import { service } from '@/services/api';
import type { ScanRecord, Product } from '@/services/types';

vi.mock('@/services/api', () => ({
  service: {
    startScan: vi.fn(),
    deleteScan: vi.fn(),
    confirmDate: vi.fn(),
    getScanById: vi.fn(),
    reanalyzeScan: vi.fn(),
    correctScan: vi.fn(),
    addSupplementaryImage: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

describe('Scan Page Completion & Persistence Flow', () => {
  let queryClient: QueryClient;

  const mockProduct: Product = {
    id: 'P-123',
    name: 'Fresh Whole Milk',
    brand: 'Amul',
    category: 'Dairy & Eggs',
    quantity: '1 L',
    date: '2026-10-25',
    dateType: 'Expiry',
    notes: 'Verified packaging',
    verified: true,
    image: '/test-product.jpg',
    scanId: 'SC-200',
  };

  const mockConfirmedScan: ScanRecord = {
    id: 'SC-200',
    timestamp: '2026-10-18T00:00:00Z',
    image: '/test-product.jpg',
    name: 'Fresh Whole Milk',
    brand: 'Amul',
    category: 'Dairy & Eggs',
    quantity: '1 L',
    analysisStatus: 'Successful',
    reviewStatus: 'Confirmed',
    productId: 'P-123',
    candidates: [
      {
        id: 'c-exp',
        printedText: 'USE BY 25/10/2026',
        date: '2026-10-25',
        dateType: 'Expiry',
        precision: 'day',
        confidence: 0.99,
        source: 'printed',
      },
    ],
  };

  const mockUnconfirmedScan: ScanRecord = {
    id: 'SC-200',
    timestamp: '2026-10-18T00:00:00Z',
    image: '/test-product.jpg',
    name: 'Fresh Whole Milk',
    brand: 'Amul',
    category: 'Dairy & Eggs',
    quantity: '1 L',
    analysisStatus: 'Successful',
    reviewStatus: 'Needs Review',
    reason: 'Please verify printed date',
    candidates: [
      {
        id: 'c-exp',
        printedText: 'USE BY 25/10/2026',
        date: '2026-10-25',
        dateType: 'Expiry',
        precision: 'day',
        confidence: 0.99,
        source: 'printed',
      },
    ],
  };

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    vi.clearAllMocks();
  });

  const renderScan = () => {
    return render(
      <QueryClientProvider client={queryClient}>
        <Scan />
      </QueryClientProvider>
    );
  };

  it('renders initial ready state without false completed state', () => {
    renderScan();
    expect(screen.getByText('Ready to scan')).toBeInTheDocument();
    expect(screen.queryByText(/Scan completed/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Product saved to inventory/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /View in Inventory/i })).not.toBeInTheDocument();
  });

  it('handles scan analysis failure gracefully without showing completed state', async () => {
    vi.mocked(service.startScan).mockRejectedValueOnce(new Error('Network error: server unreachable'));

    renderScan();

    const fileInput = screen.getByLabelText('Upload packaging image');
    const file = new File(['fake-bytes'], 'package.jpg', { type: 'image/jpeg' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(/Network error: server unreachable/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/Analysis failed · Check photo or retry/i)).toBeInTheDocument();
    expect(screen.queryByText(/Scan completed · Product saved to inventory/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /View in Inventory/i })).not.toBeInTheDocument();
  });

  it('displays review UI on successful scan analysis without premature completed state', async () => {
    vi.mocked(service.startScan).mockResolvedValueOnce(mockUnconfirmedScan);

    renderScan();

    const fileInput = screen.getByLabelText('Upload packaging image');
    const file = new File(['fake-bytes'], 'package.jpg', { type: 'image/jpeg' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Fresh Whole Milk')).toBeInTheDocument();
    });

    // Before user confirms review, should say Evidence extracted, NOT scan completed
    expect(screen.getByText(/Evidence extracted · Review details below/i)).toBeInTheDocument();
    expect(screen.queryByText(/Scan completed · Product saved to inventory/i)).not.toBeInTheDocument();

    // Completed actions must NOT be present yet
    expect(screen.queryByRole('button', { name: /Delete Scan/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /New Scan/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /View in Inventory/i })).not.toBeInTheDocument();
  });

  it('Scenario 10: Completed scan screen displays exactly Delete Scan and New Scan, and NO View in Inventory', async () => {
    vi.mocked(service.startScan).mockResolvedValueOnce(mockUnconfirmedScan);
    vi.mocked(service.confirmDate).mockResolvedValueOnce(mockProduct);
    vi.mocked(service.getScanById).mockResolvedValueOnce(mockConfirmedScan);

    renderScan();

    // 1. Upload file to trigger scan
    const fileInput = screen.getByLabelText('Upload packaging image');
    fireEvent.change(fileInput, { target: { files: [new File(['fake-bytes'], 'pkg.jpg', { type: 'image/jpeg' })] } });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Fresh Whole Milk')).toBeInTheDocument();
    });

    // 2. Check "Verified on package" for candidate
    fireEvent.click(screen.getByRole('checkbox', { name: /Expiry date/i }));

    // 3. Check overall confirmation checkbox
    const overallCheckbox = screen.getByRole('checkbox', {
      name: /I have checked the printed evidence and confirm this exact date and date type/i,
    });
    fireEvent.click(overallCheckbox);

    // 4. Click Confirm Details button
    const confirmBtn = screen.getByRole('button', { name: /Confirm Details/i });
    fireEvent.click(confirmBtn);

    // 5. Verification of completed state
    await waitFor(() => {
      expect(screen.getByText(/Scan completed · Product saved to inventory/i)).toBeInTheDocument();
    });

    // Verify actions container exists
    const completedActions = document.getElementById('completed-scan-actions');
    expect(completedActions).toBeInTheDocument();

    // Verify exactly two buttons inside completed actions: Delete Scan and New Scan
    const deleteBtn = screen.getByRole('button', { name: /Delete Scan/i });
    const newScanBtn = screen.getByRole('button', { name: /New Scan/i });
    expect(deleteBtn).toBeInTheDocument();
    expect(newScanBtn).toBeInTheDocument();

    // CRITICAL: Ensure NO "View in Inventory" button is displayed anywhere
    expect(screen.queryByRole('button', { name: /View in Inventory/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/View in Inventory/i)).not.toBeInTheDocument();
  });

  it('Scenario 7: Delete Scan asks for confirmation, calls service.deleteScan, and resets to start screen', async () => {
    vi.mocked(service.startScan).mockResolvedValueOnce(mockUnconfirmedScan);
    vi.mocked(service.confirmDate).mockResolvedValueOnce(mockProduct);
    vi.mocked(service.getScanById).mockResolvedValueOnce(mockConfirmedScan);
    vi.mocked(service.deleteScan).mockResolvedValueOnce(undefined);

    renderScan();

    const fileInput = screen.getByLabelText('Upload packaging image');
    fireEvent.change(fileInput, { target: { files: [new File(['fake-bytes'], 'pkg.jpg', { type: 'image/jpeg' })] } });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Fresh Whole Milk')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('checkbox', { name: /Expiry date/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /I have checked the printed evidence/i }));
    fireEvent.click(screen.getByRole('button', { name: /Confirm Details/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Delete Scan/i })).toBeInTheDocument();
    });

    // Click "Delete Scan" to open confirmation dialog
    fireEvent.click(screen.getByRole('button', { name: /Delete Scan/i }));

    // Confirmation dialog should be visible
    expect(screen.getByText('Delete this scan?')).toBeInTheDocument();
    expect(
      screen.getByText(/Are you sure you want to delete this scan and its saved product/i)
    ).toBeInTheDocument();

    // Click "Confirm Delete"
    const confirmDeleteBtn = screen.getByRole('button', { name: /Confirm Delete/i });
    fireEvent.click(confirmDeleteBtn);

    await waitFor(() => {
      expect(service.deleteScan).toHaveBeenCalledWith('SC-200');
    });

    // Screen should return to clean ready state
    await waitFor(() => {
      expect(screen.getByText('Ready to scan')).toBeInTheDocument();
      expect(screen.queryByDisplayValue('Fresh Whole Milk')).not.toBeInTheDocument();
    });
  });

  it('Scenario 7 (failure): Delete Scan failure displays actionable error without leaving broken state', async () => {
    vi.mocked(service.startScan).mockResolvedValueOnce(mockUnconfirmedScan);
    vi.mocked(service.confirmDate).mockResolvedValueOnce(mockProduct);
    vi.mocked(service.getScanById).mockResolvedValueOnce(mockConfirmedScan);
    vi.mocked(service.deleteScan).mockRejectedValueOnce(new Error('Database lock error during scan deletion'));

    renderScan();

    const fileInput = screen.getByLabelText('Upload packaging image');
    fireEvent.change(fileInput, { target: { files: [new File(['fake-bytes'], 'pkg.jpg', { type: 'image/jpeg' })] } });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Fresh Whole Milk')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('checkbox', { name: /Expiry date/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /I have checked the printed evidence/i }));
    fireEvent.click(screen.getByRole('button', { name: /Confirm Details/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Delete Scan/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /Delete Scan/i }));
    fireEvent.click(screen.getByRole('button', { name: /Confirm Delete/i }));

    await waitFor(() => {
      expect(screen.getByText('Database lock error during scan deletion')).toBeInTheDocument();
    });

    // Delete Scan button is still available to retry
    expect(screen.getByRole('button', { name: /Delete Scan/i })).toBeInTheDocument();
  });

  it('Scenario 8: New Scan resets scan state and image preview without deleting saved records', async () => {
    vi.mocked(service.startScan).mockResolvedValueOnce(mockUnconfirmedScan);
    vi.mocked(service.confirmDate).mockResolvedValueOnce(mockProduct);
    vi.mocked(service.getScanById).mockResolvedValueOnce(mockConfirmedScan);

    renderScan();

    const fileInput = screen.getByLabelText('Upload packaging image');
    fireEvent.change(fileInput, { target: { files: [new File(['fake-bytes'], 'pkg.jpg', { type: 'image/jpeg' })] } });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Fresh Whole Milk')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('checkbox', { name: /Expiry date/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /I have checked the printed evidence/i }));
    fireEvent.click(screen.getByRole('button', { name: /Confirm Details/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /New Scan/i })).toBeInTheDocument();
    });

    // Click "New Scan"
    fireEvent.click(screen.getByRole('button', { name: /New Scan/i }));

    // Verifies: deleteScan was NOT called
    expect(service.deleteScan).not.toHaveBeenCalled();

    // Verifies: preview is cleared and camera/ready state is restored
    await waitFor(() => {
      expect(screen.getByText('Ready to scan')).toBeInTheDocument();
      expect(screen.queryByDisplayValue('Fresh Whole Milk')).not.toBeInTheDocument();
      expect(screen.queryByAltText('Captured packaging preview')).not.toBeInTheDocument();
    });
  });

  it('Scenario 9: Supplementary capture executes using the same scan ID and merges details', async () => {
    vi.mocked(service.startScan).mockResolvedValueOnce(mockUnconfirmedScan);

    const consolidatedScan: ScanRecord = {
      ...mockUnconfirmedScan,
      name: 'Fresh Whole Milk Extra Vitamin D',
      reviewStatus: 'Needs Review',
      supplementaryImages: ['/api/scans/200/image?index=1'],
      candidates: [
        ...mockUnconfirmedScan.candidates,
        {
          id: 'c-mfg',
          printedText: 'MFG 10/10/2026',
          date: '2026-10-10',
          dateType: 'Manufacturing',
          precision: 'day',
          confidence: 0.95,
          source: 'printed',
        },
      ],
    };
    vi.mocked(service.addSupplementaryImage).mockResolvedValueOnce(consolidatedScan);

    renderScan();

    const fileInput = screen.getByLabelText('Upload packaging image');
    fireEvent.change(fileInput, { target: { files: [new File(['first-image'], 'pkg1.jpg', { type: 'image/jpeg' })] } });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Fresh Whole Milk')).toBeInTheDocument();
    });

    // Capture More Info button should be available
    const captureMoreBtn = screen.getByRole('button', { name: /Capture More Info/i });
    expect(captureMoreBtn).toBeInTheDocument();

    // Click Capture More Info
    fireEvent.click(captureMoreBtn);

    // Check camera error or indicator
    await waitFor(() => {
      expect(screen.getByText(/Camera access is not supported/i)).toBeInTheDocument();
    });

    // Upload supplementary image using file input
    const fileInput2 = screen.getByLabelText('Upload packaging image') as HTMLInputElement;
    const secondFile = new File(['second-image'], 'pkg2.jpg', { type: 'image/jpeg' });
    Object.defineProperty(fileInput2, 'files', {
      value: [secondFile],
      configurable: true,
      writable: true,
    });
    fireEvent.input(fileInput2, { target: { files: [secondFile] } });
    fireEvent.change(fileInput2, { target: { files: [secondFile] } });

    await waitFor(() => {
      expect(service.addSupplementaryImage).toHaveBeenCalledWith(
        'SC-200',
        expect.any(String),
        expect.objectContaining({
          name: 'Fresh Whole Milk',
        })
      );
      expect(screen.getByDisplayValue('Fresh Whole Milk Extra Vitamin D')).toBeInTheDocument();
    });
  });

  it('Scenario 10: Failed supplementary capture retains original scan details and displays error', async () => {
    vi.mocked(service.startScan).mockResolvedValueOnce(mockUnconfirmedScan);
    vi.mocked(service.addSupplementaryImage).mockRejectedValueOnce(new Error('Supplementary OCR failed: blurry image'));

    renderScan();

    const fileInput = screen.getByLabelText('Upload packaging image');
    fireEvent.change(fileInput, { target: { files: [new File(['first-image'], 'pkg1.jpg', { type: 'image/jpeg' })] } });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Fresh Whole Milk')).toBeInTheDocument();
    });

    const captureMoreBtn = screen.getByRole('button', { name: /Capture More Info/i });
    fireEvent.click(captureMoreBtn);

    const fileInput2 = screen.getByLabelText('Upload packaging image') as HTMLInputElement;
    const secondFile = new File(['second-image'], 'pkg2.jpg', { type: 'image/jpeg' });
    Object.defineProperty(fileInput2, 'files', {
      value: [secondFile],
      configurable: true,
      writable: true,
    });
    fireEvent.input(fileInput2, { target: { files: [secondFile] } });
    fireEvent.change(fileInput2, { target: { files: [secondFile] } });

    await waitFor(() => {
      expect(screen.getByText('Supplementary OCR failed: blurry image')).toBeInTheDocument();
    });

    // Original scan data must be preserved and still visible
    expect(screen.getByDisplayValue('Fresh Whole Milk')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Capture More Info/i })).toBeInTheDocument();
  });
});

