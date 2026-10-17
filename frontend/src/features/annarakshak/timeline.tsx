import { useState } from 'react';
import { useSuspenseQuery } from '@tanstack/react-query';
import { CalendarDays, CircleCheck, ArrowRight } from 'lucide-react';
import { productsQuery, settingsQuery } from '@/services/api';
import { daysFromToday, isExactDate } from '@/services/dates';
import type { Product } from '@/services/types';
import { resolveFoodImage } from '@/services/food-images';
import {
  Empty,
  Footer,
  PageHero,
  StatCardsRow,
} from './common';
import { ProductDialog, type ProductDialogMode } from './product-dialog';

const shortDate = (iso: string) => {
  try {
    return new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  } catch {
    return iso;
  }
};

export function ExpiryTimeline() {
  const { data } = useSuspenseQuery(productsQuery);
  const { data: settings } = useSuspenseQuery(settingsQuery);
  const [dialog, setDialog] = useState<ProductDialogMode>();

  const today = new Date();
  const end = new Date();
  end.setDate(end.getDate() + settings.alertWindow);
  const range = `${today.getDate()} – ${end.getDate()} ${end.toLocaleDateString('en-GB', { month: 'long' })}`;

  // Filter confirmed expiry dates
  const dated = data
    .filter((p) => p.verified && isExactDate(p.date) && ['Expiry', 'Use By', 'Best Before'].includes(p.dateType))
    .sort((a, b) => daysFromToday(a.date) - daysFromToday(b.date));

  return (
    <div className="page timeline-page">
      <PageHero
        title="Freshness, at a glance."
        description="Your confirmed expiry dates, in order."
        onAdd={() => setDialog({ type: 'add' })}
      />

      <StatCardsRow />

      <section className="section max-w-3xl">
        <div className="section-head">
          <h2>
            <CalendarDays />
            Upcoming expiry
          </h2>
        </div>

        <div className="upcoming-sub">
          <span>{range}</span>
          <span className="inline-flex items-center gap-1">
            <CircleCheck size={14} className="text-emerald-700" />
            Confirmed dates
          </span>
        </div>

        {dated.length ? (
          <ol className="timeline">
            {dated.map((p: Product) => {
              const d = daysFromToday(p.date);
              const isUrgent = d <= 1;
              const label =
                d < 0
                  ? 'Expired'
                  : d === 0
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
                    <img src={imgSrc} alt="" width={44} height={44} loading="lazy" />
                    <div className="min-w-0 flex-1 text-left">
                      <strong>{p.name}</strong>
                      <div className="food-meta">
                        {[p.quantity, p.storage || 'Fridge'].filter(Boolean).join(' · ')}
                      </div>
                    </div>
                    <ArrowRight size={17} />
                  </button>
                </li>
              );
            })}
          </ol>
        ) : (
          <Empty
            title="No confirmed dates yet"
            message="Add a product or confirm a scan to build your upcoming timeline."
          />
        )}
      </section>

      <Footer />

      {dialog && (
        <ProductDialog
          mode={dialog}
          onClose={() => setDialog(undefined)}
        />
      )}
    </div>
  );
}
