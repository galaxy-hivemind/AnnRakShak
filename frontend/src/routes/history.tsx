import { createFileRoute } from '@tanstack/react-router';
import { ScanHistory } from '@/features/annarakshak/history';
import { pageHead } from '@/features/annarakshak/meta';
import { scansQuery } from '@/services/api';
import { Loading, ErrorState } from '@/features/annarakshak/common';
export const Route = createFileRoute('/history')({loader:async({context})=>{await context.queryClient.ensureQueryData(scansQuery);},head:()=>pageHead('Scan History','Review demo capture history, analysis outcomes, date candidates, and independent scan records.'),pendingComponent:Loading,errorComponent:({error,reset})=><ErrorState error={error} retry={reset}/>,component:ScanHistory});
