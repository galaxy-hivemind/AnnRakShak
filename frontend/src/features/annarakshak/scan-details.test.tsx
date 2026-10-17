import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AnalysisPanel } from './scan-details';
import type { ScanRecord } from '@/services/types';
import { service } from '@/services/api';

vi.mock('@/services/api', () => ({
  service: {
    confirmDate: vi.fn(),
    getScanById: vi.fn(),
    reanalyzeScan: vi.fn(),
    correctScan: vi.fn(),
  },
}));

describe('AnalysisPanel Date Verification UX & Direct Inline Editing', () => {
  let queryClient: QueryClient;

  const mockScanWithDualDates: ScanRecord = {
    id: 'SC-101',
    timestamp: '2026-10-17T12:00:00Z',
    image: '/test.jpg',
    name: 'Organic Wheat Flour',
    brand: 'Farm Fresh',
    category: 'Grains & Cereals',
    quantity: '1 kg',
    analysisStatus: 'Successful',
    reviewStatus: 'Needs Review',
    reason: 'Multiple printed dates detected',
    candidates: [
      {
        id: 'c-mfg',
        printedText: 'MFG 01/09/2026',
        date: '2026-09-01',
        dateType: 'Manufacturing',
        precision: 'day',
        confidence: 0.95,
        source: 'printed',
      },
      {
        id: 'c-exp',
        printedText: 'EXP 01/09/2027',
        date: '2027-09-01',
        dateType: 'Expiry',
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

  const renderPanel = (scan = mockScanWithDualDates, onChange = vi.fn(), onConfirmed = vi.fn()) => {
    return render(
      <QueryClientProvider client={queryClient}>
        <AnalysisPanel scan={scan} onChange={onChange} onConfirmed={onConfirmed} />
      </QueryClientProvider>
    );
  };

  it('1. Displays both manufacturing and expiry date candidates with independent checkboxes', () => {
    renderPanel();

    expect(screen.getByText(/Manufacturing date \(MFG\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Expiry date \(EXP\)/i)).toBeInTheDocument();

    const mfgCheckbox = screen.getByRole('checkbox', { name: /Manufacturing date \(MFG\)/i });
    const expCheckbox = screen.getByRole('checkbox', { name: /Expiry date \(EXP\)/i });

    expect(mfgCheckbox).not.toBeChecked();
    expect(expCheckbox).not.toBeChecked();
    expect(mfgCheckbox).toHaveAttribute('type', 'checkbox');
    expect(expCheckbox).toHaveAttribute('type', 'checkbox');
  });

  it('2. Checking one date candidate does NOT uncheck another date candidate', () => {
    renderPanel();

    const mfgCheckbox = screen.getByRole('checkbox', { name: /Manufacturing date \(MFG\)/i });
    const expCheckbox = screen.getByRole('checkbox', { name: /Expiry date \(EXP\)/i });

    // Check MFG
    fireEvent.click(mfgCheckbox);
    expect(mfgCheckbox).toBeChecked();
    expect(expCheckbox).not.toBeChecked();

    // Check EXP - MFG must remain checked!
    fireEvent.click(expCheckbox);
    expect(mfgCheckbox).toBeChecked();
    expect(expCheckbox).toBeChecked();

    // Uncheck MFG - EXP must remain checked
    fireEvent.click(mfgCheckbox);
    expect(mfgCheckbox).not.toBeChecked();
    expect(expCheckbox).toBeChecked();
  });

  it('3. Preserves detected date types without alteration', () => {
    renderPanel();

    expect(screen.getByText(/Manufacturing date \(MFG\): 1 Sept 2026/i)).toBeInTheDocument();
    expect(screen.getByText(/Expiry date \(EXP\): 1 Sept 2027/i)).toBeInTheDocument();
  });

  it('4. The overall confirmation checkbox has independent state and is clickable', () => {
    renderPanel();

    const overallCheckbox = screen.getByLabelText(/I have checked the printed evidence and confirm/i);
    expect(overallCheckbox).not.toBeChecked();

    fireEvent.click(overallCheckbox);
    expect(overallCheckbox).toBeChecked();

    fireEvent.click(overallCheckbox);
    expect(overallCheckbox).not.toBeChecked();
  });

  it('5. Confirmation remains unavailable until required verification is satisfied', () => {
    renderPanel();

    const confirmButton = screen.getByRole('button', { name: /Confirm Details/i });
    const mfgCheckbox = screen.getByRole('checkbox', { name: /Manufacturing date \(MFG\)/i });
    const overallCheckbox = screen.getByLabelText(/I have checked the printed evidence and confirm/i);

    expect(confirmButton).toBeDisabled();
    expect(screen.getByText(/Please check "Verified on package" for at least one printed date/i)).toBeInTheDocument();

    fireEvent.click(mfgCheckbox);
    expect(confirmButton).toBeDisabled();
    expect(screen.getByText(/Please check the confirmation box above to proceed/i)).toBeInTheDocument();

    fireEvent.click(overallCheckbox);
    expect(confirmButton).toBeEnabled();
  });

  it('6. Blocks confirmation when a verified candidate has month-only precision', () => {
    const scanWithMonthOnly: ScanRecord = {
      ...mockScanWithDualDates,
      candidates: [
        {
          id: 'c-month',
          printedText: 'BEST BEFORE 11/2026',
          date: '2026-11-01',
          dateType: 'Best Before',
          precision: 'month',
        },
      ],
    };

    renderPanel(scanWithMonthOnly);

    const monthCheckbox = screen.getByRole('checkbox', { name: /Best before date \(BB\)/i });
    const overallCheckbox = screen.getByLabelText(/I have checked the printed evidence and confirm/i);
    const confirmButton = screen.getByRole('button', { name: /Confirm Details/i });

    fireEvent.click(monthCheckbox);
    fireEvent.click(overallCheckbox);

    expect(confirmButton).toBeDisabled();
    expect(screen.getByText(/An exact day cannot be inferred from month-only dates/i)).toBeInTheDocument();
  });

  it('7. Edit Details button and modal are completely removed', () => {
    renderPanel();
    // There must be no "Edit Details" button on the screen
    expect(screen.queryByRole('button', { name: /Edit Details/i })).not.toBeInTheDocument();
  });

  it('8. Editing MFG and EXP dates independently using calendar buttons', () => {
    renderPanel();

    const expCalendarBtn = screen.getByRole('button', { name: /Edit Expiry date with calendar/i });
    fireEvent.click(expCalendarBtn);

    const dateInput = screen.getByLabelText(/Select date:/i);
    expect(dateInput).toBeInTheDocument();
    expect(dateInput).toHaveValue('2027-09-01');

    fireEvent.change(dateInput, { target: { value: '2027-10-15' } });
    expect(screen.getByText(/Expiry date \(EXP\): 15 Oct 2027/i)).toBeInTheDocument();
    expect(screen.getByText(/User-entered \/ corrected/i)).toBeInTheDocument();
  });

  it('9. Supports correcting a product with only one detected date without requiring a modal', () => {
    const scanSingleDate: ScanRecord = {
      ...mockScanWithDualDates,
      candidates: [
        {
          id: 'c-only-mfg',
          printedText: 'MFG 10/10/2026',
          date: '2026-10-10',
          dateType: 'Manufacturing',
          precision: 'day',
          source: 'printed',
        },
      ],
    };

    renderPanel(scanSingleDate);

    const mfgCheckbox = screen.getByRole('checkbox', { name: /Manufacturing date \(MFG\)/i });
    const overallCheckbox = screen.getByLabelText(/I have checked the printed evidence and confirm/i);
    const confirmButton = screen.getByRole('button', { name: /Confirm Details/i });

    fireEvent.click(mfgCheckbox);
    fireEvent.click(overallCheckbox);

    expect(confirmButton).toBeEnabled();
  });

  it('10. Adds a missing date type without opening a menu', () => {
    const scanOnlyMfg: ScanRecord = {
      ...mockScanWithDualDates,
      candidates: [
        {
          id: 'c-mfg-only',
          printedText: 'MFG 01/01/2026',
          date: '2026-01-01',
          dateType: 'Manufacturing',
          precision: 'day',
          source: 'printed',
        },
      ],
    };

    renderPanel(scanOnlyMfg);

    const addExpBtn = screen.getByRole('button', { name: /\+ Add Expiry/i });
    expect(addExpBtn).toBeInTheDocument();

    fireEvent.click(addExpBtn);

    // New expiry candidate appears inline with its date input
    expect(screen.getByText(/Expiry date \(EXP\): Unset/i)).toBeInTheDocument();
    const dateInput = screen.getByLabelText(/Select date:/i);
    fireEvent.change(dateInput, { target: { value: '2026-07-01' } });

    expect(screen.getByText(/Expiry date \(EXP\): 1 Jul 2026/i)).toBeInTheDocument();
  });

  it('11. Edits detected brand, category, and quantity inline', () => {
    renderPanel();

    const brandInput = screen.getByLabelText(/Brand/i);
    const categorySelect = screen.getByLabelText(/Category/i);
    const quantityInput = screen.getByLabelText(/Quantity/i);

    expect(brandInput).toHaveValue('Farm Fresh');
    expect(categorySelect).toHaveValue('Grains & Cereals');
    expect(quantityInput).toHaveValue('1 kg');

    fireEvent.change(brandInput, { target: { value: 'Aashirvaad' } });
    fireEvent.change(categorySelect, { target: { value: 'Pantry Staples' } });
    fireEvent.change(quantityInput, { target: { value: '5 kg' } });

    expect(brandInput).toHaveValue('Aashirvaad');
    expect(categorySelect).toHaveValue('Pantry Staples');
    expect(quantityInput).toHaveValue('5 kg');
  });

  it('12. Shows missing-information buttons only for missing fields and replaces with input on click', () => {
    const scanMissingFields: ScanRecord = {
      ...mockScanWithDualDates,
      brand: '',
      category: '',
      quantity: '',
    };

    renderPanel(scanMissingFields);

    // Brand, category, quantity inputs should not be visible initially
    expect(screen.queryByLabelText(/^Brand$/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^Category$/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^Quantity$/i)).not.toBeInTheDocument();

    // Buttons for missing info must be displayed
    const addBrandBtn = screen.getByRole('button', { name: /\+ Brand/i });
    const addCategoryBtn = screen.getByRole('button', { name: /\+ Category/i });
    const addQuantityBtn = screen.getByRole('button', { name: /\+ Quantity/i });

    expect(addBrandBtn).toBeInTheDocument();
    expect(addCategoryBtn).toBeInTheDocument();
    expect(addQuantityBtn).toBeInTheDocument();

    // Clicking + Brand reveals the Brand input and removes the + Brand button
    fireEvent.click(addBrandBtn);
    expect(screen.getByLabelText(/^Brand$/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /\+ Brand/i })).not.toBeInTheDocument();

    // + Category and + Quantity remain
    expect(screen.getByRole('button', { name: /\+ Category/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /\+ Quantity/i })).toBeInTheDocument();
  });

  it('13. Preserves distinction between printed, manually entered, and calculated dates', () => {
    const scanWithCalculated: ScanRecord = {
      ...mockScanWithDualDates,
      candidates: [
        {
          id: 'c-calc',
          printedText: 'Best before 6 months from MFG',
          date: '2027-03-01',
          dateType: 'Best Before',
          precision: 'day',
          isCalculated: true,
          source: 'calculated',
          calculatedFrom: 'MFG 2026-09-01 + 6 calendar months',
        },
      ],
    };

    renderPanel(scanWithCalculated);

    expect(screen.getByText(/⚡ Calculated from shelf-life statement/i)).toBeInTheDocument();
    expect(screen.getByText(/Source: MFG 2026-09-01 \+ 6 calendar months/i)).toBeInTheDocument();
    // Must NOT be labeled as printed
    expect(screen.queryByText(/🔍 Printed on packaging/i)).not.toBeInTheDocument();
  });

  it('14. Saves inline corrections through service.confirmDate', async () => {
    const onChange = vi.fn();
    const onConfirmed = vi.fn();

    vi.mocked(service.confirmDate).mockResolvedValue({
      id: 'PR-1',
      name: 'Whole Grain Flour',
      brand: 'Aashirvaad',
      category: 'Grains & Cereals',
      quantity: '5 kg',
      date: '2027-09-01',
      dateType: 'Expiry',
      notes: 'Quantity: 5 kg | MFG: 2026-09-01 | EXP: 2027-09-01',
      verified: true,
      image: '/test.jpg',
    });

    vi.mocked(service.getScanById).mockResolvedValue({
      ...mockScanWithDualDates,
      reviewStatus: 'Confirmed',
    });

    renderPanel(mockScanWithDualDates, onChange, onConfirmed);

    // Edit product name and quantity inline
    const nameInput = screen.getByLabelText(/Product name/i);
    const quantityInput = screen.getByLabelText(/Quantity/i);

    fireEvent.change(nameInput, { target: { value: 'Whole Grain Flour' } });
    fireEvent.change(quantityInput, { target: { value: '5 kg' } });

    // Verify candidates
    const mfgCheckbox = screen.getByRole('checkbox', { name: /Manufacturing date \(MFG\)/i });
    const expCheckbox = screen.getByRole('checkbox', { name: /Expiry date \(EXP\)/i });
    const overallCheckbox = screen.getByLabelText(/I have checked the printed evidence and confirm/i);
    const confirmButton = screen.getByRole('button', { name: /Confirm Details/i });

    fireEvent.click(mfgCheckbox);
    fireEvent.click(expCheckbox);
    fireEvent.click(overallCheckbox);

    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(service.confirmDate).toHaveBeenCalledWith(
        'SC-101',
        ['c-mfg', 'c-exp'],
        expect.objectContaining({
          name: 'Whole Grain Flour',
          quantity: '5 kg',
          brand: 'Farm Fresh',
          category: 'Grains & Cereals',
        })
      );
      expect(onChange).toHaveBeenCalled();
      expect(onConfirmed).toHaveBeenCalled();
    });
  });
});
