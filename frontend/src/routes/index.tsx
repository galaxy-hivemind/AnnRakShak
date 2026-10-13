import { createFileRoute } from '@tanstack/react-router';
import { Dashboard } from '@/features/annarakshak/dashboard';
import { pageHead } from '@/features/annarakshak/meta';
import { dashboardQuery, settingsQuery, productsQuery } from '@/services/api';
import { Loading, ErrorState } from '@/features/annarakshak/common';
export const Route = createFileRoute('/')({
  loader:async({context})=>{await Promise.all([context.queryClient.ensureQueryData(dashboardQuery),context.queryClient.ensureQueryData(settingsQuery),context.queryClient.ensureQueryData(productsQuery)]);},
  head:()=>pageHead('Your Kitchen, In View','Track your pantry, approaching confirmed dates, and packaging evidence needing review with AnnaRakshak.'),
  pendingComponent:Loading,
  errorComponent:({error,reset})=><ErrorState error={error} retry={reset}/>,
  component:Dashboard,
});
