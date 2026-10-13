import { useState, type FormEvent } from 'react';
import { useQueryClient, useSuspenseQuery } from '@tanstack/react-query';
import { Plus, Trash2, LoaderCircle, FlaskConical } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { service, wasteQuery } from '@/services/api';
import { displayDate, localISO } from '@/services/dates';
import { PageIntro, Empty, Footer, PanelHead } from './common';
const blank = () => ({name:'',quantity:'',value:'',reason:'',date:localISO()});
export function WasteJournal(){
 const {data}=useSuspenseQuery(wasteQuery);const qc=useQueryClient();const [form,setForm]=useState(blank());const [error,setError]=useState('');const [busy,setBusy]=useState(false);
 const month=localISO().slice(0,7);const monthTotal=data.filter(w=>w.date.startsWith(month)).reduce((t,w)=>t+w.value,0);
 async function add(e:FormEvent){e.preventDefault();setError('');setBusy(true);try{await service.addWasteEntry({...form,value:Number(form.value||0)});await qc.invalidateQueries();setForm(blank());toast.success('Added to your waste journal');}catch(err){setError(err instanceof Error?err.message:'Unable to save entry.');}finally{setBusy(false);}}
 async function remove(id:string){await service.deleteWasteEntry(id);await qc.invalidateQueries();toast.success('Entry removed');}
 return <div className="page"><PageIntro title="Waste journal" description="Note what didn’t get used, so next week’s shopping fits a little better."><span className="page-date">This month: <b className="text-foreground">₹{monthTotal}</b></span></PageIntro>
 <div className="demo-strip"><FlaskConical size={16}/>Demo journal. Values you enter are kept only until the page is refreshed.</div>
 <div className="scan-grid"><section className="panel"><PanelHead title="Entries" subtitle={`${data.length} recorded`}/>{data.length?data.map(w=><div key={w.id} className="review-row"><div className="flex-1 min-w-0"><div className="product-name">{w.name} <span className="text-muted-foreground font-normal">· {w.quantity || 'Quantity not noted'}</span></div><div className="product-brand">{displayDate(w.date)} · {w.reason || 'No reason noted'}</div></div><b className="text-sm">₹{w.value}</b><Button variant="ghost" size="icon" aria-label={`Remove ${w.name}`} onClick={()=>void remove(w.id)}><Trash2/></Button></div>):<Empty title="Nothing logged" message="That’s a good sign. Add an entry when something goes unused."/>}</section>
 <section className="panel"><PanelHead title="Log wasted food"/><form onSubmit={add} className="analysis-body space-y-4">{error && <div role="alert" className="form-error">{error}</div>}<div className="form-grid"><div className="field full"><label htmlFor="w-name">What was wasted *</label><input id="w-name" required value={form.name} onChange={e=>setForm({...form,name:e.target.value})} placeholder="e.g. Coriander"/></div><div className="field"><label htmlFor="w-qty">Quantity</label><input id="w-qty" value={form.quantity} onChange={e=>setForm({...form,quantity:e.target.value})} placeholder="e.g. 1 bunch"/></div><div className="field"><label htmlFor="w-val">Approx. value (₹)</label><input id="w-val" type="number" min={0} value={form.value} onChange={e=>setForm({...form,value:e.target.value})} placeholder="0"/></div><div className="field"><label htmlFor="w-date">Date *</label><input id="w-date" type="date" required value={form.date} onChange={e=>setForm({...form,date:e.target.value})}/></div><div className="field"><label htmlFor="w-reason">Reason</label><input id="w-reason" value={form.reason} onChange={e=>setForm({...form,reason:e.target.value})} placeholder="e.g. Wilted before use"/></div></div><div className="flex justify-end"><Button type="submit" disabled={busy}>{busy?<LoaderCircle className="animate-spin"/>:<Plus/>}Add entry</Button></div></form></section></div>
 <Footer/></div>;
}
