import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Check, RotateCcw, LoaderCircle, CircleHelp, Calendar, Plus, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { service } from '@/services/api';
import { displayDate, isExactDate } from '@/services/dates';
import { categories, type Category, type DateCandidate, type ScanRecord } from '@/services/types';
import { StatusBadge } from './common';

export function formatDateTypeLabel(type: string): string {
  switch (type.toLowerCase()) {
    case 'manufacturing':
      return 'Manufacturing date (MFG)';
    case 'expiry':
      return 'Expiry date (EXP)';
    case 'best before':
    case 'best_before':
      return 'Best before date (BB)';
    case 'use by':
    case 'use_by':
      return 'Use by date (UB)';
    case 'packed on':
    case 'packed_on':
      return 'Packed on date';
    default:
      return `${type} date`;
  }
}

export function AnalysisPanel({
  scan,
  onChange,
  onConfirmed,
}: {
  scan: ScanRecord;
  onChange: (s: ScanRecord) => void;
  onConfirmed?: () => void;
}) {
  // Inline editable fields
  const [productName, setProductName] = useState(scan.name || '');
  const [brand, setBrand] = useState(scan.brand || '');
  const [category, setCategory] = useState<Category | ''>(scan.category || '');
  const [quantity, setQuantity] = useState(scan.quantity || '');

  // Field reveal state for missing attributes
  const [revealedFields, setRevealedFields] = useState<Record<'brand' | 'category' | 'quantity', boolean>>({
    brand: false,
    category: false,
    quantity: false,
  });

  // Date candidates editable state
  const [candidates, setCandidates] = useState<DateCandidate[]>(scan.candidates || []);
  const [editingDateId, setEditingDateId] = useState<string | null>(null);

  // Verification & Confirmation state
  const [verifiedCandidates, setVerifiedCandidates] = useState<Record<string, boolean>>({});
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const qc = useQueryClient();

  const verifiedList = candidates.filter((c) => verifiedCandidates[c.id]);
  const hasVerified = verifiedList.length > 0;
  const hasMonthOnly = verifiedList.some((c) => c.precision === 'month' || !isExactDate(c.date));
  const isVerificationComplete = hasVerified && !hasMonthOnly;

  const toggleCandidate = (id: string) => {
    setVerifiedCandidates((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const handleDateChange = (id: string, newDate: string) => {
    setCandidates((prev) =>
      prev.map((c) => {
        if (c.id !== id) return c;
        const valid = isExactDate(newDate);
        return {
          ...c,
          date: newDate,
          precision: valid ? 'day' : c.precision,
          source: 'manual',
          isCalculated: false,
        };
      })
    );
    if (isExactDate(newDate)) {
      setVerifiedCandidates((prev) => ({ ...prev, [id]: true }));
    }
  };

  const addDateCandidate = (type: 'Manufacturing' | 'Expiry') => {
    const newId = `manual-date-${Date.now()}`;
    const newCandidate: DateCandidate = {
      id: newId,
      printedText: `User added ${type} date`,
      date: '',
      dateType: type,
      precision: 'day',
      source: 'manual',
      isCalculated: false,
    };
    setCandidates((prev) => [...prev, newCandidate]);
    setEditingDateId(newId);
  };

  const hasMfgCandidate = candidates.some((c) => ['Manufacturing', 'Packed On'].includes(c.dateType));
  const hasExpCandidate = candidates.some((c) => ['Expiry', 'Use By', 'Best Before'].includes(c.dateType));

  // Determine if missing buttons should appear:
  // Show button only if field is currently empty AND not explicitly revealed by user
  const showBrandInput = Boolean(brand.trim() || revealedFields.brand);
  const showCategoryInput = Boolean(category || revealedFields.category);
  const showQuantityInput = Boolean(quantity.trim() || revealedFields.quantity);

  async function confirm() {
    if (!isVerificationComplete || !confirmed) return;
    setBusy(true);
    setError('');
    try {
      const verifiedIds = verifiedList.map((c) => c.id);
      await service.confirmDate(scan.id, verifiedIds, {
        name: productName,
        brand,
        category,
        quantity,
        candidates,
      });
      const updated = await service.getScanById(scan.id);
      onChange(updated);
      await qc.invalidateQueries();
      toast.success('Date confirmed · Product added to inventory');
      onConfirmed?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Confirmation failed.');
    } finally {
      setBusy(false);
    }
  }

  async function retry() {
    setBusy(true);
    setError('');
    try {
      const result = await service.reanalyzeScan(scan.id);
      onChange(result);
      setProductName(result.name || '');
      setBrand(result.brand || '');
      setCategory(result.category || '');
      setQuantity(result.quantity || '');
      setCandidates(result.candidates || []);
      setVerifiedCandidates({});
      setConfirmed(false);
      setEditingDateId(null);
      await qc.invalidateQueries();
      toast.success('Analysis completed. Date confirmation is still required.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="analysis-body space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <StatusBadge status={scan.analysisStatus} />
        <StatusBadge status={scan.reviewStatus} />
      </div>

      {/* Direct Inline Product Metadata Editor */}
      <div className="p-3 bg-muted/30 border border-border rounded-lg space-y-3">
        <div className="field">
          <label htmlFor="inline-product-name" className="text-xs font-semibold text-muted-foreground">
            Product name
          </label>
          <input
            id="inline-product-name"
            type="text"
            className="text-sm font-medium"
            value={productName}
            disabled={scan.reviewStatus === 'Confirmed'}
            onChange={(e) => setProductName(e.target.value)}
            placeholder="e.g. Fresh Toned Milk"
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {/* Brand */}
          {showBrandInput ? (
            <div className="field">
              <div className="flex justify-between items-center">
                <label htmlFor="inline-brand" className="text-xs text-muted-foreground">
                  Brand
                </label>
                {!brand.trim() && (
                  <button
                    type="button"
                    onClick={() => setRevealedFields((prev) => ({ ...prev, brand: false }))}
                    className="text-[10px] text-muted-foreground hover:text-foreground"
                    title="Hide empty field"
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
              <input
                id="inline-brand"
                type="text"
                className="text-xs"
                value={brand}
                disabled={scan.reviewStatus === 'Confirmed'}
                onChange={(e) => setBrand(e.target.value)}
                placeholder="e.g. Amul"
              />
            </div>
          ) : null}

          {/* Category */}
          {showCategoryInput ? (
            <div className="field">
              <div className="flex justify-between items-center">
                <label htmlFor="inline-category" className="text-xs text-muted-foreground">
                  Category
                </label>
                {!category && (
                  <button
                    type="button"
                    onClick={() => setRevealedFields((prev) => ({ ...prev, category: false }))}
                    className="text-[10px] text-muted-foreground hover:text-foreground"
                    title="Hide empty field"
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
              <select
                id="inline-category"
                className="text-xs"
                value={category}
                disabled={scan.reviewStatus === 'Confirmed'}
                onChange={(e) => setCategory(e.target.value as Category)}
              >
                <option value="">Select category…</option>
                {categories.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
          ) : null}

          {/* Quantity */}
          {showQuantityInput ? (
            <div className="field">
              <div className="flex justify-between items-center">
                <label htmlFor="inline-quantity" className="text-xs text-muted-foreground">
                  Quantity
                </label>
                {!quantity.trim() && (
                  <button
                    type="button"
                    onClick={() => setRevealedFields((prev) => ({ ...prev, quantity: false }))}
                    className="text-[10px] text-muted-foreground hover:text-foreground"
                    title="Hide empty field"
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
              <input
                id="inline-quantity"
                type="text"
                className="text-xs"
                value={quantity}
                disabled={scan.reviewStatus === 'Confirmed'}
                onChange={(e) => setQuantity(e.target.value)}
                placeholder="e.g. 500 ml or 2 packs"
              />
            </div>
          ) : null}
        </div>

        {/* Missing information buttons row */}
        {(!showBrandInput || !showCategoryInput || !showQuantityInput) && scan.reviewStatus !== 'Confirmed' && (
          <div className="flex flex-wrap items-center gap-1.5 pt-1 text-xs">
            <span className="text-[11px] text-muted-foreground mr-1">Missing details:</span>
            {!showBrandInput && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                id="add-brand-btn"
                className="h-6 text-[11px] px-2 py-0 border-dashed"
                onClick={() => setRevealedFields((prev) => ({ ...prev, brand: true }))}
              >
                + Brand
              </Button>
            )}
            {!showCategoryInput && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                id="add-category-btn"
                className="h-6 text-[11px] px-2 py-0 border-dashed"
                onClick={() => setRevealedFields((prev) => ({ ...prev, category: true }))}
              >
                + Category
              </Button>
            )}
            {!showQuantityInput && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                id="add-quantity-btn"
                className="h-6 text-[11px] px-2 py-0 border-dashed"
                onClick={() => setRevealedFields((prev) => ({ ...prev, quantity: true }))}
              >
                + Quantity
              </Button>
            )}
          </div>
        )}
      </div>

      {/* Date Candidates Section */}
      <div className="space-y-2 mt-4">
        <div className="flex justify-between items-center">
          <div className="text-xs font-semibold flex items-center gap-2">
            <CircleHelp size={14} />
            Package Date Evidence · {candidates.length} candidates
          </div>
          {scan.reviewStatus !== 'Confirmed' && (
            <div className="flex gap-1">
              {!hasMfgCandidate && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  id="add-mfg-btn"
                  className="h-6 text-[10px] px-1.5 py-0"
                  onClick={() => addDateCandidate('Manufacturing')}
                >
                  + Add MFG
                </Button>
              )}
              {!hasExpCandidate && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  id="add-exp-btn"
                  className="h-6 text-[10px] px-1.5 py-0"
                  onClick={() => addDateCandidate('Expiry')}
                >
                  + Add Expiry
                </Button>
              )}
            </div>
          )}
        </div>

        {scan.reason && <p className="text-xs text-warning">{scan.reason}</p>}

        {!candidates.length ? (
          <div className="evidence">
            <p>No readable date evidence was returned. Add a date candidate above or retry the analysis.</p>
          </div>
        ) : (
          candidates.map((c) => {
            const isChecked = !!verifiedCandidates[c.id];
            const isEditingThisDate = editingDateId === c.id;

            return (
              <div
                key={c.id}
                className={`evidence transition-colors ${
                  isChecked ? 'selected border-primary/50 bg-primary/5' : ''
                }`}
              >
                <div className="evidence-header flex items-start gap-2">
                  <input
                    type="checkbox"
                    name={`candidate-verify-${c.id}`}
                    id={`verify-${c.id}`}
                    checked={isChecked}
                    disabled={scan.reviewStatus === 'Confirmed'}
                    onChange={() => toggleCandidate(c.id)}
                    className="mt-1 shrink-0 cursor-pointer"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <label htmlFor={`verify-${c.id}`} className="font-semibold text-sm cursor-pointer">
                        {formatDateTypeLabel(c.dateType)}: {c.date ? displayDate(c.date) : 'Unset'}
                      </label>
                      {scan.reviewStatus !== 'Confirmed' && (
                        <button
                          type="button"
                          id={`calendar-btn-${c.id}`}
                          aria-label={`Edit ${c.dateType} date with calendar`}
                          onClick={() => setEditingDateId(isEditingThisDate ? null : c.id)}
                          className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded border border-border bg-card hover:bg-muted text-muted-foreground hover:text-foreground cursor-pointer"
                        >
                          <Calendar size={12} />
                          {isEditingThisDate ? 'Close picker' : 'Pick date'}
                        </button>
                      )}
                    </div>

                    {/* Inline Calendar / Date Input */}
                    {isEditingThisDate && (
                      <div className="mt-2 p-2 bg-card border border-primary/40 rounded flex items-center gap-2">
                        <label htmlFor={`date-input-${c.id}`} className="text-xs whitespace-nowrap">
                          Select date:
                        </label>
                        <input
                          id={`date-input-${c.id}`}
                          type="date"
                          value={c.date || ''}
                          onChange={(e) => handleDateChange(c.id, e.target.value)}
                          className="text-xs py-1 px-2 h-8 w-auto flex-1"
                        />
                      </div>
                    )}

                    {/* Verification label */}
                    <div className="text-xs text-primary font-medium mt-1">
                      {isChecked ? '☑ Verified on package' : '☐ Verified on package'}
                    </div>

                    {/* Provenance & Classification badges */}
                    <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
                      {c.source === 'calculated' || c.isCalculated ? (
                        <span className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded bg-warning-soft text-warning font-medium">
                          ⚡ Calculated from shelf-life statement
                        </span>
                      ) : c.source === 'manual' ? (
                        <span className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded bg-secondary text-primary font-medium">
                          ✏ User-entered / corrected
                        </span>
                      ) : (
                        <span className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground font-medium">
                          🔍 Printed on packaging
                        </span>
                      )}

                      <span className="text-[10px] text-muted-foreground">
                        {c.precision === 'month'
                          ? 'Month/year only — exact day unknown'
                          : c.precision === 'unknown'
                          ? 'Uncertain date'
                          : 'Exact day date'}
                      </span>
                    </div>

                    {(c.source === 'calculated' || c.isCalculated) && (c.calculatedFrom || c.reason) && (
                      <p className="text-[11px] text-warning mt-1">
                        Source: {c.calculatedFrom || c.reason}
                      </p>
                    )}
                  </div>
                </div>

                <blockquote>{c.printedText}</blockquote>
                {c.reason && !c.isCalculated && (
                  <p className="text-xs text-muted-foreground mt-1">{c.reason}</p>
                )}
                {c.confidence !== undefined && (
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Model confidence: {Math.round(c.confidence * 100)}% · not a verification
                  </p>
                )}
              </div>
            );
          })
        )}
      </div>

      {error && (
        <div className="form-error mt-3" role="alert">
          {error}
        </div>
      )}

      {/* Confirmation & Actions */}
      {scan.reviewStatus !== 'Confirmed' && (
        <>
          <label className="flex gap-2 items-start mt-4 text-xs font-normal leading-relaxed cursor-pointer">
            <input
              type="checkbox"
              id="overall-confirm-checkbox"
              className="mt-1 shrink-0 cursor-pointer"
              checked={confirmed}
              disabled={scan.reviewStatus === 'Confirmed'}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>I have checked the printed evidence and confirm this exact date and date type.</span>
          </label>

          {!isVerificationComplete && (
            <p className="text-xs text-warning mt-2">
              {!hasVerified
                ? 'Please check "Verified on package" for at least one printed date above to enable confirmation.'
                : 'An exact day cannot be inferred from month-only dates. Use the calendar button beside the date to set an exact day or uncheck the month-only candidate.'}
            </p>
          )}

          {isVerificationComplete && !confirmed && (
            <p className="text-xs text-muted-foreground mt-2">
              Please check the confirmation box above to proceed.
            </p>
          )}

          <div className="flex flex-wrap gap-2 mt-5">
            <Button
              id="confirm-details-btn"
              onClick={() => void confirm()}
              disabled={busy || !confirmed || !isVerificationComplete}
            >
              {busy ? <LoaderCircle className="animate-spin" /> : <Check />}
              Confirm Details
            </Button>
            <Button variant="ghost" onClick={() => void retry()} disabled={busy}>
              <RotateCcw />
              Retry Analysis
            </Button>
          </div>
        </>
      )}

      {scan.reviewStatus === 'Confirmed' && (
        <p className="text-xs text-safe mt-4">
          Date explicitly confirmed by you.{' '}
          {scan.productId ? 'Linked to your inventory.' : 'Inventory product has been removed; scan history is retained.'}
        </p>
      )}
    </div>
  );
}

export function ScanDetailDialog({
  scan,
  onClose,
  onChange,
}: {
  scan: ScanRecord;
  onClose: () => void;
  onChange: (s: ScanRecord) => void;
}) {
  return (
    <Dialog
      open
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent className="dialog-body max-w-xl">
        <DialogTitle>Scan details</DialogTitle>
        <DialogDescription>
          Scan · {new Date(scan.timestamp).toLocaleString()} · Original evidence retained.
        </DialogDescription>
        <div className="flex justify-center bg-muted rounded-md p-3">
          <img
            src={scan.image}
            width={100}
            height={110}
            alt={`Capture for ${scan.name}`}
            className="h-28 object-contain"
          />
        </div>
        <AnalysisPanel key={scan.id} scan={scan} onChange={onChange} />
      </DialogContent>
    </Dialog>
  );
}
