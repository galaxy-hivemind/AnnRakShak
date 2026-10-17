import { useState, type FormEvent } from 'react';
import { useQueryClient, useSuspenseQuery } from '@tanstack/react-query';
import { Plus, Trash2, LoaderCircle, BookOpen } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { service, wasteQuery } from '@/services/api';
import { localISO } from '@/services/dates';
import { PageHero, StatCardsRow, Footer } from './common';

const blank = () => ({ name: '', quantity: '', value: '', reason: '', date: localISO() });

const shortDate = (iso: string) => {
  try {
    return new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  } catch {
    return iso;
  }
};

export function WasteJournal() {
  const { data } = useSuspenseQuery(wasteQuery);
  const qc = useQueryClient();
  const [form, setForm] = useState(blank());
  const [dialogOpen, setDialogOpen] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const month = localISO().slice(0, 7);
  const monthTotal = data.filter((w) => w.date.startsWith(month)).reduce((t, w) => t + w.value, 0);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError('');
    if (!form.name.trim()) {
      setError('Please specify what was wasted.');
      return;
    }
    setBusy(true);
    try {
      await service.addWasteEntry({
        name: form.name.trim(),
        quantity: form.quantity.trim(),
        value: Number(form.value || 0),
        reason: form.reason.trim() || 'Unused',
        date: form.date,
      });
      await qc.invalidateQueries();
      setForm(blank());
      setDialogOpen(false);
      toast.success('Added to your waste journal');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save entry.');
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    await service.deleteWasteEntry(id);
    await qc.invalidateQueries();
    toast.success('Entry removed');
  }

  return (
    <div className="page waste-page">
      <PageHero
        title="Waste journal"
        description="Small reflections for a more mindful kitchen."
        onAdd={() => setDialogOpen(true)}
      />

      <StatCardsRow />

      <section className="waste-section">
        <div className="section-head">
          <div>
            <h2>
              <BookOpen />
              Waste journal
            </h2>
            <p>Every logged item helps buy a little smarter next week.</p>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium text-foreground">
              This month <b className="font-bold">₹{monthTotal}</b>
            </span>
            <Button size="sm" variant="outline" className="gap-2" onClick={() => setDialogOpen(true)}>
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
                <th className="w-12 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.length ? (
                data.map((w) => (
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
                    <td className="text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Remove ${w.name}`}
                        onClick={() => void remove(w.id)}
                      >
                        <Trash2 size={16} />
                      </Button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="text-center py-8 text-muted-foreground">
                    Nothing logged yet. That's great! When something goes unused, log it here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <Footer />

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="dialog-body">
          <DialogTitle>Log wasted food</DialogTitle>
          <DialogDescription>
            Record what went unused to help refine next week's kitchen habits.
          </DialogDescription>
          {error && <div role="alert" className="form-error">{error}</div>}
          <form onSubmit={add} className="space-y-4">
            <div className="form-grid">
              <div className="field full">
                <label htmlFor="w-name">Ingredient name *</label>
                <input
                  id="w-name"
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="e.g. Whole wheat bread"
                />
              </div>
              <div className="field">
                <label htmlFor="w-qty">Quantity</label>
                <input
                  id="w-qty"
                  value={form.quantity}
                  onChange={(e) => setForm({ ...form, quantity: e.target.value })}
                  placeholder="e.g. 2 slices"
                />
              </div>
              <div className="field">
                <label htmlFor="w-val">Approx. value (₹)</label>
                <input
                  id="w-val"
                  type="number"
                  min={0}
                  value={form.value}
                  onChange={(e) => setForm({ ...form, value: e.target.value })}
                  placeholder="12"
                />
              </div>
              <div className="field">
                <label htmlFor="w-date">Date *</label>
                <input
                  id="w-date"
                  type="date"
                  required
                  value={form.date}
                  onChange={(e) => setForm({ ...form, date: e.target.value })}
                />
              </div>
              <div className="field">
                <label htmlFor="w-reason">Reason</label>
                <input
                  id="w-reason"
                  value={form.reason}
                  onChange={(e) => setForm({ ...form, reason: e.target.value })}
                  placeholder="e.g. Went stale"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={busy}>
                {busy ? <LoaderCircle className="animate-spin" /> : <Plus />}
                Add entry
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
