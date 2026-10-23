import { useState, useRef, useEffect, type ReactNode } from 'react';
import { Link, useRouterState } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import {
  Shield,
  Leaf,
  LayoutGrid,
  Box,
  CalendarDays,
  Calendar,
  BookOpen,
  ScanLine,
  History,
  CircleHelp,
  Settings,
  Bell,
  Search,
  ChevronDown,
  ChevronRight,
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
  Home,
  MoreVertical,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { settingsQuery, scansQuery, service, dashboardQuery } from '@/services/api';
import { displayDate, productStatus, daysFromToday } from '@/services/dates';
import type { Product, ProductStatus } from '@/services/types';
import { resolveFoodImage, categoryImages, tomatoesImg } from '@/services/food-images';
import { formatProductDisplayName } from './product-identity';

export function getTimeGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

export function getTimeEmoji(): string {
  const hour = new Date().getHours();
  if (hour < 12) return '☀️';
  if (hour < 17) return '🌤️';
  return '🌙';
}

export const primaryNav = [
  { to: '/', name: 'Overview', icon: LayoutGrid },
  { to: '/inventory', name: 'Inventory', icon: Box },
  { to: '/timeline', name: 'Expiry timeline', icon: CalendarDays },
  { to: '/waste', name: 'Waste journal', icon: BookOpen },
] as const;

export const scanNav = { to: '/scan', name: 'Scan Product', icon: ScanLine } as const;

export const settingsNav = [
  { to: '/history', name: 'Scanned History', icon: History },
  { to: '/review', name: 'Needs Review', icon: CircleHelp },
  { to: '/settings', name: 'Settings', icon: Settings },
] as const;

export const moreNav = settingsNav;

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
  const settingsActive = settingsNav.some((n) => n.to === pathname);

  async function find(value: string) {
    const run = ++searchSequence.current;
    setQuery(value);
    setSearching(true);
    const all = await service.getProducts();
    if (run !== searchSequence.current) return;
    const lower = value.toLowerCase().trim();
    setResults(
      all.filter((p) => {
        const display = formatProductDisplayName(p).toLowerCase();
        const rawName = (p.name || '').toLowerCase();
        const brand = (p.brand || '').toLowerCase();
        const cat = (p.category || '').toLowerCase();
        return display.includes(lower) || rawName.includes(lower) || brand.includes(lower) || cat.includes(lower);
      })
    );
    setSearching(false);
  }

  // Keyboard shortcut: Cmd+K / Ctrl+K opens quick inventory search
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setSearch((prev) => !prev);
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const today = new Date();
  const dateFormatted = today.toLocaleDateString('en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });

  return (
    <div className={`app-shell ${settings?.compact ? 'compact' : ''}`}>
      {/* 1. Left Vertical Navigation Sidebar */}
      <aside className={`app-sidebar ${menu ? 'mobile-open' : ''}`}>
        <div className="sidebar-brand">
          <Link to="/" className="sidebar-brand-link" onClick={() => setMenu(false)}>
            <img
              src="/annarakshak-logo.png"
              alt="AnnRakshak — Technology Jo Ann Ko Samjhe"
              className="sidebar-logo"
            />
          </Link>
        </div>

        <nav aria-label="Main navigation" className="sidebar-nav">
          <Link
            to="/"
            onClick={() => setMenu(false)}
            className={`sidebar-nav-item ${pathname === '/' ? 'active' : ''}`}
          >
            <Home size={18} />
            <span>Home</span>
          </Link>

          <Link
            to="/inventory"
            onClick={() => setMenu(false)}
            className={`sidebar-nav-item ${pathname === '/inventory' ? 'active' : ''}`}
          >
            <Box size={18} />
            <span>Inventory</span>
          </Link>

          <Link
            to="/scan"
            onClick={() => setMenu(false)}
            className={`sidebar-nav-item ${pathname === '/scan' ? 'active' : ''}`}
            aria-label="Scan ingredients"
            title="Scan ingredients"
          >
            <ScanLine size={18} />
            <span>Scan</span>
          </Link>

          <Link
            to="/timeline"
            onClick={() => setMenu(false)}
            className={`sidebar-nav-item ${pathname === '/timeline' ? 'active' : ''}`}
          >
            <CalendarDays size={18} />
            <span>Expiry</span>
          </Link>

          {/* Settings Nav Item with Dropdown Support */}
          <div className="sidebar-settings-group">
            <Link
              to="/settings"
              onClick={() => setMenu(false)}
              className={`sidebar-nav-item flex-1 ${settingsActive ? 'active' : ''}`}
            >
              <Settings size={18} />
              <span>Settings</span>
            </Link>

            <DropdownMenu>
              <DropdownMenuTrigger
                className={`sidebar-settings-trigger ${settingsActive ? 'active' : ''}`}
                aria-label="Open settings menu"
                title="Open settings menu"
              >
                <Settings size={17} />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-52">
                {settingsNav.map((n) => (
                  <DropdownMenuItem key={n.to} asChild>
                    <Link to={n.to} className="flex items-center gap-2" onClick={() => setMenu(false)}>
                      <n.icon size={16} />
                      {n.name}
                      {n.to === '/review' && count > 0 && <span className="nav-count">{count}</span>}
                    </Link>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </nav>
      </aside>

      {/* Backdrop for mobile drawer */}
      {menu && <div className="sidebar-backdrop" onClick={() => setMenu(false)} />}

      {/* 2. Main Content Area */}
      <div className="app-content-area">
        {/* Top Header Bar */}
        <header className="app-topbar">
          <div className="topbar-left">
            <button
              className="mobile-menu-toggle"
              aria-label={menu ? 'Close navigation' : 'Open navigation'}
              aria-expanded={menu}
              onClick={() => setMenu(!menu)}
            >
              {menu ? <X size={20} /> : <Menu size={20} />}
            </button>

            {/* Header Search Field */}
            <div
              className="topbar-search-pill"
              onClick={() => setSearch(true)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  setSearch(true);
                }
              }}
              aria-label="Search your inventory"
            >
              <Search size={15} className="search-icon" />
              <span className="search-placeholder">Search your inventory...</span>
              <kbd className="search-shortcut">⌘ K</kbd>
            </div>
          </div>

          <div className="topbar-right">
            {/* Date Display */}
            <div className="topbar-date">
              <Calendar size={15} />
              <span>{dateFormatted}</span>
            </div>

            {/* Notifications Bell */}
            <Link
              to="/review"
              className={`topbar-icon-btn ${count ? 'has-badge' : ''}`}
              aria-label={`${count} records need attention`}
              title={`${count} records need attention`}
            >
              <Bell size={18} />
              {count > 0 && <span className="notification-dot">{count}</span>}
            </Link>

            {/* Profile Avatar */}
            <div className="topbar-avatar" title="Ayush's Kitchen">
              A
            </div>
          </div>
        </header>

        {/* Routed Main Page */}
        <main className="app-main">{children}</main>
      </div>

      {/* Quick Search Dialog */}
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
  addLink,
  addLabel = 'Add Ingredients',
  addIcon,
  dateText,
}: {
  kicker?: string;
  title: string;
  description: string;
  onAdd?: () => void;
  addLink?: string;
  addLabel?: string;
  addIcon?: ReactNode;
  dateText?: string;
}) {
  const today = new Date();
  const formattedDate =
    dateText ||
    `${today.toLocaleDateString('en-GB', { weekday: 'long' })}, ${today.getDate()} ${today.toLocaleDateString('en-GB', { month: 'long' })}`;

  const icon = addIcon ?? <ScanLine size={17} />;

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
        {addLink ? (
          <Button asChild size="lg" className="add-btn">
            <Link to={addLink}>
              {icon}
              <span>{addLabel}</span>
            </Link>
          </Button>
        ) : onAdd ? (
          <Button size="lg" className="add-btn" onClick={onAdd}>
            <Plus size={17} />
            {addLabel === 'Add Ingredients' ? 'Add ingredient' : addLabel}
          </Button>
        ) : null}
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

export function WelcomeGreetingHero({
  freshnessPercent = 100,
  urgentCount = 0,
}: {
  freshnessPercent?: number;
  urgentCount?: number;
}) {
  const greeting = getTimeGreeting();
  const emoji = getTimeEmoji();
  const today = new Date();
  const formattedDate = `${today.toLocaleDateString('en-GB', { weekday: 'long' })}, ${today.getDate()} ${today.toLocaleDateString('en-GB', { month: 'long' })}`;
  const isWarning = urgentCount > 0;

  return (
    <div className="welcome-hero">
      <div>
        <div className="welcome-title-row">
          <h1>{greeting}! {emoji}</h1>
          <div className={`freshness-pulse-badge ${isWarning ? 'warning' : ''}`}>
            <span className={`pulse-dot ${isWarning ? 'warning' : ''}`} />
            <span>{freshnessPercent}% Fresh</span>
            <span className="opacity-75">· {urgentCount > 0 ? `${urgentCount} need attention` : 'All items good'}</span>
          </div>
        </div>
        <p>Your kitchen inventory is up to date and organized.</p>
      </div>

      <div className="greeting-actions">
        <span className="page-date">
          <CalendarDays size={16} />
          {formattedDate}
        </span>
        <Button asChild size="lg" className="add-btn">
          <Link to="/scan">
            <ScanLine size={17} />
            <span>Add Ingredients</span>
          </Link>
        </Button>
      </div>
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
      unit: '',
      icon: Box,
      iconClass: 'bg-[#E8F1E5] text-[#1E684A] border border-[#D5E3D3]',
      caption: 'Active items in stock',
      to: '/inventory' as const,
      warm: false,
    },
    {
      label: 'Use first',
      value: String(data.expiring.length),
      unit: '',
      icon: Clock,
      iconClass: 'bg-[#FEF3C7] text-[#D97706] border border-[#FDE68A]',
      caption: data.expiring.length > 0 ? 'Within 7 days' : 'No urgent items',
      to: '/timeline' as const,
      warm: data.expiring.length > 0,
    },
    {
      label: 'Inventory value',
      value: `₹${data.inventoryValue}`,
      unit: '',
      icon: Sprout,
      iconClass: 'bg-[#E8F1E5] text-[#1E684A] border border-[#D5E3D3]',
      caption: 'Tracked pantry value',
      to: '/inventory' as const,
      warm: false,
    },
    {
      label: 'Waste this month',
      value: `₹${data.wasteThisMonth}`,
      unit: '',
      icon: TrendingDown,
      iconClass: 'bg-[#F3F4F6] text-[#4B5563] border border-[#E5E7EB]',
      caption: `${data.wasteEntries} ${data.wasteEntries === 1 ? 'item' : 'items'} wasted`,
      to: '/waste' as const,
      warm: false,
    },
  ];

  return (
    <div className="metrics-grid">
      {metrics.map((m) => (
        <Link to={m.to} className="metric-card" key={m.label}>
          <div className="metric-card-top">
            <span className="metric-label">{m.label}</span>
            <div className={`metric-icon-wrap ${m.iconClass}`}>
              <m.icon size={18} />
            </div>
          </div>
          <div className="metric-value-wrap">
            <span className={`metric-number ${m.warm ? 'warm' : ''}`}>{m.value}</span>
          </div>
          <div className="metric-caption">
            <span>{m.caption}</span>
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
  const displayName = formatProductDisplayName(product);

  return (
    <button
      className="inv-card"
      onClick={onClick}
      aria-label={`Open ${displayName}`}
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
        {/* Floating pill badge on image top-left matching reference image */}
        <div className="inv-floating-badge">
          {urgent ? (
            <span className="badge-pill warning">
              <span className="dot" />
              Expiring Soon
            </span>
          ) : (
            <span className="badge-pill fresh">
              <span className="dot" />
              Fresh
            </span>
          )}
        </div>

        {product.imageStatus === 'searching' && (
          <span className="cat-chip ml-1 text-[10px] bg-sky-950/80 text-sky-200">Finding image…</span>
        )}
        {product.imageStatus === 'retry_scheduled' && (
          <span className="cat-chip ml-1 text-[10px] bg-amber-950/80 text-amber-200">Retry queued</span>
        )}
        {product.imageSourceType === 'generated' && (
          <span className="cat-chip ml-1 text-[10px] bg-emerald-950/80 text-emerald-200" title="Studio AI photograph">AI Studio</span>
        )}
      </div>
      <div className="inv-body">
        <div className="inv-title-row">
          <strong>{displayName}</strong>
          <MoreVertical size={16} className="text-muted-foreground hover:text-foreground" />
        </div>
        <div className="food-meta">
          {product.quantity && <span>{product.quantity}</span>}
          {product.quantity && <span>•</span>}
          <span className="inline-flex items-center gap-1">
            <Refrigerator size={12} />
            {product.storage || 'Fridge'}
          </span>
        </div>
        <div className="inv-status-row">
          <span className={`use-badge ${isSafe ? 'safe' : ''}`}>
            • {dayLabel(d)}
          </span>
        </div>
        <div className="inv-confirmed-foot">
          {product.verified ? `Confirmed expiry • ${formattedExpiry}` : 'Expiry not recorded'}
        </div>
      </div>
    </button>
  );
}

export function ProductCell({ product }: { product: Pick<Product, 'image' | 'name' | 'brand' | 'category'> & { displayName?: string } }) {
  const imgSrc = resolveFoodImage(product);
  const fallbackSrc = categoryImages[product.category || 'Pantry Staples'] || tomatoesImg;
  const displayName = formatProductDisplayName(product);
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
        <div className="product-name">{displayName}</div>
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
        AnnRakShak · Smart Kitchen Inventory
      </span>
      <span>Keep your kitchen fresh and organized</span>
    </footer>
  );
}
