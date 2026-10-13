import { useState } from 'react';
import { useSuspenseQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { Box, Clock, Sprout, TrendingDown, CalendarDays, Plus, Flame, ArrowRight, ArrowUpRight, Refrigerator, Search, CircleCheck, ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { dashboardQuery, productsQuery, settingsQuery } from '@/services/api';
import { daysFromToday } from '@/services/dates';
import type { Product } from '@/services/types';
import { Empty, Footer } from './common';
import { ProductDialog, type ProductDialogMode } from './product-dialog';
const tabs = [
 {label:'All items',match:()=>true},
 {label:'Vegetables',match:(p:Product)=>p.produce==='Vegetable'},
 {label:'Dairy',match:(p:Product)=>p.category==='Dairy & Eggs'},
 {label:'Fruit',match:(p:Product)=>p.produce==='Fruit'},
 {label:'Pantry',match:(p:Product)=>p.category==='Pantry Staples' || p.category==='Grains & Cereals'},
] as const;
export function shortCategory(p:Product){return p.produce==='Vegetable'?'Vegetables':p.produce==='Fruit'?'Fruit':p.category==='Dairy & Eggs'?'Dairy':p.category==='Pantry Staples'||p.category==='Grains & Cereals'?'Pantry':p.category;}
export function dayLabel(days:number){return days===0?'Use today':days===1?'Use tomorrow':`${days} days left`;}
const shortDate=(iso:string)=>new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB',{day:'numeric',month:'short'});
function Meta({p}:{p:Product}){return <div className="food-meta">{p.quantity && <span>{p.quantity}</span>}{p.quantity && p.storage && <span aria-hidden>·</span>}{p.storage && <span className="inline-flex items-center gap-1"><Refrigerator size={12}/>{p.storage}</span>}</div>;}
export function Dashboard(){
 const {data}=useSuspenseQuery(dashboardQuery);const {data:products}=useSuspenseQuery(productsQuery);const {data:settings}=useSuspenseQuery(settingsQuery);
 const [dialog,setDialog]=useState<ProductDialogMode>();const [tab,setTab]=useState<string>('All items');const [query,setQuery]=useState('');
 const today=new Date();const end=new Date();end.setDate(end.getDate()+settings.alertWindow);
 const range=`${today.getDate()}${today.getMonth()!==end.getMonth()?' '+today.toLocaleDateString('en-GB',{month:'short'}):''} – ${end.getDate()} ${end.toLocaleDateString('en-GB',{month:'long'})}`;
 const useFirst=data.expiring.slice(0,3);
 const filter=tabs.find(t=>t.label===tab)?.match ?? (()=>true);
 const list=products.filter(p=>filter(p) && (!query || `${p.name} ${p.brand}`.toLowerCase().includes(query.toLowerCase()))).sort((a,b)=>Number(!b.image.endsWith('.svg'))-Number(!a.image.endsWith('.svg')));
 const metrics=[
  {label:'In your inventory',value:String(data.total),unit:'items',icon:Box,caption:'Tracked products in your kitchen',to:'/inventory' as const,warm:false},
  {label:'Use first',value:String(data.expiring.length),unit:'items',icon:Clock,caption:'A little attention goes a long way',to:'/timeline' as const,warm:true},
  {label:'Inventory value',value:`₹${data.inventoryValue}`,unit:'',icon:Sprout,caption:`Sample prices on ${data.pricedCount} items`,to:'/inventory' as const,warm:false},
  {label:'Waste this month',value:`₹${data.wasteThisMonth}`,unit:'',icon:TrendingDown,caption:`${data.wasteEntries} ${data.wasteEntries===1?'entry':'entries'} in your waste journal`,to:'/waste' as const,warm:false},
 ];
 return <div className="page overview">
 <div className="greeting"><div><div className="kicker">My kitchen <ChevronDown size={15}/></div><h1>A little care. A lot less waste.</h1><p>Keep your kitchen fresh and make every ingredient count.</p></div><div className="greeting-actions"><span className="page-date"><CalendarDays size={17}/>{today.toLocaleDateString('en-GB',{weekday:'long'})}, {today.toLocaleDateString('en-GB',{day:'numeric',month:'long'})}</span><Button size="lg" className="add-btn" onClick={()=>setDialog({type:'add'})}><Plus/>Add ingredient</Button></div></div>
 <div className="metrics">{metrics.map(m=><Link to={m.to} className="metric" key={m.label}><div className="metric-top"><span>{m.label}</span><m.icon/></div><div className="metric-value"><b className={m.warm?'warm':''}>{m.value}</b>{m.unit && <span>{m.unit}</span>}</div><div className="metric-sub">{m.caption}</div></Link>)}</div>
 <section className="section"><div className="section-head"><div><h2><Flame/>Use First <span className="attention">{data.expiring.length} need attention</span></h2><p>Good ingredients. Just a little less time.</p></div><Link to="/timeline" className="text-link">View all expiring <ArrowRight size={17}/></Link></div>
 {useFirst.length?<div className="use-first">{useFirst.map(p=>{const d=daysFromToday(p.date);return <button key={p.id} className="food-row" onClick={()=>setDialog({type:'view',product:p})} aria-label={`Open ${p.name}`}><img src={p.image} alt="" width={140} height={138} loading="lazy"/><div className="food-row-body"><div className="flex items-start justify-between gap-2"><strong>{p.name}</strong><ArrowUpRight size={16}/></div><Meta p={p}/><div className="food-row-foot"><span className={`use-badge ${d===0?'today':''}`}>{dayLabel(d)}</span><span className="food-date" title={p.dateType}>{shortDate(p.date)}</span></div></div></button>;})}</div>:<Empty title="Nothing needs using up" message="No confirmed dates fall within your alert window."/>}
 </section>
 <div className="lower">
  <section><div className="section-head"><h2>Your inventory <span className="muted-count">({data.total})</span></h2><Link to="/inventory" search={{q:''}} className="text-link">View inventory <ArrowRight size={17}/></Link></div>
  <div className="inv-toolbar"><div role="tablist" aria-label="Filter by type" className="tabs">{tabs.map(t=><button key={t.label} role="tab" aria-selected={tab===t.label} className={tab===t.label?'active':''} onClick={()=>setTab(t.label)}>{t.label}</button>)}</div><div className="search-input small"><Search/><input aria-label="Search ingredients" placeholder="Search ingredients" value={query} onChange={e=>setQuery(e.target.value)}/></div></div>
  {list.length?<div className="inv-grid">{list.slice(0,4).map(p=><button key={p.id} className="inv-card" onClick={()=>setDialog({type:'view',product:p})} aria-label={`Open ${p.name}`}><div className="inv-img"><img src={p.image} alt="" width={300} height={220} loading="lazy"/><span className="cat-chip">{shortCategory(p)}</span></div><div className="inv-body"><strong>{p.name}</strong><Meta p={p}/></div></button>)}</div>:<Empty title="No matching ingredients" message="Try another tab or search term."/>}
  </section>
  <aside className="upcoming"><h2><CalendarDays/>Upcoming expiry</h2><div className="upcoming-sub"><span>{range}</span><span className="inline-flex items-center gap-1"><CircleCheck size={14}/>Confirmed dates</span></div>
  {useFirst.length?<ol className="timeline">{data.expiring.slice(0,4).map(p=>{const d=daysFromToday(p.date);const label=d===0?'Today':d===1?'Tomorrow':new Date(`${p.date}T00:00:00`).toLocaleDateString('en-GB',{weekday:'long'});return <li key={p.id} className={d===0?'today':''}><div className="tl-head"><b>{label}</b><span>{shortDate(p.date)}</span></div><button className="tl-item" onClick={()=>setDialog({type:'view',product:p})} aria-label={`Open ${p.name}`}><img src={p.image} alt="" width={44} height={44} loading="lazy"/><div className="min-w-0 flex-1 text-left"><strong>{p.name}</strong><div className="food-meta">{[p.quantity,p.storage].filter(Boolean).join(' · ') || p.dateType}</div></div><ArrowRight size={18}/></button></li>;})}</ol>:<p className="text-xs text-muted-foreground mt-6">No confirmed dates in the next {settings.alertWindow} days.</p>}
  <p className="tl-note">Only user-confirmed dates appear here. Unverified scans wait in <Link to="/review">Needs Review</Link>{data.review?` (${data.review})`:''}.</p>
  </aside>
 </div>
 <Footer/>
 {dialog && <ProductDialog mode={dialog} onClose={()=>setDialog(undefined)}/>}
 </div>;
}
