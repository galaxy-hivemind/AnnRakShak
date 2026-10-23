import { useState, useRef, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Check, RotateCcw, LoaderCircle, CircleHelp, Calendar, Plus, Minus, X, AlertCircle, Camera } from 'lucide-react';
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

export function isScanFullyResolved(scan: ScanRecord): boolean {
  if (scan.reviewStatus === 'Needs Review' || scan.analysisStatus === 'Failed') {
    return false;
  }
  if (!scan.name || scan.name.trim().length < 2 || scan.name === 'Unidentified Item') {
    return false;
  }
  if (!scan.brand || scan.brand.trim().length === 0) {
    return false;
  }
  if (!scan.category) {
    return false;
  }
  if (!scan.quantity || scan.quantity.trim().length === 0) {
    return false;
  }
  const hasExactExpiry = (scan.candidates || []).some(
    (c) => ['Expiry', 'Use By', 'Best Before'].includes(c.dateType) && isExactDate(c.date)
  );
  if (!hasExactExpiry) {
    return false;
  }
  return true;
}

export function evaluateAutoAcceptance(scan: ScanRecord): {
  isEligible: boolean;
  primaryCandidateId?: string;
  reason?: string;
} {
  if (scan.analysisStatus !== 'Successful') {
    return { isEligible: false, reason: 'Analysis was not successful' };
  }
  const cleanName = (scan.name || '').trim();
  if (
    cleanName.length < 2 ||
    ['unknown', 'unknown item', 'unidentified item', 'product', 'item'].includes(cleanName.toLowerCase())
  ) {
    return { isEligible: false, reason: 'Missing or generic product identity' };
  }

  const candidates = scan.candidates || [];
  const expiryCandidates = candidates.filter((c) =>
    ['Expiry', 'Use By', 'Best Before'].includes(c.dateType)
  );

  if (expiryCandidates.length === 0) {
    return { isEligible: false, reason: 'No expiry date detected on packaging' };
  }

  // Check for conflicting expiry dates
  const validDates = Array.from(new Set(expiryCandidates.map((c) => c.date).filter(Boolean)));
  if (validDates.length > 1) {
    return { isEligible: false, reason: 'Conflicting expiry dates detected' };
  }

  // Exact day date check
  const primaryCandidate = expiryCandidates.find((c) => isExactDate(c.date) && c.precision === 'day');
  if (!primaryCandidate) {
    return { isEligible: false, reason: 'Expiry date lacks exact day format' };
  }

  // Confidence check (established threshold >= 0.80)
  const candidateConf = primaryCandidate.confidence !== undefined ? primaryCandidate.confidence : scan.confidenceScore;
  if (candidateConf === undefined || candidateConf < 0.80) {
    return { isEligible: false, reason: 'Confidence score below established threshold (0.80)' };
  }

  // Timeline consistency: Expiry must not precede Manufacturing
  const mfgCandidates = candidates.filter((c) =>
    ['Manufacturing', 'Packed On'].includes(c.dateType) && isExactDate(c.date)
  );
  for (const mfg of mfgCandidates) {
    if (primaryCandidate.date < mfg.date) {
      return { isEligible: false, reason: 'Expiry date is earlier than manufacturing date' };
    }
  }

  // Explicit safety/review flags from model or post-validation
  const reviewReason = (scan.reason || scan.decisionReason || '').toLowerCase();
  if (
    reviewReason.includes('conflict') ||
    reviewReason.includes('ambiguous') ||
    reviewReason.includes('unreadable') ||
    reviewReason.includes('multiple printed dates')
  ) {
    return { isEligible: false, reason: 'Ambiguous or conflicting evidence flagged' };
  }

  return {
    isEligible: true,
    primaryCandidateId: primaryCandidate.id,
  };
}

export function parsePersistedQuantity(raw: string | undefined | null): {
  itemCount: number;
  basePackaging: string;
} {
  if (!raw) {
    return { itemCount: 1, basePackaging: '' };
  }
  const trimmed = raw.trim();
  if (!trimmed) {
    return { itemCount: 1, basePackaging: '' };
  }

  // Exact composite format: "<count> units (<base>)" or "<count> unit (<base>)"
  const compositeMatch = trimmed.match(/^(\d+)\s*units?\s*\((.+)\)$/i);
  if (compositeMatch) {
    const parsedCount = parseInt(compositeMatch[1], 10);
    const count = parsedCount >= 1 ? parsedCount : 1;
    let base = compositeMatch[2].trim();
    while (true) {
      const innerMatch = base.match(/^(\d+)\s*units?\s*\((.+)\)$/i);
      if (innerMatch) {
        base = innerMatch[2].trim();
      } else {
        break;
      }
    }
    if (/^\d+\s*units?$/i.test(base)) {
      base = '';
    }
    return {
      itemCount: count,
      basePackaging: base,
    };
  }

  // Exact standalone units format: "<count> units" or "<count> unit"
  const standaloneUnitsMatch = trimmed.match(/^(\d+)\s*units?$/i);
  if (standaloneUnitsMatch) {
    const parsedCount = parseInt(standaloneUnitsMatch[1], 10);
    return {
      itemCount: parsedCount >= 1 ? parsedCount : 1,
      basePackaging: '',
    };
  }

  // Ordinary packaging description (e.g. "500 ml", "12 tablets", "6 eggs", "Box (large)")
  return {
    itemCount: 1,
    basePackaging: trimmed,
  };
}

export function computePersistedQuantity(itemCount: number, baseQuantity: string): string {
  const { basePackaging } = parsePersistedQuantity(baseQuantity);
  const cleanBase = basePackaging.trim();
  const safeCount = Math.max(1, Math.floor(itemCount || 1));

  if (safeCount <= 1) {
    return cleanBase;
  }
  if (cleanBase) {
    return `${safeCount} units (${cleanBase})`;
  }
  return `${safeCount} units`;
}

export function AnalysisPanel({
  scan,
  isSubsequentScan = false,
  onChange,
  onConfirmed,
  onCaptureMoreInfo,
}: {
  scan: ScanRecord;
  isSubsequentScan?: boolean;
  onChange: (s: ScanRecord) => void;
  onConfirmed?: () => void;
  onCaptureMoreInfo?: (currentEdits: {
    name?: string;
    brand?: string;
    category?: Category | '';
    quantity?: string;
  }) => void;
}) {
  const initialQtyParsed = parsePersistedQuantity(scan.quantity);

  // Inline editable fields
  const [productName, setProductName] = useState(scan.name || '');
  const [brand, setBrand] = useState(scan.brand || '');
  const [category, setCategory] = useState<Category | ''>(scan.category || '');
  const [quantity, setQuantity] = useState(initialQtyParsed.basePackaging);
  const [itemCount, setItemCount] = useState<number>(initialQtyParsed.itemCount);

  // Field reveal state for missing attributes
  const [revealedFields, setRevealedFields] = useState<Record<'brand' | 'category' | 'quantity', boolean>>({
    brand: false,
    category: false,
    quantity: false,
  });

  // Date candidates editable state
  const [candidates, setCandidates] = useState<DateCandidate[]>(scan.candidates || []);
  const [editingDateId, setEditingDateId] = useState<string | null>(null);

  const autoEval = evaluateAutoAcceptance(scan);
  const isAutoAccepted = Boolean(isSubsequentScan && autoEval.isEligible && scan.reviewStatus !== 'Confirmed');
  const userManuallyToggled = useRef<Record<string, boolean>>({});

  // Sync state if scan updates (e.g. from supplementary scan consolidation or rescan)
  useEffect(() => {
    setProductName(scan.name || '');
    setBrand(scan.brand || '');
    setCategory(scan.category || '');
    const parsedQty = parsePersistedQuantity(scan.quantity);
    setQuantity(parsedQty.basePackaging);
    setItemCount(parsedQty.itemCount);
    setCandidates(scan.candidates || []);
    userManuallyToggled.current = {};
    const evalResult = evaluateAutoAcceptance(scan);
    const shouldAccept = Boolean(isSubsequentScan && evalResult.isEligible && scan.reviewStatus !== 'Confirmed');
    if (shouldAccept && evalResult.primaryCandidateId) {
      setVerifiedCandidates({ [evalResult.primaryCandidateId]: true });
      setConfirmed(true);
    } else {
      setVerifiedCandidates({});
      setConfirmed(false);
    }
  }, [scan.id, isSubsequentScan]);

  // Verification & Confirmation state
  const [verifiedCandidates, setVerifiedCandidates] = useState<Record<string, boolean>>(() => {
    if (isAutoAccepted && autoEval.primaryCandidateId) {
      return { [autoEval.primaryCandidateId]: true };
    }
    return {};
  });
  const [confirmed, setConfirmed] = useState<boolean>(() => {
    return isAutoAccepted;
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // Auto-saved product edit state
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [saveErrorMessage, setSaveErrorMessage] = useState('');
  const debounceTimer = useRef<NodeJS.Timeout | null>(null);

  const qc = useQueryClient();

  const isConfirmed = scan.reviewStatus === 'Confirmed';
  const hasLinkedProduct = Boolean(scan.productId);

  const verifiedList = candidates.filter((c) => verifiedCandidates[c.id]);
  const hasVerified = verifiedList.length > 0;
  const hasMonthOnly = verifiedList.some((c) => c.precision === 'month' || !isExactDate(c.date));
  const isVerificationComplete = hasVerified && !hasMonthOnly;

  const toggleCandidate = (id: string) => {
    userManuallyToggled.current[id] = true;
    setVerifiedCandidates((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const handleItemCountChange = (newCount: number) => {
    if (newCount < 1) return;
    const whole = Math.floor(newCount);
    setItemCount(whole);
    if (hasLinkedProduct) {
      const computed = computePersistedQuantity(whole, quantity);
      triggerDebouncedSave({ quantity: computed });
    }
  };

  const handleItemCountInputChange = (val: string) => {
    if (val === '') {
      setItemCount(1);
      if (hasLinkedProduct) {
        const computed = computePersistedQuantity(1, quantity);
        triggerDebouncedSave({ quantity: computed });
      }
      return;
    }
    if (!/^\d+$/.test(val)) return;
    const parsed = parseInt(val, 10);
    if (parsed < 1) return;
    setItemCount(parsed);
    if (hasLinkedProduct) {
      const computed = computePersistedQuantity(parsed, quantity);
      triggerDebouncedSave({ quantity: computed });
    }
  };

  async function persistSavedProductEdits(overrides?: {
    name?: string;
    brand?: string;
    category?: Category | '';
    quantity?: string;
    candidates?: DateCandidate[];
  }) {
    if (!scan.productId) return;
    setSaveStatus('saving');
    setSaveErrorMessage('');
    try {
      const nameVal = overrides?.name !== undefined ? overrides.name : productName;
      const brandVal = overrides?.brand !== undefined ? overrides.brand : brand;
      const categoryVal = overrides?.category !== undefined ? overrides.category : category;
      const quantityVal = overrides?.quantity !== undefined ? overrides.quantity : computePersistedQuantity(itemCount, quantity);
      const cList = overrides?.candidates !== undefined ? overrides.candidates : candidates;

      const expCand = cList.find((c) => ['Expiry', 'Use By', 'Best Before'].includes(c.dateType) && isExactDate(c.date));
      const mfgCand = cList.find((c) => ['Manufacturing', 'Packed On'].includes(c.dateType) && isExactDate(c.date));
      const primary = expCand || mfgCand || cList[0];

      await service.updateProduct(scan.productId, {
        name: nameVal.trim() || scan.name,
        brand: brandVal.trim(),
        category: (categoryVal || scan.category || 'Pantry Staples') as Category,
        quantity: quantityVal.trim(),
        date: primary?.date && isExactDate(primary.date) ? primary.date : '',
        dateType: primary?.dateType || 'Expiry',
        notes: quantityVal.trim() ? `Quantity: ${quantityVal.trim()}` : '',
        verified: true,
      });

      onChange({
        ...scan,
        name: nameVal.trim() || scan.name,
        brand: brandVal.trim(),
        category: categoryVal,
        quantity: quantityVal.trim(),
        candidates: cList,
      });

      await qc.invalidateQueries();
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 3000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to update product in inventory';
      setSaveStatus('error');
      setSaveErrorMessage(msg);
      toast.error(msg);
    }
  }

  const triggerDebouncedSave = (overrides?: {
    name?: string;
    brand?: string;
    category?: Category | '';
    quantity?: string;
    candidates?: DateCandidate[];
  }) => {
    if (!hasLinkedProduct) return;
    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
    }
    debounceTimer.current = setTimeout(() => {
      void persistSavedProductEdits(overrides);
    }, 600);
  };

  const handleDateChange = (id: string, newDate: string) => {
    const updatedCandidates = candidates.map((c) => {
      if (c.id !== id) return c;
      const valid = isExactDate(newDate);
      return {
        ...c,
        date: newDate,
        precision: valid ? ('day' as const) : c.precision,
        source: 'manual' as const,
        isCalculated: false,
      };
    });
    setCandidates(updatedCandidates);
    if (isExactDate(newDate)) {
      setVerifiedCandidates((prev) => ({ ...prev, [id]: true }));
    }
    if (hasLinkedProduct) {
      void persistSavedProductEdits({ candidates: updatedCandidates });
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
    const updated = [...candidates, newCandidate];
    setCandidates(updated);
    setEditingDateId(newId);
  };

  const hasMfgCandidate = candidates.some((c) => ['Manufacturing', 'Packed On'].includes(c.dateType));
  const hasExpCandidate = candidates.some((c) => ['Expiry', 'Use By', 'Best Before'].includes(c.dateType));

  const showBrandInput = Boolean(brand.trim() || revealedFields.brand);
  const showCategoryInput = Boolean(category || revealedFields.category);
  const showQuantityInput = Boolean(quantity.trim() || revealedFields.quantity);

  async function confirm() {
    if (!isVerificationComplete || !confirmed) return;
    setBusy(true);
    setError('');
    try {
      const verifiedIds = verifiedList.map((c) => c.id);
      const finalQuantity = computePersistedQuantity(itemCount, quantity);
      const product = await service.confirmDate(scan.id, verifiedIds, {
        name: productName,
        brand,
        category,
        quantity: finalQuantity,
        candidates,
      });
      const updated = await service.getScanById(scan.id);
      onChange({
        ...updated,
        reviewStatus: 'Confirmed',
        productId: product?.id || updated.productId,
      });
      await qc.invalidateQueries();
      toast.success('Product saved to inventory');
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
      const parsedQty = parsePersistedQuantity(result.quantity);
      setQuantity(parsedQty.basePackaging);
      setItemCount(parsedQty.itemCount);
      setCandidates(result.candidates || []);
      setVerifiedCandidates({});
      setConfirmed(false);
      setEditingDateId(null);
      await qc.invalidateQueries();
      toast.success('Analysis completed.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed.');
    } finally {
      setBusy(false);
    }
  }

  const isFullyResolved = isScanFullyResolved(scan);
  const showCaptureMoreInfo = !isFullyResolved;

  const suppInputRef = useRef<HTMLInputElement>(null);
  const [suppBusy, setSuppBusy] = useState(false);

  const handleCaptureMoreInfo = () => {
    if (onCaptureMoreInfo) {
      onCaptureMoreInfo({
        name: productName,
        brand,
        category,
        quantity: computePersistedQuantity(itemCount, quantity),
      });
    } else {
      suppInputRef.current?.click();
    }
  };

  const handleSupplementaryFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setSuppBusy(true);
    try {
      const reader = new FileReader();
      reader.onload = async () => {
        try {
          const base64 = reader.result as string;
          if (service.addSupplementaryImage) {
            const updated = await service.addSupplementaryImage(scan.id, base64, {
              name: productName,
              brand,
              category,
              quantity,
            });
            onChange(updated);
            toast.success('Supplementary image analyzed and consolidated!');
          }
        } catch (err: unknown) {
          toast.error(err instanceof Error ? err.message : 'Supplementary analysis failed.');
        } finally {
          setSuppBusy(false);
          if (suppInputRef.current) suppInputRef.current.value = '';
        }
      };
      reader.readAsDataURL(file);
    } catch {
      setSuppBusy(false);
    }
  };

  return (
    <div className="analysis-body space-y-4">
      {/* Supplementary captures indicator if present */}
      {scan.supplementaryImages && scan.supplementaryImages.length > 0 && (
        <div className="flex items-center gap-2 mb-2 pb-2 border-b border-border/50 text-xs">
          <span className="text-muted-foreground font-medium">Captures:</span>
          <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium text-[11px]">
            Primary front
          </span>
          {scan.supplementaryImages.map((_, i) => (
            <span key={i} className="inline-flex items-center px-1.5 py-0.5 rounded bg-secondary text-secondary-foreground font-medium text-[11px]">
              +{i + 1} Supplementary
            </span>
          ))}
        </div>
      )}
      {/* Top Status & Confidence Overview */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
        <div className="flex items-center gap-2">
          <StatusBadge status={scan.analysisStatus} />
          <StatusBadge status={scan.reviewStatus} />
        </div>
        {hasLinkedProduct && (
          <div className="flex items-center gap-1.5 text-xs text-safe font-medium" id="save-status-indicator">
            {saveStatus === 'saving' ? (
              <>
                <LoaderCircle size={13} className="animate-spin text-primary" />
                <span className="text-muted-foreground">Saving changes…</span>
              </>
            ) : saveStatus === 'saved' ? (
              <>
                <Check size={13} className="text-safe" />
                <span>Saved to inventory</span>
              </>
            ) : saveStatus === 'error' ? (
              <>
                <AlertCircle size={13} className="text-destructive" />
                <span className="text-destructive">Failed to save changes</span>
              </>
            ) : (
              <>
                <Check size={13} className="text-safe" />
                <span>Saved to inventory</span>
              </>
            )}
          </div>
        )}
      </div>

      {/* Path A vs Path B Explanatory Card */}
      {isConfirmed ? (
        <div className="p-3 bg-safe/10 border border-safe/30 rounded-lg text-xs space-y-1">
          <div className="font-semibold text-safe flex items-center gap-1.5">
            <Check size={14} />
            <span>
              {scan.autoSaved
                ? `Saved to inventory${scan.confidenceScore ? ` · ${Math.round(scan.confidenceScore * 100)}% confidence` : ''}`
                : 'Saved to inventory'}
            </span>
          </div>
          <p className="text-muted-foreground">
            {scan.decisionReason || 'Product is stored in your kitchen inventory. Edits made below update your inventory item directly.'}
          </p>
        </div>
      ) : isAutoAccepted ? (
        <div className="p-3 bg-primary/10 border border-primary/30 rounded-lg text-xs space-y-1" id="auto-acceptance-banner">
          <div className="font-semibold text-primary flex items-center gap-1.5">
            <Check size={14} />
            <span>High-confidence date accepted · Review details & save</span>
          </div>
          <p className="text-muted-foreground">
            Model extracted an exact expiry date with high confidence. You can inspect or edit dates and quantity below, then save directly to inventory.
          </p>
        </div>
      ) : (
        <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg text-xs space-y-1">
          <div className="font-semibold text-amber-600 dark:text-amber-400 flex items-center gap-1.5">
            <CircleHelp size={14} />
            <span>Manual Review Required</span>
          </div>
          <p className="text-muted-foreground">
            {scan.decisionReason || scan.reason || 'This scan has uncertain evidence or missing information. Please review and confirm the details below to add it to your inventory.'}
          </p>
        </div>
      )}

      {saveErrorMessage && (
        <div className="form-error text-xs" role="alert">
          {saveErrorMessage}
          <button
            type="button"
            className="ml-2 underline font-semibold cursor-pointer"
            onClick={() => void persistSavedProductEdits()}
          >
            Retry save
          </button>
        </div>
      )}

      {/* Multi-Item Quantity Stepper Control */}
      <div className="p-3 bg-muted/40 border border-border rounded-lg space-y-2" id="quantity-stepper-container">
        <div className="flex items-center justify-between gap-3">
          <div>
            <label htmlFor="quantity-counter-input" className="text-xs font-semibold text-foreground block">
              Items to add
            </label>
            <span className="text-[11px] text-muted-foreground">
              {itemCount === 1 ? 'Adding 1 item' : `Adding ${itemCount} identical items`}
              {quantity.trim() ? ` · ${quantity.trim()} each` : ''}
            </span>
          </div>
          <div className="flex items-center gap-1.5" role="group">
            <Button
              type="button"
              variant="outline"
              size="icon"
              id="decrease-quantity-btn"
              aria-label="Decrease units"
              disabled={itemCount <= 1}
              onClick={() => handleItemCountChange(itemCount - 1)}
              className="h-8 w-8 rounded-md"
            >
              <Minus size={14} />
            </Button>
            <input
              type="number"
              id="quantity-counter-input"
              aria-label="Units count"
              min={1}
              step={1}
              value={itemCount}
              onChange={(e) => handleItemCountInputChange(e.target.value)}
              className="h-8 w-14 text-center text-sm font-semibold border rounded-md bg-background"
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              id="increase-quantity-btn"
              aria-label="Increase units"
              onClick={() => handleItemCountChange(itemCount + 1)}
              className="h-8 w-8 rounded-md"
            >
              <Plus size={14} />
            </Button>
          </div>
        </div>
        {itemCount > 1 && (
          <p className="text-[11px] text-muted-foreground bg-muted/60 p-2 rounded border border-border/50">
            ℹ️ Shortcut assumes all {itemCount} units share the same product details and dates. For items with differing expiry dates, scan packages individually.
          </p>
        )}
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
            onChange={(e) => {
              setProductName(e.target.value);
              triggerDebouncedSave({ name: e.target.value });
            }}
            onBlur={() => {
              if (hasLinkedProduct) void persistSavedProductEdits({ name: productName });
            }}
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
                onChange={(e) => {
                  setBrand(e.target.value);
                  triggerDebouncedSave({ brand: e.target.value });
                }}
                onBlur={() => {
                  if (hasLinkedProduct) void persistSavedProductEdits({ brand });
                }}
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
                onChange={(e) => {
                  const cat = e.target.value as Category;
                  setCategory(cat);
                  if (hasLinkedProduct) void persistSavedProductEdits({ category: cat });
                }}
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
                onChange={(e) => {
                  const newBase = e.target.value;
                  setQuantity(newBase);
                  if (hasLinkedProduct) {
                    const computed = computePersistedQuantity(itemCount, newBase);
                    triggerDebouncedSave({ quantity: computed });
                  }
                }}
                onBlur={() => {
                  if (hasLinkedProduct) {
                    const computed = computePersistedQuantity(itemCount, quantity);
                    void persistSavedProductEdits({ quantity: computed });
                  }
                }}
                placeholder="e.g. 500 ml or 2 packs"
              />
            </div>
          ) : null}
        </div>

        {/* Missing information buttons row */}
        {(!showBrandInput || !showCategoryInput || !showQuantityInput) && (
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
          <div className="flex gap-1">
            {!hasMfgCandidate && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                id="add-mfg-btn"
                className="h-6 text-[10px] px-1.5 py-0.5"
                onClick={() => addDateCandidate('Manufacturing')}
              >
                + Add Manufacturing
              </Button>
            )}
            {!hasExpCandidate && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                id="add-exp-btn"
                className="h-6 text-[10px] px-1.5 py-0.5"
                onClick={() => addDateCandidate('Expiry')}
              >
                + Add Expiry
              </Button>
            )}
          </div>
        </div>

        {candidates.length === 0 ? (
          <p className="text-xs text-muted-foreground p-3 border border-dashed rounded-md text-center">
            No printed dates detected yet. Use the buttons above to add one manually.
          </p>
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
                    disabled={isConfirmed}
                    onChange={() => toggleCandidate(c.id)}
                    className="mt-1 shrink-0 cursor-pointer"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <label htmlFor={`verify-${c.id}`} className="font-semibold text-sm cursor-pointer">
                        {formatDateTypeLabel(c.dateType)}: {c.date ? displayDate(c.date) : 'Unset'}
                      </label>
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
                      {isChecked ? (
                        isAutoAccepted && !userManuallyToggled.current[c.id]
                          ? '✨ Automatically accepted from packaging evidence'
                          : '☑ Verified on package'
                      ) : (
                        '☐ Verified on package'
                      )}
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

      {/* Path B: Manual Review Confirmation & Actions */}
      {!isConfirmed && (
        <>
          <label className="flex gap-2 items-start mt-4 text-xs font-normal leading-relaxed cursor-pointer">
            <input
              type="checkbox"
              id="overall-confirm-checkbox"
              className="mt-1 shrink-0 cursor-pointer"
              checked={confirmed}
              disabled={isConfirmed}
              onChange={(e) => {
                userManuallyToggled.current['overall'] = true;
                setConfirmed(e.target.checked);
              }}
            />
            <span>
              {isAutoAccepted
                ? 'Extracted date accepted from packaging evidence. Check or edit details before saving.'
                : 'I have checked the printed evidence and confirm this exact date and date type.'}
            </span>
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
              disabled={busy || suppBusy || !confirmed || !isVerificationComplete}
            >
              {busy ? <LoaderCircle className="animate-spin" /> : <Check />}
              {isAutoAccepted ? 'Confirm Details & Save' : 'Confirm Details'}
            </Button>
            {showCaptureMoreInfo && (
              <Button
                id="capture-more-info-btn"
                variant="outline"
                onClick={handleCaptureMoreInfo}
                disabled={busy || suppBusy}
              >
                {suppBusy ? <LoaderCircle className="animate-spin" /> : <Camera />}
                Capture More Info
              </Button>
            )}
            <Button variant="ghost" onClick={() => void retry()} disabled={busy || suppBusy}>
              <RotateCcw />
              Retry Analysis
            </Button>
          </div>
        </>
      )}

      {/* Path A & Confirmed Status Display */}
      {isConfirmed && (
        <>
          <div className="flex items-center gap-2 text-xs text-safe font-medium mt-4 p-2.5 bg-safe/10 border border-safe/30 rounded-md">
            <Check size={14} className="shrink-0" />
            <span>Saved to inventory · Linked to your kitchen items.</span>
          </div>
          {showCaptureMoreInfo && (
            <div className="mt-3">
              <Button
                id="capture-more-info-btn"
                variant="outline"
                size="sm"
                onClick={handleCaptureMoreInfo}
                disabled={busy || suppBusy}
              >
                {suppBusy ? <LoaderCircle className="animate-spin" /> : <Camera />}
                Capture More Info
              </Button>
            </div>
          )}
        </>
      )}

      <input
        ref={suppInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        aria-label="Upload supplementary packaging image"
        onChange={handleSupplementaryFile}
      />
    </div>
  );
}

export function ScanDetailDialog({
  scan,
  isSubsequentScan,
  onClose,
  onChange,
  onCaptureMoreInfo,
}: {
  scan: ScanRecord;
  isSubsequentScan?: boolean;
  onClose: () => void;
  onChange: (s: ScanRecord) => void;
  onCaptureMoreInfo?: (currentEdits: {
    name?: string;
    brand?: string;
    category?: Category | '';
    quantity?: string;
  }) => void;
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
        <div className="flex flex-wrap justify-center gap-2 bg-muted rounded-md p-3">
          <img
            src={scan.image}
            width={100}
            height={110}
            alt={`Capture for ${scan.name}`}
            className="h-28 object-contain rounded border border-border"
          />
          {scan.supplementaryImages?.map((imgUrl, idx) => (
            <img
              key={idx}
              src={imgUrl}
              width={100}
              height={110}
              alt={`Supplementary capture ${idx + 1} for ${scan.name}`}
              className="h-28 object-contain rounded border border-border"
            />
          ))}
        </div>
        <AnalysisPanel
          key={scan.id}
          scan={scan}
          isSubsequentScan={isSubsequentScan}
          onChange={onChange}
          onCaptureMoreInfo={onCaptureMoreInfo}
        />
      </DialogContent>
    </Dialog>
  );
}
