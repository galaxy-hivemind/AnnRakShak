import { createFileRoute } from '@tanstack/react-router';
import { ExpiryTimeline } from '@/features/annarakshak/timeline';
import { pageHead } from '@/features/annarakshak/meta';
import { productsQuery, settingsQuery } from '@/services/api';
import { Loading, ErrorState } from '@/features/annarakshak/common';
export const Route = createFileRoute('/timeline')({loader:async({context})=>{await Promise.all([context.queryClient.ensureQueryData(productsQuery),context.queryClient.ensureQueryData(settingsQuery)]);},head:()=>pageHead('Expiry Timeline','See every confirmed Expiry, Use By, and Best Before date in your kitchen, in date order.'),pendingComponent:Loading,errorComponent:({error,reset})=><ErrorState error={error} retry={reset}/>,component:ExpiryTimeline});
