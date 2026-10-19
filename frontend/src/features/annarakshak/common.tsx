import { useState, useRef, type ReactNode } from 'react';
import { Link, useRouterState } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import {
  Shield,
  Leaf,
  LayoutGrid,
  Box,
  CalendarDays,
  BookOpen,
  ScanLine,
  History,
  CircleHelp,
  Settings,
  Bell,
  Search,
  ChevronDown,
  Menu,
  X,
  ArrowRight,
  ArrowUpRight,
  Refrigerator,
  CircleCheck,
  Clock,
  TriangleAlert,
  LoaderCircle,
  Sprout,
  TrendingDown,
  Plus,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { settingsQuery, scansQuery, service, dashboardQuery } from '@/services/api';
import { displayDate, productStatus, daysFromToday } from '@/services/dates';
import type { Product, ProductStatus } from '@/services/types';
import { resolveFoodImage, categoryImages, tomatoesImg } from '@/services/food-images';

export const primaryNav = [
  { to: '/', name: 'Overview', icon: LayoutGrid },
  { to: '/inventory', name: 'Inventory', icon: Box },
  { to: '/timeline', name: 'Expiry timeline', icon: CalendarDays },
  { to: '/waste', name: 'Waste journal', icon: BookOpen },
] as const;

export const moreNav = [
  { to: '/scan', name: 'Scan Product', icon: ScanLine },
  { to: '/history', name: 'Scan History', icon: History },
  { to: '/review', name: 'Needs Review', icon: CircleHelp },
  { to: '/settings', name: 'Settings', icon: Settings },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [menu, setMenu] = useState(false);
  const [search, setSearch] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Product[]>([]);
  const [searching, setSearching] = useState(false);
  const searchSequence = useRef(0);

  const { data: settings } = useQuery(settingsQuery);
  const { data: scans } = useQuery(scansQuery);
  const count = scans?.filter((s) => s.reviewStatus === 'Needs Review').length || 0;
  const moreActive = moreNav.some((n) => n.to === pathname);

  async function find(value: string) {
    const run = ++searchSequence.current;
    setQuery(value);
    setSearching(true);
    const all = await service.getProducts();
    if (run !== searchSequence.current) return;
    setResults(all.filter((p) => `${p.name} ${p.brand}`.toLowerCase().includes(value.toLowerCase())));
    setSearching(false);
  }

  return (
    <div className={`app-shell ${settings?.compact ? 'compact' : ''}`}>
      <header className="topnav">
        <div className="topnav-inner">
          <Link to="/" className="brand" onClick={() => setMenu(false)}>
            <span className="brand-icon">
              <Shield size={32} strokeWidth={1.8} />
              <Leaf className="leaf" strokeWidth={2.2} />
            </span>
            <span className="brand-name">AnnRakshak</span>
          </Link>

          <nav aria-label="Main navigation" className="topnav-links">
            {primaryNav.map((n) => (
              <Link
                key={n.to}
                to={n.to}
                className={`nav-item ${pathname === n.to ? 'active' : ''}`}
              >
                <n.icon />
                <span>{n.name}</span>
              </Link>
            ))}

            {/* Subtle dropdown for advanced routes */}
            <DropdownMenu>
              <DropdownMenuTrigger
                className={`nav-item opacity-80 hover:opacity-100 ${moreActive ? 'active opacity-100' : ''}`}
                aria-label="More options"
              >
                <ChevronDown size={14} />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-52">
                {moreNav.map((n) => (
                  <DropdownMenuItem key={n.to} asChild>
                    <Link to={n.to} className="flex items-center gap-2">
                      <n.icon size={16} />
                      {n.name}
                      {n.to === '/review' && count > 0 && <span className="nav-count">{count}</span>}
                    </Link>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </nav>

          <div className="topnav-tools">
            <Link
              to="/review"
              className={`icon-btn ${count ? 'notification' : ''}`}
              aria-label={`${count} records need attention`}
              title={`${count} records need attention`}
            >
              <Bell size={19} />
            </Link>
            <span className="topnav-divider" />
            <span className="avatar" title="My kitchen">
              MK
            </span>
            <button
              className="icon-btn mobile-menu"
              aria-label={menu ? 'Close navigation' : 'Open navigation'}
              aria-expanded={menu}
              onClick={() => setMenu(!menu)}
            >
              {menu ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
        </div>

        {menu && (
          <nav aria-label="Mobile navigation" className="mobile-nav">
            {[...primaryNav, ...moreNav].map((n) => (
              <Link
                key={n.to}
                to={n.to}
                onClick={() => setMenu(false)}
                className={`nav-item ${pathname === n.to ? 'active' : ''}`}
              >
                <n.icon />
                <span>{n.name}</span>
                {n.to === '/review' && count > 0 && <span className="nav-count">{count}</span>}
              </Link>
            ))}
          </nav>
        )}
      </header>

      <main className="app-main">{children}</main>

      <Dialog open={search} onOpenChange={setSearch}>
        <DialogContent>
          <DialogTitle>Search inventory</DialogTitle>
          <DialogDescription>Find a product by its name or brand.</DialogDescription>
          <div className="search-input">
            <Search />
            <input
              autoFocus
              aria-label="Search inventory"
              value={query}
              onChange={(e) => void find(e.target.value)}
              placeholder="Product name or brand"
            />
          </div>
          {searching ? (
            <Loading />
          ) : results.length ? (
            <div className="max-h-80 overflow-y-auto">
              {results.map((p) => (
                <Link
                  key={p.id}
                  to="/inventory"
                  search={{ q: p.name }}
                  onClick={() => setSearch(false)}
                  className="review-row"
                >
                  <ProductCell product={p} />
                  <ArrowRight size={15} className="ml-auto text-primary" />
                </Link>
              ))}
            </div>
          ) : (
            <Empty title="No products found" message="Try another product name or brand." />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function PageHero({
  kicker = 'MY KITCHEN',
  title,
  description,
  onAdd,
  dateText,
}: {
  kicker?: string;
  title: string;
  description: string;
  onAdd?: () => void;
  dateText?: string;
}) {
  const today = new Date();
  const formattedDate =
    dateText ||
    `${today.toLocaleDateString('en-GB', { weekday: 'long' })}, ${today.getDate()} ${today.toLocaleDateString('en-GB', { month: 'long' })}`;

  return (
    <div className="greeting">
      <div>
        <div className="kicker">
          {kicker} <ChevronDown size={14} />
        </div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="greeting-actions">
        <span className="page-date">
          <CalendarDays size={16} />
          {formattedDate}
        </span>
        {onAdd && (
          <Button size="lg" className="add-btn" onClick={onAdd}>
            <Plus size={17} />
            Add ingredient
          </Button>
        )}
      </div>
    </div>
  );
}

export function PageIntro({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <div className="greeting">
      <div>
        <div className="kicker">
          MY KITCHEN <ChevronDown size={14} />
        </div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {children && <div className="greeting-actions">{children}</div>}
    </div>
  );
}

export function StatCardsRow() {
  const { data } = useQuery(dashboardQuery);
  if (!data) return null;

  const metrics = [
    {
      label: 'In your inventory',
      value: String(data.total),
      unit: 'items',
      icon: Box,
      caption: 'A well-stocked, thoughtful kitchen',
      to: '/inventory' as const,
      warm: false,
    },
    {
      label: 'Use first',
      value: String(data.expiring.length),
      unit: 'items',
      icon: Clock,
      caption: 'A little attention goes a long way',
      to: '/timeline' as const,
      warm: true,
      clock: true,
    },
    {
      label: 'Inventory value',
      value: `₹${data.inventoryValue}`,
      unit: '',
      icon: Sprout,
      caption: 'Good food, worth taking care of',
      to: '/inventory' as const,
      warm: false,
    },
    {
      label: 'Waste this month',
      value: `₹${data.wasteThisMonth}`,
      unit: '',
      icon: TrendingDown,
      caption: `${data.wasteEntries} ${data.wasteEntries === 1 ? 'entry' : 'entries'} in your waste journal`,
      to: '/waste' as const,
      warm: false,
    },
  ];

  return (
    <div className="metrics">
      {metrics.map((m) => (
        <Link to={m.to} className="metric" key={m.label}>
          <div className="metric-top">
            <span>{m.label}</span>
            <m.icon />
          </div>
          <div className="metric-value">
            <b className={m.warm ? 'warm' : ''}>{m.value}</b>
            {m.unit && <span>{m.unit}</span>}
          </div>
          <div className="metric-sub">
            {m.clock ? '🕒' : '↳'} {m.caption}
          </div>
        </Link>
      ))}
    </div>
  );
}

export function shortCategory(p: Product): string {
  if (p.produce === 'Vegetable') return 'Vegetables';
  if (p.produce === 'Fruit') return 'Fruit';
  if (p.category === 'Dairy & Eggs') return 'Dairy';
  if (p.category === 'Pantry Staples' || p.category === 'Grains & Cereals') return 'Pantry';
  if (p.category === 'Fresh Produce') return 'Vegetables';
  return p.category;
}

export function dayLabel(days: number): string {
  return days === 0 ? 'Use today' : days === 1 ? 'Use tomorrow' : `${days} days left`;
}

export function InventoryPhotoCard({
  product,
  onClick,
}: {
  product: Product;
  onClick: () => void;
}) {
  const d = daysFromToday(product.date);
  const urgent = d <= 2;
  const isSafe = d > 2;
  const imgSrc = resolveFoodImage(product);
  const fallbackSrc = categoryImages[product.category || 'Pantry Staples'] || tomatoesImg;
  const formattedExpiry = new Date(`${product.date}T00:00:00`).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
  });

  return (
    <button
      className="inv-card"
      onClick={onClick}
      aria-label={`Open ${product.name}`}
    >
      <div className="inv-img">
        <img
          src={imgSrc}
          alt=""
          width={320}
          height={240}
          loading="lazy"
          onError={(e) => {
            const target = e.currentTarget;
            if (target.src !== fallbackSrc && !target.src.endsWith(fallbackSrc)) {
              target.src = fallbackSrc;
            }
          }}
        />
        <span className="cat-chip">{shortCategory(product)}</span>
      </div>
      <div className="inv-body">
        <div className="inv-title-row">
          <strong>{product.name}</strong>
          <ArrowUpRight size={16} />
        </div>
        <div className="food-meta">
          {product.quantity && <span>{product.quantity}</span>}
          {product.quantity && <span>·</span>}
          <span className="inline-flex items-center gap-1">
            <Refrigerator size={12} />
            {product.storage || 'Fridge'}
          </span>
        </div>
        <div className="inv-status-row">
          <span className={`use-badge ${isSafe ? 'safe' : ''}`}>
            • {dayLabel(d)}
          </span>
          <CircleCheck size={16} className="text-emerald-700" />
        </div>
        <div className="inv-confirmed-foot">
          Confirmed expiry · {formattedExpiry}
        </div>
      </div>
    </button>
  );
}

export function ProductCell({ product }: { product: Pick<Product, 'image' | 'name' | 'brand' | 'category'> }) {
  const imgSrc = resolveFoodImage(product);
  const fallbackSrc = categoryImages[product.category || 'Pantry Staples'] || tomatoesImg;
  return (
    <div className="product-cell">
      <img
        src={imgSrc}
        width={44}
        height={48}
        alt=""
        className="product-thumb"
        loading="lazy"
        onError={(e) => {
          const target = e.currentTarget;
          if (target.src !== fallbackSrc && !target.src.endsWith(fallbackSrc)) {
            target.src = fallbackSrc;
          }
        }}
      />
      <div>
        <div className="product-name">{product.name}</div>
        <div className="product-brand">{product.brand || 'No brand specified'}</div>
      </div>
    </div>
  );
}

export function StatusBadge({
  status,
}: {
  status: ProductStatus | 'Successful' | 'Failed' | 'Confirmed' | 'Analyzing';
}) {
  const danger = ['Expired', 'Best Before Passed', 'Failed'].includes(status);
  const warn = ['Needs Review', 'Expires Today', 'Expiring Soon', 'Best Before Today', 'Best Before Soon'].includes(
    status
  );
  const neutral = ['Unknown', 'Manufactured', 'Packed'].includes(status);
  const Icon = danger ? TriangleAlert : warn ? Clock : neutral ? CalendarDays : CircleCheck;
  return (
    <span className={`status status-${danger ? 'danger' : warn ? 'warning' : neutral ? 'neutral' : 'safe'}`}>
      <Icon />
      {status}
    </span>
  );
}

export function ProductDate({ product }: { product: Product }) {
  const { data: settings } = useQuery(settingsQuery);
  return (
    <div>
      <div className="text-xs font-medium">
        {product.verified ? displayDate(product.date, settings?.dateFormat === 'long') : 'Not confirmed'}
      </div>
      <div className="text-[10px] text-muted-foreground mt-1 date-type">
        {product.dateType}
        {!product.verified ? ' · needs review' : ''}
      </div>
    </div>
  );
}

export function ProductBadge({ product }: { product: Product }) {
  const { data: settings } = useQuery(settingsQuery);
  return <StatusBadge status={productStatus(product, settings?.alertWindow)} />;
}

export function PanelHead({
  title,
  subtitle,
  children,
}: {
  title: ReactNode;
  subtitle?: string;
  children?: ReactNode;
}) {
  return (
    <div className="panel-head">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

export function Loading() {
  return (
    <div className="loading">
      <LoaderCircle size={20} className="animate-spin" />
      Loading your workspace…
    </div>
  );
}

export function Empty({
  title,
  message,
  children,
}: {
  title: string;
  message: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <Box size={32} />
      <h3>{title}</h3>
      <p className="text-xs mb-4">{message}</p>
      {children}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <div className="empty-state">
      <TriangleAlert size={30} />
      <h3>Something didn’t load</h3>
      <p className="mb-4">{error instanceof Error ? error.message : 'Please try again.'}</p>
      <Button variant="outline" onClick={retry}>
        Try again
      </Button>
    </div>
  );
}

export function Footer() {
  return (
    <footer className="footer-minimal">
      <span>
        <Leaf size={14} />
        Less waste. More possibility.
      </span>
      <span>Sample kitchen · October 2026 / Made with care, AnnRakShak</span>
    </footer>
  );
}
