import { createFileRoute } from '@tanstack/react-router';
import { WasteJournal } from '@/features/annarakshak/waste';
import { pageHead } from '@/features/annarakshak/meta';
import { wasteQuery } from '@/services/api';
import { Loading, ErrorState } from '@/features/annarakshak/common';
export const Route = createFileRoute('/waste')({loader:async({context})=>{await context.queryClient.ensureQueryData(wasteQuery);},head:()=>pageHead('Waste Journal','Log food that went unused and see what it added up to this month.'),pendingComponent:Loading,errorComponent:({error,reset})=><ErrorState error={error} retry={reset}/>,component:WasteJournal});
