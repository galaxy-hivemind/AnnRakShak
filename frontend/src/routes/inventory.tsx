import { createFileRoute } from '@tanstack/react-router';
import { Inventory } from '@/features/annarakshak/inventory';
import { pageHead } from '@/features/annarakshak/meta';
import { productsQuery, settingsQuery } from '@/services/api';
import { Loading, ErrorState } from '@/features/annarakshak/common';
export const Route = createFileRoute('/inventory')({
 validateSearch:(search:Record<string,unknown>)=>({q:typeof search['q']==='string'?search['q']:''}),
 loader:async({context})=>{await Promise.all([context.queryClient.ensureQueryData(productsQuery),context.queryClient.ensureQueryData(settingsQuery)]);},
 head:()=>pageHead('My Inventory','Manage your kitchen products, distinct printed date types, and explicitly verified dates.'),
 pendingComponent:Loading,
 errorComponent:({error,reset})=><ErrorState error={error} retry={reset}/>,
 component:Inventory,
});
