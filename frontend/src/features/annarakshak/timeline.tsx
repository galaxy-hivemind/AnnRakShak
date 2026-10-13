import { useState } from 'react';
import { useSuspenseQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { ArrowRight, CircleHelp } from 'lucide-react';
import { productsQuery, settingsQuery } from '@/services/api';
import { daysFromToday, displayDate, isExactDate } from '@/services/dates';
import type { Product } from '@/services/types';
import { PageIntro, ProductCell, ProductBadge, Empty, Footer } from './common';
import { ProductDialog, type ProductDialogMode } from './product-dialog';
const groups = [
 {name:'Past date',test:(d:number)=>d<0},{name:'Today',test:(d:number)=>d===0},{name:'Tomorrow',test:(d:number)=>d===1},{name:'This week',test:(d:number)=>d>1&&d<=7},{name:'Later',test:(d:number)=>d>7},
];
export function ExpiryTimeline(){
 const {data}=useSuspenseQuery(productsQuery);useSuspenseQuery(settingsQuery);const [dialog,setDialog]=useState<ProductDialogMode>();
 // Manufacturing and Packed On dates are never treated as expiry; unverified dates stay out.
 const dated=data.filter(p=>p.verified && isExactDate(p.date) && ['Expiry','Use By','Best Before'].includes(p.dateType)).sort((a,b)=>daysFromToday(a.date)-daysFromToday(b.date));
 const excluded=data.length-dated.length;
 return <div className="page"><PageIntro title="Expiry timeline" description="Every confirmed Expiry, Use By, and Best Before date, in order."/>
 <div className="demo-strip"><CircleHelp size={16}/><span>{excluded} products are not shown because their date is unconfirmed or is a Manufacturing/Packed On date. <Link to="/review" className="underline">Review unconfirmed scans</Link>.</span></div>
 {dated.length?groups.map(g=>{const items=dated.filter(p=>g.test(daysFromToday(p.date)));if(!items.length)return null;return <section key={g.name} className="tl-group"><h2>{g.name} <span className="muted-count">({items.length})</span></h2><div className="panel">{items.map((p:Product)=>{const d=daysFromToday(p.date);return <button key={p.id} className="review-row w-full text-left" onClick={()=>setDialog({type:'view',product:p})}><ProductCell product={p}/><div className="ml-auto flex items-center gap-4"><div className="text-right text-xs"><div>{displayDate(p.date)}</div><div className="text-[10px] text-muted-foreground mt-1">{p.dateType} · {d<0?`${-d} days ago`:d===0?'today':`in ${d} days`}</div></div><ProductBadge product={p}/><ArrowRight size={15} className="text-primary"/></div></button>;})}</div></section>;}):<Empty title="No confirmed dates yet" message="Add a product or confirm a scan to build your timeline."/>}
 <Footer/>{dialog && <ProductDialog mode={dialog} onClose={()=>setDialog(undefined)}/>}</div>;
}
