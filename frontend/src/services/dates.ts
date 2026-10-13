import type { Product, ProductStatus } from './types';
export function localISO(date = new Date()) { return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`; }
export function daysFromToday(value: string, today = localISO()) {
 const parse = (s: string) => { const [y=0,m=0,d=0] = s.split('-').map(Number); return Date.UTC(y,m-1,d); };
 return Math.round((parse(value) - parse(today)) / 86400000);
}
export function isExactDate(value: string) { if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false; const [y=0,m=0,d=0]=value.split('-').map(Number); const t=new Date(y,m-1,d); return t.getFullYear()===y && t.getMonth()===m-1 && t.getDate()===d; }
export function productStatus(p: Pick<Product,'date'|'verified'|'dateType'>, window = 7, today = localISO()): ProductStatus {
 if (!p.verified || !isExactDate(p.date)) return p.date ? 'Needs Review' : 'Unknown';
 if (p.dateType === 'Manufacturing') return 'Manufactured';
 if (p.dateType === 'Packed On') return 'Packed';
 const days = daysFromToday(p.date,today);
 if (p.dateType === 'Best Before') return days < 0 ? 'Best Before Passed' : days === 0 ? 'Best Before Today' : days <= window ? 'Best Before Soon' : 'Best Before Future';
 return days < 0 ? 'Expired' : days === 0 ? 'Expires Today' : days <= window ? 'Expiring Soon' : 'Upcoming';
}
export function displayDate(value: string, long = false) { if (!value) return 'Not identified'; if (!isExactDate(value)) return value; const [y=0,m=0,d=0]=value.split('-').map(Number); return new Date(y,m-1,d).toLocaleDateString('en-GB',{day:'numeric',month:long?'long':'short',year:'numeric'}); }
export function relativeDate(days: number) { const d=new Date(); d.setDate(d.getDate()+days); return localISO(d); }
