import { useState, type FormEvent } from 'react';
import { useSuspenseQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import {
  Flame,
  ArrowRight,
  ArrowUpRight,
  Refrigerator,
  Search,
  CalendarDays,
  CircleCheck,
  BookOpen,
  Plus,
  LoaderCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { toast } from 'sonner';
import { dashboardQuery, productsQuery, settingsQuery, wasteQuery, service } from '@/services/api';
import { daysFromToday, localISO } from '@/services/dates';
import type { Product } from '@/services/types';
import { resolveFoodImage } from '@/services/food-images';
import {
  Empty,
  Footer,
  PageHero,
  StatCardsRow,
  InventoryPhotoCard,
  dayLabel,
} from './common';
import { ProductDialog, type ProductDialogMode } from './product-dialog';

const tabs = [
  { label: 'All items', match: () => true },
  { label: 'Vegetables', match: (p: Product) => p.produce === 'Vegetable' || p.category === 'Fresh Produce' },
  { label: 'Dairy', match: (p: Product) => p.category === 'Dairy & Eggs' },
  { label: 'Fruit', match: (p: Product) => p.produce === 'Fruit' },
  { label: 'Pantry', match: (p: Product) => p.category === 'Pantry Staples' || p.category === 'Grains & Cereals' },
] as const;

const shortDate = (iso: string) => {
  try {
    return new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
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
  const [tab, setTab] = useState<string>('All items');
  const [query, setQuery] = useState('');
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

  const today = new Date();
  const end = new Date();
  end.setDate(end.getDate() + settings.alertWindow);
  const range = `${today.getDate()} – ${end.getDate()} ${end.toLocaleDateString('en-GB', { month: 'long' })}`;

  const useFirst = data.expiring.slice(0, 2);
  const filter = tabs.find((t) => t.label === tab)?.match ?? (() => true);
  const list = products.filter(
    (p) => filter(p) && (!query || `${p.name} ${p.brand}`.toLowerCase().includes(query.toLowerCase()))
  );

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
    <div className="page overview">
      <PageHero
        title="A little care. A lot less waste."
        description="Keep your kitchen fresh and make every ingredient count."
        addLink="/scan"
        addLabel="Add Ingredients"
      />

      <StatCardsRow />

      {/* Use First Section */}
      <section className="section">
        <div className="section-head">
          <div>
            <h2>
              <Flame />
              Use First
              {data.expiring.length > 0 && (
                <span className="attention">{data.expiring.length} need attention</span>
              )}
            </h2>
            <p>Good ingredients. Just a little less time.</p>
          </div>
          <Link to="/timeline" className="text-link">
            View all expiring <ArrowRight size={16} />
          </Link>
        </div>

        {useFirst.length ? (
          <div className="use-first">
            {useFirst.map((p) => {
              const d = daysFromToday(p.date);
              const imgSrc = resolveFoodImage(p);
              return (
                <button
                  key={p.id}
                  className="food-row"
                  onClick={() => setDialog({ type: 'view', product: p })}
                  aria-label={`Open ${p.name}`}
                >
                  <img src={imgSrc} alt="" width={126} height={126} loading="lazy" />
                  <div className="food-row-body">
                    <div>
                      <div className="flex items-start justify-between gap-2">
                        <strong>{p.name}</strong>
                        <ArrowUpRight size={16} />
                      </div>
                      <div className="food-meta">
                        {p.quantity && <span>{p.quantity}</span>}
                        {p.quantity && <span>·</span>}
                        <span className="inline-flex items-center gap-1">
                          <Refrigerator size={12} />
                          {p.storage || 'Fridge'}
                        </span>
                      </div>
                    </div>
                    <div className="food-row-foot">
                      <span className="use-badge">• {dayLabel(d)}</span>
                      <span className="food-date">{shortDate(p.date)}</span>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        ) : (
          <Empty title="Nothing needs using up" message="No confirmed dates fall within your alert window." />
        )}
      </section>

      {/* Lower Two-Column Section: Inventory & Upcoming Expiry */}
      <div className="lower">
        <section>
          <div className="section-head">
            <h2>
              Your inventory <span className="muted-count">({data.total})</span>
            </h2>
            <Link to="/inventory" search={{ q: '' }} className="text-link">
              View inventory <ArrowRight size={16} />
            </Link>
          </div>

          <div className="inv-toolbar">
            <div role="tablist" aria-label="Filter by type" className="tabs">
              {tabs.map((t) => (
                <button
                  key={t.label}
                  role="tab"
                  aria-selected={tab === t.label}
                  className={tab === t.label ? 'active' : ''}
                  onClick={() => setTab(t.label)}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="search-input small">
              <Search />
              <input
                aria-label="Search ingredients"
                placeholder="Search ingredients"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
          </div>

          {list.length ? (
            <div className="inv-grid">
              {list.slice(0, 6).map((p) => (
                <InventoryPhotoCard
                  key={p.id}
                  product={p}
                  onClick={() => setDialog({ type: 'view', product: p })}
                />
              ))}
            </div>
          ) : (
            <Empty title="No matching ingredients" message="Try another tab or search term." />
          )}
        </section>

        {/* Right column: Upcoming expiry */}
        <aside className="upcoming">
          <h2>
            <CalendarDays />
            Upcoming expiry
          </h2>
          <div className="upcoming-sub">
            <span>{range}</span>
            <span className="inline-flex items-center gap-1">
              <CircleCheck size={14} className="text-emerald-700" />
              Confirmed dates
            </span>
          </div>

          {data.expiring.length ? (
            <ol className="timeline">
              {data.expiring.slice(0, 4).map((p) => {
                const d = daysFromToday(p.date);
                const isUrgent = d <= 1;
                const label =
                  d === 0
                    ? 'Today'
                    : d === 1
                    ? 'Tomorrow'
                    : new Date(`${p.date}T00:00:00`).toLocaleDateString('en-GB', { weekday: 'long' });
                const imgSrc = resolveFoodImage(p);

                return (
                  <li key={p.id} className={isUrgent ? 'tomorrow' : ''}>
                    <div className="tl-head">
                      <b>{label}</b>
                      <span>{shortDate(p.date)}</span>
                    </div>
                    <button
                      className="tl-item"
                      onClick={() => setDialog({ type: 'view', product: p })}
                      aria-label={`Open ${p.name}`}
                    >
                      <img src={imgSrc} alt="" width={40} height={40} loading="lazy" />
                      <div className="min-w-0 flex-1 text-left">
                        <strong>{p.name}</strong>
                        <div className="food-meta">
                          {[p.quantity, p.storage || 'Fridge'].filter(Boolean).join(' · ')}
                        </div>
                      </div>
                      <ArrowRight size={16} />
                    </button>
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className="text-xs text-muted-foreground mt-4">
              No confirmed dates in the next {settings.alertWindow} days.
            </p>
          )}
        </aside>
      </div>

      {/* Waste Journal Section (Screenshot 2) */}
      <section className="waste-section">
        <div className="section-head">
          <div>
            <h2>
              <BookOpen />
              Waste journal
            </h2>
            <p>Small reflections for a more mindful kitchen.</p>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium text-foreground">
              This month <b className="font-bold">₹{data.wasteThisMonth}</b>
            </span>
            <Button size="sm" variant="outline" className="gap-2" onClick={() => setLogWasteOpen(true)}>
              <Plus size={15} />
              Log waste
            </Button>
          </div>
        </div>

        <div className="waste-card">
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
