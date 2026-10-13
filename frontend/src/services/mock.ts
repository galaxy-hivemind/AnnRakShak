import spinach from '@/assets/food-spinach.jpg';
import milk from '@/assets/food-milk.jpg';
import tomatoes from '@/assets/food-tomatoes.jpg';
import carrots from '@/assets/food-carrots.jpg';
import { categories, type WasteEntry, type Product, type ProductInput, type ScanRecord, type Settings, type FoodSafetyService } from './types';
import { relativeDate, productStatus, daysFromToday, isExactDate } from './dates';
const seeds: [string,string,number,number,string,Product['dateType']][] = [
 ['Greek Yogurt','Epigamia',0,9,'90 g','Expiry'], ['Whole Wheat Bread','Britannia',1,4,'400 g','Expiry'], ['Farm Fresh Eggs','Licious',0,5,'6 pieces','Best Before'], ['Paneer','Amul',0,8,'200 g','Use By'], ['Orange Juice','Tropicana',3,-2,'1 L','Expiry'], ['Oat Milk','Oatly',3,23,'1 L','Best Before'], ['Rolled Oats','Quaker',1,64,'1 kg','Best Before'], ['Dark Chocolate','Amul',2,41,'150 g','Best Before'], ['Peanut Butter','Pintola',4,38,'350 g','Best Before'], ['Basmati Rice','India Gate',1,120,'5 kg','Best Before'], ['Salted Butter','Amul',0,16,'100 g','Expiry'], ['Green Tea','Organic India',3,180,'25 bags','Best Before'], ['Mixed Nuts','Farmley',2,51,'200 g','Best Before'], ['Pasta Fusilli','Borges',1,130,'500 g','Best Before'], ['Tomato Ketchup','Kissan',4,42,'500 g','Best Before'], ['Olive Oil','Figaro',4,-1,'500 ml','Best Before'], ['Chickpeas','Tata Sampann',4,-30,'500 g','Packed On'], ['Cheddar Cheese','Britannia',0,26,'200 g','Expiry'], ['Coffee','Blue Tokai',3,-10,'250 g','Manufacturing'], ['Corn Flakes','Kellogg’s',1,93,'475 g','Best Before'], ['Digestive Biscuits','McVitie’s',2,32,'250 g','Best Before'], ['Frozen Peas','Safal',5,67,'500 g','Best Before'], ['Coconut Water','Raw Pressery',3,6,'200 ml','Use By'],
];
function image(category: Product['category']) { return `/products/${categories.indexOf(category)}.svg`; }
let products: Product[] = seeds.map(([name,brand,c,days,quantity,dateType],i)=>({id:`PR-${1001+i}`, name,brand,category:categories[c] ?? categories[0],quantity,date:relativeDate(days),dateType,notes:'',verified:true,image:image(categories[c] ?? categories[0])}));
// Demo-only fresh items with sample prices and storage, so the overview has realistic photos.
const fresh: Product[] = [
 {id:'PR-0901',name:'Baby spinach',brand:'Farm fresh',category:'Fresh Produce',produce:'Vegetable',quantity:'250 g',storage:'Fridge',price:40,date:relativeDate(0),dateType:'Use By',notes:'',verified:true,image:spinach},
 {id:'PR-0902',name:'Fresh milk',brand:'Amul',category:'Dairy & Eggs',quantity:'1 litre',storage:'Fridge',price:68,date:relativeDate(1),dateType:'Use By',notes:'',verified:true,image:milk},
 {id:'PR-0903',name:'Tomatoes',brand:'Farm fresh',category:'Fresh Produce',produce:'Vegetable',quantity:'500 g',storage:'Fridge',price:30,date:relativeDate(2),dateType:'Best Before',notes:'',verified:true,image:tomatoes},
 {id:'PR-0904',name:'Fresh carrots',brand:'Farm fresh',category:'Fresh Produce',produce:'Vegetable',quantity:'500 g',storage:'Fridge',price:45,date:relativeDate(6),dateType:'Best Before',notes:'',verified:true,image:carrots},
];
products.unshift(...fresh);
let waste: WasteEntry[] = [{id:'WJ-1',name:'Coriander',quantity:'1 bunch',value:12,reason:'Wilted before use',date:relativeDate(-3)},{id:'WJ-2',name:'Whole wheat bread',quantity:'4 slices',value:20,reason:'Forgotten at the back of the shelf',date:relativeDate(-6)}];
const reviewSeeds = [
 {name:'Crunchy Peanut Butter',brand:'Pintola',category:categories[4],reason:'Multiple possible dates', candidates:[{id:'c1',printedText:`MFD ${relativeDate(-30)} · EXP ${relativeDate(150)}`,date:relativeDate(150),dateType:'Expiry' as const,precision:'day' as const,confidence:.86},{id:'c2',printedText:`MFD ${relativeDate(-30)}`,date:relativeDate(-30),dateType:'Manufacturing' as const,precision:'day' as const}]},
 {name:'Instant Noodles',brand:'Maggi',category:categories[2],reason:'Month/year-only date',candidates:[{id:'c1',printedText:'BEST BEFORE 12/2026',date:'2026-12',dateType:'Best Before' as const,precision:'month' as const,reason:'No exact day printed'}]},
 {name:'Mango Drink',brand:'Frooti',category:categories[3],reason:'Ambiguous date format',candidates:[{id:'c1',printedText:'EXP 11/12/26',date:'2026-12-11',dateType:'Expiry' as const,precision:'day' as const,reason:'Could mean 11 December or 12 November'},{id:'c2',printedText:'EXP 11/12/26',date:'2026-11-12',dateType:'Expiry' as const,precision:'day' as const}]},
 {name:'Organic Honey',brand:'Dabur',category:categories[4],reason:'Missing date',candidates:[]},
 {name:'Unidentified package',brand:'Not identified',category:categories[4],reason:'Failed analysis',candidates:[]},
 {name:'Natural Curd',brand:'Mother Dairy',category:categories[0],reason:'Conflicting date evidence',candidates:[{id:'c1',printedText:`USE BY ${relativeDate(4)} (side label)`,date:relativeDate(4),dateType:'Use By' as const,precision:'day' as const},{id:'c2',printedText:`EXP ${relativeDate(8)} (lid)`,date:relativeDate(8),dateType:'Expiry' as const,precision:'day' as const}]},
];
let scans: ScanRecord[] = reviewSeeds.map((s,i)=>({...s,id:`SC-${2048-i}`,timestamp:new Date(Date.now()-i*3700000).toISOString(),image:image(s.category),analysisStatus:i===4?'Failed':'Successful',reviewStatus:'Needs Review'}));
scans.push(...products.slice(0,7).map((p,i)=>({id:`SC-${2042-i}`,timestamp:new Date(Date.now()-(i+8)*3700000).toISOString(),image:p.image,name:p.name,brand:p.brand,category:p.category,analysisStatus:'Successful' as const,reviewStatus:'Confirmed' as const,productId:p.id,candidates:[{id:'c1',printedText:`${p.dateType.toUpperCase()} ${p.date}`,date:p.date,dateType:p.dateType,precision:'day' as const}]})));
let settings: Settings = {alertWindow:7,compact:false,dateFormat:'short'};
const delay = async () => new Promise<void>(resolve=>setTimeout(resolve,220));
const copy = <T,>(data:T):T => structuredClone(data);
function requireProduct(id:string) { const p=products.find(p=>p.id===id); if(!p) throw new Error('Product not found. It may have been removed.'); return p; }
function requireScan(id:string) { const s=scans.find(s=>s.id===id); if(!s) throw new Error('Scan record not found.'); return s; }
function validate(data:ProductInput) { if(!data.name.trim()) throw new Error('Enter a product name.'); if(data.date && !isExactDate(data.date)) throw new Error('Enter a valid full calendar date.'); if(data.verified && !isExactDate(data.date)) throw new Error('A full date is required to confirm a product date.'); }
function create(data:ProductInput): Product { validate(data); const p: Product={...data,name:data.name.trim(),id:`PR-${Date.now()}`,image:image(data.category)}; products.unshift(p); return p; }
function monthWaste(){const m=relativeDate(0).slice(0,7);return waste.filter(w=>w.date.startsWith(m));}
export const mockService: FoodSafetyService = {
 async getDashboardSummary() { await delay(); return copy({total:products.length,verified:products.filter(p=>p.verified && isExactDate(p.date) && ['Expiry','Use By'].includes(p.dateType)).length,expired:products.filter(p=>productStatus(p)==='Expired').length,today:products.filter(p=>productStatus(p)==='Expires Today').length,soon:products.filter(p=>productStatus(p,settings.alertWindow)==='Expiring Soon').length,review:scans.filter(s=>s.reviewStatus==='Needs Review').length,expiring:products.filter(p=>['Expires Today','Expiring Soon','Best Before Today','Best Before Soon'].includes(productStatus(p,settings.alertWindow))).sort((a,b)=>daysFromToday(a.date)-daysFromToday(b.date)),reviewScans:scans.filter(s=>s.reviewStatus==='Needs Review'),recent:scans.slice(0,5),categories:categories.map(name=>({name,count:products.filter(p=>p.category===name).length})),inventoryValue:products.reduce((t,p)=>t+(p.price||0),0),pricedCount:products.filter(p=>p.price).length,wasteThisMonth:monthWaste().reduce((t,w)=>t+w.value,0),wasteEntries:monthWaste().length}); },
 async getProducts(){await delay();return copy(products);},
 async getProductById(id){await delay();return copy(requireProduct(id));},
 async createProduct(data){await delay();return copy(create(data));},
 async updateProduct(id,data){await delay();validate(data);const p=requireProduct(id);Object.assign(p,data);return copy(p);},
 async deleteProduct(id){await delay();requireProduct(id);products=products.filter(p=>p.id!==id);for(const s of scans) if(s.productId===id) delete s.productId;},
 async getScanHistory(){await delay();return copy(scans);},
 async getScanById(id){await delay();return copy(requireScan(id));},
 async startScan(upload){await delay();const s:ScanRecord={id:`SC-${Date.now()}`,timestamp:new Date().toISOString(),image:upload || image(categories[0]),name:'Fresh Toned Milk',brand:'Amul',category:categories[0],analysisStatus:'Successful',reviewStatus:'Needs Review',reason:'Multiple possible dates',candidates:[{id:'c1',printedText:`USE BY ${relativeDate(4)} · BATCH A241`,date:relativeDate(4),dateType:'Use By',precision:'day',confidence:.92},{id:'c2',printedText:`PACKED ON ${relativeDate(-1)}`,date:relativeDate(-1),dateType:'Packed On',precision:'day'}]};scans.unshift(s);return copy(s);},
 async reanalyzeScan(id){await delay();const s=requireScan(id);if(s.reviewStatus==='Confirmed') return copy(s);s.analysisStatus='Successful'; if(!s.candidates.length){s.candidates=[{id:'c1',printedText:`BEST BEFORE ${relativeDate(30)}`,date:relativeDate(30),dateType:'Best Before',precision:'day'}];s.reason='Date awaiting confirmation';}return copy(s);},
 async getDateCandidates(id){await delay();return copy(requireScan(id).candidates);},
 async simulateAnalysisFailure(id){await delay();const s=requireScan(id);s.analysisStatus='Failed';s.reason='Failed analysis';s.candidates=[];return copy(s);},
 async confirmDate(id,candidateId){await delay();const s=requireScan(id);if(s.productId)return copy(requireProduct(s.productId));const c=s.candidates.find(c=>c.id===candidateId);if(!c || c.precision!=='day' || !isExactDate(c.date))throw new Error('This evidence has no exact date. Enter a full date from the package, or leave it in review.');const p=create({name:s.name,brand:s.brand,category:s.category,quantity:'',date:c.date,dateType:c.dateType,notes:`Original evidence: ${c.printedText}`,verified:true});p.scanId=id;s.productId=p.id;s.reviewStatus='Confirmed';return copy(p);},
 async correctScan(id,data){await delay();const s=requireScan(id);if(!data.verified)throw new Error('Explicit date confirmation is required.');validate(data);const p=s.productId?requireProduct(s.productId):create(data);Object.assign(p,data);p.scanId=id;s.productId=p.id;s.reviewStatus='Confirmed';return copy(p);},
 async getWasteJournal(){await delay();return copy([...waste].sort((a,b)=>b.date.localeCompare(a.date)));},
 async addWasteEntry(data){await delay();if(!data.name.trim())throw new Error('Enter what was wasted.');if(!isExactDate(data.date))throw new Error('Enter a valid date.');if(!(data.value>=0))throw new Error('Enter a value of 0 or more.');const w={...data,name:data.name.trim(),id:`WJ-${Date.now()}`};waste.unshift(w);return copy(w);},
 async deleteWasteEntry(id){await delay();waste=waste.filter(w=>w.id!==id);},
 async getSettings(){await delay();return copy(settings);},
 async updateSettings(data){await delay();if(data.alertWindow<1 || data.alertWindow>30)throw new Error('Choose between 1 and 30 days.');settings=copy(data);return copy(settings);},
};
