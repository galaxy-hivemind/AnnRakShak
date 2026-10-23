import { useState, type FormEvent } from 'react';
import { useSuspenseQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import {
  Leaf,
  ScanLine,
  ArrowRight,
  Refrigerator,
  Search,
  CalendarDays,
  CircleCheck,
  BookOpen,
  Plus,
  LoaderCircle,
  ChevronRight,
  MoreVertical,
  LayoutGrid,
  List,
  Pencil,
  Trash2,
  Eye,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { toast } from 'sonner';
import { dashboardQuery, productsQuery, settingsQuery, wasteQuery, service } from '@/services/api';
import { daysFromToday, localISO } from '@/services/dates';
import type { Product } from '@/services/types';
import { resolveFoodImage, categoryImages, tomatoesImg } from '@/services/food-images';
import {
  Empty,
  Footer,
  StatCardsRow,
  dayLabel,
  getTimeGreeting,
  shortCategory,
} from './common';
import { formatProductDisplayName } from './product-identity';
import { ProductDialog, type ProductDialogMode } from './product-dialog';

const tabs = [
  { label: 'All', match: () => true },
  { label: 'Vegetables', match: (p: Product) => p.produce === 'Vegetable' || p.category === 'Fresh Produce' },
  { label: 'Dairy', match: (p: Product) => p.category === 'Dairy & Eggs' },
  { label: 'Fruits', match: (p: Product) => p.produce === 'Fruit' },
  { label: 'Pantry', match: (p: Product) => p.category === 'Pantry Staples' || p.category === 'Grains & Cereals' },
  {
    label: 'Others',
    match: (p: Product) =>
      p.category !== 'Dairy & Eggs' &&
      p.category !== 'Fresh Produce' &&
      p.category !== 'Pantry Staples' &&
      p.category !== 'Grains & Cereals' &&
      p.produce !== 'Fruit' &&
      p.produce !== 'Vegetable',
  },
] as const;

const shortDate = (iso: string) => {
  try {
    return new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  } catch {
    return iso;
  }
};

const fullDateWithYear = (iso: string) => {
  try {
    return new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
  } catch {
    return iso;
  }
};

export function Dashboard() {
  const qc = useQueryClient();
  const { data } = useSuspenseQuery(dashboardQuery);
  const { data: products } = useSuspenseQuery(productsQuery);
  const { data: settings } = useSuspenseQuery(settingsQuery);
  const { data: wasteEntries } = useSuspenseQuery(wasteQuery);

  const [dialog, setDialog] = useState<ProductDialogMode>();
  const [tab, setTab] = useState<string>('All');
  const [query, setQuery] = useState('');
  const [sortOrder, setSortOrder] = useState<'soonest' | 'latest' | 'name'>('soonest');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');

  const [logWasteOpen, setLogWasteOpen] = useState(false);
  const [wasteForm, setWasteForm] = useState({
    name: '',
    quantity: '',
    value: '',
    reason: '',
    date: localISO(),
  });
  const [wasteBusy, setWasteBusy] = useState(false);
  const [wasteError, setWasteError] = useState('');

  const greeting = getTimeGreeting();

  // Filter items according to category pill & search query
  const filter = tabs.find((t) => t.label === tab)?.match ?? (() => true);
  const list = products
    .filter((p) => {
      if (!filter(p)) return false;
      if (!query) return true;
      const lower = query.toLowerCase().trim();
      const display = formatProductDisplayName(p).toLowerCase();
      const rawName = (p.name || '').toLowerCase();
      const brand = (p.brand || '').toLowerCase();
      const cat = (p.category || '').toLowerCase();
      return display.includes(lower) || rawName.includes(lower) || brand.includes(lower) || cat.includes(lower);
    })
    .sort((a, b) => {
      if (sortOrder === 'name') {
        return formatProductDisplayName(a).localeCompare(formatProductDisplayName(b));
      }
      const dayA = a.verified && a.date ? daysFromToday(a.date) : 9999;
      const dayB = b.verified && b.date ? daysFromToday(b.date) : 9999;
      return sortOrder === 'soonest' ? dayA - dayB : dayB - dayA;
    });

  // Group upcoming expiring items chronologically by date
  const groupedExpiring = (() => {
    const sorted = [...data.expiring].sort((a, b) => {
      const dayA = a.date ? daysFromToday(a.date) : 9999;
      const dayB = b.date ? daysFromToday(b.date) : 9999;
      return dayA - dayB;
    });

    const groups: { dateStr: string; dateLabel: string; items: Product[] }[] = [];
    const dateMap = new Map<string, Product[]>();

    for (const p of sorted.slice(0, 10)) {
      if (!p.date) continue;
      const existing = dateMap.get(p.date) || [];
      existing.push(p);
      dateMap.set(p.date, existing);
    }

    for (const [dateStr, items] of dateMap.entries()) {
      const d = daysFromToday(dateStr);
      let dateLabel = fullDateWithYear(dateStr);
      if (d === 0) dateLabel = `${fullDateWithYear(dateStr)} (Today)`;
      else if (d === 1) dateLabel = `${fullDateWithYear(dateStr)} (Tomorrow)`;
      groups.push({ dateStr, dateLabel, items });
    }

    return groups;
  })();

  async function handleAddWaste(e: FormEvent) {
    e.preventDefault();
    setWasteError('');
    if (!wasteForm.name.trim()) {
      setWasteError('Please specify what was wasted.');
      return;
    }
    setWasteBusy(true);
    try {
      await service.addWasteEntry({
        name: wasteForm.name.trim(),
        quantity: wasteForm.quantity.trim(),
        value: Number(wasteForm.value || 0),
        reason: wasteForm.reason.trim() || 'Unused',
        date: wasteForm.date,
      });
      await qc.invalidateQueries();
      setLogWasteOpen(false);
      setWasteForm({ name: '', quantity: '', value: '', reason: '', date: localISO() });
      toast.success('Logged to your waste journal');
    } catch (err) {
      setWasteError(err instanceof Error ? err.message : 'Unable to log waste.');
    } finally {
      setWasteBusy(false);
    }
  }

  return (
    <div className="page dashboard-page">
      {/* 1. Main Welcome Hero Banner matching reference image */}
      <section className="dashboard-banner">
        <div className="banner-left">
          <h1 className="banner-title">{greeting}, Ayush!</h1>
          <p className="banner-subtitle">Fresh food. Less waste. A healthier tomorrow.</p>

          <div className="banner-action-card">
            <div className="card-header-row">
              <div className="card-leaf-icon">
                <Leaf size={18} />
              </div>
              <div className="card-header-text">
                <h3>Keep track of your kitchen</h3>
                <p>Scan, manage, and never miss an expiry date.</p>
              </div>
            </div>

            <div className="card-buttons-row">
              <Button
                className="banner-primary-btn"
                onClick={() => setDialog({ type: 'add' })}
              >
                <Plus size={16} />
                <span>Add Ingredient</span>
              </Button>

              <Button
                variant="outline"
                className="banner-secondary-btn add-btn"
                asChild
              >
                <Link to="/scan">
                  <ScanLine size={16} />
                  <span>Add Ingredients</span>
                </Link>
              </Button>
            </div>
          </div>
        </div>

        <div className="banner-right">
          <img
            src="/banner-produce.png"
            alt="Fresh produce and vegetables"
            className="banner-produce-image"
          />
        </div>
      </section>

      {/* 2. Original Four Statistics Blocks (Mandatory Preserved Metrics) */}
      <StatCardsRow />

      {/* 3. Split Layout: Inventory on Left, Upcoming Expiry on Right */}
      <div className="dashboard-grid">
        {/* Left Column: Your Inventory */}
        <section className="inventory-column">
          <div className="inventory-header">
            <div className="flex items-baseline gap-2">
              <h2 className="inventory-title">Your Inventory</h2>
              <span className="inventory-count">({products.length} items)</span>
            </div>
            <Link to="/inventory" search={{ q: '' }} className="view-all-link">
              <span>View all</span>
              <ArrowRight size={14} />
            </Link>
          </div>

          {/* Filter Pills and Toolbar Controls */}
          <div className="inventory-toolbar-row">
            <div role="tablist" aria-label="Filter by category" className="category-pills">
              {tabs.map((t) => (
                <button
                  key={t.label}
                  role="tab"
                  aria-selected={tab === t.label}
                  className={`category-pill ${tab === t.label ? 'active' : ''}`}
                  onClick={() => setTab(t.label)}
                >
                  {t.label}
                </button>
              ))}
            </div>

            <div className="toolbar-actions">
              <select
                className="sort-dropdown"
                aria-label="Sort inventory"
                value={sortOrder}
                onChange={(e) => setSortOrder(e.target.value as any)}
              >
                <option value="soonest">Sort: Expiry (Soonest)</option>
                <option value="latest">Sort: Expiry (Latest)</option>
                <option value="name">Sort: Name (A-Z)</option>
              </select>

              <div className="view-toggle">
                <button
                  className={`toggle-btn ${viewMode === 'grid' ? 'active' : ''}`}
                  onClick={() => setViewMode('grid')}
                  aria-label="Grid layout"
                  title="Grid layout"
                >
                  <LayoutGrid size={15} />
                </button>
                <button
                  className={`toggle-btn ${viewMode === 'list' ? 'active' : ''}`}
                  onClick={() => setViewMode('list')}
                  aria-label="List layout"
                  title="List layout"
                >
                  <List size={15} />
                </button>
              </div>
            </div>
          </div>

          {/* Product Cards Grid / List */}
          {list.length ? (
            <div className={viewMode === 'grid' ? 'product-cards-grid' : 'product-cards-list'}>
              {list.slice(0, 6).map((p) => {
                const d = p.date ? daysFromToday(p.date) : 9999;
                const isUrgent = d <= 2 && d >= 0;
                const isExpired = d < 0;
                const imgSrc = resolveFoodImage(p);
                const fallbackSrc = categoryImages[p.category || 'Pantry Staples'] || tomatoesImg;
                const displayName = formatProductDisplayName(p);
                const formattedDate = p.date ? shortDate(p.date) : '';

                return (
                  <div
                    key={p.id}
                    className="product-card"
                    onClick={() => setDialog({ type: 'view', product: p })}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        setDialog({ type: 'view', product: p });
                      }
                    }}
                  >
                    {/* Card Photo & Floating Badge */}
                    <div className="product-card-img-wrap">
                      <img
                        src={imgSrc}
                        alt=""
                        className="product-card-img"
                        loading="lazy"
                        onError={(e) => {
                          const target = e.currentTarget;
                          if (target.src !== fallbackSrc && !target.src.endsWith(fallbackSrc)) {
                            target.src = fallbackSrc;
                          }
                        }}
                      />
                      <div className="product-card-floating-badge">
                        {isExpired ? (
                          <span className="badge-pill expired">
                            <span className="badge-dot" />
                            Expired
                          </span>
                        ) : isUrgent ? (
                          <span className="badge-pill warning">
                            <span className="badge-dot" />
                            Expiring Soon
                          </span>
                        ) : (
                          <span className="badge-pill fresh">
                            <span className="badge-dot" />
                            Fresh
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Card Body */}
                    <div className="product-card-body">
                      <div className="product-title-row">
                        <strong className="product-name" title={displayName}>
                          {displayName}
                        </strong>

                        {/* Three-dots menu */}
                        <DropdownMenu>
                          <DropdownMenuTrigger
                            className="three-dots-btn"
                            aria-label={`Options for ${displayName}`}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <MoreVertical size={16} />
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-36">
                            <DropdownMenuItem
                              onClick={(e) => {
                                e.stopPropagation();
                                setDialog({ type: 'view', product: p });
                              }}
                            >
                              <Eye size={14} className="mr-2" />
                              View details
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={(e) => {
                                e.stopPropagation();
                                setDialog({ type: 'edit', product: p });
                              }}
                            >
                              <Pencil size={14} className="mr-2" />
                              Edit
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              className="text-destructive focus:text-destructive"
                              onClick={(e) => {
                                e.stopPropagation();
                                setDialog({ type: 'delete', product: p });
                              }}
                            >
                              <Trash2 size={14} className="mr-2" />
                              Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>

                      <div className="product-meta-row">
                        {p.quantity && <span>{p.quantity}</span>}
                        {p.quantity && <span className="meta-sep">•</span>}
                        <span className="inline-flex items-center gap-1">
                          <Refrigerator size={12} className="text-muted-foreground" />
                          {p.storage || 'Fridge'}
                        </span>
                      </div>

                      <div className="product-expiry-status">
                        {p.date && p.verified ? (
                          <span className={`expiry-pill ${isUrgent ? 'warning' : isExpired ? 'expired' : 'safe'}`}>
                            <span className="dot" />
                            {dayLabel(d)}
                          </span>
                        ) : (
                          <span className="expiry-pill neutral">
                            <span className="dot" />
                            No expiry date
                          </span>
                        )}
                      </div>

                      <div className="product-footer-note">
                        {p.verified && p.date
                          ? `Confirmed expiry • ${formattedDate}`
                          : 'Expiry not recorded'}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <Empty title="No matching ingredients" message="Try another category or search term." />
          )}
        </section>

        {/* Right Column: Upcoming Expiry Panel */}
        <aside className="upcoming-expiry-panel">
          <div className="panel-header-row">
            <div className="flex items-center gap-2">
              <CalendarDays size={18} className="text-[#1E684A]" />
              <h2 className="panel-title">Upcoming Expiry</h2>
            </div>
            <Link to="/timeline" className="view-all-link">
              <span>View all</span>
              <ArrowRight size={14} />
            </Link>
          </div>

          {groupedExpiring.length ? (
            <div className="expiry-date-groups">
              {groupedExpiring.map((group) => (
                <div key={group.dateStr} className="date-group-block">
                  <div className="date-group-title">{group.dateLabel}</div>
                  <div className="date-group-items">
                    {group.items.map((p) => {
                      const d = p.date ? daysFromToday(p.date) : 9999;
                      const dotClass = d <= 1 ? 'dot-urgent' : d <= 3 ? 'dot-warning' : 'dot-safe';
                      const imgSrc = resolveFoodImage(p);
                      const fallbackSrc = categoryImages[p.category || 'Pantry Staples'] || tomatoesImg;
                      const displayName = formatProductDisplayName(p);

                      return (
                        <div
                          key={p.id}
                          className="expiry-item-row"
                          onClick={() => setDialog({ type: 'view', product: p })}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              setDialog({ type: 'view', product: p });
                            }
                          }}
                        >
                          <span className={`status-bullet ${dotClass}`} />
                          <img
                            src={imgSrc}
                            alt=""
                            className="expiry-item-thumb"
                            loading="lazy"
                            onError={(e) => {
                              const target = e.currentTarget;
                              if (target.src !== fallbackSrc && !target.src.endsWith(fallbackSrc)) {
                                target.src = fallbackSrc;
                              }
                            }}
                          />
                          <div className="expiry-item-info">
                            <strong className="item-name">{displayName}</strong>
                            <div className="item-meta">
                              {[p.quantity, p.storage || 'Fridge'].filter(Boolean).join(' • ')}
                            </div>
                          </div>
                          <ChevronRight size={16} className="item-arrow" />
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground py-8 text-center">
              No confirmed dates in the next {settings.alertWindow} days.
            </p>
          )}
        </aside>
      </div>

      {/* 4. Preserved Waste Journal Section */}
      <section className="waste-journal-section">
        <div className="section-header-row">
          <div>
            <h2 className="section-title flex items-center gap-2">
              <BookOpen size={20} className="text-[#1E684A]" />
              Waste journal
            </h2>
            <p className="section-subtitle">Small reflections for a more mindful kitchen.</p>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium text-foreground">
              This month <b className="font-bold text-[#1E684A]">₹{data.wasteThisMonth}</b>
            </span>
            <Button size="sm" variant="outline" className="gap-2" onClick={() => setLogWasteOpen(true)}>
              <Plus size={15} />
              Log waste
            </Button>
          </div>
        </div>

        <div className="waste-table-card">
          <table className="waste-table">
            <thead>
              <tr>
                <th>Ingredient</th>
                <th>Quantity</th>
                <th>Reason</th>
                <th>Date</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {wasteEntries.length ? (
                wasteEntries.slice(0, 5).map((w) => (
                  <tr key={w.id}>
                    <td>
                      <strong>{w.name}</strong>
                    </td>
                    <td>{w.quantity || '—'}</td>
                    <td>
                      <span className="reason-chip">{w.reason || 'Unused'}</span>
                    </td>
                    <td>{shortDate(w.date)}</td>
                    <td>
                      <b>₹{w.value}</b>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="text-center py-6 text-muted-foreground">
                    No waste entries recorded this month.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <Footer />

      {/* Product View / Edit / Add Dialog */}
      {dialog && (
        <ProductDialog
          mode={dialog}
          onClose={() => setDialog(undefined)}
        />
      )}

      {/* Log waste dialog */}
      <Dialog open={logWasteOpen} onOpenChange={setLogWasteOpen}>
        <DialogContent className="dialog-body">
          <DialogTitle>Log wasted food</DialogTitle>
          <DialogDescription>
            Record what went unused to help refine next week's kitchen habits.
          </DialogDescription>
          {wasteError && <div role="alert" className="form-error">{wasteError}</div>}
          <form onSubmit={handleAddWaste} className="space-y-4">
            <div className="form-grid">
              <div className="field full">
                <label htmlFor="w-name">Ingredient name *</label>
                <input
                  id="w-name"
                  required
                  value={wasteForm.name}
                  onChange={(e) => setWasteForm({ ...wasteForm, name: e.target.value })}
                  placeholder="e.g. Whole wheat bread"
                />
              </div>
              <div className="field">
                <label htmlFor="w-qty">Quantity</label>
                <input
                  id="w-qty"
                  value={wasteForm.quantity}
                  onChange={(e) => setWasteForm({ ...wasteForm, quantity: e.target.value })}
                  placeholder="e.g. 2 slices"
                />
              </div>
              <div className="field">
                <label htmlFor="w-val">Approx. value (₹)</label>
                <input
                  id="w-val"
                  type="number"
                  min={0}
                  value={wasteForm.value}
                  onChange={(e) => setWasteForm({ ...wasteForm, value: e.target.value })}
                  placeholder="12"
                />
              </div>
              <div className="field">
                <label htmlFor="w-date">Date *</label>
                <input
                  id="w-date"
                  type="date"
                  required
                  value={wasteForm.date}
                  onChange={(e) => setWasteForm({ ...wasteForm, date: e.target.value })}
                />
              </div>
              <div className="field">
                <label htmlFor="w-reason">Reason</label>
                <input
                  id="w-reason"
                  value={wasteForm.reason}
                  onChange={(e) => setWasteForm({ ...wasteForm, reason: e.target.value })}
                  placeholder="e.g. Went stale"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="outline" onClick={() => setLogWasteOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={wasteBusy}>
                {wasteBusy ? <LoaderCircle className="animate-spin" /> : <Plus />}
                Add entry
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
