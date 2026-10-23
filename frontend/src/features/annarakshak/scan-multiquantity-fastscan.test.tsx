import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AnalysisPanel, evaluateAutoAcceptance, computePersistedQuantity, parsePersistedQuantity } from './scan-details';
import { Scan } from './scan';
import type { ScanRecord } from '@/services/types';
import { service } from '@/services/api';

vi.mock('@/services/api', () => ({
  service: {
    startScan: vi.fn(),
    confirmDate: vi.fn(),
    getScanById: vi.fn(),
    reanalyzeScan: vi.fn(),
    deleteScan: vi.fn(),
    updateProduct: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

describe('Multi-Quantity, Faster Scanning & Confidence Acceptance Tests', () => {
  let queryClient: QueryClient;

  const highConfidenceScan: ScanRecord = {
    id: 'SC-301',
    timestamp: '2026-10-21T12:00:00Z',
    image: '/milk.jpg',
    name: 'Fresh Toned Milk',
    brand: 'Amul',
    category: 'Dairy & Eggs',
    quantity: '500 ml',
    analysisStatus: 'Successful',
    reviewStatus: 'Needs Review',
    confidenceScore: 0.95,
    candidates: [
      {
        id: 'c-exp-1',
        printedText: 'USE BY 28/10/2026',
        date: '2026-10-28',
        dateType: 'Use By',
        precision: 'day',
        confidence: 0.96,
        source: 'printed',
      },
    ],
  };

  const lowConfidenceScan: ScanRecord = {
    id: 'SC-302',
    timestamp: '2026-10-21T12:05:00Z',
    image: '/blurry.jpg',
    name: 'Cereal Flakes',
    brand: 'Kelloggs',
    category: 'Grains & Cereals',
    quantity: '1 kg',
    analysisStatus: 'Successful',
    reviewStatus: 'Needs Review',
    confidenceScore: 0.65,
    candidates: [
      {
        id: 'c-exp-low',
        printedText: 'EXP ??/??/2027',
        date: '2027-05-15',
        dateType: 'Expiry',
        precision: 'day',
        confidence: 0.60,
        source: 'printed',
      },
    ],
  };

  const conflictingDatesScan: ScanRecord = {
    id: 'SC-303',
    timestamp: '2026-10-21T12:10:00Z',
    image: '/snack.jpg',
    name: 'Potato Chips',
    brand: 'Lays',
    category: 'Snacks',
    quantity: '200 g',
    analysisStatus: 'Successful',
    reviewStatus: 'Needs Review',
    reason: 'Multiple printed dates detected with conflicting values',
    candidates: [
      {
        id: 'c-exp-a',
        printedText: 'EXP 10/11/2026',
        date: '2026-11-10',
        dateType: 'Expiry',
        precision: 'day',
        confidence: 0.88,
        source: 'printed',
      },
      {
        id: 'c-exp-b',
        printedText: 'BEST BEFORE 15/12/2026',
        date: '2026-12-15',
        dateType: 'Best Before',
        precision: 'day',
        confidence: 0.85,
        source: 'printed',
      },
    ],
  };

  const mfgOnlyScan: ScanRecord = {
    id: 'SC-304',
    timestamp: '2026-10-21T12:15:00Z',
    image: '/biscuit.jpg',
    name: 'Butter Biscuits',
    brand: 'Britannia',
    category: 'Snacks',
    quantity: '100 g',
    analysisStatus: 'Successful',
    reviewStatus: 'Needs Review',
    candidates: [
      {
        id: 'c-mfg-only',
        printedText: 'MFD 01/10/2026',
        date: '2026-10-01',
        dateType: 'Manufacturing',
        precision: 'day',
        confidence: 0.98,
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

  const renderPanel = (
    scan: ScanRecord,
    isSubsequentScan = false,
    onChange = vi.fn(),
    onConfirmed = vi.fn()
  ) => {
    return render(
      <QueryClientProvider client={queryClient}>
        <AnalysisPanel
          scan={scan}
          isSubsequentScan={isSubsequentScan}
          onChange={onChange}
          onConfirmed={onConfirmed}
        />
      </QueryClientProvider>
    );
  };

  describe('Feature 1: Multi-Quantity Support', () => {
    it('1. Default quantity is 1 and units counter renders with - button disabled at 1', () => {
      renderPanel(highConfidenceScan);

      const counterInput = screen.getByLabelText(/Items to add/i);
      expect(counterInput).toHaveValue(1);

      const decreaseBtn = screen.getByRole('button', { name: /Decrease units/i });
      expect(decreaseBtn).toBeDisabled();

      const increaseBtn = screen.getByRole('button', { name: /Increase units/i });
      expect(increaseBtn).toBeEnabled();
    });

    it('2. Clicking + increments quantity and enables - button', () => {
      renderPanel(highConfidenceScan);

      const counterInput = screen.getByLabelText(/Items to add/i);
      const increaseBtn = screen.getByRole('button', { name: /Increase units/i });
      const decreaseBtn = screen.getByRole('button', { name: /Decrease units/i });

      fireEvent.click(increaseBtn);
      expect(counterInput).toHaveValue(2);
      expect(decreaseBtn).toBeEnabled();
      expect(screen.getByText(/Adding 2 identical items/i)).toBeInTheDocument();

      fireEvent.click(increaseBtn);
      expect(counterInput).toHaveValue(3);

      fireEvent.click(decreaseBtn);
      expect(counterInput).toHaveValue(2);
    });

    it('3. Direct numeric entry accepts valid positive integers and rejects 0, negatives, and nonnumerics', () => {
      renderPanel(highConfidenceScan);

      const counterInput = screen.getByLabelText(/Items to add/i);

      // Enter 4
      fireEvent.change(counterInput, { target: { value: '4' } });
      expect(counterInput).toHaveValue(4);

      // Rejects negative
      fireEvent.change(counterInput, { target: { value: '-2' } });
      expect(counterInput).toHaveValue(4);

      // Rejects zero
      fireEvent.change(counterInput, { target: { value: '0' } });
      expect(counterInput).toHaveValue(4);

      // Rejects fractional / non-integer
      fireEvent.change(counterInput, { target: { value: '3.7' } });
      expect(counterInput).toHaveValue(4);

      // Empty reverts safely to 1
      fireEvent.change(counterInput, { target: { value: '' } });
      expect(counterInput).toHaveValue(1);
    });

    it('4. parsePersistedQuantity correctly parses composite and ordinary quantities', () => {
      // Reopening composite format
      expect(parsePersistedQuantity('4 units (500 ml)')).toEqual({ itemCount: 4, basePackaging: '500 ml' });
      expect(parsePersistedQuantity('1 unit (500 ml)')).toEqual({ itemCount: 1, basePackaging: '500 ml' });
      expect(parsePersistedQuantity('2 units (12 tablets)')).toEqual({ itemCount: 2, basePackaging: '12 tablets' });

      // Standalone units
      expect(parsePersistedQuantity('4 units')).toEqual({ itemCount: 4, basePackaging: '' });
      expect(parsePersistedQuantity('1 unit')).toEqual({ itemCount: 1, basePackaging: '' });

      // Ordinary packaging quantities preserved as single-item
      expect(parsePersistedQuantity('500 ml')).toEqual({ itemCount: 1, basePackaging: '500 ml' });
      expect(parsePersistedQuantity('12 tablets')).toEqual({ itemCount: 1, basePackaging: '12 tablets' });
      expect(parsePersistedQuantity('6 eggs')).toEqual({ itemCount: 1, basePackaging: '6 eggs' });
      expect(parsePersistedQuantity('Box of 10')).toEqual({ itemCount: 1, basePackaging: 'Box of 10' });

      // Empty and undefined
      expect(parsePersistedQuantity('')).toEqual({ itemCount: 1, basePackaging: '' });
      expect(parsePersistedQuantity(undefined)).toEqual({ itemCount: 1, basePackaging: '' });

      // Malformed or unrecognized values handled conservatively without discarding original information
      expect(parsePersistedQuantity('Box (large)')).toEqual({ itemCount: 1, basePackaging: 'Box (large)' });
      expect(parsePersistedQuantity('4 units (unclosed')).toEqual({ itemCount: 1, basePackaging: '4 units (unclosed' });

      // Self-healing: unwraps any prior nested strings
      expect(parsePersistedQuantity('2 units (4 units (500 ml))')).toEqual({ itemCount: 2, basePackaging: '500 ml' });
    });

    it('5. computePersistedQuantity helper computes idempotent quantity semantics', () => {
      // 1 item with package size preserves package size
      expect(computePersistedQuantity(1, '500 ml')).toBe('500 ml');
      // 1 item with no package size preserves empty
      expect(computePersistedQuantity(1, '')).toBe('');
      // Multiple items with package size
      expect(computePersistedQuantity(4, '500 ml')).toBe('4 units (500 ml)');
      // Multiple items without package size
      expect(computePersistedQuantity(3, '')).toBe('3 units');
      // Existing units string
      expect(computePersistedQuantity(5, '1 unit')).toBe('5 units');

      // Idempotency: formatting an already formatted string does NOT nest
      expect(computePersistedQuantity(2, '4 units (500 ml)')).toBe('2 units (500 ml)');
      expect(computePersistedQuantity(4, '4 units (500 ml)')).toBe('4 units (500 ml)');
      expect(computePersistedQuantity(3, '2 units (4 units (500 ml))')).toBe('3 units (500 ml)');

      // Decreasing count to 1 restores the single-item format
      expect(computePersistedQuantity(1, '4 units (500 ml)')).toBe('500 ml');
      expect(computePersistedQuantity(1, '2 units (12 tablets)')).toBe('12 tablets');

      // Ordinary packaging descriptions preserved at count 1
      expect(computePersistedQuantity(1, '12 tablets')).toBe('12 tablets');
      expect(computePersistedQuantity(3, '12 tablets')).toBe('3 units (12 tablets)');
      expect(computePersistedQuantity(1, 'Box (large)')).toBe('Box (large)');
      expect(computePersistedQuantity(2, 'Box (large)')).toBe('2 units (Box (large))');
    });

    it('6. Reopening an existing item with "4 units (500 ml)" initializes counter to 4 and packaging to 500 ml', () => {
      const existingMultiScan: ScanRecord = {
        ...highConfidenceScan,
        id: 'SC-EXISTING',
        productId: 'PR-100',
        quantity: '4 units (500 ml)',
        reviewStatus: 'Confirmed',
      };

      renderPanel(existingMultiScan);

      const counterInput = screen.getByLabelText(/Items to add/i);
      expect(counterInput).toHaveValue(4);

      // Helper text shows 4 identical items and 500 ml each
      expect(screen.getByText(/Adding 4 identical items · 500 ml each/i)).toBeInTheDocument();

      // Inline packaging input has base quantity "500 ml" (not "4 units (500 ml)")
      const quantityInput = screen.getByDisplayValue('500 ml');
      expect(quantityInput).toBeInTheDocument();
    });

    it('7. Decreasing count to 1 restores single-item packaging format and debounces updateProduct', async () => {
      const existingMultiScan: ScanRecord = {
        ...highConfidenceScan,
        id: 'SC-EXISTING-2',
        productId: 'PR-101',
        quantity: '4 units (500 ml)',
        reviewStatus: 'Confirmed',
      };

      vi.mocked(service.updateProduct).mockResolvedValueOnce({
        id: 'PR-101',
        name: 'Fresh Toned Milk',
        brand: 'Amul',
        category: 'Dairy & Eggs',
        quantity: '500 ml',
        date: '2026-10-28',
        dateType: 'Use By',
        notes: 'Quantity: 500 ml',
        verified: true,
        image: '/milk.jpg',
      });

      renderPanel(existingMultiScan);

      const counterInput = screen.getByLabelText(/Items to add/i);
      fireEvent.change(counterInput, { target: { value: '1' } });

      expect(counterInput).toHaveValue(1);
      expect(screen.getByText(/Adding 1 item · 500 ml each/i)).toBeInTheDocument();

      await waitFor(() => {
        expect(service.updateProduct).toHaveBeenCalledWith(
          'PR-101',
          expect.objectContaining({
            quantity: '500 ml',
          })
        );
      });
    });

    it('8. Reopening ordinary packaging e.g. "12 tablets" preserves count 1 and packaging size intact', () => {
      const tabletScan: ScanRecord = {
        ...highConfidenceScan,
        id: 'SC-TABLETS',
        productId: 'PR-102',
        quantity: '12 tablets',
        reviewStatus: 'Confirmed',
      };

      renderPanel(tabletScan);

      const counterInput = screen.getByLabelText(/Items to add/i);
      expect(counterInput).toHaveValue(1);
      expect(screen.getByText(/Adding 1 item · 12 tablets each/i)).toBeInTheDocument();
      expect(screen.getByDisplayValue('12 tablets')).toBeInTheDocument();
    });

    it('9. Reopening malformed packaging string preserves original without silent corruption', () => {
      const malformedScan: ScanRecord = {
        ...highConfidenceScan,
        id: 'SC-MALFORMED',
        productId: 'PR-103',
        quantity: 'Box (large)',
        reviewStatus: 'Confirmed',
      };

      renderPanel(malformedScan);

      const counterInput = screen.getByLabelText(/Items to add/i);
      expect(counterInput).toHaveValue(1);
      expect(screen.getByDisplayValue('Box (large)')).toBeInTheDocument();
    });

    it('10. Persists selected multi-quantity through confirmDate when saved', async () => {
      const onChange = vi.fn();
      const onConfirmed = vi.fn();

      vi.mocked(service.confirmDate).mockResolvedValueOnce({
        id: 'PR-99',
        name: 'Fresh Toned Milk',
        brand: 'Amul',
        category: 'Dairy & Eggs',
        quantity: '4 units (500 ml)',
        date: '2026-10-28',
        dateType: 'Use By',
        notes: 'Quantity: 4 units (500 ml) | Use By: 2026-10-28 [Verified]',
        verified: true,
        image: '/milk.jpg',
      });
      vi.mocked(service.getScanById).mockResolvedValueOnce({
        ...highConfidenceScan,
        reviewStatus: 'Confirmed',
        productId: 'PR-99',
      });

      renderPanel(highConfidenceScan, false, onChange, onConfirmed);

      // Set quantity to 4
      const counterInput = screen.getByLabelText(/Items to add/i);
      fireEvent.change(counterInput, { target: { value: '4' } });

      // Verify and confirm
      const expCheckbox = screen.getByRole('checkbox', { name: /Use by date \(UB\)/i });
      const overallCheckbox = screen.getByLabelText(/I have checked the printed evidence and confirm/i);
      const confirmButton = screen.getByRole('button', { name: /Confirm Details/i });

      fireEvent.click(expCheckbox);
      fireEvent.click(overallCheckbox);
      fireEvent.click(confirmButton);

      await waitFor(() => {
        expect(service.confirmDate).toHaveBeenCalledWith(
          'SC-301',
          ['c-exp-1'],
          expect.objectContaining({
            quantity: '4 units (500 ml)',
            name: 'Fresh Toned Milk',
          })
        );
        expect(onConfirmed).toHaveBeenCalled();
      });
    });

    it('11. Changing quantity does NOT trigger startScan, reanalyzeScan, or OCR/Gemini calls', () => {
      renderPanel(highConfidenceScan);

      const counterInput = screen.getByLabelText(/Items to add/i);
      fireEvent.change(counterInput, { target: { value: '5' } });

      expect(service.startScan).not.toHaveBeenCalled();
      expect(service.reanalyzeScan).not.toHaveBeenCalled();
    });
  });

  describe('Feature 3: Confidence-Based Automatic Date Acceptance for Subsequent Scans', () => {
    it('1. evaluateAutoAcceptance accepts high-confidence, valid, unambiguous expiry dates', () => {
      const result = evaluateAutoAcceptance(highConfidenceScan);
      expect(result.isEligible).toBe(true);
      expect(result.primaryCandidateId).toBe('c-exp-1');
    });

    it('2. evaluateAutoAcceptance rejects low confidence (< 0.80)', () => {
      const result = evaluateAutoAcceptance(lowConfidenceScan);
      expect(result.isEligible).toBe(false);
      expect(result.reason).toMatch(/Confidence score below established threshold/i);
    });

    it('3. evaluateAutoAcceptance rejects conflicting expiry dates', () => {
      const result = evaluateAutoAcceptance(conflictingDatesScan);
      expect(result.isEligible).toBe(false);
      expect(result.reason).toMatch(/Conflicting expiry dates detected/i);
    });

    it('4. evaluateAutoAcceptance rejects manufacturing-only scans (never synthesizes expiry from MFG)', () => {
      const result = evaluateAutoAcceptance(mfgOnlyScan);
      expect(result.isEligible).toBe(false);
      expect(result.reason).toMatch(/No expiry date detected/i);
    });

    it('5. On subsequent scans with high confidence, automatically accepts date without mandatory checkbox friction', () => {
      renderPanel(highConfidenceScan, true);

      // Auto-accepted banner is visible
      expect(screen.getByText(/High-confidence date accepted · Review details & save/i)).toBeInTheDocument();

      // Candidate is pre-accepted
      expect(screen.getByText(/✨ Automatically accepted from packaging evidence/i)).toBeInTheDocument();
      const candCheckbox = screen.getByRole('checkbox', { name: /Use by date \(UB\)/i });
      expect(candCheckbox).toBeChecked();

      // Overall confirm checkbox is checked
      const overallCheckbox = screen.getByRole('checkbox', {
        name: /Extracted date accepted from packaging evidence/i,
      });
      expect(overallCheckbox).toBeChecked();

      // Confirm button is enabled immediately for explicit user save
      const saveBtn = screen.getByRole('button', { name: /Confirm Details & Save/i });
      expect(saveBtn).toBeEnabled();
    });

    it('6. First scan preserves existing manual review flow even if high confidence', () => {
      // isSubsequentScan = false
      renderPanel(highConfidenceScan, false);

      expect(screen.getByText(/Manual Review Required/i)).toBeInTheDocument();
      const candCheckbox = screen.getByRole('checkbox', { name: /Use by date \(UB\)/i });
      expect(candCheckbox).not.toBeChecked();

      const saveBtn = screen.getByRole('button', { name: /Confirm Details/i });
      expect(saveBtn).toBeDisabled();
    });

    it('7. Subsequent scan with low confidence preserves existing review safeguards', () => {
      renderPanel(lowConfidenceScan, true);

      expect(screen.getByText(/Manual Review Required/i)).toBeInTheDocument();
      const candCheckbox = screen.getByRole('checkbox', { name: /Expiry date \(EXP\)/i });
      expect(candCheckbox).not.toBeChecked();

      const saveBtn = screen.getByRole('button', { name: /Confirm Details/i });
      expect(saveBtn).toBeDisabled();
    });

    it('8. Accepted dates remain fully editable before saving', () => {
      renderPanel(highConfidenceScan, true);

      const editBtn = screen.getByRole('button', { name: /Edit Use By date with calendar/i });
      fireEvent.click(editBtn);

      const dateInput = screen.getByLabelText(/Select date:/i);
      expect(dateInput).toHaveValue('2026-10-28');

      fireEvent.change(dateInput, { target: { value: '2026-11-05' } });
      expect(screen.getByText(/Use by date \(UB\): 5 Nov 2026/i)).toBeInTheDocument();
      expect(screen.getByText(/User-entered \/ corrected/i)).toBeInTheDocument();
    });

    it('9. Saving is strictly an explicit user action (no persistence before button click)', async () => {
      vi.mocked(service.confirmDate).mockResolvedValueOnce({
        id: 'PR-99',
        name: 'Fresh Toned Milk',
        brand: 'Amul',
        category: 'Dairy & Eggs',
        quantity: '500 ml',
        date: '2026-10-28',
        dateType: 'Use By',
        notes: '',
        verified: true,
        image: '/milk.jpg',
      });
      vi.mocked(service.getScanById).mockResolvedValueOnce({
        ...highConfidenceScan,
        reviewStatus: 'Confirmed',
        productId: 'PR-99',
      });

      renderPanel(highConfidenceScan, true);

      // No confirmDate call yet
      expect(service.confirmDate).not.toHaveBeenCalled();

      // Explicit click
      const saveBtn = screen.getByRole('button', { name: /Confirm Details & Save/i });
      fireEvent.click(saveBtn);

      await waitFor(() => {
        expect(service.confirmDate).toHaveBeenCalledTimes(1);
      });
    });

    it('10. Unchecking the auto-accepted candidate disables the save button', () => {
      renderPanel(highConfidenceScan, true);

      const candCheckbox = screen.getByRole('checkbox', { name: /Use by date \(UB\)/i });
      expect(candCheckbox).toBeChecked();

      fireEvent.click(candCheckbox);
      expect(candCheckbox).not.toBeChecked();

      const saveBtn = screen.getByRole('button', { name: /Confirm Details/i });
      expect(saveBtn).toBeDisabled();
      expect(screen.getByText(/Please check "Verified on package" for at least one printed date/i)).toBeInTheDocument();
    });
  });

  describe('Feature 4: End-to-End Workflow Consistency & No Leakage', () => {
    it('1. Quantity and dates do not leak between consecutive scans in the session', async () => {
      vi.mocked(service.startScan)
        .mockResolvedValueOnce(highConfidenceScan)
        .mockResolvedValueOnce(lowConfidenceScan);

      render(
        <QueryClientProvider client={queryClient}>
          <Scan />
        </QueryClientProvider>
      );

      // Perform first scan
      const fileInput = screen.getByLabelText('Upload packaging image');
      const file1 = new File(['pkg1'], 'pkg1.jpg', { type: 'image/jpeg' });
      fireEvent.change(fileInput, { target: { files: [file1] } });

      await waitFor(() => {
        expect(screen.getByDisplayValue('Fresh Toned Milk')).toBeInTheDocument();
      });

      // Change quantity to 4 on scan 1
      const counterInput = screen.getByLabelText(/Items to add/i);
      fireEvent.change(counterInput, { target: { value: '4' } });
      expect(counterInput).toHaveValue(4);

      // Trigger new scan
      const clearBtn = screen.getByRole('button', { name: /Clear/i });
      fireEvent.click(clearBtn);

      // Perform second scan (low confidence)
      const file2 = new File(['pkg2'], 'pkg2.jpg', { type: 'image/jpeg' });
      fireEvent.change(fileInput, { target: { files: [file2] } });

      await waitFor(() => {
        expect(screen.getByDisplayValue('Cereal Flakes')).toBeInTheDocument();
      });

      // Quantity must be reset to default 1, NOT leaked from previous scan (4)
      const counterInput2 = screen.getByLabelText(/Items to add/i);
      expect(counterInput2).toHaveValue(1);

      // Low confidence scan must require manual review
      expect(screen.getByText(/Manual Review Required/i)).toBeInTheDocument();
    });

    it('2. Double submissions and rapid clicks do not trigger duplicate scan requests', async () => {
      vi.mocked(service.startScan).mockReturnValue(
        new Promise((resolve) => setTimeout(() => resolve(highConfidenceScan), 100))
      );

      render(
        <QueryClientProvider client={queryClient}>
          <Scan />
        </QueryClientProvider>
      );

      const fileInput = screen.getByLabelText('Upload packaging image');
      const file = new File(['pkg'], 'pkg.jpg', { type: 'image/jpeg' });

      // Rapidly fire multiple changes
      fireEvent.change(fileInput, { target: { files: [file] } });
      fireEvent.change(fileInput, { target: { files: [file] } });
      fireEvent.change(fileInput, { target: { files: [file] } });

      await waitFor(() => {
        expect(screen.getByDisplayValue('Fresh Toned Milk')).toBeInTheDocument();
      });

      // Exactly one startScan request was made
      expect(service.startScan).toHaveBeenCalledTimes(1);
    });

    it('3. Failed save retains recoverable form state and succeeds on retry', async () => {
      vi.mocked(service.confirmDate)
        .mockRejectedValueOnce(new Error('Network timeout: database locked'))
        .mockResolvedValueOnce({
          id: 'PR-99',
          name: 'Fresh Toned Milk',
          brand: 'Amul',
          category: 'Dairy & Eggs',
          quantity: '3 units (500 ml)',
          date: '2026-10-28',
          dateType: 'Use By',
          notes: '',
          verified: true,
          image: '/milk.jpg',
        });
      vi.mocked(service.getScanById).mockResolvedValueOnce({
        ...highConfidenceScan,
        reviewStatus: 'Confirmed',
        productId: 'PR-99',
      });

      renderPanel(highConfidenceScan, true);

      // Change quantity to 3
      const counterInput = screen.getByLabelText(/Items to add/i);
      fireEvent.change(counterInput, { target: { value: '3' } });

      const saveBtn = screen.getByRole('button', { name: /Confirm Details & Save/i });
      fireEvent.click(saveBtn);

      await waitFor(() => {
        expect(screen.getByText(/Network timeout: database locked/i)).toBeInTheDocument();
      });

      // Form state is retained and recoverable
      expect(counterInput).toHaveValue(3);
      expect(screen.getByDisplayValue('Fresh Toned Milk')).toBeInTheDocument();
      expect(saveBtn).toBeEnabled();

      // Retry save: succeeds with same retained quantity and state
      fireEvent.click(saveBtn);

      await waitFor(() => {
        expect(service.confirmDate).toHaveBeenCalledTimes(2);
        expect(service.confirmDate).toHaveBeenLastCalledWith(
          'SC-301',
          ['c-exp-1'],
          expect.objectContaining({
            quantity: '3 units (500 ml)',
            name: 'Fresh Toned Milk',
          })
        );
      });
    });
  });
});
