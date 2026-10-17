import { useState, useEffect } from 'react';
import { useSuspenseQuery } from '@tanstack/react-query';
import { useSearch } from '@tanstack/react-router';
import { Search, Plus, ArrowRight } from 'lucide-react';
import { productsQuery } from '@/services/api';
import { categories, type Product } from '@/services/types';
import { daysFromToday } from '@/services/dates';
import {
  Empty,
  Footer,
  PageHero,
  StatCardsRow,
  InventoryPhotoCard,
} from './common';
import { ProductDialog, type ProductDialogMode } from './product-dialog';

const tabs = [
  { label: 'All items', match: () => true },
  { label: 'Vegetables', match: (p: Product) => p.produce === 'Vegetable' || p.category === 'Fresh Produce' },
  { label: 'Dairy', match: (p: Product) => p.category === 'Dairy & Eggs' },
  { label: 'Fruit', match: (p: Product) => p.produce === 'Fruit' },
  { label: 'Pantry', match: (p: Product) => p.category === 'Pantry Staples' || p.category === 'Grains & Cereals' },
] as const;

export function Inventory() {
  const { data } = useSuspenseQuery(productsQuery);
  const search = useSearch({ from: '/inventory' });

  const initialCategory = categories.find((c) => c === search.q);
  const [query, setQuery] = useState(initialCategory ? '' : search.q || '');
  const [tab, setTab] = useState<string>('All items');
  const [dialog, setDialog] = useState<ProductDialogMode>();

  useEffect(() => {
    if (search.q) {
      const c = categories.find((cat) => cat === search.q);
      if (c) {
        if (c === 'Dairy & Eggs') setTab('Dairy');
        else if (c === 'Fresh Produce') setTab('Vegetables');
        else if (c === 'Pantry Staples' || c === 'Grains & Cereals') setTab('Pantry');
      } else {
        setQuery(search.q);
      }
    }
  }, [search.q]);

  const filter = tabs.find((t) => t.label === tab)?.match ?? (() => true);
  const rows = data
    .filter(
      (p) => filter(p) && (!query || `${p.name} ${p.brand}`.toLowerCase().includes(query.toLowerCase()))
    )
    .sort((a, b) => {
      const dayA = a.verified && a.date ? daysFromToday(a.date) : Infinity;
      const dayB = b.verified && b.date ? daysFromToday(b.date) : Infinity;
      return dayA - dayB;
    });

  return (
    <div className="page inventory-page">
      <PageHero
        title="Everything in your kitchen."
        description="Know what you have, and what needs your attention."
        onAdd={() => setDialog({ type: 'add' })}
      />

      <StatCardsRow />

      <section className="section">
        <div className="section-head">
          <h2>
            Your inventory <span className="muted-count">({data.length})</span>
          </h2>
          <button
            onClick={() => setDialog({ type: 'add' })}
            className="text-link bg-transparent border-0 p-0 cursor-pointer"
          >
            Add ingredient <ArrowRight size={16} />
          </button>
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

        {rows.length ? (
          <div className="inv-grid">
            {rows.map((p) => (
              <InventoryPhotoCard
                key={p.id}
                product={p}
                onClick={() => setDialog({ type: 'view', product: p })}
              />
            ))}
          </div>
        ) : (
          <div className="panel">
            <Empty
              title={data.length ? 'No matching ingredients' : 'Your inventory is ready'}
              message={
                data.length
                  ? 'Try adjusting your search query or switching categories.'
                  : 'Start tracking your kitchen by adding your first ingredient.'
              }
            >
              <button
                className="add-btn mt-3"
                onClick={() => {
                  if (!data.length) setDialog({ type: 'add' });
                  else {
                    setQuery('');
                    setTab('All items');
                  }
                }}
              >
                <Plus size={16} />
                {data.length ? 'Clear filters' : 'Add ingredient'}
              </button>
            </Empty>
          </div>
        )}
      </section>

      <Footer />

      {dialog && (
        <ProductDialog
          key={`${dialog.type}-${'product' in dialog ? dialog.product.id : ''}`}
          mode={dialog}
          onClose={() => setDialog(undefined)}
        />
      )}
    </div>
  );
}
